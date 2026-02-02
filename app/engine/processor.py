from datetime import datetime
from app.storage.db import db_production
from app.storage.schemas import IoTRecord
from app.engine.logic import create_production_record_on_changeover, initialize_production_record
from app.config import THRESHOLD, NODE_ID

async def process_and_save_defect(ai_data, machinecode=None):
    if ai_data is None:
        return None

    count = ai_data["count"]
    
    if count < THRESHOLD:
        print(f">>> [AI] Phát hiện lỗi: {count} < {THRESHOLD}. Đang lưu DefectRecord...")
        defect_doc = {
            "timestamp": datetime.utcnow(),
            "node_id": NODE_ID,
            "machinecode": machinecode,
            "defectcode": "d1",
            "source": "CAM",
            "raw_image": ai_data["image_bytes"]
        }
        await db_production["defect_records"].insert_one(defect_doc)
        return True
    
    print(f">>> [AI] OK: Số lượng {count} đạt yêu cầu.")
    return False

async def process_and_save_hmi_defect(hmi_data):
    if not hmi_data:
        return False

    try:
        defect_doc = {
            "timestamp": datetime.utcnow(),
            "machinecode": hmi_data.get("device"),
            "defectcode": hmi_data.get("defectcode"),
            "source": "HMI"
        }
        await db_production["defect_records"].insert_one(defect_doc)
        print(f">>> [DB] Đã lưu Defect từ HMI: {hmi_data.get('defectcode')} cho {hmi_data.get('device')}")
        return True
    except Exception as e:
        print(f">>> [DB ERROR] Lưu HMI Defect thất bại: {e}")
        return False

async def process_and_save_counter(counter_msg):
    if not counter_msg:
        return False

    try:
        record = IoTRecord(
            machinecode=counter_msg.get("device"),
            raw_value=counter_msg.get("shootcountnumber", 0)
        )
        doc = record.model_dump(exclude_none=True)
        if "id" in doc:
            doc["_id"] = doc.pop("id")
        if "_id" in doc and doc["_id"] is None:
            del doc["_id"]
            
        await db_production["iot_records"].insert_one(doc)
        print(f">>> [DB] Saved IoTRecord for {record.machinecode}: {record.raw_value}")
        return True
    except Exception as e:
        print(f">>> [DB ERROR] IoTRecord save failed: {e}")
        return False

async def process_hmi_changeover(data):
    if not data:
        return False

    try:
        now = datetime.utcnow()
        machinecode = data.get("device")
        new_productcode = data.get("productcode")
        old_productcode = data.get("oldproduct")
        
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
