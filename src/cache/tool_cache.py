"""Tool result cache with Redis backend."""

import json
from typing import Any

from src.core import get_logger

logger = get_logger("cache.tool_cache")


class ToolResultCache:
    """Redis-backed cache for MCP tool results."""

    def __init__(self, redis_url: str) -> None:
        """Initialize tool cache.

        Args:
            redis_url: Redis connection URL
        """
        self._redis_url = redis_url
        self._client = None

    @property
    def client(self):
        """Lazy-load Redis client."""
        if self._client is None:
            try:
                import redis.asyncio as redis
                self._client = redis.from_url(self._redis_url)
            except Exception as e:
                logger.warning("Failed to connect to Redis", error=str(e))
        return self._client

    async def get(self, key: str) -> Any | None:
        """Get cached value.

        Args:
            key: Cache key

        Returns:
            Cached value or None
        """
        if not self.client:
            return None

        try:
            data = await self.client.get(key)
            if data:
                return json.loads(data)
        except Exception as e:
            logger.warning("Cache get failed", key=key, error=str(e))

        return None

    async def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: int = 120,
    ) -> bool:
        """Set cached value.

        Args:
            key: Cache key
            value: Value to cache
            ttl_seconds: Time to live in seconds

        Returns:
            True if cached successfully
        """
        if not self.client:
            return False

        try:
            data = json.dumps(value)
            await self.client.setex(key, ttl_seconds, data)
            return True
        except Exception as e:
            logger.warning("Cache set failed", key=key, error=str(e))
            return False

    async def delete(self, key: str) -> bool:
        """Delete cached value.

        Args:
            key: Cache key

        Returns:
            True if deleted
        """
        if not self.client:
            return False

        try:
            await self.client.delete(key)
            return True
        except Exception as e:
            logger.warning("Cache delete failed", key=key, error=str(e))
            return False

    async def clear_prefix(self, prefix: str) -> int:
        """Clear all keys with prefix.

        Args:
            prefix: Key prefix

        Returns:
            Number of keys deleted
        """
        if not self.client:
            return 0

        try:
            keys = []
            async for key in self.client.scan_iter(match=f"{prefix}*"):
                keys.append(key)

            if keys:
                await self.client.delete(*keys)
                return len(keys)
        except Exception as e:
            logger.warning("Cache clear failed", prefix=prefix, error=str(e))

        return 0

    async def health_check(self) -> dict[str, Any]:
        """Check cache health.

        Returns:
            Health status
        """
        if not self.client:
            return {"status": "unavailable", "error": "No Redis connection"}

        try:
            await self.client.ping()
            info = await self.client.info("memory")
            return {
                "status": "healthy",
                "used_memory": info.get("used_memory_human", "unknown"),
            }
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}

    async def close(self) -> None:
        """Close Redis connection."""
        if self._client:
            await self._client.close()
            self._client = None
