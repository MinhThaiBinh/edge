from app.storage.schemas import ProductionRecord
from app.storage.db import get_production_db, get_database
from datetime import datetime, timedelta
from typing import Optional
import sys

async def create_production_record_on_changeover(
    machinecode: str,
    old_productcode: str,
    new_productcode: str,
    changeover_timestamp: datetime,
    shiftcode: Optional[str] = None
) -> Optional[ProductionRecord]:
    try:
        print(f">>> [LOGIC] Bắt đầu tạo ProductionRecord cho {machinecode} - {old_productcode}")
        sys.stdout.flush()
        db = get_production_db()
        db_master = get_database()
        now_utc = datetime.utcnow()
        
        existing_record = await db.production_records.find_one(
            {"machinecode": machinecode, "status": "running"},
            sort=[("createtime", -1)]
        )
        
        if existing_record:
            start_time = existing_record["createtime"]
            target_id = existing_record["_id"]
            actual_productcode = existing_record.get("productcode", old_productcode)
        else:
            prefix = f"{old_productcode}-{now_utc.strftime('%d-%m-%Y')}-{machinecode}"
            target_id = f"{prefix}-1"
            start_time = changeover_timestamp
            actual_productcode = old_productcode
        
        iot_pipeline = [
            {"$match": {
                "machinecode": machinecode,
                "timestamp": {"$gte": start_time, "$lt": changeover_timestamp}
            }},
            {"$group": {"_id": None, "total_count": {"$sum": "$raw_value"}}}
        ]
        iot_result = await db.iot_records.aggregate(iot_pipeline).to_list(1)
        total_count = iot_result[0]["total_count"] if iot_result else 0
        
        defect_pipeline = [
            {"$match": {
                "machinecode": machinecode,
                "timestamp": {"$gte": start_time, "$lt": changeover_timestamp}
            }},
            {"$group": {"_id": None, "defect_count": {"$sum": 1}}}
        ]
        defect_result = await db.defect_records.aggregate(defect_pipeline).to_list(1)
        defect_count = defect_result[0]["defect_count"] if defect_result else 0
        
        run_seconds = int((changeover_timestamp - start_time).total_seconds())
        downtime_seconds = 0
        
        p_code = actual_productcode.strip() if actual_productcode else ""

        wp_doc = await db_master["workingparameter"].find_one({"productcode": p_code})
        if not wp_doc:
            wp_doc = await db_master["workingparameter"].find_one({"productcode": {"$regex": f"^{p_code}$", "$options": "i"}})
        idealcyclesec = wp_doc["idealcyclesec"] if wp_doc and "idealcyclesec" in wp_doc else 1.0
        
        product_doc = await db_master["product"].find_one({"productcode": p_code})
        if not product_doc:
            product_doc = await db_master["product"].find_one({"productcode": {"$regex": f"^{p_code}$", "$options": "i"}})
        plannedqty = product_doc.get("plannedqty", 0) if product_doc else 0
        
        if total_count > 0 and run_seconds > 0:
            total_seconds = run_seconds + downtime_seconds
            availability = run_seconds / total_seconds if total_seconds > 0 else 0.0
            ideal_total_time = idealcyclesec * total_count
            performance = ideal_total_time / run_seconds
            quality = (total_count - defect_count) / total_count
            oee = availability * performance * quality
            avg_cycle = run_seconds / total_count
        else:
            availability = performance = quality = oee = avg_cycle = 0.0
        
        shift_info = await get_current_shift()

        record = ProductionRecord(
            id=target_id,
            machinecode=machinecode,
            productcode=actual_productcode,
            idealcyclesec=idealcyclesec,
            shiftcode=shift_info["shiftcode"],
            startshift=shift_info["startshift"],
            endshift=shift_info["endshift"],
            breakstart=shift_info["breakstart"],
            breakend=shift_info["breakend"],
            plannedqty=plannedqty,
            run_seconds=run_seconds,
            downtime_seconds=downtime_seconds,
            avg_cycle=round(avg_cycle, 2),
            total_count=total_count,
            defect_count=defect_count,
            availability=round(availability, 4),
            performance=round(performance, 4),
            quality=round(quality, 4),
            oee=round(oee, 4),
            is_synced=False,
            status="closed"
        )
        
        await db.production_records.replace_one(
            {"_id": target_id}, 
            record.model_dump(by_alias=True, exclude_none=True),
            upsert=True
        )
        print(f">>> [LOGIC] Đã ngắt (Finalized) ProductionRecord: {target_id} (OEE={record.oee})")
        return record
    except Exception as e:
        print(f">>> [LOGIC ERROR] Lỗi trong create_production_record_on_changeover: {e}")
        return None

