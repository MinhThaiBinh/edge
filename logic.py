from models import ProductionRecord
from database import get_production_db, get_database
from datetime import datetime, timedelta
from typing import Optional
import sys

async def create_production_record_on_changeover(
    machinecode: str,
    old_productcode: str,
    new_productcode: str,
    changeover_timestamp: datetime,
    shiftcode: Optional[str] = None
) -> Optional[ProductionRecord]:
    """
    Tạo ProductionRecord cho product cũ khi xảy ra changeover (đổi mã hàng).
    Hàm này tổng hợp dữ liệu từ iot_records và defect_records cho product cũ,
    tính toán OEE, và lưu ProductionRecord. Sau đó, có thể khởi tạo cho product mới.
    
    Args:
        machinecode: Mã máy.
        old_productcode: Mã sản phẩm cũ (trước changeover).
        new_productcode: Mã sản phẩm mới (sau changeover).
        shiftcode: Mã ca làm việc.
        changeover_timestamp: Thời gian changeover.
    
    Returns:
        ProductionRecord cho product cũ, hoặc None nếu không có dữ liệu.
    """
    try:
        print(f">>> [LOGIC] Bắt đầu tạo ProductionRecord cho {machinecode} - {old_productcode}")
        sys.stdout.flush()
        db = get_production_db()
        db_master = get_database()
        now_utc = datetime.utcnow()
        
        # Tìm bản ghi đang "running" của máy này (Luôn ưu tiên chốt bản ghi đang chạy của máy)
        # Không lọc theo prefix để tránh lỗi lệch ngày hoặc lệch mã hàng
        existing_record = await db.production_records.find_one(
            {"machinecode": machinecode, "status": "running"},
            sort=[("createtime", -1)]
        )
        
        if existing_record:
            start_time = existing_record["createtime"]
            target_id = existing_record["_id"]
            # Nếu bản ghi tìm thấy có productcode khác với old_productcode dự kiến,
            # lấy luôn productcode từ bản ghi đó để đảm bảo tính toán đúng cho mã hàng đó.
            actual_productcode = existing_record.get("productcode", old_productcode)
        else:
            # Fallback nếu không thấy record running: Lấy theo prefix mặc định
            prefix = f"{old_productcode}-{now_utc.strftime('%d-%m-%Y')}-{machinecode}"
            target_id = f"{prefix}-1"
            start_time = changeover_timestamp
            actual_productcode = old_productcode
        
        print(f">>> [LOGIC] Đang xử lý chốt bản ghi {target_id} cho sản phẩm {actual_productcode}")
        
        # Tổng hợp total_count từ iot_records trong khoảng thời gian
        iot_pipeline = [
            {"$match": {
                "machinecode": machinecode,
                "timestamp": {"$gte": start_time, "$lt": changeover_timestamp}
            }},
            {"$group": {"_id": None, "total_count": {"$sum": "$raw_value"}}}
        ]
        iot_result = await db.iot_records.aggregate(iot_pipeline).to_list(1)
        total_count = iot_result[0]["total_count"] if iot_result else 0
        
        # Tổng hợp defect_count từ defect_records
        defect_pipeline = [
            {"$match": {
                "machinecode": machinecode,
                "timestamp": {"$gte": start_time, "$lt": changeover_timestamp}
            }},
            {"$group": {"_id": None, "defect_count": {"$sum": 1}}}
        ]
        defect_result = await db.defect_records.aggregate(defect_pipeline).to_list(1)
        defect_count = defect_result[0]["defect_count"] if defect_result else 0
        
        # Tính run_seconds và downtime_seconds (giả định từ dữ liệu hoặc config)
        # Trong thực tế, tích hợp với HMI data hoặc tính từ timestamps
        run_seconds = int((changeover_timestamp - start_time).total_seconds())  # Giả định toàn bộ thời gian là run time
        downtime_seconds = 0  # Giả định, cần tính từ HMI
        
        # Chuẩn hóa productcode
        p_code = actual_productcode.strip() if actual_productcode else ""

        # 1. Lấy Ideal Cycle Time từ bảng workingparameter
        wp_doc = await db_master["workingparameter"].find_one({"productcode": p_code})
        # Try case-insensitive if not found
        if not wp_doc:
            wp_doc = await db_master["workingparameter"].find_one({"productcode": {"$regex": f"^{p_code}$", "$options": "i"}})
            
        idealcyclesec = wp_doc["idealcyclesec"] if wp_doc and "idealcyclesec" in wp_doc else 1.0
        
        # 2. Lấy Planned Qty từ bảng product
        product_doc = await db_master["product"].find_one({"productcode": p_code})
        if not product_doc:
            product_doc = await db_master["product"].find_one({"productcode": {"$regex": f"^{p_code}$", "$options": "i"}})
            
        plannedqty = product_doc.get("plannedqty", 0) if product_doc else 0
        
        # Tính toán OEE
        if total_count > 0 and run_seconds > 0:
            total_seconds = run_seconds + downtime_seconds
            availability = run_seconds / total_seconds if total_seconds > 0 else 0.0
            ideal_total_time = idealcyclesec * total_count
            performance = ideal_total_time / run_seconds
            quality = (total_count - defect_count) / total_count
            oee = availability * performance * quality
            avg_cycle = run_seconds / total_count
        else:
            availability = performance = quality = oee = avg_cycle = 0.0
        
        # Tình trạng: Đã đóng
        status = "closed"

        # Lấy thông tin ca để điền vào record
        shift_info = await get_current_shift()

        record = ProductionRecord(
            id=target_id,
            machinecode=machinecode,
            productcode=old_productcode,
            idealcyclesec=idealcyclesec,
            shiftcode=shift_info["shiftcode"],
            startshift=shift_info["startshift"],
            endshift=shift_info["endshift"],
            breakstart=shift_info["breakstart"],
            breakend=shift_info["breakend"],
            plannedqty=plannedqty,
            run_seconds=run_seconds,
            downtime_seconds=downtime_seconds,
            avg_cycle=round(avg_cycle, 2),
            total_count=total_count,
            defect_count=defect_count,
            availability=round(availability, 4),
            performance=round(performance, 4),
            quality=round(quality, 4),
            oee=round(oee, 4),
            is_synced=False,
            status=status
        )
        
        # Ghi đè (Replace) để "ngắt" bản ghi cũ, không tạo thêm bản ghi mới
        await db.production_records.replace_one(
            {"_id": target_id}, 
            record.model_dump(by_alias=True, exclude_none=True),
            upsert=True
        )
        print(f">>> [LOGIC] Đã ngắt (Finalized) ProductionRecord: {target_id} (OEE={record.oee})")
        sys.stdout.flush()
        
        return record
    except Exception as e:
        print(f">>> [LOGIC ERROR] Lỗi trong create_production_record_on_changeover: {e}")
        sys.stdout.flush()
        return None

