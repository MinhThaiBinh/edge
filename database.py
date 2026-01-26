from motor.motor_asyncio import AsyncIOMotorClient

# Thay doi connection string neu MongoDB cua ban co user/pass hoac o host khac
MONGODB_URL = "mongodb://congminh_mongo:congminh_mongo@192.168.1.79:27017/?authSource=admin"

client = AsyncIOMotorClient(MONGODB_URL)
db = client.masterdata  # Database chua du lieu danh muc (Master Data)
db_production = client.production # Database chua du lieu thuc te (IoT, Defect, Production Records)

def get_database():
    return db

def get_production_db():
    return db_production

async def ensure_timeseries():
    """
    Khởi tạo các bảng Time-series nếu chưa tồn tại
    """
    existing_collections = await db_production.list_collection_names()
    
    if "iot_records" not in existing_collections:
        print(">>> Đang tạo bảng timeseries 'iot_records'...")
        await db_production.create_collection(
            "iot_records",
            timeseries={
                "timeField": "timestamp",
                "metaField": "node_id",
                "granularity": "seconds"
            }
        )
    
    if "production_records" not in existing_collections:
        print(">>> Đang tạo bảng timeseries 'production_records'...")
        await db_production.create_collection(
            "production_records",
            timeseries={
                "timeField": "timestamp",
                "metaField": "machine_id",
                "granularity": "minutes"
            }
        )
