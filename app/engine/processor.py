from datetime import datetime
from bson import ObjectId
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
        # Nếu là msg do chính hệ thống phản hồi (có status), bỏ qua để tránh vòng lặp
        if "status" in data:
            return False

        record_id_str = data.get("id")
        machinecode = (data.get("machine") or data.get("device") or "").strip()
        downtime_code = (data.get("downtimecode") or "").strip()
        
        if not record_id_str:
            print(">>> [DOWNTIME] Từ chối msg: Thiếu ID bản ghi")
            return False

        # 1. Kiểm tra tính hợp lệ của downtime_code trong Master Data (Case-insensitive)
        db_master = get_database()
        master_entry = await db_master["downtime"].find_one({
            "downtimecode": {"$regex": f"^{downtime_code}$", "$options": "i"}
        })
        
        if not master_entry:
            print(f">>> [DOWNTIME ERROR] Mã lỗi '{downtime_code}' không tồn tại trong danh mục 'downtime'")
            return False
            
        # Sử dụng đúng mã lỗi từ Master Data thay vì mã user gửi lên
        downtime_code = master_entry.get("downtimecode", downtime_code)
            
        reason = master_entry.get("downtimename", "Unknown Reason")
        
        db = db_production
        # 2. Tìm bản ghi downtime bằng ID
        try:
            target = await db.downtime_records.find_one({"_id": ObjectId(record_id_str)})
        except:
            print(f">>> [DOWNTIME] ID không hợp lệ: {record_id_str}")
            return False
            
        if target:
            await db.downtime_records.update_one(
                {"_id": target["_id"]},
                {"$set": {
                    "downtime_code": downtime_code,
                    "reason": reason
                }}
            )
            print(f">>> [DOWNTIME] Đã cập nhật cho ID {record_id_str}: {downtime_code} - {reason}")
            
            # --- Gửi thông báo MQTT sau khi cập nhật ---
            mqtt_publish("topic/downtimeinput", {
                "id": str(target["_id"]),
                "machine": machinecode or target.get("machinecode"),
                "status": target.get("status", "unknown"),
                "downtimecode": downtime_code,
                "createtime": target.get("start_time"),
                "endtime": target.get("end_time") if target.get("end_time") else "None"
            })
            
            # Sau khi cập nhật downtime, update lại production kpi
            await update_current_production_stats(machinecode or target.get("machinecode"))
            return True
        else:
            print(f">>> [DOWNTIME] Không tìm thấy bản ghi ID {record_id_str}")
            return False
            
    except Exception as e:
        print(f">>> [DOWNTIME ERROR] Lỗi update lý do: {e}")
        return False
