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
            
        # Tìm record đang chạy của máy
        existing_record = await db.production_records.find_one(
            query,
            sort=[("createtime", -1)]
        )
        
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
        new_p = new_productcode.strip() if new_productcode else ""
        
        print(f">>> [LOGIC] Bắt đầu tạo ProductionRecord cho {m_code} - {old_p}")
        sys.stdout.flush()
        db = get_production_db()
        db_master = get_database()
        now_utc = datetime.utcnow()
        
        query = {"machinecode": m_code, "status": "running"}
        if target_record_id:
            query = {"_id": target_record_id}
            
        existing_record = await db.production_records.find_one(
            query,
            sort=[("createtime", -1)]
        )
        
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
            {"$match": {
                "machinecode": m_code,
                "timestamp": {"$gte": start_time, "$lt": changeover_timestamp}
            }},
            {"$group": {"_id": None, "total_count": {"$sum": 1}}}
        ]
        iot_result = await db.iot_records.aggregate(iot_pipeline).to_list(1)
        total_count = iot_result[0]["total_count"] if iot_result else 0
        
        defect_pipeline = [
            {"$match": {
                "machinecode": m_code,
                "timestamp": {"$gte": start_time, "$lt": changeover_timestamp}
            }},
            {"$group": {"_id": None, "defect_count": {"$sum": 1}}}
        ]
        defect_result = await db.defect_records.aggregate(defect_pipeline).to_list(1)
        defect_count = defect_result[0]["defect_count"] if defect_result else 0
        
        run_seconds = int((changeover_timestamp - start_time).total_seconds())
        # Aggregate downtime for this record
        downtime_pipeline = [
            {"$match": {
                "machinecode": m_code,
                "start_time": {"$gte": start_time, "$lte": changeover_timestamp}
            }},
            {"$group": {"_id": None, "total_downtime": {"$sum": "$duration_seconds"}}}
        ]
        downtime_result = await db.downtime_records.aggregate(downtime_pipeline).to_list(1)
        downtime_seconds = downtime_result[0]["total_downtime"] if downtime_result else 0
        
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
            availability = performance = quality = oee = avg_cycle = 0.0
        
        shift_info = await get_current_shift()

        record = ProductionRecord(
            id=target_id,
            endtime=changeover_timestamp,
            createtime=start_time,
            machinecode=m_code,
            productcode=actual_productcode,
            shiftcode=shift_info["shiftcode"],
            startshift=shift_info["startshift"],
            endshift=shift_info["endshift"],
            breakstart=shift_info["breakstart"],
            breakend=shift_info["breakend"],
            status="closed",
            is_synced=False,
            kpis={
                "availability": round(availability, 4),
                "performance": round(performance, 4),
                "quality": round(quality, 4),
                "oee": round(oee, 4)
            },
            stats={
                "total_count": total_count,
                "defect_count": defect_count,
                "avg_cycle": round(avg_cycle, 2),
                "run_seconds": run_seconds,
                "actual_run_seconds": actual_run_seconds,
                "downtime_seconds": downtime_seconds,
                "idealcyclesec": idealcyclesec,
                "plannedqty": plannedqty
            }
        )
        
        await db.production_records.replace_one(
            {"_id": target_id}, 
            record.model_dump(by_alias=True, exclude_none=True),
            upsert=True
        )
        # Publish closed record
        final_doc = record.model_dump(by_alias=True, exclude_none=True)
        if "_id" in final_doc: final_doc["_id"] = str(final_doc["_id"])
        mqtt_publish("topic/get/productionrecord", final_doc)

        print(f">>> [LOGIC] Đã ngắt (Finalized) ProductionRecord: {target_id} (OEE={record.kpis.oee})")
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

    # Chuyển đổi sang UTC để khớp với dữ liệu trong DB
    utc_now = datetime.utcnow()
    local_now = datetime.now()
    offset = local_now - utc_now
    
    start_utc = start_dt - offset
    end_utc = end_dt - offset
    breakstart_utc = (breakstart_dt - offset) if breakstart_dt else None
    breakend_utc = (breakend_dt - offset) if breakend_dt else None

    return {
        "shiftcode": active_shift["shiftcode"],
        "startshift": start_utc, "endshift": end_utc,
        "breakstart": breakstart_utc, "breakend": breakend_utc
    }

