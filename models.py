from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional

class ProductionData(BaseModel):
    node_id: str
    counter: int
    defect_count: int
    status: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class AIRecord(BaseModel):
    result: str
    confidence: float
    timestamp: datetime = Field(default_factory=datetime.utcnow)