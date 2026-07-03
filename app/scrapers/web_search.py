import asyncio
import re
from html import unescape
from urllib.parse import parse_qs, quote_plus, urlparse

import httpx
from bs4 import BeautifulSoup

from app.api.v1.schemas.search import SearchPlatform, SearchRequest
from app.config import settings
from app.extractors.structured_data import extract_structured_data
from app.scrapers.base import ScrapedLead
from app.services.domain_rate_limiter import domain_from_url, wait_for_domain
from app.services.metrics import fetch_errors_total
from app.services.quality import enrich_quality, has_valid_contact, normalize_valid_contacts
from app.services.url_cache import get_cached_page, set_cached_page
from app.utils.logger import get_logger

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", re.I)
PHONE_RE = re.compile(r"(?:\+\d{1,3}[\s.-]?)?(?:\(?\d{1,4}\)?[\s.-]?){3,}\d{2,4}")
POSTAL_CITY_RE = re.compile(r"\b(?P<postal_code>\d{5})\s+(?P<city>[A-ZÀ-Ÿ][A-Za-zÀ-ÿ' -]{2,})\b")
ADDRESS_RE = re.compile(
    r"\b(?P<address>\d{1,4}\s+(?:rue|avenue|av\.?|boulevard|bd|chemin|route|place|impasse|allee|allée|quai)\s+[^,;|]{3,80})",
    re.I,
)

logger = get_logger(__name__)


