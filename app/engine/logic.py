from app.storage.schemas import ProductionRecord, DowntimeRecord
from app.storage.db import get_production_db, get_database
from datetime import datetime, timedelta
from typing import Optional
import sys
from app.utils.messaging import mqtt_publish

async def finalize_production_record_on_shift_change(machinecode: str, old_shift_info: dict, timestamp: datetime, target_record_id: Optional[str] = None):
    """Chốt bản ghi khi hết ca và chuẩn bị cho ca mới."""
    try:
        db = get_production_db()
        query = {"machinecode": machinecode, "status": "running"}
        if target_record_id:
            query = {"_id": target_record_id}
            
        existing_record = await db.production_records.find_one(query, sort=[("createtime", -1)])
        if existing_record:
            p_code = existing_record.get("productcode")
            print(f">>> [SHIFT] Đang chốt bản ghi ca cũ cho máy {machinecode}")
            await create_production_record_on_changeover(
                machinecode=machinecode,
                old_productcode=p_code,
                new_productcode=p_code, 
                changeover_timestamp=timestamp,
                target_record_id=existing_record.get("_id")
            )
    except Exception as e:
        print(f">>> [SHIFT ERROR] Lỗi finalize_production_record_on_shift_change: {e}")

async def calculate_downtime_in_range(machinecode: str, start: datetime, end: datetime) -> int:
    """Tính tổng số giây downtime thực tế trong khoảng [start, end]."""
    try:
        db = get_production_db()
        # Giao thoa: downtime.start < end AND (downtime.end > start OR downtime.status == 'active')
        query = {
            "machinecode": machinecode,
            "start_time": {"$lt": end},
            "$or": [
                {"end_time": {"$gt": start}},
                {"status": "active"}
            ]
        }
        dts = await db.downtime_records.find(query).to_list(None)
        total = 0
        for dt in dts:
            d_start = dt["start_time"]
            d_end = dt.get("end_time") or datetime.utcnow()
            
            # Tính phần giao thoa
            actual_start = max(start, d_start)
            actual_end = min(end, d_end)
            
            if actual_start < actual_end:
                total += int((actual_end - actual_start).total_seconds())
        return max(0, total)
    except Exception as e:
        print(f">>> [LOGIC ERROR] Lỗi calculate_downtime_in_range: {e}")
        return 0