async def get_current_shift_code() -> str:
    info = await get_current_shift()
    return info["shiftcode"]

async def initialize_production_record(machinecode: str, productcode: str):
    try:
        m_code = machinecode.strip()
        p_code = productcode.strip() if productcode else ""
        
        db_master = get_database()
        shift_info = await get_current_shift()
        
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
        prefix = f"{p_code}-{date_str}-{m_code}"
        
        db = get_production_db()
        regex = f"^{prefix}-"
        count = await db.production_records.count_documents({"_id": {"$regex": regex}})
        new_stt = count + 1
        record_id = f"{prefix}-{new_stt}"

        record = ProductionRecord(
            id=record_id,
            machinecode=m_code,
            productcode=p_code,
            shiftcode=shift_info["shiftcode"],
            startshift=shift_info["startshift"],
            endshift=shift_info["endshift"],
            breakstart=shift_info["breakstart"],
            breakend=shift_info["breakend"],
            status="running",
            machinestatus="running",
            is_synced=False,
            stats={
                "idealcyclesec": idealcyclesec,
                "plannedqty": plannedqty
            }
        )
        
        await db.production_records.insert_one(record.model_dump(by_alias=True, exclude_none=True))
        # Publish initial record
        init_doc = record.model_dump(by_alias=True, exclude_none=True)
        if "_id" in init_doc: init_doc["_id"] = str(init_doc["_id"])
        mqtt_publish("topic/get/productionrecord", init_doc)
        print(f">>> [LOGIC] Đã khởi tạo ProductionRecord mới: {record_id}")
        return record
    except Exception as e:
        print(f">>> [LOGIC ERROR] Lỗi trong initialize_production_record: {e}")
        return None