class WebSearchScraper:
    def __init__(self) -> None:
        self.headers = {
            "User-Agent": settings.SCRAPER_USER_AGENT,
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
        }

    async def scrape(self, request: SearchRequest) -> list[ScrapedLead]:
        platforms = self._expand_platforms(request)
        desired_results = min(request.max_results, max(request.min_results, 1))
        per_platform = max(desired_results, request.max_results // max(1, len(platforms)))
        results: list[ScrapedLead] = []
        seen_urls: set[str] = set()

        async with httpx.AsyncClient(
            headers=self.headers,
            follow_redirects=True,
            timeout=settings.SCRAPER_TIMEOUT,
        ) as client:
            for platform in platforms:
                query_variants = self._build_query_variants(request, platform)[: settings.SCRAPER_MAX_QUERY_VARIANTS]
                for query in query_variants:
                    if len(results) >= request.max_results:
                        break
                    remaining = request.max_results - len(results)
                    search_limit = min(
                        max(per_platform, desired_results),
                        settings.SCRAPER_MAX_RESULTS_PER_QUERY,
                        remaining,
                    )
                    search_results = await self._search(client, query, platform, search_limit)
                    for item in search_results:
                        if not self._matches_keyword_filters(item, request):
                            continue
                        url = item.get("url")
                        if url and url in seen_urls:
                            continue
                        if url:
                            seen_urls.add(url)
                        try:
                            lead = await asyncio.wait_for(
                                self._lead_from_result(client, item, platform, request),
                                timeout=settings.SCRAPER_ITEM_TIMEOUT_SECONDS,
                            )
                        except asyncio.TimeoutError:
                            logger.warning(
                                "Result extraction timeout",
                                platform=platform.value,
                                url=url,
                                timeout=settings.SCRAPER_ITEM_TIMEOUT_SECONDS,
                            )
                            continue
                        if (
                            lead
                            and request.target_type.value == "lead"
                            and request.require_valid_contact
                        ):
                            quality = enrich_quality(lead, request.location)
                            normalize_valid_contacts(lead, quality)
                            lead.raw_data["quality"] = quality
                            if not has_valid_contact(quality):
                                continue
                        if lead:
                            results.append(lead)
                        await asyncio.sleep(settings.DELAY_DIRECTORY_MIN)
                        if len(results) >= request.max_results:
                            break
                    if len(results) >= desired_results:
                        break
        return results[: request.max_results]

    def _expand_platforms(self, request: SearchRequest) -> list[SearchPlatform]:
        if SearchPlatform.ALL in request.platforms:
            if request.target_type.value == "signal":
                return [SearchPlatform.GOOGLE, SearchPlatform.FACEBOOK, SearchPlatform.TIKTOK]
            if request.target_type.value == "property":
                return [
                    SearchPlatform.GOOGLE,
                    SearchPlatform.PAGES_JAUNES,
                    SearchPlatform.FACEBOOK,
                    SearchPlatform.TIKTOK,
                ]
            return [SearchPlatform.GOOGLE, SearchPlatform.LINKEDIN, SearchPlatform.PAGES_JAUNES]
        return request.platforms

    def _build_query(self, request: SearchRequest, platform: SearchPlatform) -> str:
        location = f" {request.location}" if request.location else ""
        keyword_terms = " OR ".join(f'"{item}"' for item in request.include_keywords)
        if keyword_terms:
            keyword_terms = f"({keyword_terms})"
        excluded_terms = " ".join(f'-"{item}"' for item in request.exclude_keywords)
        suffix = " ".join(item for item in [keyword_terms, excluded_terms] if item)
        suffix = f" {suffix}" if suffix else ""
        if platform == SearchPlatform.LINKEDIN:
            return f'site:linkedin.com/in OR site:linkedin.com/company {request.query}{location}{suffix}'
        if platform == SearchPlatform.PAGES_JAUNES:
            return f"site:pagesjaunes.fr {request.query}{location}{suffix}"
        if platform == SearchPlatform.FACEBOOK:
            return f"site:facebook.com {request.query}{location}{suffix}"
        if platform == SearchPlatform.TIKTOK:
            return f"site:tiktok.com {request.query}{location}{suffix}"
        return f"{request.query}{location}{suffix}"

    def _build_query_variants(self, request: SearchRequest, platform: SearchPlatform) -> list[str]:
        base_query = self._build_query(request, platform)
        if request.min_results <= 1:
            return [base_query]

        variants = [base_query]
        if request.target_type.value == "signal":
            signal_extras = {
                "travel": ["je voyage", "voyage prevu", "destination"],
                "moving": ["je demenage", "demenagement prevu", "nouvelle ville"],
                "buy": ["cherche a acheter", "budget achat", "recherche bien"],
                "rent": ["cherche a louer", "recherche location", "besoin logement"],
                "sell": ["a vendre", "annonce vente", "cherche acheteur"],
            }
            extras = signal_extras.get(request.signal_intent.value if request.signal_intent else "", [])
            extras.extend(["publication publique", "annonce", "post"])
        elif request.target_type.value == "property":
            extras = [
                "annonce",
                "prix",
                "agence immobiliere",
                "particulier",
                "site annonce immobiliere",
            ]
        elif request.lead_category and request.lead_category.value == "real_estate":
            intent_terms = {
                "buy": ["cherche a acheter", "recherche achat", "budget achat"],
                "rent": ["cherche a louer", "recherche location", "budget location"],
                "sell": ["vendeur", "cherche acheteur", "bien a vendre"],
                "lease": ["cherche bail", "bail commercial", "location longue duree"],
            }
            extras = intent_terms.get(request.lead_intent.value if request.lead_intent else "", [])
            extras.extend(
                [
                    "contact telephone email",
                    "numero WhatsApp",
                    "demande immobiliere",
                    "particulier cherche",
                    "besoin logement",
                    "groupe public immobilier",
                    "annonce recherche",
                ]
            )
        else:
            extras = [
                "contact",
                "email telephone",
                "site officiel",
                "annuaire",
                "entreprise",
            ]

        for extra in extras:
            variants.append(f"{base_query} {extra}")
        if request.property_type:
            for property_type in request.property_type:
                variants.append(f"{base_query} {property_type.value}")
        if request.budget_min or request.budget_max:
            budget_parts = ["budget"]
            if request.budget_min:
                budget_parts.append(f"min {int(request.budget_min)}")
            if request.budget_max:
                budget_parts.append(f"max {int(request.budget_max)}")
            variants.append(f"{base_query} {' '.join(budget_parts)}")
        return list(dict.fromkeys(variants))

    async def _search(
        self,
        client: httpx.AsyncClient,
        query: str,
        platform: SearchPlatform,
        limit: int,
    ) -> list[dict]:
        if self._should_use_tavily():
            try:
                results = await self._tavily_search(client, query, platform, limit)
                if results:
                    return results[:limit]
            except Exception as exc:
                logger.warning("Tavily search failed, falling back", error=str(exc), platform=platform.value)

        results = await self._duckduckgo_search(client, query, limit)
        if not results:
            results = await self._google_search(client, query, limit)
        return results[:limit]

    def _should_use_tavily(self) -> bool:
        provider = settings.SCRAPER_DISCOVERY_PROVIDER.lower()
        return bool(settings.TAVILY_API_KEY) and provider in {"auto", "tavily", "tavily_first"}

    async def _tavily_search(
        self,
        client: httpx.AsyncClient,
        query: str,
        platform: SearchPlatform,
        limit: int,
    ) -> list[dict]:
        payload = {
            "query": query,
            "search_depth": settings.TAVILY_SEARCH_DEPTH,
            "max_results": min(max(limit, 1), 20),
            "include_answer": False,
            "include_raw_content": settings.TAVILY_INCLUDE_RAW_CONTENT,
            "include_favicon": True,
            "topic": "general",
            "country": settings.TAVILY_COUNTRY,
        }
        include_domains = self._tavily_domains(platform)
        if include_domains:
            payload["include_domains"] = include_domains

        response = await client.post(
            f"{settings.TAVILY_BASE_URL.rstrip('/')}/search",
            headers={"Authorization": f"Bearer {settings.TAVILY_API_KEY}"},
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        items: list[dict] = []
        for result in data.get("results", []):
            items.append(
                {
                    "title": result.get("title") or "",
                    "url": result.get("url"),
                    "snippet": result.get("content") or "",
                    "raw_content": result.get("raw_content"),
                    "provider": "tavily",
                    "provider_score": result.get("score"),
                    "favicon": result.get("favicon"),
                }
            )
        return items

    def _tavily_domains(self, platform: SearchPlatform) -> list[str]:
        if platform == SearchPlatform.PAGES_JAUNES:
            return ["pagesjaunes.fr"]
        if platform == SearchPlatform.LINKEDIN:
            return ["linkedin.com"]
        if platform == SearchPlatform.FACEBOOK:
            return ["facebook.com"]
        if platform == SearchPlatform.TIKTOK:
            return ["tiktok.com"]
        return []

    def _matches_keyword_filters(self, item: dict, request: SearchRequest) -> bool:
        text = " ".join(
            str(item.get(key) or "") for key in ["title", "snippet", "raw_content"]
        ).lower()
        if any(keyword.lower() in text for keyword in request.exclude_keywords):
            return False
        if request.include_keywords and not any(
            keyword.lower() in text for keyword in request.include_keywords
        ):
            return False
        return True

    async def _duckduckgo_search(self, client: httpx.AsyncClient, query: str, limit: int) -> list[dict]:
        url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
        await wait_for_domain(url)
        response = await client.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")
        items: list[dict] = []
        for result in soup.select(".result"):
            link = result.select_one("a.result__a")
            if not link:
                continue
            url = self._clean_duckduckgo_url(link.get("href"))
            snippet = result.select_one(".result__snippet")
            items.append(
                {
                    "title": link.get_text(" ", strip=True),
                    "url": url,
                    "snippet": snippet.get_text(" ", strip=True) if snippet else "",
                    "provider": "duckduckgo",
                }
            )
            if len(items) >= limit:
                break
        return items

    async def _google_search(self, client: httpx.AsyncClient, query: str, limit: int) -> list[dict]:
        url = f"https://www.google.com/search?q={quote_plus(query)}&hl=fr&num={limit}"
        await wait_for_domain(url)
        response = await client.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")
        items: list[dict] = []
        for link in soup.select("a"):
            url = self._clean_google_url(link.get("href"))
            title = link.get_text(" ", strip=True)
            if not url or not title or "google." in urlparse(url).netloc:
                continue
            items.append({"title": title, "url": url, "snippet": "", "provider": "google"})
            if len(items) >= limit:
                break
        return items

    async def _lead_from_result(
        self,
        client: httpx.AsyncClient,
        item: dict,
        platform: SearchPlatform,
        request: SearchRequest,
    ) -> ScrapedLead | None:
        location = request.location
        url = item.get("url")
        if not url:
            return None
        if (
            settings.PAGES_JAUNES_DEDICATED_EXTRACTOR
            and platform == SearchPlatform.PAGES_JAUNES
            and "pagesjaunes.fr" in urlparse(url).netloc
        ):
            return await self._lead_from_pages_jaunes_result(client, item, location)

        title = unescape(item.get("title") or "").strip()
        snippet = unescape(item.get("snippet") or "").strip()
        raw_content = item.get("raw_content") or ""
        page_text, structured = ("", {})
        if raw_content:
            page_text = raw_content
        elif (
            platform in {SearchPlatform.FACEBOOK, SearchPlatform.TIKTOK}
            and request.target_type.value in {"signal", "property"}
        ):
            page_text = ""
        else:
            page_text, structured = await self._fetch_page(client, url)
        if not structured and item.get("raw_content"):
            structured = {}
        combined_text = " ".join(part for part in [title, snippet, page_text[:3000]] if part)

        email = structured.get("email") or self._first_match(EMAIL_RE, combined_text)
        phone = structured.get("phone") or self._first_match(PHONE_RE, combined_text)
        if request.target_type.value == "lead" and (not email or not phone):
            extra_text = await self._crawl_contact_pages(client, url)
            email = email or self._first_match(EMAIL_RE, extra_text)
            phone = phone or self._first_match(PHONE_RE, extra_text)
        domain = urlparse(url).netloc.replace("www.", "")
        company_name = structured.get("company_name") or self._guess_company(title, domain)

        return ScrapedLead(
            source=platform.value,
            source_url=url,
            full_name=self._guess_person_name(title) if platform == SearchPlatform.LINKEDIN else None,
            job_title=self._guess_job_title(title),
            company_name=company_name,
            company_domain=domain,
            email=email,
            phone=phone,
            linkedin_url=url if "linkedin.com" in domain else None,
            website=structured.get("website") or url,
            city=structured.get("city") or location,
            country=structured.get("country"),
            raw_description=snippet or title,
            raw_data={
                "title": title,
                "snippet": snippet,
                "url": url,
                "provider": item.get("provider", "unknown"),
                "provider_score": item.get("provider_score"),
                "favicon": item.get("favicon"),
                "structured_data": structured,
            },
        )

    async def _lead_from_pages_jaunes_result(
        self,
        client: httpx.AsyncClient,
        item: dict,
        location: str | None,
    ) -> ScrapedLead | None:
        url = item.get("url")
        if not url:
            return None
        title = unescape(item.get("title") or "").strip()
        snippet = unescape(item.get("snippet") or "").strip()
        raw_content = item.get("raw_content") or ""
        page_text, structured = ("", {})
        if raw_content:
            page_text = raw_content
        else:
            page_text, structured = await self._fetch_page(client, url)

        combined_text = " ".join(part for part in [title, snippet, page_text[:5000]] if part)
        phone = structured.get("phone") or self._first_match(PHONE_RE, combined_text)
        email = structured.get("email") or self._first_match(EMAIL_RE, combined_text)
        address = structured.get("address") or self._extract_address(combined_text)
        postal_city = self._extract_postal_city(combined_text)
        official_site = structured.get("website") or self._extract_official_website(combined_text, url)
        company_name = structured.get("company_name") or self._guess_pages_jaunes_company(title, snippet)
        category = self._guess_pages_jaunes_category(title, snippet)

        city = structured.get("city") or postal_city.get("city") or location
        country = structured.get("country") or "FR"
        domain = urlparse(official_site or url).netloc.replace("www.", "")

        return ScrapedLead(
            source=SearchPlatform.PAGES_JAUNES.value,
            source_url=url,
            company_name=company_name,
            company_domain=domain,
            email=email,
            phone=phone,
            website=official_site or url,
            city=city,
            country=country,
            raw_description=snippet or title,
            raw_data={
                "title": title,
                "snippet": snippet,
                "url": url,
                "provider": item.get("provider", "unknown"),
                "provider_score": item.get("provider_score"),
                "favicon": item.get("favicon"),
                "structured_data": structured,
                "extraction_method": "pages_jaunes_dedicated",
                "address": address,
                "postal_code": structured.get("postal_code") or postal_city.get("postal_code"),
                "category": category,
            },
        )

    async def _fetch_page(self, client: httpx.AsyncClient, url: str) -> tuple[str, dict]:
        cached = await get_cached_page(url)
        if cached:
            return cached
        domain = domain_from_url(url)
        for attempt in range(settings.MAX_RETRIES):
            try:
                await wait_for_domain(url)
                response = await client.get(url)
                content_type = response.headers.get("content-type", "")
                if response.status_code >= 400:
                    fetch_errors_total.labels(domain=domain, status=str(response.status_code)).inc()
                    return "", {}
                if "text/html" not in content_type:
                    return "", {}
                structured = extract_structured_data(response.text)
                soup = BeautifulSoup(response.text, "lxml")
                for tag in soup(["script", "style", "noscript"]):
                    tag.decompose()
                text = soup.get_text(" ", strip=True)
                await set_cached_page(url, text, structured)
                return text, structured
            except Exception:
                fetch_errors_total.labels(domain=domain, status="exception").inc()
                await asyncio.sleep(min(2**attempt, 8))
        return "", {}

    async def _crawl_contact_pages(self, client: httpx.AsyncClient, url: str) -> str:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return ""
        base = f"{parsed.scheme}://{parsed.netloc}"
        paths = await self._contact_paths_from_sitemap(client, base)
        paths.extend(["/contact", "/contactez-nous", "/mentions-legales", "/a-propos", "/about", "/equipe", "/team"])
        paths = list(dict.fromkeys(paths))[: settings.SITE_CRAWLER_MAX_CONTACT_PAGES]
        texts: list[str] = []
        for path in paths:
            text, _ = await self._fetch_page(client, f"{base}{path}")
            if text:
                texts.append(text[:2000])
            if self._first_match(EMAIL_RE, " ".join(texts)) and self._first_match(PHONE_RE, " ".join(texts)):
                break
        return " ".join(texts)

    async def _contact_paths_from_sitemap(self, client: httpx.AsyncClient, base: str) -> list[str]:
        if not settings.SITE_CRAWLER_ENABLE_SITEMAP:
            return []
        sitemap_url = f"{base}/sitemap.xml"
        try:
            await wait_for_domain(sitemap_url)
            response = await client.get(sitemap_url)
            if response.status_code >= 400:
                return []
            soup = BeautifulSoup(response.text, "xml")
            paths: list[str] = []
            wanted = ("contact", "mentions", "about", "a-propos", "equipe", "team")
            for loc in soup.find_all("loc"):
                value = loc.get_text(strip=True)
                parsed = urlparse(value)
                if parsed.path and any(term in parsed.path.lower() for term in wanted):
                    paths.append(parsed.path)
                if len(paths) >= settings.SITE_CRAWLER_MAX_CONTACT_PAGES:
                    break
            return paths
        except Exception:
            return []

    def _clean_google_url(self, href: str | None) -> str | None:
        if not href:
            return None
        if href.startswith("/url?"):
            return parse_qs(urlparse(href).query).get("q", [None])[0]
        if href.startswith("http"):
            return href
        return None

    def _clean_duckduckgo_url(self, href: str | None) -> str | None:
        if not href:
            return None
        if "uddg=" in href:
            return parse_qs(urlparse(href).query).get("uddg", [href])[0]
        return href

    def _first_match(self, pattern: re.Pattern, text: str) -> str | None:
        match = pattern.search(text)
        return match.group(0).strip() if match else None

    def _guess_company(self, title: str, domain: str) -> str | None:
        if " - " in title:
            return title.split(" - ")[-1].strip()[:255]
        if " | " in title:
            return title.split(" | ")[-1].strip()[:255]
        return domain.split(".")[0].replace("-", " ").title() if domain else None

    def _guess_pages_jaunes_company(self, title: str, snippet: str) -> str | None:
        text = title or snippet
        text = re.sub(r"\s*-\s*PagesJaunes.*$", "", text, flags=re.I).strip()
        text = re.sub(r"\s*\|\s*PagesJaunes.*$", "", text, flags=re.I).strip()
        if " - " in text:
            first = text.split(" - ", 1)[0].strip()
            if first:
                return first[:255]
        if "," in text:
            first = text.split(",", 1)[0].strip()
            if first:
                return first[:255]
        return text[:255] if text else None

    def _guess_pages_jaunes_category(self, title: str, snippet: str) -> str | None:
        text = " ".join(part for part in [title, snippet] if part)
        lower = text.lower()
        categories = {
            "restaurant": "restaurant",
            "plombier": "plombier",
            "electricien": "electricien",
            "électricien": "electricien",
            "avocat": "avocat",
            "dentiste": "dentiste",
            "coiffeur": "coiffeur",
            "garage": "garage",
            "agence immobiliere": "agence immobiliere",
            "agence immobilière": "agence immobiliere",
        }
        for needle, category in categories.items():
            if needle in lower:
                return category
        return None

    def _extract_address(self, text: str) -> str | None:
        match = ADDRESS_RE.search(text)
        return match.group("address").strip(" ,.-")[:255] if match else None

    def _extract_postal_city(self, text: str) -> dict:
        match = POSTAL_CITY_RE.search(text)
        if not match:
            return {}
        return {
            "postal_code": match.group("postal_code"),
            "city": match.group("city").strip(" ,.-")[:120],
        }

    def _extract_official_website(self, text: str, source_url: str) -> str | None:
        urls = re.findall(r"https?://[^\s\"'<>]+", text)
        for candidate in urls:
            domain = urlparse(candidate).netloc.replace("www.", "")
            if domain and "pagesjaunes.fr" not in domain:
                return candidate.rstrip(").,;")
        return None

    def _guess_person_name(self, title: str) -> str | None:
        cleaned = re.split(r"\s[-|]\s", title, maxsplit=1)[0].strip()
        return cleaned[:255] if cleaned and len(cleaned.split()) <= 5 else None

    def _guess_job_title(self, title: str) -> str | None:
        parts = re.split(r"\s[-|]\s", title)
        if len(parts) >= 2:
            return parts[1].strip()[:255]
        return None
