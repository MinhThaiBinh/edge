from datetime import datetime
from bson import ObjectId
from app.storage.db import db_production, get_database
from app.storage.schemas import IoTRecord
from app.engine.logic import (
    create_production_record_on_changeover, 
    initialize_production_record,
    update_current_production_stats,
    close_active_downtime
)
from app.config import THRESHOLD, NODE_ID
from app.utils.messaging import mqtt_publish

async def process_and_save_defect(ai_data, machinecode=None):
    if ai_data is None:
        return None

    count = ai_data.get("count", 0)
    ng_pill = ai_data.get("ng_pill", 0)
    machinecode = machinecode.strip() if machinecode else None
    
    # 1. Xử lý lỗi thiếu số lượng (d1)
    if count < THRESHOLD:
        print(f">>> [AI] Phát hiện lỗi thiếu viên: {count} < {THRESHOLD}. Đang lưu DefectRecord d1...")
        defect_doc = {
            "timestamp": datetime.utcnow(),
            "node_id": NODE_ID,
            "machinecode": machinecode,
            "defectcode": "d1",
            "source": "CAM",
            "raw_image": ai_data.get("image_bytes")
        }
        await db_production["defect_records"].insert_one(defect_doc)
        await update_current_production_stats(machinecode, do_publish=False)
        return True

    # 2. Xử lý lỗi viên nén không đạt (ng_pill -> d3)
    if ng_pill > 0:
        print(f">>> [AI] Phát hiện viên lỗi (ng_pill): {ng_pill}. Đang lưu DefectRecord d3...")
        defect_doc = {
            "timestamp": datetime.utcnow(),
            "node_id": NODE_ID,
            "machinecode": machinecode,
            "defectcode": "d3",
            "source": "CAM",
            "raw_image": ai_data.get("image_bytes")
        }
        await db_production["defect_records"].insert_one(defect_doc)
        await update_current_production_stats(machinecode, do_publish=False)
        return True
    
    print(f">>> [AI] OK: Số lượng {count} đạt yêu cầu.")
    return False

async def process_and_save_hmi_defect(hmi_data):
    """
    Standard Payload: { "machinecode": "m001", "defectcode": "d1" }
    """
    if not hmi_data:
        return False

    try:
        machinecode = str(hmi_data.get("machinecode", "")).strip()
        defectcode = str(hmi_data.get("defectcode", "")).strip()
        
        if not machinecode or not defectcode:
            print(f">>> [PROCESSOR ERROR] HMI Defect thiếu thông tin hoặc sai định dạng: {hmi_data}")
            return False

        defect_doc = {
            "timestamp": datetime.utcnow(),
            "machinecode": machinecode,
            "defectcode": defectcode,
            "source": "HMI"
        }
        await db_production["defect_records"].insert_one(defect_doc)
        print(f">>> [DB] Đã lưu Defect từ HMI: {defectcode} cho {machinecode}")
        await update_current_production_stats(machinecode, do_publish=False)
        return True
    except Exception as e:
        print(f">>> [DB ERROR] Lưu HMI Defect thất bại: {e}")
        return False

async def process_and_save_counter(counter_msg):
    """
    Standard Payload: { "machinecode": "m002", "timestamp": "...", "shootcountnumber": 1439 }
    """
    if not counter_msg:
        return False

    try:
        machinecode = str(counter_msg.get("machinecode", "")).strip()
        raw_value = counter_msg.get("shootcountnumber", 0)
        now = datetime.utcnow()
        
        if not machinecode:
            print(f">>> [PROCESSOR ERROR] Counter thiếu machinecode: {counter_msg}")
            return False
        
        # 0. Nếu đang có downtime active thì đóng lại
        await close_active_downtime(machinecode)

        # 1. Tìm bản ghi gần nhất để tính actual_cycle_time
        actual_cycle_time = 0.0
        last_record = await db_production["iot_records"].find_one(
            {"machinecode": machinecode},
            sort=[("timestamp", -1)]
        )
        
        if last_record and "timestamp" in last_record:
            prev_ts = last_record["timestamp"]
            diff = (now - prev_ts).total_seconds()
            actual_cycle_time = round(diff, 2)
            
        # 2. Lưu IoT record
        record = {
            "timestamp": now,
            "machinecode": machinecode,
            "data": {
                "raw_value": raw_value,
                "actual_cycle_time": actual_cycle_time
            }
        }
        await db_production["iot_records"].insert_one(record)
        print(f">>> [DB] Saved IoTRecord for {machinecode}: val={raw_value}, cycle={actual_cycle_time}s")
        
        # 3. Cập nhật OEE/KPI
        await update_current_production_stats(machinecode, do_publish=False)
        

            
        return True
    except Exception as e:
        print(f">>> [DB ERROR] IoTRecord save failed: {e}")
        return False

