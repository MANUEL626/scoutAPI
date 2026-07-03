"""
Schémas Pydantic — Lead
"""
from typing import Optional, List
from enum import Enum
from datetime import datetime
from pydantic import BaseModel, field_validator, model_validator


class QualificationLevel(str, Enum):
    HOT = "hot"
    WARM = "warm"
    COLD = "cold"
    UNQUALIFIED = "unqualified"


class LeadSource(str, Enum):
    GOOGLE = "google"
    LINKEDIN = "linkedin"
    PAGES_JAUNES = "pages_jaunes"
    KOMPASS = "kompass"
    SOCIETE_COM = "societe_com"
    MANUAL = "manual"


class LeadBase(BaseModel):
    # Identité
    full_name: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    job_title: Optional[str] = None

    # Entreprise
    company_name: Optional[str] = None
    company_domain: Optional[str] = None
    company_size: Optional[str] = None
    industry: Optional[str] = None

    # Contact
    email: Optional[str] = None
    phone: Optional[str] = None
    linkedin_url: Optional[str] = None
    website: Optional[str] = None

    # Localisation
    city: Optional[str] = None
    country: Optional[str] = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, v):
        if v and "@" not in v:
            return None
        return v.lower().strip() if v else None

    @field_validator("linkedin_url")
    @classmethod
    def validate_linkedin(cls, v):
        if v and "linkedin.com" not in v:
            return None
        return v

    @field_validator("phone")
    @classmethod
    def clean_phone(cls, v):
        if not v:
            return None
        import re
        cleaned = re.sub(r'[^\d+\s\-\(\)]', '', v).strip()
        return cleaned if len(cleaned) >= 8 else None

    @model_validator(mode="after")
    def split_full_name(self):
        if self.full_name and not self.first_name:
            parts = self.full_name.strip().split(" ", 1)
            self.first_name = parts[0]
            self.last_name = parts[1] if len(parts) > 1 else None
        return self


class LeadCreate(LeadBase):
    source: LeadSource
    source_url: Optional[str] = None


class LeadScore(BaseModel):
    score: int  # 0-100
    contact_completeness: int  # 0-25
    role_relevance: int  # 0-25
    company_fit: int  # 0-25
    data_freshness: int  # 0-25
    qualification: QualificationLevel
    missing_data: List[str] = []
    disqualification_reason: Optional[str] = None


class Lead(LeadBase):
    id: Optional[str] = None
    source: Optional[LeadSource] = None
    source_url: Optional[str] = None
    score: Optional[int] = None
    qualification: QualificationLevel = QualificationLevel.UNQUALIFIED
    is_verified: bool = False
    fingerprint: Optional[str] = None
    scraped_at: Optional[datetime] = None
    raw_description: Optional[str] = None

    model_config = {"from_attributes": True}