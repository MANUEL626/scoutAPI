"""
Schémas Pydantic — Job
"""
from typing import Optional, List
from enum import Enum
from datetime import datetime
from pydantic import BaseModel, Field

from app.api.v1.schemas.lead import Lead
from app.api.v1.schemas.property import Property
from app.api.v1.schemas.search import SearchTargetType
from app.api.v1.schemas.signal import Signal


class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


class JobResponse(BaseModel):
    job_id: str
    target_type: SearchTargetType = SearchTargetType.LEAD
    status: JobStatus
    progress: int = Field(default=0, ge=0, le=100, description="Progression en %")
    message: str = ""
    total_leads: int = 0
    total_properties: int = 0
    total_signals: int = 0
    total_results: int = 0
    leads: Optional[List[Lead]] = None
    properties: Optional[List[Property]] = None
    signals: Optional[List[Signal]] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    error: Optional[str] = None

    model_config = {"from_attributes": True}