async def process_hmi_changeover(data):
    """
    Standard Payload: { "machinecode": "m002", "product": "pd002", "oldproduct": "pd001" }
    """
    if not data:
        return False

    try:
        now = datetime.utcnow()
        machinecode = str(data.get("machine") or data.get("machinecode", "")).strip()
        new_productcode = str(data.get("product") or data.get("productcode", "")).strip()
        old_productcode = str(data.get("oldproduct") or data.get("oldproductcode", "")).strip()
        
        if not machinecode or not new_productcode:
            print(f">>> [PROCESSOR ERROR] Changeover thiếu thông tin: {data}")
            return False

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

async def process_hmi_downtime_reason(data):
    """
    Standard Payload: { "id": "objectid_string", "machinecode": "m001", "downtimecode": "dt01" }
    """
    if not data:
        return False
        
    try:
        if "status" in data and data.get("status") in ["active", "closed"]:
            return False

        record_id_str = data.get("id")
        machinecode = str(data.get("machinecode", "")).strip()
        downtime_code = str(data.get("downtimecode", "")).strip()
        
        if not machinecode or not downtime_code:
            print(f">>> [PROCESSOR ERROR] Downtime Reason thiếu thông tin: {data}")
            return False

        db_master = get_database()
        master_entry = await db_master["downtime"].find_one({
            "downtimecode": {"$regex": f"^{downtime_code}$", "$options": "i"}
        })
        
        if not master_entry:
            print(f">>> [DOWNTIME ERROR] Mã lỗi '{downtime_code}' không tồn tại trong danh mục 'downtime'")
            downtime_code = "default"
            reason = "Unknown Reason"
        else:
            downtime_code = master_entry.get("downtimecode")
            reason = master_entry.get("downtimename")
        
        try:
            query = {"_id": ObjectId(record_id_str)}
        except:
            query = {"machinecode": machinecode, "status": "active"}

        res = await db_production["downtime_records"].update_one(
            query,
            {"$set": {
                "downtime_code": downtime_code,
                "reason": reason
            }}
        )
        
        if res.modified_count > 0:
            target = await db_production["downtime_records"].find_one(query)
            print(f">>> [DOWNTIME] Đã cập nhật cho ID {record_id_str}: {downtime_code} - {reason}")
            
            mqtt_publish("topic/downtimeinput", {
                "id": str(target["_id"]),
                "machine": machinecode or target.get("machinecode"),
                "status": target.get("status"),
                "downtimecode": downtime_code,
                "createtime": target.get("start_time"),
                "endtime": target.get("end_time") if target.get("end_time") else "None",
                "duration": target.get("duration_seconds", 0)
            })
            
            await update_current_production_stats(machinecode or target.get("machinecode"), do_publish=False)
            return True
        return False
    except Exception as e:
        print(f">>> [DOWNTIME ERROR] Lỗi update lý do: {e}")
        return False

async def process_get_defect_master(data):
    """
    Standard Payload: { "machinecode": "m001" }
    """
    try:
        machinecode = str(data.get("machinecode", "Unknown")).strip()
        print(f">>> [PROCESSOR] Nhận yêu cầu defect master cho máy: {machinecode}")
        
        db_master = get_database()
        # Lấy tất cả defect từ bảng 'defect'
        defects = await db_master["defect"].find({}, {"_id": 0}).to_list(None)
        
        mqtt_publish("topic/get/defectmaster/res", {
            "machinecode": machinecode,
            "defects": defects,
            "timestamp": datetime.utcnow()
        })
        print(f">>> [DB] Đã gửi {len(defects)} defect records cho {machinecode}")
        return True
    except Exception as e:
        print(f">>> [ERROR] Lỗi lấy defect master: {e}")
        return False

async def process_get_product_master(data):
    """
    Standard Payload: { "machinecode": "m001", "getproduct": "changover" }
    """
    try:
        machinecode = str(data.get("machinecode", "Unknown")).strip()
        req_type = str(data.get("getproduct", "")).lower().strip()
        print(f">>> [PROCESSOR] Nhận yêu cầu product master cho máy: {machinecode} (type={req_type})")
        
        if req_type == "changover":
            db_master = get_database()
            # Lấy tất cả product từ bảng 'product'
            products = await db_master["product"].find({}, {"_id": 0}).to_list(None)
            
            # Publish kết quả trả về topic/get/productcode/res khi nhận request là "changover"
            mqtt_publish("topic/get/productcode/res", products)
            print(f">>> [DB] Đã gửi {len(products)} product records cho {machinecode}")
            return True
        else:
            print(f">>> [PROCESSOR] Bỏ qua yêu cầu product master không hợp lệ: {req_type}")
            return False
            
    except Exception as e:
        print(f">>> [ERROR] Lỗi lấy product master: {e}")
        return False

