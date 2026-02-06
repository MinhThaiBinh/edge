from pymongo import MongoClient

SRC = "mongodb://congminh_mongo:congminh_mongo@192.168.1.77:27017/?authSource=admin"
DST = "mongodb://congminh_mongo:congminh_mongo@192.168.1.134:27017/?authSource=admin"
DB = "masterdata"

src = MongoClient(SRC)[DB]
dst = MongoClient(DST)[DB]

for name in src.list_collection_names():
    s = src[name]
    d = dst[name]

    d.drop()
    batch = []
    for doc in s.find():
        batch.append(doc)
        if len(batch) == 1000:
            d.insert_many(batch)
            batch.clear()

    if batch:
        d.insert_many(batch)

print("DONE")
