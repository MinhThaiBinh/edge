from motor.motor_asyncio import AsyncIOMotorClient

# Kết nối MongoDB
MONGODB_URL = "mongodb://congminh_mongo:congminh_mongo@192.168.1.77:27017/?authSource=admin"

client = AsyncIOMotorClient(MONGODB_URL)
db = client.masterdata
db_production = client.production

def get_database():
    return db

def get_production_db():    
    return db_production    

async def ensure_collections():
    """Tự động khởi tạo các bảng nếu chưa tồn tại (bảng bình thường, không dùng Time-Series)."""
    try:
        # Kiểm tra nếu collection đã tồn tại thì không tạo lại
        existing_collections = await db_production.list_collection_names()
        if "iot_records" not in existing_collections:
            await db_production.create_collection("iot_records")
            print(">>> [DB] Đã tạo bảng iot_records (Standard Collection)")
            
        if "defect_records" not in existing_collections:
            await db_production.create_collection("defect_records")
            print(">>> [DB] Đã tạo bảng defect_records (Standard Collection)")
            
    except Exception as e:
        print(f">>> [DB ERROR] Lỗi khởi tạo collection: {e}")

# Giữ alias để main.py không bị lỗi khi gọi
async def ensure_timeseries():
    await ensure_collections()

