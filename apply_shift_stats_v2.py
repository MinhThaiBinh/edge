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

# 1. Update app/storage/schemas.py - Try a shorter match
schemas_path = 'app/storage/schemas.py'
old_schemas = "class ChangeoverRecord(BaseModel):"
new_schemas = """class ShiftKPIs(BaseModel):
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

# 2. Update app/main.py - Shorter match
main_path = 'app/main.py'
old_publisher_part = "await update_current_production_stats(m_code)"
new_publisher_part = """await update_current_production_stats(m_code, do_publish=False) # Tắt publish record lẻ
                
                # 2. Lấy stats tổng hợp của cả ca và publish
                from app.engine.logic import get_current_shift_stats
                shift_stats = await get_current_shift_stats(m_code)
                if shift_stats:
                    mqtt_publish("topic/get/productionrecord", shift_stats)"""

update_file(main_path, old_publisher_part, new_publisher_part)
