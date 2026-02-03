from datetime import datetime
from app.storage.db import db_production, get_database
from app.storage.schemas import IoTRecord
from app.engine.logic import (
    create_production_record_on_changeover, 
    initialize_production_record,
    update_current_production_stats,
    close_active_downtime
)
from app.config import THRESHOLD, NODE_ID
from app.utils.messaging import mqtt_publish

async def process_and_save_defect(ai_data, machinecode=None):
    if ai_data is None:
        return None

    count = ai_data["count"]
    
    if count < THRESHOLD:
        print(f">>> [AI] Phát hiện lỗi: {count} < {THRESHOLD}. Đang lưu DefectRecord...")
        machinecode = machinecode.strip() if machinecode else None
        defect_doc = {
            "timestamp": datetime.utcnow(),
            "node_id": NODE_ID,
            "machinecode": machinecode,
            "defectcode": "d1",
            "source": "CAM",
            "raw_image": ai_data["image_bytes"]
        }
        await db_production["defect_records"].insert_one(defect_doc)
        # Cập nhật KPI ngay khi có lỗi
        await update_current_production_stats(machinecode)
        return True
    
    print(f">>> [AI] OK: Số lượng {count} đạt yêu cầu.")
    return False

async def process_and_save_hmi_defect(hmi_data):
    if not hmi_data:
        return False

    try:
        print(f">>> [PROCESSOR] Nhận dữ liệu Defect từ HMI: {hmi_data}")
        machinecode = (hmi_data.get("device") or hmi_data.get("machinecode", "")).strip()
        defectcode = (hmi_data.get("defectcode", "")).strip()
        
        if not machinecode:
            print(">>> [DB ERROR] Lưu HMI Defect thất bại: Thiếu machinecode/device")
            return False

        defect_doc = {
            "timestamp": datetime.utcnow(),
            "machinecode": machinecode,
            "defectcode": defectcode,
            "source": "HMI"
        }
        await db_production["defect_records"].insert_one(defect_doc)
        print(f">>> [DB] Đã lưu Defect từ HMI: {defectcode} cho {machinecode}")
        # Cập nhật KPI ngay khi có lỗi từ HMI
        await update_current_production_stats(machinecode)
        return True
    except Exception as e:
        print(f">>> [DB ERROR] Lưu HMI Defect thất bại: {e}")
        return False

async def process_and_save_counter(counter_msg):
    if not counter_msg:
        return False

    try:
        machinecode = counter_msg.get("device", "").strip()
        raw_value = counter_msg.get("shootcountnumber", 0)
        now = datetime.utcnow()
        
        # 0. Nếu đang có downtime active thì đóng lại
        await close_active_downtime(machinecode)

        # 1. Tìm bản ghi gần nhất để tính actual_cycle_time
        actual_cycle_time = 0.0
        last_record = await db_production["iot_records"].find_one(
            {"machinecode": machinecode},
            sort=[("timestamp", -1)]
        )
        
        if last_record and "timestamp" in last_record:
            prev_ts = last_record["timestamp"]
            diff = (now - prev_ts).total_seconds()
            # Giới hạn giá trị hợp lý (ví dụ: nếu lâu quá không có signal thì reset hoặc cap lại)
            actual_cycle_time = round(diff, 2)
            
        # 2. Tạo record với cấu trúc object mới
        record = IoTRecord(
            timestamp=now,
            machinecode=machinecode,
            data={
                "raw_value": raw_value,
                "actual_cycle_time": actual_cycle_time
            }
        )
        
        doc = record.model_dump(by_alias=True, exclude_none=True)
        if "id" in doc:
            doc["_id"] = doc.pop("id")
        if "_id" in doc and doc["_id"] is None:
            del doc["_id"]
            
        await db_production["iot_records"].insert_one(doc)
        print(f">>> [DB] Saved IoTRecord for {machinecode}: val={raw_value}, cycle={actual_cycle_time}s")
        
        # Cập nhật KPI real-time cho ProductionRecord
        await update_current_production_stats(machinecode)
        return True
    except Exception as e:
        print(f">>> [DB ERROR] IoTRecord save failed: {e}")
        return False

