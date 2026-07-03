"""
Exceptions personnalisées ScoutAPI
"""
from fastapi import HTTPException


class ScoutAPIException(Exception):
    """Base exception ScoutAPI."""
    def __init__(self, message: str, code: str = "INTERNAL_ERROR"):
        self.message = message
        self.code = code
        super().__init__(message)


class BlockedByTargetError(ScoutAPIException):
    """Le scraper a été bloqué par le site cible."""
    def __init__(self, platform: str, reason: str):
        super().__init__(
            message=f"Blocked by {platform}: {reason}",
            code="SCRAPER_BLOCKED"
        )
        self.platform = platform
        self.reason = reason


class ProxyExhaustedError(ScoutAPIException):
    """Tous les proxies sont épuisés ou en échec."""
    def __init__(self):
        super().__init__(
            message="All proxies are unhealthy or exhausted",
            code="PROXY_EXHAUSTED"
        )


class AIParsingError(ScoutAPIException):
    """Erreur lors du parsing IA."""
    def __init__(self, model: str, reason: str):
        super().__init__(
            message=f"AI parsing failed with {model}: {reason}",
            code="AI_PARSING_ERROR"
        )


class RateLimitError(ScoutAPIException):
    """Rate limit atteint pour un domaine."""
    def __init__(self, domain: str):
        super().__init__(
            message=f"Rate limit reached for {domain}",
            code="RATE_LIMIT_EXCEEDED"
        )


class JobNotFoundError(HTTPException):
    def __init__(self, job_id: str):
        super().__init__(status_code=404, detail=f"Job '{job_id}' not found")


class LeadNotFoundError(HTTPException):
    def __init__(self, lead_id: str):
        super().__init__(status_code=404, detail=f"Lead '{lead_id}' not found")


class PropertyNotFoundError(HTTPException):
    def __init__(self, property_id: str):
        super().__init__(status_code=404, detail=f"Property '{property_id}' not found")


class SignalNotFoundError(HTTPException):
    def __init__(self, signal_id: str):
        super().__init__(status_code=404, detail=f"Signal '{signal_id}' not found")
