"""
Schémas Pydantic — Search & Jobs
"""
from typing import Optional, List, Dict, Any
from enum import Enum
from datetime import datetime
from pydantic import BaseModel, Field

from app.api.v1.schemas.lead import Lead, LeadSource


class SearchPlatform(str, Enum):
    GOOGLE = "google"
    LINKEDIN = "linkedin"
    PAGES_JAUNES = "pages_jaunes"
    ALL = "all"


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=500, description="Requête de recherche")
    platforms: List[SearchPlatform] = Field(
        default=[SearchPlatform.GOOGLE],
        description="Plateformes à scraper"
    )
    location: Optional[str] = Field(None, description="Localisation géographique")
    max_results: int = Field(default=20, ge=1, le=200)
    async_mode: bool = Field(
        default=True,
        description="Si True, retourne un job_id immédiatement (recommandé)"
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "query": "CFO fintech France",
                "platforms": ["google", "linkedin"],
                "location": "Paris",
                "max_results": 50,
                "async_mode": True,
            }
        }
    }


class SearchResponse(BaseModel):
    job_id: Optional[str] = None
    leads: Optional[List[Lead]] = None
    total: int = 0
    message: str = ""
    async_mode: bool = True


class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


class JobResponse(BaseModel):
    job_id: str
    status: JobStatus
    progress: int = Field(default=0, ge=0, le=100, description="Progression en %")
    message: str = ""
    total_leads: int = 0
    leads: Optional[List[Lead]] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    error: Optional[str] = None

    model_config = {"from_attributes": True}