from motor.motor_asyncio import AsyncIOMotorClient
from app.config import MONGODB_URL

# Kết nối MongoDB
client = AsyncIOMotorClient(MONGODB_URL)
db = client.masterdata
db_production = client.production

def get_database():
    return db

def get_production_db():    
    return db_production    

async def ensure_collections():
    """Tự động khởi tạo các bảng nếu chưa tồn tại."""
    try:
        existing_collections = await db_production.list_collection_names()
        if "iot_records" not in existing_collections:
            await db_production.create_collection("iot_records")
            print(">>> [DB] Đã tạo bảng iot_records")
            
        if "defect_records" not in existing_collections:
            await db_production.create_collection("defect_records")
            print(">>> [DB] Đã tạo bảng defect_records")
            
        if "shift_stats" not in existing_collections:
            await db_production.create_collection("shift_stats")
            print(">>> [DB] Đã tạo bảng shift_stats")
            
    except Exception as e:
        print(f">>> [DB ERROR] Lỗi khởi tạo collection: {e}")

async def ensure_timeseries():
    await ensure_collections()