async def create_production_record_on_changeover(
    machinecode: str,
    old_productcode: str,
    new_productcode: str,
    changeover_timestamp: datetime,
    shiftcode: Optional[str] = None,
    target_record_id: Optional[str] = None
) -> Optional[ProductionRecord]:
    try:
        m_code = machinecode.strip() if machinecode else ""
        old_p = old_productcode.strip() if old_productcode else ""
        sys.stdout.flush()
        db = get_production_db()
        db_master = get_database()
        now_utc = datetime.utcnow()
        
        query = {"machinecode": m_code, "status": "running"}
        if target_record_id:
            query = {"_id": target_record_id}
            
        existing_record = await db.production_records.find_one(query, sort=[("createtime", -1)])
        
        if existing_record:
            start_time = existing_record["createtime"]
            target_id = existing_record["_id"]
            actual_productcode = existing_record.get("productcode", old_p).strip()
        else:
            prefix = f"{old_p}-{now_utc.strftime('%d-%m-%Y')}-{m_code}"
            target_id = f"{prefix}-1"
            start_time = changeover_timestamp
            actual_productcode = old_p
        
        iot_pipeline = [
            {"$match": {"machinecode": m_code, "timestamp": {"$gte": start_time, "$lt": changeover_timestamp}}},
            {"$group": {"_id": None, "total_count": {"$sum": 1}}}
        ]
        iot_result = await db.iot_records.aggregate(iot_pipeline).to_list(1)
        total_count = iot_result[0]["total_count"] if iot_result else 0
        
        defect_pipeline = [
            {"$match": {"machinecode": m_code, "timestamp": {"$gte": start_time, "$lt": changeover_timestamp}}},
            {"$group": {"_id": None, "defect_count": {"$sum": 1}}}
        ]
        defect_result = await db.defect_records.aggregate(defect_pipeline).to_list(1)
        defect_count = defect_result[0]["defect_count"] if defect_result else 0
        
        run_seconds = int((changeover_timestamp - start_time).total_seconds())
        downtime_seconds = await calculate_downtime_in_range(m_code, start_time, changeover_timestamp)
        
        p_code = actual_productcode.strip() if actual_productcode else ""
        wp_doc = await db_master["workingparameter"].find_one({"productcode": p_code})
        if not wp_doc:
            wp_doc = await db_master["workingparameter"].find_one({"productcode": {"$regex": f"^{p_code}$", "$options": "i"}})
        idealcyclesec = wp_doc["idealcyclesec"] if wp_doc and "idealcyclesec" in wp_doc else 1.0
        
        product_doc = await db_master["product"].find_one({"productcode": p_code})
        if not product_doc:
            product_doc = await db_master["product"].find_one({"productcode": {"$regex": f"^{p_code}$", "$options": "i"}})
        plannedqty = product_doc.get("plannedqty", 0) if product_doc else 0
        
        actual_run_seconds = max(0, run_seconds - downtime_seconds)
        availability = actual_run_seconds / run_seconds if run_seconds > 0 else 0.0

        if total_count > 0:
            ideal_total_time = idealcyclesec * total_count
            performance = ideal_total_time / actual_run_seconds if actual_run_seconds > 0 else 0.0
            quality = (total_count - defect_count) / total_count
            oee = availability * performance * quality
            avg_cycle = actual_run_seconds / total_count
        else:
            performance = quality = oee = avg_cycle = 0.0
        
        shift_info = await get_current_shift()

        record = ProductionRecord(
            id=target_id, endtime=changeover_timestamp, createtime=start_time,
            machinecode=m_code, productcode=actual_productcode,
            shiftcode=shift_info["shiftcode"], startshift=shift_info["startshift"],
            endshift=shift_info["endshift"], breakstart=shift_info["breakstart"],
            breakend=shift_info["breakend"], status="closed", is_synced=False,
            kpis={
                "availability": round(availability, 2),
                "performance": round(performance, 2),
                "quality": round(quality, 2),
                "oee": round(oee, 2)
            },
            stats={
                "total_count": total_count, "defect_count": defect_count, "good_product": int(total_count - defect_count),
                "avg_cycle": round(avg_cycle, 2), "run_seconds": run_seconds,
                "actual_run_seconds": actual_run_seconds, "downtime_seconds": downtime_seconds,
                "idealcyclesec": round(float(idealcyclesec), 2), "PlannedQty": plannedqty
            }
        )
        await db.production_records.replace_one({"_id": target_id}, record.model_dump(by_alias=True, exclude_none=True), upsert=True)
        final_doc = record.model_dump(by_alias=True, exclude_none=True)
        if "_id" in final_doc: final_doc["_id"] = str(final_doc["_id"])
        mqtt_publish("topic/get/productionrecord", final_doc)
        print(f">>> [LOGIC] Đã finalize ProductionRecord: {target_id} (OEE={record.kpis.oee})")
        return record
    except Exception as e:
        print(f">>> [LOGIC ERROR] Lỗi create_production_record_on_changeover: {e}")
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
        s_start, s_end = to_sec(s.get("shiftstarttime")), to_sec(s.get("shiftendtime"))
        is_in_shift = False
        if s_start <= s_end:
            if s_start <= current_seconds <= s_end: is_in_shift = True
        else:
            if current_seconds >= s_start or current_seconds <= s_end: is_in_shift = True
        if is_in_shift:
            active_shift = s
            active_shift["_start_sec"], active_shift["_end_sec"] = s_start, s_end
            break

    if not active_shift: active_shift = {"shiftcode": "SHIFT_01", "_start_sec": 21600, "_end_sec": 50400}
    start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(seconds=active_shift["_start_sec"])
    end_dt = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(seconds=active_shift["_end_sec"])
    if active_shift["_start_sec"] > active_shift["_end_sec"]:
        if current_seconds >= active_shift["_start_sec"]: end_dt += timedelta(days=1)
        else: start_dt -= timedelta(days=1)

    break_info = active_shift.get("breaktime", {})
    b_start_sec, b_end_sec = break_info.get("breakstart"), break_info.get("breakend")
    breakstart_dt = breakend_dt = None
    if b_start_sec is not None and b_end_sec is not None:
        breakstart_dt = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(seconds=b_start_sec)
        breakend_dt = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(seconds=b_end_sec)
        if active_shift["_start_sec"] > active_shift["_end_sec"]:
            if current_seconds >= active_shift["_start_sec"]:
                if b_start_sec < active_shift["_start_sec"]: breakstart_dt += timedelta(days=1); breakend_dt += timedelta(days=1)
            else:
                if b_start_sec > active_shift["_end_sec"]: breakstart_dt -= timedelta(days=1); breakend_dt -= timedelta(days=1)
    
    utc_now, local_now = datetime.utcnow(), datetime.now()
    offset = local_now - utc_now
    return {
        "shiftcode": active_shift["shiftcode"],
        "startshift": start_dt - offset, "endshift": end_dt - offset,
        "breakstart": (breakstart_dt - offset) if breakstart_dt else None,
        "breakend": (breakend_dt - offset) if breakend_dt else None
    }