async def process_hmi_changeover(data):
    if not data:
        return False

    try:
        print(f">>> [PROCESSOR] Nhận dữ liệu Changeover từ HMI: {data}")
        now = datetime.utcnow()
        machinecode = (data.get("device") or data.get("machinecode", "")).strip()
        new_productcode = (data.get("productcode", "")).strip()
        old_productcode = (data.get("oldproduct") or data.get("old_productcode", "")).strip()
        
        changeover_doc = {
            "timestamp": now,
            "machinecode": machinecode,
            "productcode": new_productcode,
            "oldproduct": old_productcode,
            "source": "HMI"
        }
        await db_production["changeover_records"].insert_one(changeover_doc)
        print(f">>> [DB] Đã lưu Changeover sự kiện: {new_productcode} cho {machinecode}")

        if old_productcode:
            print(f">>> [PROCESSOR] Đang chốt sản lượng cho sản phẩm cũ: {old_productcode}")
            await create_production_record_on_changeover(
                machinecode=machinecode,
                old_productcode=old_productcode,
                new_productcode=new_productcode,
                changeover_timestamp=now
            )

        print(f">>> [PROCESSOR] Đang khởi tạo bản ghi mới cho sản phẩm: {new_productcode}")
        await initialize_production_record(machinecode, new_productcode)

        return True
    except Exception as e:
        print(f">>> [DB ERROR] Lưu Changeover thất bại: {e}")
        return False

async def process_hmi_downtime_reason(data):
    """Xử lý cập nhật lý do downtime từ topic/downtimeinput."""
    if not data:
        return False
        
    try:
        machinecode = data.get("device")
        downtime_code = data.get("downtimecode")
        
        # 1. Kiểm tra tính hợp lệ của downtime_code trong Master Data
        db_master = get_database()
        master_entry = await db_master["downtimemaster"].find_one({"downtimecode": downtime_code})
        
        if not master_entry:
            print(f">>> [DOWNTIME] Từ chối msg: Mã lỗi {downtime_code} không tồn tại trong Downtime Master")
            return False
            
        # Ưu tiên lấy reason từ Master Data nếu message không có reason chi tiết
        reason = data.get("reason") or master_entry.get("downtimename", "Unknown Reason")
        
        db = db_production
        # Tìm bản ghi downtime active gần nhất hoặc vừa mới đóng
        # Ưu tiên bản ghi đang active
        target = await db.downtime_records.find_one(
            {"machinecode": machinecode, "status": "active"},
            sort=[("start_time", -1)]
        )
        
        # Nếu không có active, tìm bản ghi vừa đóng (trong vòng 10p qua)
        if not target:
            target = await db.downtime_records.find_one(
                {"machinecode": machinecode, "status": "closed"},
                sort=[("end_time", -1)]
            )
            
        if target:
            await db.downtime_records.update_one(
                {"_id": target["_id"]},
                {"$set": {
                    "downtime_code": downtime_code,
                    "reason": reason
                }}
            )
            print(f">>> [DOWNTIME] Đã cập nhật lý do cho {machinecode}: {downtime_code} - {reason}")
            
            # --- NEW: Gửi thông báo MQTT sau khi cập nhật lý do ---
            mqtt_publish("topic/downtimeinput", {
                "id": str(target["_id"]),
                "machine": machinecode,
                "status": target.get("status", "unknown"),
                "downtimecode": downtime_code,
                "createtime": target.get("start_time"),
                "endtime": target.get("end_time", "None")
            })
            
            # Sau khi cập nhật downtime, update lại production kpi
            await update_current_production_stats(machinecode)
            return True
        else:
            print(f">>> [DOWNTIME] Không tìm thấy bản ghi downtime để cập nhật cho {machinecode}")
            return False
            
    except Exception as e:
        print(f">>> [DOWNTIME ERROR] Lỗi update lý do: {e}")
        return False
