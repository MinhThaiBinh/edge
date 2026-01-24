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
