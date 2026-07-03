"""
Schemas Pydantic - Search
"""
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.api.v1.schemas.lead import Lead, LeadCategory, LeadIntent
from app.api.v1.schemas.property import Property, PropertyType, TransactionType
from app.api.v1.schemas.signal import Signal, SignalCategory, SignalIntent


class SearchTargetType(str, Enum):
    LEAD = "lead"
    PROPERTY = "property"
    SIGNAL = "signal"


class SearchPlatform(str, Enum):
    GOOGLE = "google"
    LINKEDIN = "linkedin"
    PAGES_JAUNES = "pages_jaunes"
    FACEBOOK = "facebook"
    TIKTOK = "tiktok"
    ALL = "all"


class SearchRequest(BaseModel):
    target_type: SearchTargetType = Field(
        default=SearchTargetType.LEAD,
        description="Type de resultat a collecter: lead ou property",
    )
    query: str = Field(..., min_length=2, max_length=500, description="Requete de recherche")
    platforms: List[SearchPlatform] = Field(
        default=[SearchPlatform.GOOGLE],
        description="Plateformes a scraper",
    )
    location: Optional[str] = Field(None, description="Localisation geographique")
    lead_category: Optional[LeadCategory] = Field(
        default=None,
        description="Categorie de lead attendu quand target_type=lead",
    )
    lead_intent: Optional[LeadIntent] = Field(
        default=None,
        description="Intention du lead quand target_type=lead: buy, rent, sell, lease ou other",
    )
    signal_category: Optional[SignalCategory] = Field(
        default=None,
        description="Categorie du signal public recherche",
    )
    signal_intent: Optional[SignalIntent] = Field(
        default=None,
        description="Intention detectee: travel, moving, buy, rent, sell ou other",
    )
    include_keywords: List[str] = Field(
        default_factory=list,
        description="Mots ou expressions qui doivent orienter la recherche",
    )
    exclude_keywords: List[str] = Field(
        default_factory=list,
        description="Mots ou expressions a exclure des resultats",
    )
    language: Optional[str] = Field(default=None, max_length=12)
    property_type: Optional[List[PropertyType]] = Field(
        default=None,
        description="Type(s) de bien attendu(s) pour une property ou une demande immobiliere",
    )
    transaction_type: Optional[TransactionType] = Field(
        default=None,
        description="Type de transaction attendu quand target_type=property",
    )
    budget_min: Optional[float] = Field(
        default=None,
        ge=0,
        description="Budget minimum pour une demande immobiliere",
    )
    budget_max: Optional[float] = Field(
        default=None,
        ge=0,
        description="Budget maximum pour une demande immobiliere",
    )
    max_results: int = Field(default=20, ge=1, le=200)
    min_results: int = Field(
        default=5,
        ge=0,
        le=200,
        description="Nombre minimum de resultats que le scraper doit essayer d'obtenir",
    )
    require_valid_contact: bool = Field(
        default=True,
        description="Pour les leads, exige au moins un email valide ou un telephone valide",
    )
    only_new: bool = Field(
        default=False,
        description="Si True, les resultats deja presents en base sont ignores dans les resultats retournes",
    )
    async_mode: bool = Field(
        default=True,
        description="Si True, retourne un job_id immediatement (recommande)",
    )

    @field_validator("property_type", mode="before")
    @classmethod
    def normalize_property_type(cls, value):
        if value is None or isinstance(value, list):
            values = value
        else:
            values = [value]
        return [item.lower() if isinstance(item, str) else item for item in values]

    @field_validator(
        "target_type",
        "lead_category",
        "lead_intent",
        "transaction_type",
        "signal_category",
        "signal_intent",
        mode="before",
    )
    @classmethod
    def normalize_enum_value(cls, value):
        if isinstance(value, str):
            return value.lower()
        return value

    @field_validator("platforms", mode="before")
    @classmethod
    def normalize_platforms(cls, value):
        if value is None:
            return value
        values = value if isinstance(value, list) else [value]
        return [item.lower() if isinstance(item, str) else item for item in values]

    @field_validator("include_keywords", "exclude_keywords", mode="before")
    @classmethod
    def normalize_keywords(cls, value):
        if value is None:
            return []
        values = value if isinstance(value, list) else [value]
        return [str(item).strip() for item in values if str(item).strip()]

    @model_validator(mode="after")
    def clamp_min_results(self):
        if self.min_results > self.max_results:
            self.min_results = self.max_results
        return self

    model_config = {
        "json_schema_extra": {
            "example": {
                "target_type": "lead",
                "query": "CFO fintech France",
                "platforms": ["google", "linkedin"],
                "location": "Paris",
                "lead_category": None,
                "lead_intent": None,
                "signal_category": None,
                "signal_intent": None,
                "include_keywords": [],
                "exclude_keywords": [],
                "language": "fr",
                "property_type": ["house", "restaurant"],
                "transaction_type": None,
                "budget_min": None,
                "budget_max": None,
                "max_results": 50,
                "min_results": 5,
                "require_valid_contact": True,
                "only_new": False,
                "async_mode": True,
            }
        }
    }


class SearchResponse(BaseModel):
    job_id: Optional[str] = None
    leads: Optional[List[Lead]] = None
    properties: Optional[List[Property]] = None
    signals: Optional[List[Signal]] = None
    total: int = 0
    message: str = ""
    async_mode: bool = True
