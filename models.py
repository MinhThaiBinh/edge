from pydantic import BaseModel, Field
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
class IoTRecord(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    node_id: str
    raw_value: int
    msg_payload: dict # Lưu lại nội dung gốc từ MQTT

class DefectRecord(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    node_id: str
    defectcode: str
    raw_image: bytes
    

class ProductionRecord(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    machine_id: str
    total_count: int      # Lấy từ Counter
    defect_count: int     # Lấy từ AI
    downtime_seconds: int
    availability: float   # (A)
    performance: float    # (P)
    quality: float        # (Q)
    oee: float