async def get_current_shift_code() -> str:
    info = await get_current_shift()
    return info["shiftcode"]

async def initialize_production_record(machinecode: str, productcode: str):
    try:
        m_code, p_code = machinecode.strip(), productcode.strip() if productcode else ""
        db_master = get_database()
        shift_info = await get_current_shift()
        wp_doc = await db_master["workingparameter"].find_one({"productcode": p_code})
        if not wp_doc: wp_doc = await db_master["workingparameter"].find_one({"productcode": {"$regex": f"^{p_code}$", "$options": "i"}})
        idealcyclesec = wp_doc["idealcyclesec"] if wp_doc and "idealcyclesec" in wp_doc else 1.0
        product_doc = await db_master["product"].find_one({"productcode": p_code})
        if not product_doc: product_doc = await db_master["product"].find_one({"productcode": {"$regex": f"^{p_code}$", "$options": "i"}})
        plannedqty = product_doc.get("plannedqty", 0) if product_doc else 0
        p_name = product_doc.get("productname") if product_doc else None

        machine_doc = await db_master["machine"].find_one({"machinecode": m_code})
        if not machine_doc: machine_doc = await db_master["machine"].find_one({"machinecode": {"$regex": f"^{m_code}$", "$options": "i"}})
        m_name = machine_doc.get("machinename") if machine_doc else None

        now = datetime.utcnow()
        prefix = f"{p_code}-{now.strftime('%d-%m-%Y')}-{m_code}"
        db = get_production_db()
        count = await db.production_records.count_documents({"_id": {"$regex": f"^{prefix}-"}})
        record_id = f"{prefix}-{count + 1}"
        record = ProductionRecord(
            id=record_id, machinecode=m_code, productcode=p_code,
            shiftcode=shift_info["shiftcode"], startshift=shift_info["startshift"],
            endshift=shift_info["endshift"], breakstart=shift_info["breakstart"],
            breakend=shift_info["breakend"], status="running", machinestatus="running",
            productname=p_name, machinename=m_name,
            is_synced=False, stats={"idealcyclesec": round(float(idealcyclesec), 2), "PlannedQty": plannedqty}
        )
        await db.production_records.insert_one(record.model_dump(by_alias=True, exclude_none=True))
        init_doc = record.model_dump(by_alias=True, exclude_none=True)
        if "_id" in init_doc: init_doc["_id"] = str(init_doc["_id"])
        mqtt_publish("topic/get/productionrecord", init_doc)
        print(f">>> [LOGIC] Khởi tạo ProductionRecord mới: {record_id}")
        return record
    except Exception as e:
        print(f">>> [LOGIC ERROR] Lỗi initialize_production_record: {e}")
        return None

