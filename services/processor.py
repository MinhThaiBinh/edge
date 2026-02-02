from models import IoTRecord
from database import db_production
from datetime import datetime
from logic import create_production_record_on_changeover, initialize_production_record

THRESHOLD = 12
NODE_ID = "AIOT_001"

async def process_and_save_defect(ai_data, machinecode=None):
    """
    Xử lý lưu kết quả phát hiện lỗi từ Camera AI.
    """
    if ai_data is None:
        return

    count = ai_data["count"]
    
    # KIỂM TRA ĐIỀU KIỆN NGƯỠNG
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
    """
    Xử lý lưu thông tin lỗi nhận được từ HMI qua MQTT.
    """
    if not hmi_data:
        return

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
    """
    Sử dụng IoTRecord model để lưu dữ liệu Counter (Bảng bình thường).
    """
    if not counter_msg:
        return

    try:
        record = IoTRecord(
            machinecode=counter_msg.get("device"),
            raw_value=counter_msg.get("shootcountnumber", 0)
        )

        doc = record.model_dump(exclude_none=True)
        
        # Mapping MongoDB _id
        if "id" in doc:
            doc["_id"] = doc.pop("id")
        if "_id" in doc and doc["_id"] is None:
            del doc["_id"]
            
        # KHÔNG DÙNG machine_id nữa, chỉ dùng machinecode thống nhất cho tất cả bảng
        await db_production["iot_records"].insert_one(doc)
        print(f">>> [DB] Saved IoTRecord for {record.machinecode}: {record.raw_value}")
        return True
    except Exception as e:
        print(f">>> [DB ERROR] IoTRecord save failed: {e}")
        return False

async def process_hmi_changeover(data):
    """
    Xử lý thông tin thay đổi sản phẩm (Changeover) từ HMI.
    """
    if not data:
        return

    try:
        now = datetime.utcnow()
        machinecode = data.get("device")
        new_productcode = data.get("productcode")
        old_productcode = data.get("oldproduct")
        
        # 1. Lưu bản ghi sự kiện Changeover
        changeover_doc = {
            "timestamp": now,
            "machinecode": machinecode,
            "productcode": new_productcode,
            "oldproduct": old_productcode,
            "source": "HMI"
        }
        await db_production["changeover_records"].insert_one(changeover_doc)
        print(f">>> [DB] Đã lưu Changeover sự kiện: {new_productcode} cho {machinecode}")

        # 2. CHỐT BẢN GHI CŨ (Close old record)
        if old_productcode:
            print(f">>> [PROCESSOR] Đang chốt sản lượng cho sản phẩm cũ: {old_productcode}")
            await create_production_record_on_changeover(
                machinecode=machinecode,
                old_productcode=old_productcode,
                new_productcode=new_productcode,
                changeover_timestamp=now
            )

        # 3. KHỞI TẠO BẢN GHI MỚI (Start new record)
        print(f">>> [PROCESSOR] Đang khởi tạo bản ghi mới cho sản phẩm: {new_productcode}")
        await initialize_production_record(machinecode, new_productcode)

        return True
    except Exception as e:
        print(f">>> [DB ERROR] Lưu Changeover thất bại: {e}")
        return False
