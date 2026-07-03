from openai import AsyncOpenAI

from app.config import settings


class OpenRouterClient:
    def __init__(self) -> None:
        self.enabled = bool(settings.OPENROUTER_API_KEY)
        self._client = (
            AsyncOpenAI(
                api_key=settings.OPENROUTER_API_KEY,
                base_url=settings.OPENROUTER_BASE_URL,
                default_headers={
                    "HTTP-Referer": settings.OPENROUTER_SITE_URL,
                    "X-Title": settings.OPENROUTER_APP_NAME,
                },
            )
            if self.enabled
            else None
        )

    async def summarize_lead(self, text: str) -> str | None:
        if not self._client or not text:
            return None
        response = await self._client.chat.completions.create(
            model=settings.AI_MODEL_PARSING,
            messages=[
                {
                    "role": "system",
                    "content": "Extract a concise French B2B lead summary from noisy web text.",
                },
                {"role": "user", "content": text[:4000]},
            ],
            max_tokens=120,
            temperature=0,
        )
        return response.choices[0].message.content