async def update_current_production_stats(machinecode: str, do_publish: bool = True):
    try:
        db, now, m_code = get_production_db(), datetime.utcnow(), machinecode.strip()
        record_doc = await db.production_records.find_one({"machinecode": m_code, "status": "running"}, sort=[("createtime", -1)])
        if not record_doc: return
        start_time, record_id = record_doc["createtime"], record_doc["_id"]
        iot_result = await db.iot_records.aggregate([{"$match": {"machinecode": m_code, "timestamp": {"$gte": start_time, "$lte": now}}}, {"$group": {"_id": None, "total_count": {"$sum": 1}}}]).to_list(1)
        total_count = iot_result[0]["total_count"] if iot_result else 0
        defect_result = await db.defect_records.aggregate([{"$match": {"machinecode": m_code, "timestamp": {"$gte": start_time, "$lte": now}}}, {"$group": {"_id": None, "defect_count": {"$sum": 1}}}]).to_list(1)
        defect_count = defect_result[0]["defect_count"] if defect_result else 0
        run_seconds = int((now - start_time).total_seconds())
        downtime_seconds = await calculate_downtime_in_range(m_code, start_time, now)
        
        db_master = get_database()
        p_code = record_doc.get("productcode", "").strip()
        wp_doc = await db_master["workingparameter"].find_one({"productcode": p_code})
        if not wp_doc: wp_doc = await db_master["workingparameter"].find_one({"productcode": {"$regex": f"^{p_code}$", "$options": "i"}})
        idealcyclesec = wp_doc["idealcyclesec"] if wp_doc and "idealcyclesec" in wp_doc else 1.0
        product_doc = await db_master["product"].find_one({"productcode": p_code})
        if not product_doc: product_doc = await db_master["product"].find_one({"productcode": {"$regex": f"^{p_code}$", "$options": "i"}})
        plannedqty = product_doc.get("plannedqty", 0) if product_doc else 0
        active_dt = await db.downtime_records.find_one({"machinecode": m_code, "status": "active"})
        
        actual_run_seconds = max(0, run_seconds - downtime_seconds)
        availability = actual_run_seconds / run_seconds if run_seconds > 0 else 0.0
        if total_count > 0:
            performance = (idealcyclesec * total_count) / actual_run_seconds if actual_run_seconds > 0 else 0.0
            quality = (total_count - defect_count) / total_count
            oee = availability * performance * quality
            avg_cycle = actual_run_seconds / total_count
        else: performance = quality = oee = avg_cycle = 0.0
        machine_status_now = "stopped" if active_dt else "running"
        
        # Lấy tên sản phẩm và tên máy để cập nhật (nếu chưa có hoặc để đảm bảo đồng bộ)
        p_name = product_doc.get("productname") if product_doc else None
        machine_doc = await db_master["machine"].find_one({"machinecode": m_code})
        if not machine_doc: machine_doc = await db_master["machine"].find_one({"machinecode": {"$regex": f"^{m_code}$", "$options": "i"}})
        m_name = machine_doc.get("machinename") if machine_doc else None

        update_data = {"$set": {
            "machinestatus": machine_status_now,
            "productname": p_name,
            "machinename": m_name,
            "kpis": {"availability": round(availability, 2), "performance": round(performance, 2), "quality": round(quality, 2), "oee": round(oee, 2)},
            "stats": {"total_count": total_count, "defect_count": defect_count, "good_product": int(total_count - defect_count), "avg_cycle": round(avg_cycle, 2), "run_seconds": run_seconds, "actual_run_seconds": actual_run_seconds, "downtime_seconds": downtime_seconds, "idealcyclesec": round(float(idealcyclesec), 2), "PlannedQty": plannedqty}
        }}
        await db.production_records.update_one({"_id": record_id}, update_data)
        if do_publish:
            updated_doc = await db.production_records.find_one({"_id": record_id})
            if updated_doc:
                if "_id" in updated_doc: updated_doc["_id"] = str(updated_doc["_id"])
                mqtt_publish("topic/get/productionrecord", updated_doc)
    except Exception as e: print(f">>> [LOGIC ERROR] Lỗi update_current_production_stats: {e}")

