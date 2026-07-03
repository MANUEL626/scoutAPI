import socket

import phonenumbers

from app.scrapers.base import ScrapedLead


GENERIC_EMAIL_PREFIXES = {
    "admin",
    "contact",
    "hello",
    "info",
    "office",
    "sales",
    "support",
}

COUNTRY_REGION_ALIASES = {
    "benin": "BJ",
    "bj": "BJ",
    "cotonou": "BJ",
    "cote d'ivoire": "CI",
    "côte d'ivoire": "CI",
    "ci": "CI",
    "abidjan": "CI",
    "france": "FR",
    "fr": "FR",
    "lome": "TG",
    "lomé": "TG",
    "tg": "TG",
    "togo": "TG",
}


def validate_email(email: str | None) -> dict:
    if not email or "@" not in email:
        return {"valid_syntax": False, "domain_has_mx": False, "type": None}
    local, domain = email.rsplit("@", 1)
    valid_syntax = bool(local and "." in domain)
    domain_has_mx = False
    try:
        socket.getaddrinfo(domain, 25)
        domain_has_mx = True
    except OSError:
        try:
            socket.getaddrinfo(domain, 80)
            domain_has_mx = True
        except OSError:
            domain_has_mx = False
    email_type = "role_based" if local.lower() in GENERIC_EMAIL_PREFIXES else "personal_or_named"
    return {
        "valid_syntax": valid_syntax,
        "domain_has_mx": domain_has_mx,
        "type": email_type,
    }


def validate_phone(phone: str | None, country: str | None = None) -> dict:
    if not phone:
        return {"is_valid": False, "e164": None, "country": None}
    region = COUNTRY_REGION_ALIASES.get((country or "").strip().lower(), "FR")
    try:
        parsed = phonenumbers.parse(phone, region)
    except phonenumbers.NumberParseException:
        return {"is_valid": False, "e164": None, "country": None}
    return {
        "is_valid": phonenumbers.is_valid_number(parsed),
        "e164": phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164),
        "country": phonenumbers.region_code_for_number(parsed),
    }


def confidence_score(lead: ScrapedLead, email_quality: dict, phone_quality: dict) -> int:
    score = 0
    if lead.source in {"pages_jaunes", "linkedin"}:
        score += 15
    if lead.raw_data.get("extraction_method") == "pages_jaunes_dedicated":
        score += 15
    if lead.raw_data.get("provider") == "tavily":
        score += 15
    if lead.raw_data.get("address"):
        score += 10
    if lead.company_name:
        score += 15
    if lead.company_domain:
        score += 10
    if email_quality.get("valid_syntax"):
        score += 15
    if email_quality.get("domain_has_mx"):
        score += 10
    if phone_quality.get("is_valid"):
        score += 15
    if lead.source_url and lead.website:
        score += 5
    return min(score, 100)


def enrich_quality(lead: ScrapedLead, location_hint: str | None = None) -> dict:
    email_quality = validate_email(lead.email)
    phone_quality = validate_phone(lead.phone, lead.country or location_hint)
    return {
        "email_quality": email_quality,
        "phone_quality": phone_quality,
        "confidence_score": confidence_score(lead, email_quality, phone_quality),
    }


def has_valid_contact(quality: dict) -> bool:
    email_quality = quality.get("email_quality", {})
    phone_quality = quality.get("phone_quality", {})
    email_is_valid = bool(
        email_quality.get("valid_syntax") and email_quality.get("domain_has_mx")
    )
    return email_is_valid or bool(phone_quality.get("is_valid"))


def normalize_valid_contacts(lead: ScrapedLead, quality: dict) -> None:
    email_quality = quality.get("email_quality", {})
    phone_quality = quality.get("phone_quality", {})
    if not (email_quality.get("valid_syntax") and email_quality.get("domain_has_mx")):
        lead.email = None
    if phone_quality.get("is_valid"):
        lead.phone = phone_quality.get("e164") or lead.phone
    else:
        lead.phone = None