async def get_current_shift():
    now = datetime.now()
    current_seconds = now.hour * 3600 + now.minute * 60 + now.second
    db_master = get_database()
    all_shifts = await db_master["shift"].find().to_list(100)
    
    active_shift = None
    for s in all_shifts:
        def to_sec(val):
            if isinstance(val, (int, float)): return int(val)
            if isinstance(val, datetime): return val.hour * 3600 + val.minute * 60 + val.second
            return 0
        s_start = to_sec(s.get("shiftstarttime"))
        s_end = to_sec(s.get("shiftendtime"))
        
        is_in_shift = False
        if s_start <= s_end:
            if s_start <= current_seconds <= s_end: is_in_shift = True
        else:
            if current_seconds >= s_start or current_seconds <= s_end: is_in_shift = True
        
        if is_in_shift:
            active_shift = s
            active_shift["_start_sec"] = s_start
            active_shift["_end_sec"] = s_end
            break

    if not active_shift:
        active_shift = {"shiftcode": "SHIFT_01", "_start_sec": 21600, "_end_sec": 50400}

    start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(seconds=active_shift["_start_sec"])
    end_dt = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(seconds=active_shift["_end_sec"])

    if active_shift["_start_sec"] > active_shift["_end_sec"]:
        if current_seconds >= active_shift["_start_sec"]: end_dt += timedelta(days=1)
        else: start_dt -= timedelta(days=1)

    break_info = active_shift.get("breaktime", {})
    b_start_sec = break_info.get("breakstart")
    b_end_sec = break_info.get("breakend")
    breakstart_dt = breakend_dt = None
    
    if b_start_sec is not None and b_end_sec is not None:
        breakstart_dt = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(seconds=b_start_sec)
        breakend_dt = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(seconds=b_end_sec)
        if active_shift["_start_sec"] > active_shift["_end_sec"]:
            if current_seconds >= active_shift["_start_sec"]:
                if b_start_sec < active_shift["_start_sec"]:
                    breakstart_dt += timedelta(days=1); breakend_dt += timedelta(days=1)
            else:
                if b_start_sec > active_shift["_end_sec"]:
                    breakstart_dt -= timedelta(days=1); breakend_dt -= timedelta(days=1)

    return {
        "shiftcode": active_shift["shiftcode"],
        "startshift": start_dt, "endshift": end_dt,
        "breakstart": breakstart_dt, "breakend": breakend_dt
    }

async def get_current_shift_code() -> str:
    info = await get_current_shift()
    return info["shiftcode"]

async def initialize_production_record(machinecode: str, productcode: str):
    try:
        db_master = get_database()
        shift_info = await get_current_shift()
        p_code = productcode.strip() if productcode else ""
        
        wp_doc = await db_master["workingparameter"].find_one({"productcode": p_code})
        if not wp_doc:
            wp_doc = await db_master["workingparameter"].find_one({"productcode": {"$regex": f"^{p_code}$", "$options": "i"}})
        idealcyclesec = wp_doc["idealcyclesec"] if wp_doc and "idealcyclesec" in wp_doc else 1.0
        
        product_doc = await db_master["product"].find_one({"productcode": p_code})
        if not product_doc:
            product_doc = await db_master["product"].find_one({"productcode": {"$regex": f"^{p_code}$", "$options": "i"}})
        plannedqty = product_doc.get("plannedqty", 0) if product_doc else 0

        now = datetime.utcnow()
        date_str = now.strftime("%d-%m-%Y")
        prefix = f"{productcode}-{date_str}-{machinecode}"
        
        db = get_production_db()
        regex = f"^{prefix}-"
        count = await db.production_records.count_documents({"_id": {"$regex": regex}})
        new_stt = count + 1
        record_id = f"{prefix}-{new_stt}"

        record = ProductionRecord(
            id=record_id,
            machinecode=machinecode,
            productcode=productcode,
            idealcyclesec=idealcyclesec,
            shiftcode=shift_info["shiftcode"],
            startshift=shift_info["startshift"],
            endshift=shift_info["endshift"],
            breakstart=shift_info["breakstart"],
            breakend=shift_info["breakend"],
            plannedqty=plannedqty,
            run_seconds=0, downtime_seconds=0, avg_cycle=0, total_count=0, defect_count=0,
            availability=0, performance=0, quality=0, oee=0, is_synced=False, status="running"
        )
        
        await db.production_records.insert_one(record.model_dump(by_alias=True, exclude_none=True))
        print(f">>> [LOGIC] Đã khởi tạo ProductionRecord mới: {record_id}")
        return record
    except Exception as e:
        print(f">>> [LOGIC ERROR] Lỗi trong initialize_production_record: {e}")
        return None