async def get_current_shift():
    """
    Xác định thông tin ca hiện tại dựa trên giờ hệ thống.
    Trả về dict chứa shiftcode, start_datetime, end_datetime.
    """
    now = datetime.now()
    current_seconds = now.hour * 3600 + now.minute * 60 + now.second
    
    db_master = get_database()
    # Lấy tất cả các ca để xử lý linh hoạt (vì số lượng ca rất ít)
    all_shifts = await db_master["shift"].find().to_list(100)
    
    active_shift = None
    
    for s in all_shifts:
        # Hỗ trợ cả kiểu dữ liệu int (giây) và datetime (lấy giờ phút)
        def to_sec(val):
            if isinstance(val, (int, float)): return int(val)
            if isinstance(val, datetime): return val.hour * 3600 + val.minute * 60 + val.second
            return 0
            
        s_start = to_sec(s.get("shiftstarttime"))
        s_end = to_sec(s.get("shiftendtime"))
        
        # Logic kiểm tra trong ca
        is_in_shift = False
        if s_start <= s_end:
            # Ca ngày bình thường
            if s_start <= current_seconds <= s_end:
                is_in_shift = True
        else:
            # Ca đêm (vắt qua đêm)
            if current_seconds >= s_start or current_seconds <= s_end:
                is_in_shift = True
        
        if is_in_shift:
            active_shift = s
            # Bổ sung các giá trị chuẩn hóa để tính toán bên dưới
            active_shift["_start_sec"] = s_start
            active_shift["_end_sec"] = s_end
            break

    if not active_shift:
        # Fallback default
        active_shift = {
            "shiftcode": "SHIFT_01",
            "_start_sec": 21600, # 6:00
            "_end_sec": 50400    # 14:00
        }

    # Tính toán start/end datetime thực tế
    start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(seconds=active_shift["_start_sec"])
    end_dt = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(seconds=active_shift["_end_sec"])

    # Xử lý ca đêm cho datetime (nếu start > end)
    if active_shift["_start_sec"] > active_shift["_end_sec"]:
        if current_seconds >= active_shift["_start_sec"]:
            end_dt += timedelta(days=1)
        else:
            start_dt -= timedelta(days=1)

    # Lấy thông tin breaktime
    break_info = active_shift.get("breaktime", {})
    b_start_sec = break_info.get("breakstart")
    b_end_sec = break_info.get("breakend")
    
    breakstart_dt = None
    breakend_dt = None
    
    if b_start_sec is not None and b_end_sec is not None:
        breakstart_dt = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(seconds=b_start_sec)
        breakend_dt = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(seconds=b_end_sec)
        
        # Xử lý breaktime vắt qua đêm (hiếm nhưng có thể) hoặc thuộc ngày hôm sau của ca đêm
        if active_shift["_start_sec"] > active_shift["_end_sec"]:
            # Nếu ca đêm bắt đầu hôm nay:
            if current_seconds >= active_shift["_start_sec"]:
                # Nếu break < start (vd start 22h, break 2h sáng), thì break thuộc ngày mai
                if b_start_sec < active_shift["_start_sec"]:
                    breakstart_dt += timedelta(days=1)
                    breakend_dt += timedelta(days=1)
            else:
                # Nếu đang ở ngày mai của ca đêm (sau 0h):
                # Nếu break > end (vd break 22h tối qua), thì break thuộc hôm qua
                if b_start_sec > active_shift["_end_sec"]:
                    breakstart_dt -= timedelta(days=1)
                    breakend_dt -= timedelta(days=1)

    return {
        "shiftcode": active_shift["shiftcode"],
        "startshift": start_dt,
        "endshift": end_dt,
        "breakstart": breakstart_dt,
        "breakend": breakend_dt
    }