async def update_current_production_stats(machinecode: str, do_publish: bool = True):
    """Cập nhật real-time stats và kpis cho ProductionRecord đang chạy."""
    try:
        db = get_production_db()
        now = datetime.utcnow()
        m_code = machinecode.strip()
        
        # 1. Lấy record đang active
        record_doc = await db.production_records.find_one(
            {"machinecode": m_code, "status": "running"},
            sort=[("createtime", -1)]
        )
        if not record_doc:
            print(f">>> [DEBUG ERROR] Không tìm thấy bản ghi 'running' cho máy: '{m_code}'")
            return
            
        start_time = record_doc["createtime"]
        record_id = record_doc["_id"]
        
        # 2. Tính tổng sản lượng (total_count)
        iot_pipeline = [
            {"$match": {
                "machinecode": m_code,
                "timestamp": {"$gte": start_time, "$lte": now}
            }},
            {"$group": {"_id": None, "total_count": {"$sum": 1}}}
        ]
        iot_result = await db.iot_records.aggregate(iot_pipeline).to_list(1)
        total_count = iot_result[0]["total_count"] if iot_result else 0
        
        # 3. Tính số lượng lỗi (defect_count)
        defect_pipeline = [
            {"$match": {
                "machinecode": machinecode,
                "timestamp": {"$gte": start_time, "$lte": now}
            }},
            {"$group": {"_id": None, "defect_count": {"$sum": 1}}}
        ]
        defect_result = await db.defect_records.aggregate(defect_pipeline).to_list(1)
        defect_count = defect_result[0]["defect_count"] if defect_result else 0
        
        # 4. Tính toán thời gian và OEE
        run_seconds = int((now - start_time).total_seconds())
        # Lấy các tham số từ stats hiện tại hoặc mặc định
        current_stats = record_doc.get("stats", {})
        idealcyclesec = current_stats.get("idealcyclesec", 1.0)
        plannedqty = current_stats.get("plannedqty", 0)
        
        # --- NEW: Tính toán Downtime thực tế ---
        # Lấy tổng downtime từ bảng downtime_records cho bản ghi này
        downtime_pipeline = [
            {"$match": {
                "machinecode": m_code,
                "start_time": {"$gte": start_time}
            }},
            {"$group": {"_id": None, "total_downtime": {"$sum": "$duration_seconds"}}}
        ]
        downtime_result = await db.downtime_records.aggregate(downtime_pipeline).to_list(1)
        downtime_seconds = downtime_result[0]["total_downtime"] if downtime_result else 0
        
        # Nếu đang có downtime active, tính thêm thời gian trôi qua từ lúc start downtime đến hiện tại
        active_dt = await db.downtime_records.find_one({"machinecode": m_code, "status": "active"})
        if active_dt:
            current_dt_seconds = int((now - active_dt["start_time"]).total_seconds())
            downtime_seconds += max(0, current_dt_seconds)

        # Tính toán thời gian thực tế (Luôn tính, không phụ thuộc total_count)
        actual_run_seconds = max(0, run_seconds - downtime_seconds)
        availability = actual_run_seconds / run_seconds if run_seconds > 0 else 0.0

        if total_count > 0:
            ideal_total_time = idealcyclesec * total_count
            performance = ideal_total_time / actual_run_seconds if actual_run_seconds > 0 else 0.0
            quality = (total_count - defect_count) / total_count
            oee = availability * performance * quality
            avg_cycle = actual_run_seconds / total_count
        else:
            # Nếu chưa có sản phẩm, P và Q mặc định là 0, OEE là 0, nhưng A vẫn phản ánh đúng trạng thái dừng/chạy
            performance = quality = oee = avg_cycle = 0.0

        # 5. Xác định machinestatus (running/stopped)
        active_dt = await db.downtime_records.find_one({"machinecode": machinecode, "status": "active"})
        machine_status_now = "stopped" if active_dt else "running"

        # 6. Cập nhật vào DB
        update_data = {
            "$set": {
                "machinestatus": machine_status_now,
                "kpis": {
                    "availability": round(availability, 4),
                    "performance": round(performance, 4),
                    "quality": round(quality, 4),
                    "oee": round(oee, 4)
                },
                "stats": {
                    "total_count": total_count,
                    "defect_count": defect_count,
                    "avg_cycle": round(avg_cycle, 2),
                    "run_seconds": run_seconds, # Tổng thời gian kể từ đầu ca
                    "actual_run_seconds": actual_run_seconds,
                    "downtime_seconds": downtime_seconds,
                    "idealcyclesec": idealcyclesec,
                    "plannedqty": plannedqty
                }
            }
        }
        
        res = await db.production_records.update_one({"_id": record_id}, update_data)
        # --- Tự động publish sau khi cập nhật (nếu yêu cầu) ---
        if do_publish:
            updated_doc = await db.production_records.find_one({"_id": record_id})
            if updated_doc:
                if "_id" in updated_doc: updated_doc["_id"] = str(updated_doc["_id"])
                mqtt_publish("topic/get/productionrecord", updated_doc)

        if res.modified_count > 0:
            print(f">>> [LOGIC] Đã cập nhật thành công {machinecode}: OEE={round(oee*100, 2)}%")
        else:
            print(f">>> [LOGIC] Không có thay đổi dữ liệu cho {machinecode}")
            
    except Exception as e:
        print(f">>> [LOGIC ERROR] Lỗi update_current_production_stats: {e}")