async def check_and_create_downtime():
    try:
        db, db_master, now = get_production_db(), get_database(), datetime.utcnow()
        active_prods = await db.production_records.find({"status": "running"}).to_list(None)
        for prod in active_prods:
            m_code, p_code = prod["machinecode"].strip(), prod.get("productcode", "").strip()
            wp_doc = await db_master["workingparameter"].find_one({"productcode": p_code})
            threshold = wp_doc.get("downtimethreshold", 300) if wp_doc else 300
            if await db.downtime_records.find_one({"machinecode": m_code, "status": "active"}): continue
            last_iot = await db.iot_records.find_one({"machinecode": m_code}, sort=[("timestamp", -1)])
            last_ts = last_iot["timestamp"] if last_iot else prod["createtime"]
            
            # Kiểm tra xem đã có bản ghi downtime nào với start_time này chưa (tránh trùng lặp do polling)
            if await db.downtime_records.find_one({"machinecode": m_code, "start_time": last_ts}): continue
            if (now - last_ts).total_seconds() > threshold:
                new_dt = DowntimeRecord(machinecode=m_code, start_time=last_ts, status="active")
                res = await db.downtime_records.insert_one(new_dt.model_dump(by_alias=True, exclude_none=True))
                new_id = res.inserted_id
                mqtt_publish("topic/downtimeinput", {"id": str(new_id), "machine": m_code, "status": "active", "downtimecode": "default", "createtime": last_ts, "endtime": "None", "duration": 0})
    except Exception as e: print(f">>> [DOWNTIME ERROR] Lỗi check_and_create_downtime: {e}")

async def close_active_downtime(machinecode: str):
    try:
        db, now, m_code = get_production_db(), datetime.utcnow(), machinecode.strip()
        active_dts = await db.downtime_records.find({"machinecode": m_code, "status": "active"}).to_list(None)
        if active_dts:
            for dt in active_dts:
                duration = int((now - dt["start_time"]).total_seconds())
                await db.downtime_records.update_one({"_id": dt["_id"]}, {"$set": {"end_time": now, "duration_seconds": max(0, duration), "status": "closed"}})
            last_dt = active_dts[-1]
            last_duration = int((now - last_dt["start_time"]).total_seconds())
            d_code = last_dt.get("downtime_code") or "default"
            mqtt_publish("topic/downtimeinput", {"id": str(last_dt["_id"]), "machine": m_code, "status": "closed", "downtimecode": d_code, "createtime": last_dt["start_time"], "endtime": now, "duration": max(0, last_duration)})
            return True
        return False
    except Exception as e: print(f">>> [DOWNTIME ERROR] Lỗi close_active_downtime: {e}"); return False

