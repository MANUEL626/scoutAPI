"""
Schemas Pydantic - Property
"""
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class PropertyType(str, Enum):
    HOUSE = "house"
    APARTMENT = "apartment"
    LAND = "land"
    BUILDING = "building"
    COMMERCIAL = "commercial"
    RESTAURANT = "restaurant"
    BUSINESS = "business"
    FURNITURE = "furniture"
    OTHER = "other"


class TransactionType(str, Enum):
    SALE = "sale"
    RENT = "rent"
    LEASE = "lease"
    OTHER = "other"


class Property(BaseModel):
    id: Optional[str] = None
    title: Optional[str] = None
    property_type: PropertyType = PropertyType.OTHER
    transaction_type: TransactionType = TransactionType.OTHER
    price: Optional[float] = None
    currency: Optional[str] = None
    location_text: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    surface: Optional[float] = None
    surface_unit: Optional[str] = None
    rooms: Optional[int] = None
    bedrooms: Optional[int] = None
    seller_name: Optional[str] = None
    seller_phone: Optional[str] = None
    seller_email: Optional[str] = None
    seller_website: Optional[str] = None
    source: str
    source_url: Optional[str] = None
    score: int = Field(default=0, ge=0, le=100)
    confidence_score: Optional[int] = None
    is_verified: bool = False
    fingerprint: Optional[str] = None
    scraped_at: Optional[datetime] = None
    raw_description: Optional[str] = None
    raw_data: Optional[Dict[str, Any]] = None

    model_config = {"from_attributes": True}