async def check_and_create_downtime():
    """Kiểm tra và tạo DowntimeRecord nếu quá threshold không có counter."""
    try:
        db = get_production_db()
        db_master = get_database()
        now = datetime.utcnow()
        
        # Lấy tất cả các máy đang có ProductionRecord "running"
        active_productions = await db.production_records.find({"status": "running"}).to_list(None)
        
        for prod in active_productions:
            m_code = prod["machinecode"].strip()
            p_code = prod.get("productcode").strip() if prod.get("productcode") else ""
            
            # Lấy threshold từ bảng workingparameter
            wp_doc = await db_master["workingparameter"].find_one({"productcode": p_code})
            # Nếu không tìm thấy hoặc không có field, mặc định là 300s (5 phút)
            threshold_seconds = wp_doc.get("downtimethreshold", 300) if wp_doc else 300
            
            # Kiểm tra xem đã có downtime active chưa
            active_dt = await db.downtime_records.find_one({"machinecode": m_code, "status": "active"})
            if active_dt:
                continue
                
            # Kiểm tra lần cuối nhận counter
            last_iot = await db.iot_records.find_one(
                {"machinecode": m_code},
                sort=[("timestamp", -1)]
            )
            
            last_ts = last_iot["timestamp"] if last_iot else prod["createtime"]
            diff_seconds = (now - last_ts).total_seconds()
            
            if diff_seconds > threshold_seconds:
                # Tạo bản ghi downtime mới
                new_dt = DowntimeRecord(
                    machinecode=m_code,
                    start_time=last_ts,
                    status="active",
                    downtime_code="default",
                    reason=""
                )
                await db.downtime_records.insert_one(new_dt.model_dump(by_alias=True, exclude_none=True))
                print(f">>> [DOWNTIME] Phát hiện máy {m_code} dừng hoạt động. Đã tạo DowntimeRecord.")
                
                # --- NEW: Gửi thông báo MQTT ---
                mqtt_publish("topic/downtimeinput", {
                    "id": str(new_dt.id) if new_dt.id else "new",
                    "machine": m_code,
                    "status": "active",
                    "downtimecode": new_dt.downtime_code,
                    "createtime": new_dt.start_time,
                    "endtime": "None"
                })

    except Exception as e:
        print(f">>> [DOWNTIME ERROR] Lỗi trong check_and_create_downtime: {e}")

async def close_active_downtime(machinecode: str):
    """Đóng tất cả bản ghi downtime đang active của máy khi có counter trở lại."""
    try:
        db = get_production_db()
        now = datetime.utcnow()
        m_code = machinecode.strip()
        
        # Tìm các bản ghi đang active
        active_dts = await db.downtime_records.find({"machinecode": m_code, "status": "active"}).to_list(None)
        
        if active_dts:
            for dt in active_dts:
                start_time = dt["start_time"]
                duration = int((now - start_time).total_seconds())
                
                await db.downtime_records.update_one(
                    {"_id": dt["_id"]},
                    {
                        "$set": {
                            "end_time": now,
                            "duration_seconds": max(0, duration),
                            "status": "closed"
                        }
                    }
                )
            print(f">>> [DOWNTIME] Máy {m_code} hoạt động trở lại. Đã đóng {len(active_dts)} bản ghi downtime.")
            
            # Gửi thông báo MQTT cho bản ghi cuối cùng (để HMI cập nhật)
            last_dt = active_dts[-1]
            mqtt_publish("topic/downtimeinput", {
                "id": str(last_dt["_id"]),
                "machine": m_code,
                "status": "closed",
                "downtimecode": "",
                "createtime": last_dt["start_time"],
                "endtime": now
            })
            return True
        return False
    except Exception as e:
        print(f">>> [DOWNTIME ERROR] Lỗi trong close_active_downtime: {e}")
        return False


