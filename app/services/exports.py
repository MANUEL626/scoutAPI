import csv
import io

from app.models.scraping import LeadRecord, PropertyRecord


LEAD_EXPORT_FIELDS = [
    "id",
    "job_id",
    "full_name",
    "job_title",
    "company_name",
    "lead_category",
    "lead_intent",
    "demand_property_type",
    "demand_location",
    "budget_min",
    "budget_max",
    "email",
    "phone",
    "linkedin_url",
    "website",
    "city",
    "country",
    "source",
    "source_url",
    "score",
    "qualification",
    "scraped_at",
]


def leads_to_csv(leads: list[LeadRecord]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=LEAD_EXPORT_FIELDS)
    writer.writeheader()
    for lead in leads:
        writer.writerow(
            {
                "id": lead.id,
                "job_id": lead.job_id,
                "full_name": lead.full_name,
                "job_title": lead.job_title,
                "company_name": lead.company_name,
                "lead_category": lead.lead_category,
                "lead_intent": lead.lead_intent,
                "demand_property_type": lead.demand_property_type,
                "demand_location": lead.demand_location,
                "budget_min": lead.budget_min,
                "budget_max": lead.budget_max,
                "email": lead.email,
                "phone": lead.phone,
                "linkedin_url": lead.linkedin_url,
                "website": lead.website,
                "city": lead.city,
                "country": lead.country,
                "source": lead.source,
                "source_url": lead.source_url,
                "score": lead.score,
                "qualification": lead.qualification,
                "scraped_at": lead.scraped_at.isoformat() if lead.scraped_at else None,
            }
        )
    return buffer.getvalue()


PROPERTY_EXPORT_FIELDS = [
    "id",
    "job_id",
    "title",
    "property_type",
    "transaction_type",
    "price",
    "currency",
    "location_text",
    "city",
    "country",
    "surface",
    "surface_unit",
    "seller_name",
    "seller_phone",
    "seller_email",
    "seller_website",
    "source",
    "source_url",
    "score",
    "scraped_at",
]


def properties_to_csv(properties: list[PropertyRecord]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=PROPERTY_EXPORT_FIELDS)
    writer.writeheader()
    for item in properties:
        writer.writerow(
            {
                "id": item.id,
                "job_id": item.job_id,
                "title": item.title,
                "property_type": item.property_type,
                "transaction_type": item.transaction_type,
                "price": item.price,
                "currency": item.currency,
                "location_text": item.location_text,
                "city": item.city,
                "country": item.country,
                "surface": item.surface,
                "surface_unit": item.surface_unit,
                "seller_name": item.seller_name,
                "seller_phone": item.seller_phone,
                "seller_email": item.seller_email,
                "seller_website": item.seller_website,
                "source": item.source,
                "source_url": item.source_url,
                "score": item.score,
                "scraped_at": item.scraped_at.isoformat() if item.scraped_at else None,
            }
        )
    return buffer.getvalue()
