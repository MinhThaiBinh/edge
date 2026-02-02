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

# --- BẢNG TỰ SINH (IoT & Production) --- 
# Các bảng này sẽ được lưu vào database "production"
class IoTRecord(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: Optional[Any] = Field(alias="_id", default=None)
    # time-series friendly fields
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    # Updated field name to machinecode as requested
    machinecode: str = Field(..., alias="machinecode")
    raw_value: int = Field(..., alias="raw_value")

class ProductionRecord(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")
    
    id: Optional[str] = Field(alias="_id", default=None)
    createtime: datetime = Field(default_factory=datetime.utcnow) #lấy thời điểm tạo ra record
    machinecode: str #lấy từ iot counter
    productcode: str #lấy từ iot counter
    idealcyclesec: float #lấy từ bảng workingparameter
    shiftcode: str #lấy từ bảng shift(thời điểm hiện tại là shift nào thì lấy shiftcode đó)
    startshift: datetime = Field(default_factory=datetime.utcnow) #lấy thời điểm bắt đầu ca
    endshift: datetime = Field(default_factory=datetime.utcnow) #lấy thời điểm kết thúc ca
    breakstart: Optional[datetime] = None #lấy thời điểm bắt đầu nghỉ
    breakend: Optional[datetime] = None #lấy thời điểm kết thúc nghỉ
    plannedqty: int #lấy từ bảng product qua
    run_seconds: int #createtime-endtime
    downtime_seconds: int
    avg_cycle: float
    total_count: int      # Lấy từ Counter
    defect_count: int     # Lấy từ AI và HMI   
    availability: float   # (A)
    performance: float    # (P) 
    quality: float        # (Q)
    oee: float
    is_synced: bool
    status: str = "running" # running hoặc closed

class ChangeoverRecord(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    machinecode: str
    productcode: str
    oldproduct: Optional[str]
    source: str
