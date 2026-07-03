from dataclasses import dataclass, field


@dataclass
class ScrapedLead:
    source: str
    source_url: str | None = None
    full_name: str | None = None
    job_title: str | None = None
    company_name: str | None = None
    company_domain: str | None = None
    email: str | None = None
    phone: str | None = None
    linkedin_url: str | None = None
    website: str | None = None
    city: str | None = None
    country: str | None = None
    raw_description: str | None = None
    raw_data: dict = field(default_factory=dict)
