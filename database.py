from motor.motor_asyncio import AsyncIOMotorClient

# Thay đổi connection string nếu MongoDB của bạn có user/pass hoặc ở host khác
MONGODB_URL = "mongodb://congminh_mongo:congminh_mongo@192.168.1.108:27017/?authSource=admin"

client = AsyncIOMotorClient(MONGODB_URL)
db = client.masterdata  # Tên database

def get_database():
    return db