async def get_current_shift_code() -> str:
    """Wrapper trả về chỉ mã ca (cho tương thích ngược)"""
    info = await get_current_shift()
    return info["shiftcode"]

async def initialize_production_record(machinecode: str, productcode: str):
    """
    Khởi tạo một bản ghi production mới khi bắt đầu ca hoặc sau changeover.
    """
    try:
        db_master = get_database()
        shift_info = await get_current_shift()
        
        # Chuẩn hóa productcode
        p_code = productcode.strip() if productcode else ""

        # 1. Lấy Ideal Cycle Time từ bảng workingparameter
        wp_doc = await db_master["workingparameter"].find_one({"productcode": p_code})
        if not wp_doc:
            wp_doc = await db_master["workingparameter"].find_one({"productcode": {"$regex": f"^{p_code}$", "$options": "i"}})
            
        idealcyclesec = wp_doc["idealcyclesec"] if wp_doc and "idealcyclesec" in wp_doc else 1.0
        
        # 2. Lấy Planned Qty từ bảng product
        product_doc = await db_master["product"].find_one({"productcode": p_code})
        if not product_doc:
            product_doc = await db_master["product"].find_one({"productcode": {"$regex": f"^{p_code}$", "$options": "i"}})
            
        plannedqty = product_doc.get("plannedqty", 0) if product_doc else 0

        # TẠO _ID TÙY CHỈNH: mã hàng-ngày-tháng-năm-máy-stt
        now = datetime.utcnow()
        date_str = now.strftime("%d-%m-%Y")
        prefix = f"{productcode}-{date_str}-{machinecode}"
        
        db = get_production_db()
        # Đếm số lượng record của machine/product này trong ngày để lấy STT
        regex = f"^{prefix}-"
        count = await db.production_records.count_documents({"_id": {"$regex": regex}})
        new_stt = count + 1
        record_id = f"{prefix}-{new_stt}"

        record = ProductionRecord(
            id=record_id,
            machinecode=machinecode,
            productcode=productcode,
            idealcyclesec=idealcyclesec,
            shiftcode=shift_info["shiftcode"],
            startshift=shift_info["startshift"],
            endshift=shift_info["endshift"],
            breakstart=shift_info["breakstart"],
            breakend=shift_info["breakend"],
            plannedqty=plannedqty,
            run_seconds=0,
            downtime_seconds=0,
            avg_cycle=0,
            total_count=0,
            defect_count=0,
            availability=0,
            performance=0,
            quality=0,
            oee=0,
            is_synced=False,
            status="running"
        )
        
        await db.production_records.insert_one(record.model_dump(by_alias=True, exclude_none=True))
        print(f">>> [LOGIC] Đã khởi tạo ProductionRecord mới: {record_id}")
        sys.stdout.flush()
        return record
    except Exception as e:
        print(f">>> [LOGIC ERROR] Lỗi trong initialize_production_record: {e}")
        sys.stdout.flush()
        return None