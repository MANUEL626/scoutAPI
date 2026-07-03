import json

from bs4 import BeautifulSoup


def extract_structured_data(html: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    extracted: dict = {}
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            payload = json.loads(script.string or "{}")
        except json.JSONDecodeError:
            continue
        for item in _iter_items(payload):
            item_type = item.get("@type")
            if isinstance(item_type, list):
                types = {str(value).lower() for value in item_type}
            else:
                types = {str(item_type).lower()}
            if not types.intersection({"organization", "localbusiness", "restaurant", "professionalservice"}):
                continue
            extracted.setdefault("company_name", item.get("name"))
            extracted.setdefault("email", item.get("email"))
            extracted.setdefault("phone", item.get("telephone"))
            extracted.setdefault("website", item.get("url"))
            address = item.get("address")
            if isinstance(address, dict):
                extracted.setdefault("city", address.get("addressLocality"))
                extracted.setdefault("country", address.get("addressCountry"))
                extracted.setdefault("postal_code", address.get("postalCode"))
                extracted.setdefault("address", address.get("streetAddress"))
    og_site = soup.select_one('meta[property="og:site_name"]')
    if og_site and og_site.get("content"):
        extracted.setdefault("company_name", og_site["content"])
    return {key: value for key, value in extracted.items() if value}


def _iter_items(payload):
    if isinstance(payload, list):
        for item in payload:
            yield from _iter_items(item)
    elif isinstance(payload, dict):
        graph = payload.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                yield from _iter_items(item)
        yield payload
