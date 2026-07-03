"""Schemas Pydantic - Public intent signals."""
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class SignalCategory(str, Enum):
    TRAVEL = "travel"
    RELOCATION = "relocation"
    PROPERTY_DEMAND = "property_demand"
    PROPERTY_SALE = "property_sale"
    OTHER = "other"


class SignalIntent(str, Enum):
    TRAVEL = "travel"
    MOVING = "moving"
    BUY = "buy"
    RENT = "rent"
    SELL = "sell"
    OTHER = "other"


class Signal(BaseModel):
    id: Optional[str] = None
    signal_category: SignalCategory = SignalCategory.OTHER
    signal_intent: SignalIntent = SignalIntent.OTHER
    content: Optional[str] = None
    author_name: Optional[str] = None
    author_handle: Optional[str] = None
    location_text: Optional[str] = None
    language: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    source: str
    source_url: Optional[str] = None
    confidence_score: int = Field(default=0, ge=0, le=100)
    has_valid_contact: bool = False
    fingerprint: Optional[str] = None
    scraped_at: Optional[datetime] = None
    raw_data: Optional[Dict[str, Any]] = None

    model_config = {"from_attributes": True}
