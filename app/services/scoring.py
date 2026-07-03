from app.api.v1.schemas.lead import QualificationLevel
from app.scrapers.base import ScrapedLead


def score_lead(lead: ScrapedLead, query: str) -> tuple[int, QualificationLevel]:
    score = 0
    if lead.email:
        score += 30
    if lead.phone:
        score += 20
    if lead.full_name:
        score += 10
    if lead.company_name:
        score += 15
    if lead.website or lead.linkedin_url:
        score += 15
    if lead.raw_description and any(term.lower() in lead.raw_description.lower() for term in query.split()):
        score += 10

    if score >= 70:
        return score, QualificationLevel.HOT
    if score >= 45:
        return score, QualificationLevel.WARM
    if score >= 20:
        return score, QualificationLevel.COLD
    return score, QualificationLevel.UNQUALIFIED