async def process_get_downtime_request(data):
    """
    Standard Payload: { "machinecode": "m002", "getdowntime": "downtime" }
    """
    try:
        from app.engine.logic import get_current_shift
        machinecode = str(data.get("machinecode", "")).strip()
        req_type = str(data.get("getdowntime", "")).strip()
        
        if not machinecode or req_type != "downtime":
            return False
            
        print(f">>> [PROCESSOR] Nhận yêu cầu fetch downtime cho máy: {machinecode}")
        
        # 1. Lấy ca hiện tại
        shift_info = await get_current_shift()
        start_shift = shift_info["startshift"]
        
        # 2. Truy vấn tất cả downtime của máy trong ca này
        # (Bao gồm cả active và closed, miễn là bắt đầu trong ca)
        query = {
            "machinecode": machinecode,
            "start_time": {"$gte": start_shift}
        }
        
        downtimes = await db_production["downtime_records"].find(query).sort("start_time", 1).to_list(None)
        
        # 3. Publish từng bản ghi xuống topic/downtimeinput
        for dt in downtimes:
            mqtt_publish("topic/downtimeinput", {
                "id": str(dt["_id"]),
                "machine": machinecode,
                "status": dt.get("status"),
                "downtimecode": dt.get("downtime_code") or "default",
                "createtime": dt.get("start_time"),
                "endtime": dt.get("end_time") if dt.get("end_time") else "None",
                "duration": dt.get("duration_seconds", 0)
            })
            
        print(f">>> [DB] Đã gửi {len(downtimes)} bản ghi downtime cho máy {machinecode}")
        return True
    except Exception as e:
        print(f">>> [ERROR] Lỗi process_get_downtime_request: {e}")
        return False

async def process_get_downtime_master(data):
    """
    Standard Payload: { "getdowntime": "downtimcode" }
    """
    try:
        req_type = str(data.get("getdowntime", "")).strip()
        if req_type != "downtimcode":
            return False

        print(f">>> [PROCESSOR] Nhận yêu cầu fetch downtime master")
        from app.storage.db import get_database
        db_master = get_database()
        
        # Lấy tất cả bản ghi từ bảng downtime (Master)
        downtime_masters = await db_master["downtime"].find({}, {"_id": 0}).to_list(None)
        
        # Publish kết quả xuống topic/get/downtimecode/res
        mqtt_publish("topic/get/downtimecode/res", downtime_masters)
        print(f">>> [DB] Đã gửi {len(downtime_masters)} bản ghi downtime master")
        return True
    except Exception as e:
        print(f">>> [ERROR] Lỗi process_get_downtime_master: {e}")
        return False

async def process_update_downtime_reason(data):
    """
    Standard Payload: { "_id": "...", "downtimecode": "toilet" }
    """
    if not data: return False
    
    try:
        record_id_str = data.get("_id")
        downtime_code = str(data.get("downtimecode", "")).strip()
        
        if not record_id_str or not downtime_code:
            print(f">>> [PROCESSOR ERROR] Update downtime thiếu thông tin: {data}")
            return False

        # 1. Tìm thông tin trong master
        db_master = get_database()
        master_entry = await db_master["downtime"].find_one({
            "downtimecode": {"$regex": f"^{downtime_code}$", "$options": "i"}
        })
        
        if master_entry:
            downtime_code = master_entry.get("downtimecode")
            reason = master_entry.get("downtimename")
        else:
            reason = f"Unknown ({downtime_code})"

        # 2. Update record
        query = {"_id": ObjectId(record_id_str)}
        res = await db_production["downtime_records"].update_one(
            query,
            {"$set": {
                "downtime_code": downtime_code,
                "reason": reason
            }}
        )
        
        if res.modified_count > 0:
            target = await db_production["downtime_records"].find_one(query)
            m_code = target.get("machinecode")
            print(f">>> [DOWNTIME] Đã cập nhật _id {record_id_str} thành {downtime_code}")
            
            # 3. Publish update xuống HMI (optional but good for sync)
            mqtt_publish("topic/downtimeinput", {
                "id": str(target["_id"]),
                "machine": m_code,
                "status": target.get("status"),
                "downtimecode": downtime_code,
                "createtime": target.get("start_time"),
                "endtime": target.get("end_time") if target.get("end_time") else "None",
                "duration": target.get("duration_seconds", 0)
            })
            
            if m_code:
                await update_current_production_stats(m_code, do_publish=False)
            return True
        else:
            print(f">>> [DOWNTIME] Không tìm thấy hoặc không có thay đổi cho _id {record_id_str}")
            return False
            
    except Exception as e:
        print(f">>> [ERROR] Lỗi process_update_downtime_reason: {e}")
        return False



