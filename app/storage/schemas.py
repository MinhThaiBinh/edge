from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional, List, Dict, Any

# --- BẢNG ĐÃ CÓ SẴN (Master) ---

class DefectMaster(BaseModel):
    defectcode: str
    defectname: str
    defectgroup: str

class DefectGroupMaster(BaseModel):
    defectgroupcode: str
    defectgroupname: str

class DowntimeMaster(BaseModel):
    downtimecode: str
    downtimename: str
    downtimetype: str
    downtimegroupcode: str

class DowntimeGroupMaster(BaseModel):
    downtimegroupcode: str
    downtimegroupname: str

class MachineMaster(BaseModel):
    machinecode: str
    machinename: str
    machinegroupcode: str

class ProductMaster(BaseModel):
    productcode: str
    productname: str
    productgroupcode: str
    productprimaryunit: str
    productsecondaryunit: str
    productconversionrate: float

class ShiftMaster(BaseModel):
    shiftcode: str
    shiftname: str
    shiftstarttime: int
    shiftendtime: int

class WorkingParameterMaster(BaseModel):
    productcode: str
    idealcyclesec: float
    downtimethreshold: float

# --- BẢNG TỰ SINH (IoT & Production) --- 
# Các bảng này sẽ được lưu vào database "production"
class IoTData(BaseModel):
    raw_value: int = Field(..., alias="raw_value")
    actual_cycle_time: float = Field(default=0.0, alias="actual_cycle_time")

class IoTRecord(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: Optional[Any] = Field(alias="_id", default=None)
    # time-series friendly fields
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    # Updated field name to machinecode as requested
    machinecode: str = Field(..., alias="machinecode")
    data: IoTData

class ProductionKPIs(BaseModel):
    availability: float = 0.0
    performance: float = 0.0
    quality: float = 0.0
    oee: float = 0.0

class ProductionStats(BaseModel):
    total_count: int = 0
    defect_count: int = 0
    avg_cycle: float = 0.0
    run_seconds: int = 0
    downtime_seconds: int = 0
    idealcyclesec: float = 0.0
    plannedqty: int = 0

class ProductionRecord(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")
    
    id: Optional[str] = Field(alias="_id", default=None)
    machinecode: str #lấy từ iot counter
    productcode: str #lấy từ iot counter
    shiftcode: str #lấy từ bảng shift
    status: str = "running" # running hoặc closed
    machinestatus: str = "running" # running hoặc stopped (Trạng thái thực tế máy)
    is_synced: bool = False

    # Time info
    createtime: datetime = Field(default_factory=datetime.utcnow) #lấy thời điểm tạo ra record
    startshift: datetime = Field(default_factory=datetime.utcnow) #lấy thời điểm bắt đầu ca
    endshift: datetime = Field(default_factory=datetime.utcnow) #lấy thời điểm kết thúc ca
    breakstart: Optional[datetime] = None #lấy thời điểm bắt đầu nghỉ
    breakend: Optional[datetime] = None #lấy thời điểm kết thúc nghỉ
    
    # Data Objects
    kpis: ProductionKPIs = Field(default_factory=ProductionKPIs)
    stats: ProductionStats = Field(default_factory=ProductionStats)

class ChangeoverRecord(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    machinecode: str
    productcode: str
    oldproduct: Optional[str]
    source: str

class DowntimeRecord(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")
    
    id: Optional[Any] = Field(alias="_id", default=None)
    machinecode: str
    start_time: datetime = Field(default_factory=datetime.utcnow)
    end_time: Optional[datetime] = None
    duration_seconds: int = 0
    downtime_code: Optional[str] = "default" # Mặc định là lỗi chưa xác định
    reason: Optional[str] = ""
    status: str = "active" # active hoặc closed