async def get_current_shift_stats(machinecode: str):
    """Tổng hợp KPI và Stats của nguyên ca hiện tại cho một máy."""
    try:
        db = get_production_db()
        shift_info = await get_current_shift()
        m_code = machinecode.strip()
        
        # Tìm tất cả các record của máy này trong ca hiện tại
        # Bao gồm cả 'running' và 'closed'
        records = await db.production_records.find({
            "machinecode": m_code,
            "shiftcode": shift_info["shiftcode"],
            "createtime": {"$gte": shift_info["startshift"]}
        }).to_list(None)
        
        total_count = 0
        defect_count = 0
        run_seconds = 0
        actual_run_seconds = 0
        downtime_seconds = 0
        weighted_ideal_time = 0.0
        
        for r in records:
            stats = r.get("stats", {})
            total_count += stats.get("total_count", 0)
            defect_count += stats.get("defect_count", 0)
            run_seconds += stats.get("run_seconds", 0)
            actual_run_seconds += stats.get("actual_run_seconds", 0)
            downtime_seconds += stats.get("downtime_seconds", 0)
            
            # Tính weighted ideal time for P
            ideal = stats.get("idealcyclesec", 1.0)
            weighted_ideal_time += ideal * stats.get("total_count", 0)
            
        # Tính toán KPI tổng của ca
        availability = actual_run_seconds / run_seconds if run_seconds > 0 else 0.0
        performance = weighted_ideal_time / actual_run_seconds if actual_run_seconds > 0 else 0.0
        quality = (total_count - defect_count) / total_count if total_count > 0 else 0.0
        oee = availability * performance * quality
        
        summary = {
            "machinecode": m_code,
            "shiftcode": shift_info["shiftcode"],
            "startshift": shift_info["startshift"],
            "endshift": shift_info["endshift"],
            "timestamp": datetime.utcnow(),
            "kpis": {
                "availability": round(availability, 4),
                "performance": round(performance, 4),
                "quality": round(quality, 4),
                "oee": round(oee, 4)
            },
            "stats": {
                "total_count": total_count,
                "defect_count": defect_count,
                "run_seconds": run_seconds,
                "actual_run_seconds": actual_run_seconds,
                "downtime_seconds": downtime_seconds
            }
        }
        return summary
    except Exception as e:
        print(f">>> [LOGIC ERROR] Lỗi get_current_shift_stats: {e}")
        return None

async def ensure_active_production_records():
    """Kiểm tra tất cả các máy, nếu trong ca hiện tại chưa có record thì tự động sinh ra."""
    try:
        db_master = get_database()
        db_prod = get_production_db()
        
        # 1. Lấy danh sách máy từ danh mục
        # Lưu ý: collection tên là 'machine' (theo logic xử lý trước đó)
        machines = await db_master["machine"].find().to_list(None)
        if not machines:
            # Try 'machine_master' just in case, but schemas.py has MachineMaster
            # and README says database 'masterdata'
            print(">>> [AUTO-RECORD] Không tìm thấy danh sách máy trong masterdata.machine")
            return

        # 2. Lấy thông tin ca hiện tại
        shift_info = await get_current_shift()
        shift_code = shift_info["shiftcode"]
        start_shift = shift_info["startshift"]

        for m in machines:
            m_code = m.get("machinecode", "").strip()
            if not m_code: continue

            # 3. Kiểm tra thông minh hơn: Theo Mã ca và Ranh giới thời gian của ca đó
            shift_start_utc = shift_info["startshift"]
            exists = await db_prod.production_records.find_one({
                "machinecode": m_code,
                "shiftcode": shift_code,
                "createtime": {"$gte": shift_start_utc}
            })

            if not exists:
                print(f">>> [AUTO-RECORD] Máy {m_code} chưa có bản ghi trong ca {shift_code}. Đang tự động khởi tạo...")
                
                # Tìm mã sản phẩm cuối cùng của máy này để tiếp tục sản xuất
                last_any_record = await db_prod.production_records.find_one(
                    {"machinecode": m_code},
                    sort=[("createtime", -1)]
                )
                
                p_code = ""
                if last_any_record:
                    p_code = last_any_record.get("productcode", "")
                
                # Nếu không tìm thấy sản phẩm cũ, có thể lấy từ iot_records gần nhất
                if not p_code:
                    last_iot = await db_prod.iot_records.find_one(
                        {"machinecode": m_code},
                        sort=[("timestamp", -1)]
                    )
                    if last_iot:
                        # Lưu ý: Schema IoTRecord không chứa productcode, thường chỉ lấy từ ProductionRecord
                        pass

                if p_code:
                    await initialize_production_record(m_code, p_code)
                    print(f">>> [AUTO-RECORD] Tự động tạo bản ghi thành công cho {m_code} - {p_code}")
                else:
                    print(f">>> [AUTO-RECORD] Không tìm thấy mã sản phẩm cũ cho máy {m_code}, bỏ qua tự động sinh.")

    except Exception as e:
        print(f">>> [AUTO-RECORD ERROR] Lỗi trong ensure_active_production_records: {e}")