async def get_current_shift_stats(machinecode: str):
    try:
        db, shift_info, m_code = get_production_db(), await get_current_shift(), machinecode.strip()
        records = await db.production_records.find({"machinecode": m_code, "shiftcode": shift_info["shiftcode"], "createtime": {"$gte": shift_info["startshift"]}}).to_list(None)
        total_count = defect_count = run_seconds = actual_run_seconds = downtime_seconds = 0
        total_standard_time = weighted_avg_cycle_sum = 0.0
        product_plans, db_master = {}, get_database()
        for r in records:
            stats = r.get("stats", {})
            dur = stats.get("run_seconds", 0)
            total_count += stats.get("total_count", 0)
            defect_count += stats.get("defect_count", 0)
            run_seconds += dur
            actual_run_seconds += stats.get("actual_run_seconds", 0)
            downtime_seconds += stats.get("downtime_seconds", 0)
            ideal, avg, p_code = stats.get("idealcyclesec", 1.0), stats.get("avg_cycle", 0.0), r.get("productcode", "").strip()
            p_qty = stats.get("PlannedQty", stats.get("plannedqty", 0))
            if p_code:
                if p_qty == 0:
                    p_doc = await db_master["product"].find_one({"productcode": p_code}) or await db_master["product"].find_one({"productcode": {"$regex": f"^{p_code}$", "$options": "i"}})
                    p_qty = p_doc.get("plannedqty", 0) if p_doc else 0
                product_plans[p_code] = max(product_plans.get(p_code, 0), p_qty)
            total_standard_time += ideal * stats.get("total_count", 0)
            weighted_avg_cycle_sum += avg * dur
            
        availability = actual_run_seconds / run_seconds if run_seconds > 0 else 0.0
        performance = total_standard_time / actual_run_seconds if actual_run_seconds > 0 else 0.0
        quality = (total_count - defect_count) / total_count if total_count > 0 else 0.0
        oee = availability * performance * quality
        shift_ideal = total_standard_time / total_count if total_count > 0 else 0.0
        # Fix: Tính vận tốc trung bình thực tế bằng tổng thời gian chạy / tổng sản phẩm
        shift_avg = actual_run_seconds / total_count if total_count > 0 else 0.0
        
        current_machine_status = "running"
        current_product_code = None
        current_product_name = None

        for r in records:
            if r.get("status") == "running":
                current_machine_status = r.get("machinestatus", "running")
                current_product_code = r.get("productcode")
                break
        
        if current_product_code:
            p_doc = await db_master["product"].find_one({"productcode": current_product_code})
            if not p_doc:
                p_doc = await db_master["product"].find_one({"productcode": {"$regex": f"^{current_product_code}$", "$options": "i"}})
            if p_doc:
                current_product_name = p_doc.get("productname")
        
        m_doc = await db_master["machine"].find_one({"machinecode": m_code})
        if not m_doc:
            m_doc = await db_master["machine"].find_one({"machinecode": {"$regex": f"^{m_code}$", "$options": "i"}})
        current_machine_name = m_doc.get("machinename") if m_doc else None

        summary = {
            "_id": f"{shift_info['shiftcode']}-{shift_info['startshift'].strftime('%d%m%Y')}-{m_code}",
            "machinecode": m_code, "shiftcode": shift_info["shiftcode"], "startshift": shift_info["startshift"], 
            "endshift": shift_info["endshift"], "timestamp": datetime.utcnow(),
            "machinestatus": current_machine_status,
            "productcode": current_product_code,
            "productname": current_product_name,
            "machinename": current_machine_name,
            "kpis": {"availability": round(availability, 2), "performance": round(performance, 2), "quality": round(quality, 2), "oee": round(oee, 2)},
            "stats": {
                "total_count": total_count, "defect_count": defect_count, "good_product": int(total_count - defect_count), "run_seconds": run_seconds, 
                "actual_run_seconds": actual_run_seconds, "downtime_seconds": downtime_seconds, 
                "idealcyclesec": round(shift_ideal, 2), "avg_cycle": round(shift_avg, 2), 
                "PlannedQty": sum(product_plans.values()), "StandardTime": round(total_standard_time, 2)
            }
        }
        await db.shift_stats.replace_one({"_id": summary["_id"]}, summary, upsert=True)
        return summary
    except Exception as e: print(f">>> [LOGIC ERROR] Lỗi get_current_shift_stats: {e}"); return None

async def ensure_active_production_records():
    try:
        db_master, db_prod, shift_info = get_database(), get_production_db(), await get_current_shift()
        machines = await db_master["machine"].find().to_list(None)
        for m in machines:
            m_code = m.get("machinecode", "").strip()
            if m_code and not await db_prod.production_records.find_one({"machinecode": m_code, "shiftcode": shift_info["shiftcode"], "createtime": {"$gte": shift_info["startshift"]}}):
                last = await db_prod.production_records.find_one({"machinecode": m_code}, sort=[("createtime", -1)])
                if last: await initialize_production_record(m_code, last.get("productcode", ""))
    except Exception as e: print(f">>> [AUTO-RECORD ERROR] Lỗi ensure_active_production_records: {e}")
