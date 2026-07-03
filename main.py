"""
ScoutAPI — Lead Scraping API
Entry point principal FastAPI
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import text

from app.api.v1.routers import auth, health, search, leads, jobs, properties, signals
from app.config import settings
from app.db.database import engine, Base
from app.cache.redis_client import redis_client
from app.models import User, RefreshToken
from app.utils.logger import get_logger
from app.web.auth_page import auth_page

logger = get_logger(__name__)

# ─── Rate Limiter ──────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)


async def ensure_runtime_schema(conn) -> None:
    if not settings.DATABASE_URL.startswith("postgresql"):
        return
    statements = [
        "ALTER TABLE leads ADD COLUMN IF NOT EXISTS lead_category VARCHAR(64) DEFAULT 'other' NOT NULL",
        "ALTER TABLE leads ADD COLUMN IF NOT EXISTS lead_intent VARCHAR(64)",
        "ALTER TABLE leads ADD COLUMN IF NOT EXISTS demand_property_type VARCHAR(64)",
        "ALTER TABLE leads ADD COLUMN IF NOT EXISTS demand_location VARCHAR(255)",
        "ALTER TABLE leads ADD COLUMN IF NOT EXISTS budget_min DOUBLE PRECISION",
        "ALTER TABLE leads ADD COLUMN IF NOT EXISTS budget_max DOUBLE PRECISION",
        "CREATE INDEX IF NOT EXISTS ix_leads_lead_category ON leads (lead_category)",
        "CREATE INDEX IF NOT EXISTS ix_leads_lead_intent ON leads (lead_intent)",
        "CREATE INDEX IF NOT EXISTS ix_leads_demand_property_type ON leads (demand_property_type)",
    ]
    for statement in statements:
        await conn.execute(text(statement))


# ─── Lifespan (startup / shutdown) ────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting ScoutAPI...", version=settings.APP_VERSION, env=settings.APP_ENV)

    # Créer les tables DB
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await ensure_runtime_schema(conn)
    logger.info("Database tables ready")

    # Connecter Redis
    await redis_client.connect()
    logger.info("Redis connected")

    yield

    # Shutdown
    await redis_client.disconnect()
    await engine.dispose()
    logger.info("ScoutAPI shutdown complete")


# ─── App ───────────────────────────────────────────────────────
app = FastAPI(
    title="ScoutAPI",
    description="🕷️ API de scraping intelligent pour la génération de leads B2B",
    version=settings.APP_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# ─── Middlewares ──────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.APP_ENV == "development" else settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if settings.APP_ENV == "production":
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Prometheus metrics
Instrumentator().instrument(app).expose(app, endpoint="/metrics")

# ─── Routers ──────────────────────────────────────────────────
app.include_router(health.router, prefix="/v1", tags=["Health"])
app.include_router(auth.router, prefix="/v1", tags=["Auth"])
app.include_router(search.router, prefix="/v1", tags=["Search"])
app.include_router(leads.router, prefix="/v1", tags=["Leads"])
app.include_router(properties.router, prefix="/v1", tags=["Properties"])
app.include_router(signals.router, prefix="/v1", tags=["Signals"])
app.include_router(jobs.router, prefix="/v1", tags=["Jobs"])


@app.get("/", include_in_schema=False)
async def root():
    return {
        "name": "ScoutAPI",
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "status": "running",
    }


@app.get("/auth", include_in_schema=False)
async def auth_ui():
    return auth_page()
