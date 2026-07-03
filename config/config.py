"""
Configuration centralisée — chargée depuis .env via pydantic-settings
"""
import json
from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ─── Application ────────────────────────────────────────
    APP_NAME: str = "ScoutAPI"
    APP_VERSION: str = "1.0.0"
    APP_ENV: str = "development"
    APP_DEBUG: bool = True
    APP_SECRET_KEY: str = "change-me-in-production"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    APP_WORKERS: int = 1
    ALLOWED_ORIGINS: str = "*"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    JWT_ALGORITHM: str = "HS256"
    API_KEY_PREFIX: str = "sk_scout_"
    API_KEY_DEFAULT_NAME: str = "n8n"

    # ─── Database ────────────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://scoutapi:scoutapi_password@localhost:5432/scoutapi_db"

    # ─── Redis ───────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"
    CACHE_TTL_SECONDS: int = 86400
    ARQ_QUEUE_NAME: str = "scoutapi:jobs"
    ARQ_JOB_TIMEOUT_SECONDS: int = 600

    # ─── OpenRouter / AI ─────────────────────────────────────
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENROUTER_SITE_URL: str = "http://localhost:8000"
    OPENROUTER_APP_NAME: str = "ScoutAPI"

    AI_MODEL_PARSING: str = "openai/gpt-oss-120b:free"
    AI_MODEL_QUALIFICATION: str = "deepseek/deepseek-chat-v3.1:free"
    AI_MODEL_ENRICHMENT: str = "google/gemini-2.0-flash-exp:free"
    AI_MODEL_DETECTION: str = "qwen/qwen3-32b:free"
    AI_MODEL_FALLBACK: str = "nvidia/nemotron-nano-9b-v2:free"

    # Tavily Search
    TAVILY_API_KEY: str = ""
    TAVILY_BASE_URL: str = "https://api.tavily.com"
    TAVILY_SEARCH_DEPTH: str = "basic"
    TAVILY_INCLUDE_RAW_CONTENT: bool = False
    TAVILY_COUNTRY: str = "france"

    # ─── Proxies ─────────────────────────────────────────────
    PROXY_LIST: str = ""
    PROXY_HEALTH_CHECK_INTERVAL: int = 300
    PROXY_MAX_FAILURES: int = 3

    @property
    def proxy_list(self) -> List[str]:
        if not self.PROXY_LIST:
            return []
        return [p.strip() for p in self.PROXY_LIST.split(",") if p.strip()]

    @property
    def allowed_origins(self) -> List[str]:
        if self.ALLOWED_ORIGINS.strip() == "*":
            return ["*"]
        try:
            parsed = json.loads(self.ALLOWED_ORIGINS)
            if isinstance(parsed, list):
                return [str(origin) for origin in parsed]
        except json.JSONDecodeError:
            pass
        return [origin.strip() for origin in self.ALLOWED_ORIGINS.split(",") if origin.strip()]

    # ─── Scraping — Délais ───────────────────────────────────
    DELAY_GOOGLE_MIN: float = 3.0
    DELAY_GOOGLE_MAX: float = 8.0
    DELAY_LINKEDIN_MIN: float = 5.0
    DELAY_LINKEDIN_MAX: float = 15.0
    DELAY_DIRECTORY_MIN: float = 1.0
    DELAY_DIRECTORY_MAX: float = 4.0

    MAX_RETRIES: int = 3
    MAX_CONCURRENT_SCRAPERS: int = 3
    SCRAPER_TIMEOUT: int = 30
    SCRAPER_DISCOVERY_TIMEOUT_SECONDS: int = 240
    SCRAPER_ITEM_TIMEOUT_SECONDS: int = 12
    SCRAPER_MAX_QUERY_VARIANTS: int = 5
    SCRAPER_MAX_RESULTS_PER_QUERY: int = 6
    SCRAPER_DISCOVERY_PROVIDER: str = "auto"
    URL_CACHE_TTL_SECONDS: int = 21600
    SITE_CRAWLER_MAX_CONTACT_PAGES: int = 5
    SITE_CRAWLER_ENABLE_SITEMAP: bool = True
    MERGE_DUPLICATE_LEADS: bool = True
    PAGES_JAUNES_DEDICATED_EXTRACTOR: bool = True
    SCRAPER_USER_AGENT: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    )

    # ─── LinkedIn ────────────────────────────────────────────
    LINKEDIN_EMAIL: str = ""
    LINKEDIN_PASSWORD: str = ""
    LINKEDIN_MAX_PROFILE_VIEWS_PER_DAY: int = 80
    LINKEDIN_MAX_SEARCHES_PER_DAY: int = 40

    # ─── Rate Limiting API ───────────────────────────────────
    RATE_LIMIT_REQUESTS_PER_MINUTE: int = 60
    RATE_LIMIT_REQUESTS_PER_HOUR: int = 1000
    FREE_MAX_ACTIVE_JOBS_PER_USER: int = 3
    FREE_MAX_JOBS_PER_DAY: int = 20
    FREE_MAX_RESULTS_PER_JOB: int = 50
    DOMAIN_RATE_LIMIT_DEFAULT_SECONDS: float = 1.5
    DOMAIN_RATE_LIMIT_PAGESJAUNES_SECONDS: float = 4.0
    DOMAIN_RATE_LIMIT_LINKEDIN_SECONDS: float = 15.0
    DOMAIN_RATE_LIMIT_GOOGLE_SECONDS: float = 8.0

    # ─── Captcha ─────────────────────────────────────────────
    TWOCAPTCHA_API_KEY: Optional[str] = None
    ANTICAPTCHA_API_KEY: Optional[str] = None

    # ─── Logging ─────────────────────────────────────────────
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"
    LOG_FILE: str = "logs/scoutapi.log"


settings = Settings()
