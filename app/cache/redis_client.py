from typing import Optional

from redis.asyncio import Redis

from app.config import settings


class RedisClient:
    def __init__(self) -> None:
        self._client: Optional[Redis] = None

    async def connect(self) -> None:
        if self._client is None:
            self._client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
        await self._client.ping()

    async def disconnect(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def ping(self) -> bool:
        try:
            if self._client is None:
                await self.connect()
            return bool(await self._client.ping())
        except Exception:
            return False

    async def get(self, key: str):
        if self._client is None:
            await self.connect()
        return await self._client.get(key)

    async def set(self, key: str, value: str, ttl: Optional[int] = None) -> None:
        if self._client is None:
            await self.connect()
        await self._client.set(key, value, ex=ttl)

    async def delete(self, key: str) -> None:
        if self._client is None:
            await self.connect()
        await self._client.delete(key)

    async def exists(self, key: str) -> bool:
        if self._client is None:
            await self.connect()
        return bool(await self._client.exists(key))

    async def ttl(self, key: str) -> int:
        if self._client is None:
            await self.connect()
        return await self._client.ttl(key)


redis_client = RedisClient()
