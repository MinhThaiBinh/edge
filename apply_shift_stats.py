import os

def update_file(path, old_text, new_text):
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    if old_text not in content:
        print(f"ERROR: Could not find old_text in {path}")
        return False
    new_content = content.replace(old_text, new_text)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print(f"SUCCESS: Updated {path}")
    return True

# 1. Update app/storage/schemas.py
schemas_path = 'app/storage/schemas.py'
old_schemas = """    # Data Objects
    kpis: ProductionKPIs = Field(default_factory=ProductionKPIs)
    stats: ProductionStats = Field(default_factory=ProductionStats)

class ChangeoverRecord(BaseModel):"""

new_schemas = """    # Data Objects
    kpis: ProductionKPIs = Field(default_factory=ProductionKPIs)
    stats: ProductionStats = Field(default_factory=ProductionStats)

class ShiftKPIs(BaseModel):
    availability: float = 0.0
    performance: float = 0.0
    quality: float = 0.0
    oee: float = 0.0

class ShiftStats(BaseModel):
    total_count: int = 0
    defect_count: int = 0
    run_seconds: int = 0
    actual_run_seconds: int = 0
    downtime_seconds: int = 0
    
class ShiftSummary(BaseModel):
    machinecode: str
    shiftcode: str
    startshift: datetime
    endshift: datetime
    kpis: ShiftKPIs = Field(default_factory=ShiftKPIs)
    stats: ShiftStats = Field(default_factory=ShiftStats)
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class ChangeoverRecord(BaseModel):"""

update_file(schemas_path, old_schemas, new_schemas)

# 2. Update app/engine/logic.py
logic_path = 'app/engine/logic.py'
new_func = """
async def get_current_shift_stats(machinecode: str):
    \"\"\"Tổng hợp KPI và Stats của nguyên ca hiện tại cho một máy.\"\"\"
    try:
        db = get_production_db()
        shift_info = await get_current_shift()
        m_code = machinecode.strip()
        
        # Tìm tất cả các record của máy này trong ca hiện tại
        # Bao gồm cả 'running' và 'closed'
        records = await db.production_records.find({
            "machinecode": m_code,
            "shiftcode": shift_info["shiftcode"],
            "createtime": {"$gte": shift_info["startshift"]}
        }).to_list(None)
        
        total_count = 0
        defect_count = 0
        run_seconds = 0
        actual_run_seconds = 0
        downtime_seconds = 0
        weighted_ideal_time = 0.0
        
        for r in records:
            stats = r.get("stats", {})
            total_count += stats.get("total_count", 0)
            defect_count += stats.get("defect_count", 0)
            run_seconds += stats.get("run_seconds", 0)
            actual_run_seconds += stats.get("actual_run_seconds", 0)
            downtime_seconds += stats.get("downtime_seconds", 0)
            
            # Tính weighted ideal time for P
            ideal = stats.get("idealcyclesec", 1.0)
            weighted_ideal_time += ideal * stats.get("total_count", 0)
            
        # Tính toán KPI tổng của ca
        availability = actual_run_seconds / run_seconds if run_seconds > 0 else 0.0
        performance = weighted_ideal_time / actual_run_seconds if actual_run_seconds > 0 else 0.0
        quality = (total_count - defect_count) / total_count if total_count > 0 else 0.0
        oee = availability * performance * quality
        
        summary = {
            "machinecode": m_code,
            "shiftcode": shift_info["shiftcode"],
            "startshift": shift_info["startshift"],
            "endshift": shift_info["endshift"],
            "timestamp": datetime.utcnow(),
            "kpis": {
                "availability": round(availability, 4),
                "performance": round(performance, 4),
                "quality": round(quality, 4),
                "oee": round(oee, 4)
            },
            "stats": {
                "total_count": total_count,
                "defect_count": defect_count,
                "run_seconds": run_seconds,
                "actual_run_seconds": actual_run_seconds,
                "downtime_seconds": downtime_seconds
            }
        }
        return summary
    except Exception as e:
        print(f">>> [LOGIC ERROR] Lỗi get_current_shift_stats: {e}")
        return None

async def ensure_active_production_records():"""

update_file(logic_path, "async def ensure_active_production_records():", new_func)

# 3. Update app/main.py
main_path = 'app/main.py'
old_publisher = """async def production_record_publisher_task():
    \"\"\"Task chạy ngầm: Cập nhật KPI và Publish dữ liệu mỗi 1s.\"\"\"
    from app.storage.db import get_production_db
    db = get_production_db()
    while True:
        try:
            active_prods = await db.production_records.find({"status": "running"}).to_list(None)
            for p in active_prods:
                m_code = p["machinecode"]
                # Cập nhật OEE/Stats theo thời gian thực (để tính Availability ngay cả khi không có counter)
                await update_current_production_stats(m_code)"""

new_publisher = """async def production_record_publisher_task():
    \"\"\"Task chạy ngầm: Cập nhật KPI và Publish dữ liệu mỗi 1s.\"\"\"
    from app.storage.db import get_production_db
    from app.engine.logic import get_current_shift_stats
    db = get_production_db()
    while True:
        try:
            # 1. Cập nhật record đang chạy (vẫn cần để tính OEE cá nhân)
            active_prods = await db.production_records.find({"status": "running"}).to_list(None)
            for p in active_prods:
                m_code = p["machinecode"]
                await update_current_production_stats(m_code, do_publish=False) # Tắt publish record lẻ
                
                # 2. Lấy stats tổng hợp của cả ca và publish
                shift_stats = await get_current_shift_stats(m_code)
                if shift_stats:
                    mqtt_publish("topic/get/productionrecord", shift_stats)"""

update_file(main_path, old_publisher, new_publisher)
