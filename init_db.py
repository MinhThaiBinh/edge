import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from database import MONGODB_URL

async def init_db():
    client = AsyncIOMotorClient(MONGODB_URL)
    db_production = client.production
    
    # Danh sách các collection timeseries cần tạo
    timeseries_collections = {
        "iot_records": {
            "timeField": "timestamp",
            "metaField": "node_id",
            "granularity": "seconds"
        }
    }

    existing_collections = await db_production.list_collection_names()
    
    for coll_name, ts_options in timeseries_collections.items():
        if coll_name not in existing_collections:
            print(f"Đang tạo bảng timeseries: {coll_name}...")
            await db_production.create_collection(
                coll_name,
                timeseries=ts_options
            )
            print(f"Đã tạo xong {coll_name}")
        else:
            print(f"Bảng {coll_name} đã tồn tại.")

    print("Khởi tạo database thành công!")

if __name__ == "__main__":
    asyncio.run(init_db())
