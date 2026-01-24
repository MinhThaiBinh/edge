from database import db_production
from datetime import datetime

THRESHOLD = 12
NODE_ID = "AIOT_001"

async def process_and_save_defect(ai_data):
    """
    ai_data: nhan tu camera_sys.capture_and_detect()
    """
    if ai_data is None:
        return

    count = ai_data["count"]
    
    # KIEM TRA DIEU KIEN NGUONG
    if count < THRESHOLD:
        print(f">>> Phat hien loi: {count} < {THRESHOLD}. Dang luu DefectRecord...")
        
        # Tao object de luu vao MongoDB
        # Luu y: defectcode ban co the tu quy dinh (vi du: 101 la thieu hang)
        defect_doc = {
            "timestamp": datetime.utcnow(),
            "node_id": NODE_ID,
            "defectcode": "d1", 
            "raw_image": ai_data["image_bytes"] # Luu truc tiep binary vao Mongo
        }
        
        # Luu vao collection 'defect_records' cua database PRODUCTION
        await db_production["defect_records"].insert_one(defect_doc)
        return True
    
    print(f">>> OK: So luong {count} dat yeu cau.")
    return False
