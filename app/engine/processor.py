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

    count = ai_data.get("count", 0)
    ng_pill = ai_data.get("ng_pill", 0)
    machinecode = machinecode.strip() if machinecode else None
    
    # 1. Xử lý lỗi thiếu số lượng (d1)
    if count < THRESHOLD:
        print(f">>> [AI] Phát hiện lỗi thiếu viên: {count} < {THRESHOLD}. Đang lưu DefectRecord d1...")
        defect_doc = {
            "timestamp": datetime.utcnow(),
            "node_id": NODE_ID,
            "machinecode": machinecode,
            "defectcode": "d1",
            "source": "CAM",
            "raw_image": ai_data.get("image_bytes")
        }
        await db_production["defect_records"].insert_one(defect_doc)
        await update_current_production_stats(machinecode, do_publish=False)
        return True

    # 2. Xử lý lỗi viên nén không đạt (ng_pill -> d3)
    if ng_pill > 0:
        print(f">>> [AI] Phát hiện viên lỗi (ng_pill): {ng_pill}. Đang lưu DefectRecord d3...")
        defect_doc = {
            "timestamp": datetime.utcnow(),
            "node_id": NODE_ID,
            "machinecode": machinecode,
            "defectcode": "d3",
            "source": "CAM",
            "raw_image": ai_data.get("image_bytes")
        }
        await db_production["defect_records"].insert_one(defect_doc)
        await update_current_production_stats(machinecode, do_publish=False)
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
        await update_current_production_stats(machinecode, do_publish=False)
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
            actual_cycle_time = round(diff, 2)
            
        # 2. Lưu IoT record
        record = {
            "timestamp": now,
            "machinecode": machinecode,
            "data": {
                "raw_value": raw_value,
                "actual_cycle_time": actual_cycle_time
            }
        }
        await db_production["iot_records"].insert_one(record)
        print(f">>> [DB] Saved IoTRecord for {machinecode}: val={raw_value}, cycle={actual_cycle_time}s")
        
        # 3. Cập nhật OEE/KPI
        await update_current_production_stats(machinecode, do_publish=False)
        

            
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
    if not data:
        return False
        
    try:
        if "status" in data and data.get("status") in ["active", "closed"]:
            return False

        record_id_str = data.get("id")
        machinecode = (data.get("machine") or data.get("device") or "").strip()
        downtime_code = (data.get("downtimecode") or "").strip()
        
        if not record_id_str:
            return False

        db_master = get_database()
        master_entry = await db_master["downtime"].find_one({
            "downtimecode": {"$regex": f"^{downtime_code}$", "$options": "i"}
        })
        
        if not master_entry:
            print(f">>> [DOWNTIME ERROR] Mã lỗi '{downtime_code}' không tồn tại trong danh mục 'downtime'")
            downtime_code = "default"
            reason = "Unknown Reason"
        else:
            downtime_code = master_entry.get("downtimecode")
            reason = master_entry.get("downtimename")
        
        try:
            query = {"_id": ObjectId(record_id_str)}
        except:
            query = {"machinecode": machinecode, "status": "active"}

        res = await db_production["downtime_records"].update_one(
            query,
            {"$set": {
                "downtime_code": downtime_code,
                "reason": reason
            }}
        )
        
        if res.modified_count > 0:
            target = await db_production["downtime_records"].find_one(query)
            print(f">>> [DOWNTIME] Đã cập nhật cho ID {record_id_str}: {downtime_code} - {reason}")
            
            mqtt_publish("topic/downtimeinput", {
                "id": str(target["_id"]),
                "machine": machinecode or target.get("machinecode"),
                "status": target.get("status"),
                "downtimecode": downtime_code,
                "createtime": target.get("start_time"),
                "endtime": target.get("end_time") if target.get("end_time") else "None"
            })
            
            await update_current_production_stats(machinecode or target.get("machinecode"), do_publish=False)
            return True
        return False
    except Exception as e:
        print(f">>> [DOWNTIME ERROR] Lỗi update lý do: {e}")
        return False

async def process_get_defect_master(data):
    """Xử lý yêu cầu lấy danh sách defect master từ HMI/Client."""
    try:
        machine = data.get("machine", "Unknown")
        print(f">>> [PROCESSOR] Nhận yêu cầu defect master cho máy: {machine}")
        
        db_master = get_database()
        # Lấy tất cả defect từ bảng 'defect'
        defects = await db_master["defect"].find({}, {"_id": 0}).to_list(None)
        
        # Publish kết quả trả về topic mong muốn (thường là cùng topic hoặc topic response)
        # Theo yêu cầu là publish vào, ta dùng lại topic/get/defectmaster hoặc một topic response
        # Ở đây ta publish vào chính nó hoặc topic quy định để client nhận
        mqtt_publish("topic/get/defectmaster/res", {
            "machine": machine,
            "defects": defects,
            "timestamp": datetime.utcnow()
        })
        print(f">>> [DB] Đã gửi {len(defects)} defect records cho {machine}")
        return True
    except Exception as e:
        print(f">>> [ERROR] Lỗi lấy defect master: {e}")
        return False
