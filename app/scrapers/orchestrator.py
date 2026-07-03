import json
import re
import asyncio
from datetime import datetime, timezone
from hashlib import sha256
from time import monotonic
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.job import JobStatus
from app.api.v1.schemas.lead import LeadCategory, LeadIntent
from app.api.v1.schemas.property import PropertyType, TransactionType
from app.api.v1.schemas.search import SearchRequest, SearchTargetType
from app.api.v1.schemas.signal import SignalCategory, SignalIntent
from app.cache.redis_client import redis_client
from app.models.scraping import LeadRecord, PropertyRecord, ScrapeJob, ScrapeJobLog, SignalRecord
from app.scrapers.base import ScrapedLead
from app.scrapers.web_search import WebSearchScraper
from app.services.scoring import score_lead
from app.services.metrics import job_duration_seconds, jobs_total, leads_total
from app.services.quality import (
    enrich_quality,
    has_valid_contact,
    normalize_valid_contacts,
    validate_email,
    validate_phone,
)
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


class ScrapingOrchestrator:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.scraper = WebSearchScraper()

    async def create_job(self, job_id: str, user_id: str, request: SearchRequest) -> None:
        self.db.add(
            ScrapeJob(
                id=job_id,
                user_id=user_id,
                status=JobStatus.PENDING.value,
                progress=0,
                message="Job en attente de traitement...",
                query=request.query,
                location=request.location,
                request_data=request.model_dump(mode="json"),
            )
        )
        self.db.add(
            ScrapeJobLog(
                job_id=job_id,
                user_id=user_id,
                level="info",
                message="Job created",
                data=request.model_dump(mode="json"),
            )
        )
        await self.db.commit()

    async def run(self, job_id: str, user_id: str, request: SearchRequest) -> list[LeadRecord | PropertyRecord | SignalRecord]:
        start = monotonic()
        await self._add_log(job_id, user_id, "info", "Scraping started", {"query": request.query})
        await self._update_job(job_id, JobStatus.PROCESSING, 10, "Scraping en cours...")
        try:
            if await self._is_cancelled(job_id):
                await self._update_job(job_id, JobStatus.FAILED, 100, "Job annule", error="cancelled")
                jobs_total.labels(status="cancelled").inc()
                return []
            await self._update_job(job_id, JobStatus.PROCESSING, 25, "Discovery des resultats en cours...")
            scraped_leads = await asyncio.wait_for(
                self.scraper.scrape(request),
                timeout=settings.SCRAPER_DISCOVERY_TIMEOUT_SECONDS,
            )
            if await self._is_cancelled(job_id):
                await self._update_job(job_id, JobStatus.FAILED, 100, "Job annule", error="cancelled")
                jobs_total.labels(status="cancelled").inc()
                return []
            await self._add_log(job_id, user_id, "info", "Discovery completed", {"items": len(scraped_leads)})
            message = "Enregistrement des leads..."
            if request.target_type == SearchTargetType.PROPERTY:
                message = "Enregistrement des biens..."
            elif request.target_type == SearchTargetType.SIGNAL:
                message = "Enregistrement des signaux publics..."
            await self._update_job(job_id, JobStatus.PROCESSING, 70, message)

            if request.target_type == SearchTargetType.PROPERTY:
                records = await self._save_properties(job_id, user_id, request, scraped_leads)
                await self._add_log(job_id, user_id, "info", "Properties saved", {"total": len(records)})
            elif request.target_type == SearchTargetType.SIGNAL:
                records = await self._save_signals(job_id, user_id, request, scraped_leads)
                await self._add_log(job_id, user_id, "info", "Signals saved", {"total": len(records)})
            else:
                records = await self._save_leads(job_id, user_id, request, scraped_leads)
                await self._add_log(job_id, user_id, "info", "Leads saved", {"total": len(records)})
                for record in records:
                    leads_total.labels(source=record.source, qualification=record.qualification).inc()

            result_labels = {
                SearchTargetType.LEAD: "lead(s)",
                SearchTargetType.PROPERTY: "bien(s)",
                SearchTargetType.SIGNAL: "signal(aux)",
            }
            result_label = result_labels[request.target_type]
            await self._update_job(
                job_id,
                JobStatus.DONE,
                100,
                f"Scraping termine: {len(records)} {result_label} collecte(s).",
                total_leads=len(records),
                leads=records if request.target_type == SearchTargetType.LEAD else None,
                properties=records if request.target_type == SearchTargetType.PROPERTY else None,
                signals=records if request.target_type == SearchTargetType.SIGNAL else None,
                target_type=request.target_type,
            )
            jobs_total.labels(status=JobStatus.DONE.value).inc()
            job_duration_seconds.observe(monotonic() - start)
            return records
        except asyncio.TimeoutError:
            message = f"Discovery timeout after {settings.SCRAPER_DISCOVERY_TIMEOUT_SECONDS}s"
            logger.warning("Scraping job timed out", job_id=job_id, timeout=settings.SCRAPER_DISCOVERY_TIMEOUT_SECONDS)
            await self._add_log(job_id, user_id, "error", "Scraping timeout", {"error": message})
            await self._update_job(job_id, JobStatus.FAILED, 100, "Scraping trop long", error=message)
            jobs_total.labels(status=JobStatus.FAILED.value).inc()
            job_duration_seconds.observe(monotonic() - start)
            return []
        except Exception as exc:
            logger.exception("Scraping job failed", job_id=job_id, error=str(exc))
            await self._add_log(job_id, user_id, "error", "Scraping failed", {"error": str(exc)})
            await self._update_job(job_id, JobStatus.FAILED, 100, "Scraping echoue", error=str(exc))
            jobs_total.labels(status=JobStatus.FAILED.value).inc()
            job_duration_seconds.observe(monotonic() - start)
            return []

    async def _save_leads(
        self,
        job_id: str,
        user_id: str,
        request: SearchRequest,
        scraped_leads: list[ScrapedLead],
    ) -> list[LeadRecord]:
        records: list[LeadRecord] = []
        skipped_invalid_contact = 0
        for lead in scraped_leads:
            fingerprint = self._fingerprint(user_id, lead)
            existing = await self.db.scalar(
                select(LeadRecord).where(
                    LeadRecord.user_id == user_id,
                    LeadRecord.fingerprint == fingerprint,
                )
            )
            if existing:
                if settings.MERGE_DUPLICATE_LEADS:
                    await self._merge_existing_lead(existing, lead, request.query)
                if request.require_valid_contact and not self._record_has_valid_contact(existing, request.location):
                    skipped_invalid_contact += 1
                    continue
                if request.only_new:
                    continue
                records.append(existing)
                continue

            quality = (lead.raw_data or {}).get("quality") or enrich_quality(lead, request.location)
            if request.require_valid_contact and not has_valid_contact(quality):
                skipped_invalid_contact += 1
                continue
            if request.require_valid_contact:
                normalize_valid_contacts(lead, quality)
            score, qualification = score_lead(lead, request.query)
            score = min(100, int((score * 0.7) + (quality["confidence_score"] * 0.3)))
            lead_category = request.lead_category or self._infer_lead_category(request.query, lead)
            lead_intent = request.lead_intent or self._infer_lead_intent(request.query, lead)
            raw_data = dict(lead.raw_data or {})
            raw_data["quality"] = quality
            raw_data["target_type"] = SearchTargetType.LEAD.value
            record = LeadRecord(
                user_id=user_id,
                job_id=job_id,
                full_name=lead.full_name,
                job_title=lead.job_title,
                company_name=lead.company_name,
                company_domain=lead.company_domain,
                lead_category=lead_category.value,
                lead_intent=lead_intent.value if lead_intent else None,
                demand_property_type=self._property_types_to_string(request.property_type),
                demand_location=request.location,
                budget_min=request.budget_min,
                budget_max=request.budget_max,
                email=lead.email,
                phone=lead.phone,
                linkedin_url=lead.linkedin_url,
                website=lead.website,
                city=lead.city,
                country=lead.country,
                source=lead.source,
                source_url=lead.source_url,
                score=score,
                qualification=qualification.value,
                fingerprint=fingerprint,
                raw_description=lead.raw_description,
                raw_data=raw_data,
            )
            self.db.add(record)
            records.append(record)

        await self.db.commit()
        for record in records:
            await self.db.refresh(record)
        if skipped_invalid_contact:
            await self._add_log(
                job_id,
                user_id,
                "info",
                "Leads without valid contact filtered",
                {"filtered": skipped_invalid_contact},
            )
        return records

    async def _save_properties(
        self,
        job_id: str,
        user_id: str,
        request: SearchRequest,
        scraped_leads: list[ScrapedLead],
    ) -> list[PropertyRecord]:
        records: list[PropertyRecord] = []
        for item in scraped_leads:
            fingerprint = self._property_fingerprint(user_id, item)
            existing = await self.db.scalar(
                select(PropertyRecord).where(
                    PropertyRecord.user_id == user_id,
                    PropertyRecord.fingerprint == fingerprint,
                )
            )
            if existing:
                await self._merge_existing_property(existing, item, request.query)
                if request.only_new:
                    continue
                records.append(existing)
                continue

            quality = enrich_quality(item)
            title = self._property_title(item, request.query)
            raw_data = dict(item.raw_data or {})
            raw_data["quality"] = quality
            raw_data["target_type"] = SearchTargetType.PROPERTY.value
            price, currency = self._extract_price(item.raw_description or title or "")
            surface, surface_unit = self._extract_surface(item.raw_description or title or "")
            record = PropertyRecord(
                user_id=user_id,
                job_id=job_id,
                title=title,
                property_type=self._select_property_type(request, item).value,
                transaction_type=(request.transaction_type or self._infer_transaction_type(request.query, item)).value,
                price=price,
                currency=currency,
                location_text=item.city or request.location,
                city=item.city or request.location,
                country=item.country,
                surface=surface,
                surface_unit=surface_unit,
                seller_name=item.company_name or item.full_name,
                seller_phone=item.phone,
                seller_email=item.email,
                seller_website=item.website,
                source=item.source,
                source_url=item.source_url,
                score=quality["confidence_score"],
                fingerprint=fingerprint,
                raw_description=item.raw_description,
                raw_data=raw_data,
            )
            self.db.add(record)
            records.append(record)

        await self.db.commit()
        for record in records:
            await self.db.refresh(record)
        return records

    async def _save_signals(
        self,
        job_id: str,
        user_id: str,
        request: SearchRequest,
        scraped_items: list[ScrapedLead],
    ) -> list[SignalRecord]:
        records: list[SignalRecord] = []
        for item in scraped_items:
            fingerprint = self._signal_fingerprint(user_id, item)
            existing = await self.db.scalar(
                select(SignalRecord).where(
                    SignalRecord.user_id == user_id,
                    SignalRecord.fingerprint == fingerprint,
                )
            )
            if existing:
                if request.only_new:
                    continue
                records.append(existing)
                continue

            quality = (item.raw_data or {}).get("quality") or enrich_quality(item, request.location)
            normalize_valid_contacts(item, quality)
            category = request.signal_category or self._infer_signal_category(request, item)
            intent = request.signal_intent or self._infer_signal_intent(request, item)
            raw_data = dict(item.raw_data or {})
            raw_data["quality"] = quality
            raw_data["target_type"] = SearchTargetType.SIGNAL.value
            record = SignalRecord(
                user_id=user_id,
                job_id=job_id,
                signal_category=category.value,
                signal_intent=intent.value,
                content=item.raw_description,
                author_name=item.full_name or item.company_name,
                author_handle=self._extract_social_handle(item.source_url),
                location_text=item.city or request.location,
                language=request.language,
                email=item.email,
                phone=item.phone,
                source=item.source,
                source_url=item.source_url,
                confidence_score=self._signal_confidence(request, item, quality),
                has_valid_contact=has_valid_contact(quality),
                fingerprint=fingerprint,
                raw_data=raw_data,
            )
            self.db.add(record)
            records.append(record)

        await self.db.commit()
        for record in records:
            await self.db.refresh(record)
        return records

    async def _update_job(
        self,
        job_id: str,
        status: JobStatus,
        progress: int,
        message: str,
        total_leads: int = 0,
        leads: list[LeadRecord] | None = None,
        properties: list[PropertyRecord] | None = None,
        signals: list[SignalRecord] | None = None,
        target_type: SearchTargetType | None = None,
        error: str | None = None,
    ) -> None:
        job = await self.db.get(ScrapeJob, job_id)
        if target_type is None and job:
            target_type = SearchTargetType(
                job.request_data.get("target_type", SearchTargetType.LEAD.value)
            )
        target_type = target_type or SearchTargetType.LEAD
        if job:
            job.status = status.value
            job.progress = progress
            job.message = message
            job.total_leads = total_leads
            job.error = error
            job.updated_at = datetime.now(timezone.utc)
            await self.db.commit()

        payload = {
            "job_id": job_id,
            "status": status.value,
            "target_type": target_type.value,
            "progress": progress,
            "message": message,
            "total_leads": total_leads if target_type == SearchTargetType.LEAD else 0,
            "total_properties": total_leads if target_type == SearchTargetType.PROPERTY else 0,
            "total_signals": total_leads if target_type == SearchTargetType.SIGNAL else 0,
            "total_results": total_leads,
            "leads": [self._lead_to_dict(lead) for lead in leads] if leads else [],
            "properties": [self._property_to_dict(item) for item in properties] if properties else [],
            "signals": [self._signal_to_dict(item) for item in signals] if signals else [],
            "created_at": (job.created_at if job else datetime.now(timezone.utc)).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "error": error,
            "user_id": job.user_id if job else None,
        }
        await redis_client.set(f"job:{job_id}", json.dumps(payload), ttl=3600)

    def _fingerprint(self, user_id: str, lead: ScrapedLead) -> str:
        identity = lead.email or lead.phone or lead.linkedin_url or lead.source_url or ""
        raw = f"{user_id}:{identity}:{lead.company_domain}:{lead.company_name}".lower()
        return sha256(raw.encode("utf-8")).hexdigest()

    def _record_has_valid_contact(self, lead: LeadRecord, location_hint: str | None = None) -> bool:
        quality = {
            "email_quality": validate_email(lead.email),
            "phone_quality": validate_phone(lead.phone, lead.country or location_hint),
        }
        return has_valid_contact(quality)

    def _property_fingerprint(self, user_id: str, item: ScrapedLead) -> str:
        title = self._property_title(item, "") or ""
        price, _ = self._extract_price(item.raw_description or title)
        identity = item.source_url or f"{title}:{price}:{item.city}:{item.phone}"
        raw = f"{user_id}:{identity}".lower()
        return sha256(raw.encode("utf-8")).hexdigest()

    def _signal_fingerprint(self, user_id: str, item: ScrapedLead) -> str:
        identity = item.source_url or f"{item.source}:{item.raw_description}:{item.city}"
        return sha256(f"{user_id}:{identity}".lower().encode("utf-8")).hexdigest()

    async def _merge_existing_lead(self, existing: LeadRecord, lead: ScrapedLead, query: str) -> None:
        changed = False
        for attr in [
            "full_name",
            "job_title",
            "company_name",
            "company_domain",
            "email",
            "phone",
            "linkedin_url",
            "website",
            "city",
            "country",
            "source_url",
            "raw_description",
        ]:
            if not getattr(existing, attr) and getattr(lead, attr, None):
                setattr(existing, attr, getattr(lead, attr))
                changed = True

        quality = enrich_quality(lead)
        score, qualification = score_lead(lead, query)
        score = min(100, int((score * 0.7) + (quality["confidence_score"] * 0.3)))
        if score > existing.score:
            existing.score = score
            existing.qualification = qualification.value
            changed = True

        inferred_category = self._infer_lead_category(query, lead)
        inferred_intent = self._infer_lead_intent(query, lead)
        if existing.lead_category == LeadCategory.OTHER.value and inferred_category != LeadCategory.OTHER:
            existing.lead_category = inferred_category.value
            changed = True
        if not existing.lead_intent and inferred_intent:
            existing.lead_intent = inferred_intent.value
            changed = True

        raw_data = dict(existing.raw_data or {})
        sources = raw_data.setdefault("merged_sources", [])
        if lead.source_url and lead.source_url not in sources:
            sources.append(lead.source_url)
            changed = True
        raw_data["quality"] = max(
            [raw_data.get("quality", {}), quality],
            key=lambda item: item.get("confidence_score", 0),
        )
        existing.raw_data = raw_data
        if changed:
            await self.db.commit()
            await self.db.refresh(existing)

    def _infer_lead_category(self, query: str, lead: ScrapedLead) -> LeadCategory:
        text = f"{query} {lead.company_name or ''} {lead.raw_description or ''}".lower()
        real_estate_terms = [
            "immobilier",
            "maison",
            "villa",
            "appartement",
            "terrain",
            "parcelle",
            "immeuble",
            "loyer",
            "location",
            "louer",
            "acheter",
            "achat",
            "vente",
            "agence immobiliere",
            "agence immobilière",
        ]
        if any(term in text for term in real_estate_terms):
            return LeadCategory.REAL_ESTATE
        return LeadCategory.OTHER

    def _infer_lead_intent(self, query: str, lead: ScrapedLead) -> LeadIntent | None:
        text = f"{query} {lead.raw_description or ''}".lower()
        if any(term in text for term in ["cherche a acheter", "cherche à acheter", "veut acheter", "achat", "acheter"]):
            return LeadIntent.BUY
        if any(term in text for term in ["cherche a louer", "cherche à louer", "veut louer", "location", "louer", "loyer"]):
            return LeadIntent.RENT
        if any(term in text for term in ["vend", "vendre", "a vendre", "à vendre", "vente"]):
            return LeadIntent.SELL
        if "bail" in text:
            return LeadIntent.LEASE
        return None

    def _infer_signal_category(self, request: SearchRequest, item: ScrapedLead) -> SignalCategory:
        text = f"{request.query} {item.raw_description or ''}".lower()
        if any(term in text for term in ["demenage", "déménage", "demenagement", "déménagement", "relocalisation"]):
            return SignalCategory.RELOCATION
        if any(term in text for term in ["voyage", "touriste", "vacances", "destination", "sejour", "séjour"]):
            return SignalCategory.TRAVEL
        if any(term in text for term in ["cherche a acheter", "cherche à acheter", "cherche a louer", "cherche à louer", "besoin logement"]):
            return SignalCategory.PROPERTY_DEMAND
        if any(term in text for term in ["a vendre", "à vendre", "vente", "cherche acheteur"]):
            return SignalCategory.PROPERTY_SALE
        return SignalCategory.OTHER

    def _infer_signal_intent(self, request: SearchRequest, item: ScrapedLead) -> SignalIntent:
        text = f"{request.query} {item.raw_description or ''}".lower()
        if any(term in text for term in ["demenage", "déménage", "demenagement", "déménagement"]):
            return SignalIntent.MOVING
        if any(term in text for term in ["voyage", "touriste", "vacances", "destination"]):
            return SignalIntent.TRAVEL
        if any(term in text for term in ["acheter", "achat"]):
            return SignalIntent.BUY
        if any(term in text for term in ["louer", "location", "loyer"]):
            return SignalIntent.RENT
        if any(term in text for term in ["vendre", "a vendre", "à vendre", "vente"]):
            return SignalIntent.SELL
        return SignalIntent.OTHER

    def _signal_confidence(self, request: SearchRequest, item: ScrapedLead, quality: dict) -> int:
        text = (item.raw_description or "").lower()
        score = 15
        if item.source in {"facebook", "tiktok"}:
            score += 20
        if request.location and request.location.lower() in f"{item.city or ''} {text}".lower():
            score += 20
        if request.include_keywords and any(keyword.lower() in text for keyword in request.include_keywords):
            score += 20
        if self._infer_signal_category(request, item) != SignalCategory.OTHER:
            score += 15
        if has_valid_contact(quality):
            score += 10
        return min(score, 100)

    def _extract_social_handle(self, source_url: str | None) -> str | None:
        if not source_url:
            return None
        parsed = urlparse(source_url)
        parts = [part for part in parsed.path.split("/") if part]
        if not parts:
            return None
        if "tiktok.com" in parsed.netloc and parts[0].startswith("@"):
            return parts[0]
        if "facebook.com" in parsed.netloc:
            ignored = {"groups", "marketplace", "share", "watch", "reel", "posts"}
            if parts[0].lower() not in ignored:
                return parts[0]
        return None

    async def _merge_existing_property(self, existing: PropertyRecord, item: ScrapedLead, query: str) -> None:
        changed = False
        title = self._property_title(item, query)
        price, currency = self._extract_price(item.raw_description or title or "")
        surface, surface_unit = self._extract_surface(item.raw_description or title or "")
        updates = {
            "title": title,
            "price": price,
            "currency": currency,
            "surface": surface,
            "surface_unit": surface_unit,
            "seller_name": item.company_name or item.full_name,
            "seller_phone": item.phone,
            "seller_email": item.email,
            "seller_website": item.website,
            "city": item.city,
            "country": item.country,
            "source_url": item.source_url,
            "raw_description": item.raw_description,
        }
        for attr, value in updates.items():
            if not getattr(existing, attr) and value:
                setattr(existing, attr, value)
                changed = True

        quality = enrich_quality(item)
        if quality["confidence_score"] > existing.score:
            existing.score = quality["confidence_score"]
            changed = True

        raw_data = dict(existing.raw_data or {})
        sources = raw_data.setdefault("merged_sources", [])
        if item.source_url and item.source_url not in sources:
            sources.append(item.source_url)
            changed = True
        raw_data["quality"] = max(
            [raw_data.get("quality", {}), quality],
            key=lambda data: data.get("confidence_score", 0),
        )
        raw_data["target_type"] = SearchTargetType.PROPERTY.value
        existing.raw_data = raw_data
        if changed:
            await self.db.commit()
            await self.db.refresh(existing)

    def _property_title(self, item: ScrapedLead, query: str) -> str | None:
        if item.company_name:
            return item.company_name[:500]
        if item.raw_description:
            return item.raw_description.strip().splitlines()[0][:500]
        if query:
            return query[:500]
        return item.source_url

    def _infer_property_type(self, query: str, item: ScrapedLead) -> PropertyType:
        text = f"{query} {item.company_name or ''} {item.raw_description or ''}".lower()
        if any(term in text for term in ["terrain", "parcelle", "lot "]):
            return PropertyType.LAND
        if any(term in text for term in ["maison", "villa"]):
            return PropertyType.HOUSE
        if any(term in text for term in ["appartement", "studio"]):
            return PropertyType.APARTMENT
        if any(term in text for term in ["immeuble", "building"]):
            return PropertyType.BUILDING
        if "restaurant" in text:
            return PropertyType.RESTAURANT
        if any(term in text for term in ["commerce", "boutique", "local commercial", "fonds de commerce"]):
            return PropertyType.COMMERCIAL
        if any(term in text for term in ["meuble", "mobilier"]):
            return PropertyType.FURNITURE
        if any(term in text for term in ["business", "entreprise a vendre", "entreprise à vendre"]):
            return PropertyType.BUSINESS
        return PropertyType.OTHER

    def _select_property_type(self, request: SearchRequest, item: ScrapedLead) -> PropertyType:
        inferred = self._infer_property_type(request.query, item)
        requested = request.property_type or []
        if not requested:
            return inferred
        if inferred in requested:
            return inferred
        return requested[0]

    def _property_types_to_string(self, property_types: list[PropertyType] | None) -> str | None:
        if not property_types:
            return None
        return ",".join(item.value for item in property_types)

    def _infer_transaction_type(self, query: str, item: ScrapedLead) -> TransactionType:
        text = f"{query} {item.raw_description or ''}".lower()
        if any(term in text for term in ["a louer", "à louer", "location", "loyer"]):
            return TransactionType.RENT
        if any(term in text for term in ["bail", "lease"]):
            return TransactionType.LEASE
        if any(term in text for term in ["a vendre", "à vendre", "vente", "vendre"]):
            return TransactionType.SALE
        return TransactionType.OTHER

    def _extract_price(self, text: str) -> tuple[float | None, str | None]:
        pattern = re.compile(
            r"(?P<amount>\d[\d\s.,]{2,})\s*(?P<currency>fcfa|xof|cfa|eur|€|usd|\$)?",
            re.IGNORECASE,
        )
        match = pattern.search(text)
        if not match:
            return None, None
        raw_amount = match.group("amount").replace(" ", "").replace(",", ".")
        try:
            amount = float(raw_amount)
        except ValueError:
            return None, None
        currency = (match.group("currency") or "").upper()
        if currency in {"FCFA", "CFA"}:
            currency = "XOF"
        if currency == "€":
            currency = "EUR"
        if currency == "$":
            currency = "USD"
        return amount, currency or None

    def _extract_surface(self, text: str) -> tuple[float | None, str | None]:
        match = re.search(r"(\d+(?:[.,]\d+)?)\s*(m2|m²|ha|hectare|hectares)", text, re.IGNORECASE)
        if not match:
            return None, None
        surface = float(match.group(1).replace(",", "."))
        unit = match.group(2).lower()
        if unit == "m²":
            unit = "m2"
        if unit in {"hectare", "hectares"}:
            unit = "ha"
        return surface, unit

    async def _add_log(self, job_id: str, user_id: str, level: str, message: str, data: dict | None = None) -> None:
        self.db.add(
            ScrapeJobLog(
                job_id=job_id,
                user_id=user_id,
                level=level,
                message=message,
                data=data or {},
            )
        )
        await self.db.commit()

    async def _is_cancelled(self, job_id: str) -> bool:
        return await redis_client.exists(f"job:{job_id}:cancel")

    def _lead_to_dict(self, lead: LeadRecord) -> dict:
        return {
            "id": lead.id,
            "full_name": lead.full_name,
            "first_name": lead.first_name,
            "last_name": lead.last_name,
            "job_title": lead.job_title,
            "company_name": lead.company_name,
            "company_domain": lead.company_domain,
            "company_size": lead.company_size,
            "industry": lead.industry,
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
            "is_verified": lead.is_verified,
            "fingerprint": lead.fingerprint,
            "scraped_at": lead.scraped_at.isoformat() if lead.scraped_at else None,
            "raw_description": lead.raw_description,
            "confidence_score": lead.confidence_score,
            "email_valid_syntax": lead.email_valid_syntax,
            "email_domain_has_mx": lead.email_domain_has_mx,
            "phone_is_valid": lead.phone_is_valid,
        }

    def _property_to_dict(self, item: PropertyRecord) -> dict:
        return {
            "id": item.id,
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
            "rooms": item.rooms,
            "bedrooms": item.bedrooms,
            "seller_name": item.seller_name,
            "seller_phone": item.seller_phone,
            "seller_email": item.seller_email,
            "seller_website": item.seller_website,
            "source": item.source,
            "source_url": item.source_url,
            "score": item.score,
            "confidence_score": item.confidence_score,
            "is_verified": item.is_verified,
            "fingerprint": item.fingerprint,
            "scraped_at": item.scraped_at.isoformat() if item.scraped_at else None,
            "raw_description": item.raw_description,
            "raw_data": item.raw_data,
        }

    def _signal_to_dict(self, item: SignalRecord) -> dict:
        return {
            "id": item.id,
            "signal_category": item.signal_category,
            "signal_intent": item.signal_intent,
            "content": item.content,
            "author_name": item.author_name,
            "author_handle": item.author_handle,
            "location_text": item.location_text,
            "language": item.language,
            "email": item.email,
            "phone": item.phone,
            "source": item.source,
            "source_url": item.source_url,
            "confidence_score": item.confidence_score,
            "has_valid_contact": item.has_valid_contact,
            "fingerprint": item.fingerprint,
            "scraped_at": item.scraped_at.isoformat() if item.scraped_at else None,
            "raw_data": item.raw_data,
        }
