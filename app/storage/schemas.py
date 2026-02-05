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
    good_product: int = 0
    avg_cycle: float = 0.0
    run_seconds: int = 0
    actual_run_seconds: int = 0
    downtime_seconds: int = 0
    idealcyclesec: float = 0.0
    PlannedQty: int = Field(0, alias="PlannedQty")

class ProductionRecord(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")
    
    id: Optional[str] = Field(alias="_id", default=None)
    machinecode: str 
    productcode: str 
    shiftcode: str 
    status: str = "running" 
    machinestatus: str = "running" 
    productname: Optional[str] = None
    machinename: Optional[str] = None
    is_synced: bool = False

    # Time info
    createtime: datetime = Field(default_factory=datetime.utcnow) 
    endtime: Optional[datetime] = None 
    startshift: datetime = Field(default_factory=datetime.utcnow) 
    endshift: datetime = Field(default_factory=datetime.utcnow) 
    breakstart: Optional[datetime] = None 
    breakend: Optional[datetime] = None 

    # Data Objects
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
    good_product: int = 0
    run_seconds: int = 0
    actual_run_seconds: int = 0
    downtime_seconds: int = 0
    idealcyclesec: float = 0.0
    avg_cycle: float = 0.0
    PlannedQty: int = Field(0, alias="PlannedQty") # Weighted plannedqty for the whole shift
    StandardTime: float = Field(0.0, alias="StandardTime")
    
class ShiftSummary(BaseModel):
    machinecode: str
    shiftcode: str
    startshift: datetime
    endshift: datetime
    kpis: ShiftKPIs = Field(default_factory=ShiftKPIs)
    stats: ShiftStats = Field(default_factory=ShiftStats)
    machinestatus: str = "running"
    productcode: Optional[str] = None
    productname: Optional[str] = None
    machinename: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)

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
    downtime_code: Optional[str] = "default" 
    reason: Optional[str] = ""
    status: str = "active"
