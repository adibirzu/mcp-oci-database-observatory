"""Response caching for fast AI agent interactions.

Implements tiered TTL caching based on data volatility:
- Static: 1 hour (profiles, regions, parsers)
- Stable: 30 min (compartments, log sources)
- Infrastructure: 10-15 min (fleet summary, databases)
- Analysis: 2 min (CPU analysis, queries)
- Real-time: 0 (health, ping)
"""

import asyncio
import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional


class CacheTier(Enum):
    """Cache tier with TTL in seconds."""

    STATIC = 3600  # 1 hour - profiles, regions, parsers
    STABLE = 1800  # 30 min - compartments, log sources
    INFRASTRUCTURE = 600  # 10 min - fleet, databases
    ANALYSIS = 120  # 2 min - performance analysis
    REAL_TIME = 0  # No caching - health, ping


# Tool-to-tier mapping
TOOL_CACHE_TIERS: Dict[str, CacheTier] = {
    # Static - rarely changes
    "list_oci_profiles": CacheTier.STATIC,
    "list_cached_regions": CacheTier.STATIC,
    "list_parsers": CacheTier.STATIC,
    "list_labels": CacheTier.STATIC,
    # Stable - changes occasionally
    "list_compartments": CacheTier.STABLE,
    "list_log_sources": CacheTier.STABLE,
    "list_active_log_sources": CacheTier.STABLE,
    "list_entities": CacheTier.STABLE,
    "list_log_groups": CacheTier.STABLE,
    "get_profile_info": CacheTier.STABLE,
    # Infrastructure - changes with deployments
    "get_fleet_summary": CacheTier.INFRASTRUCTURE,
    "search_databases": CacheTier.INFRASTRUCTURE,
    "list_autonomous_databases": CacheTier.INFRASTRUCTURE,
    "list_connections": CacheTier.INFRASTRUCTURE,
    "get_schema_info": CacheTier.INFRASTRUCTURE,
    # Analysis - relatively fresh data
    "analyze_cpu_usage": CacheTier.ANALYSIS,
    "analyze_memory_usage": CacheTier.ANALYSIS,
    "analyze_io_performance": CacheTier.ANALYSIS,
    # Backward compatibility aliases
    "skill_analyze_cpu_usage": CacheTier.ANALYSIS,
    "skill_analyze_memory_usage": CacheTier.ANALYSIS,
    "skill_analyze_io_performance": CacheTier.ANALYSIS,
    "execute_logan_query": CacheTier.ANALYSIS,
    # Real-time - no caching
    "health_check": CacheTier.REAL_TIME,
    "ping": CacheTier.REAL_TIME,
    "execute_sql": CacheTier.REAL_TIME,
    "database_status": CacheTier.REAL_TIME,
}


@dataclass
class CacheEntry:
    """Single cache entry with metadata."""

    value: Any
    created_at: float
    ttl: float
    hits: int = 0

    def is_expired(self) -> bool:
        """Check if entry has expired."""
        if self.ttl <= 0:
            return True
        return time.time() - self.created_at > self.ttl


@dataclass
class CacheStats:
    """Cache statistics for monitoring."""

    hits: int = 0
    misses: int = 0
    evictions: int = 0
    entries: int = 0
    memory_bytes: int = 0

    def hit_rate(self) -> float:
        """Calculate hit rate percentage."""
        total = self.hits + self.misses
        if total == 0:
            return 0.0
        return (self.hits / total) * 100


class ResponseCache:
    """In-memory cache with TTL and eviction.

    Thread-safe via asyncio locks. Designed for fast
    AI agent response times.
    """

    def __init__(self, max_entries: int = 1000, redis_url: str | None = None):
        """Initialize cache.

        Args:
            max_entries: Maximum cache entries before eviction
        """
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = asyncio.Lock()
        self._max_entries = max_entries
        self._stats = CacheStats()
        self._redis_url = redis_url or os.getenv("MCP_REDIS_URL") or os.getenv("REDIS_URL")
        self._redis_prefix = os.getenv("MCP_CACHE_KEY_PREFIX", "mcp:cache")
        self._redis_namespace = f"{self._redis_prefix}:responses"
        backend = os.getenv("MCP_CACHE_BACKEND", "").lower()
        self._use_redis = bool(self._redis_url) if backend != "memory" else False
        self._client = None

    async def _get_client(self):
        if self._client is None:
            import redis.asyncio as redis

            self._client = redis.from_url(self._redis_url, decode_responses=True)
            await self._client.ping()
        return self._client

    def _redis_key(self, key: str) -> str:
        return f"{self._redis_namespace}:{key}"

    def _make_key(self, tool_name: str, args: Dict[str, Any]) -> str:
        """Generate cache key from tool name and args.

        Args:
            tool_name: Name of the tool
            args: Tool arguments

        Returns:
            Unique cache key
        """
        # Sort args for consistent keys
        sorted_args = json.dumps(args, sort_keys=True, default=str)
        combined = f"{tool_name}:{sorted_args}"
        digest = hashlib.sha256(combined.encode()).hexdigest()[:32]
        return f"{tool_name}:{digest}"

    def get_ttl(self, tool_name: str) -> float:
        """Get TTL for a tool.

        Args:
            tool_name: Name of the tool

        Returns:
            TTL in seconds
        """
        tier = TOOL_CACHE_TIERS.get(tool_name, CacheTier.ANALYSIS)
        return tier.value

    async def get(self, tool_name: str, args: Dict[str, Any]) -> Optional[Any]:
        """Get cached value if not expired.

        Args:
            tool_name: Name of the tool
            args: Tool arguments

        Returns:
            Cached value or None if miss/expired
        """
        key = self._make_key(tool_name, args)

        async with self._lock:
            if self._use_redis:
                try:
                    client = await self._get_client()
                    value = await client.get(self._redis_key(key))
                    if value is None:
                        self._stats.misses += 1
                        return None
                    self._stats.hits += 1
                    try:
                        return json.loads(value)
                    except json.JSONDecodeError:
                        return value
                except Exception:
                    self._stats.misses += 1
                    return None

            entry = self._cache.get(key)
            if entry is None:
                self._stats.misses += 1
                return None

            if entry.is_expired():
                del self._cache[key]
                self._stats.misses += 1
                self._stats.evictions += 1
                return None

            entry.hits += 1
            self._stats.hits += 1
            return entry.value

    async def set(
        self, tool_name: str, args: Dict[str, Any], value: Any, ttl: Optional[float] = None
    ) -> None:
        """Set cache value.

        Args:
            tool_name: Name of the tool
            args: Tool arguments
            value: Value to cache
            ttl: Optional TTL override
        """
        if ttl is None:
            ttl = self.get_ttl(tool_name)

        if ttl <= 0:
            return  # Don't cache real-time data

        key = self._make_key(tool_name, args)

        async with self._lock:
            if self._use_redis:
                try:
                    client = await self._get_client()
                    payload = json.dumps(value, default=str)
                    await client.setex(self._redis_key(key), int(ttl), payload)
                    self._stats.entries += 1
                    return
                except Exception:
                    self._use_redis = False

            # Evict oldest if at capacity
            if len(self._cache) >= self._max_entries:
                await self._evict_oldest()

            self._cache[key] = CacheEntry(
                value=value,
                created_at=time.time(),
                ttl=ttl,
            )
            self._stats.entries = len(self._cache)

    async def _evict_oldest(self) -> None:
        """Evict oldest entries to make room."""
        # Sort by created_at and remove oldest 10%
        entries = sorted(self._cache.items(), key=lambda x: x[1].created_at)
        to_remove = max(1, len(entries) // 10)

        for key, _ in entries[:to_remove]:
            del self._cache[key]
            self._stats.evictions += 1

    async def invalidate(self, tool_name: Optional[str] = None) -> int:
        """Invalidate cache entries.

        Args:
            tool_name: Optional tool name to invalidate (None = all)

        Returns:
            Number of entries invalidated
        """
        async with self._lock:
            if self._use_redis:
                try:
                    client = await self._get_client()
                    if tool_name is None:
                        pattern = f"{self._redis_namespace}:*"
                    else:
                        pattern = f"{self._redis_namespace}:{tool_name}:*"
                    keys = [k async for k in client.scan_iter(match=pattern)]
                    if keys:
                        await client.delete(*keys)
                    self._stats.entries = 0
                    return len(keys)
                except Exception:
                    self._use_redis = False

            if tool_name is None:
                count = len(self._cache)
                self._cache.clear()
                self._stats.entries = 0
                return count

            # Invalidate entries for specific tool
            keys_to_remove = [
                k for k, v in self._cache.items() if tool_name in str(v.value)
            ]
            for key in keys_to_remove:
                del self._cache[key]

            self._stats.entries = len(self._cache)
            return len(keys_to_remove)

    async def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics.

        Returns:
            Cache statistics dict
        """
        async with self._lock:
            if self._use_redis:
                try:
                    client = await self._get_client()
                    keys = [k async for k in client.scan_iter(match=f"{self._redis_namespace}:*")]
                    self._stats.entries = len(keys)
                except Exception:
                    self._use_redis = False

            if not self._use_redis:
                # Clean expired entries
                expired_keys = [k for k, v in self._cache.items() if v.is_expired()]
                for key in expired_keys:
                    del self._cache[key]
                    self._stats.evictions += 1

                self._stats.entries = len(self._cache)

            return {
                "backend": "redis" if self._use_redis else "memory",
                "hits": self._stats.hits,
                "misses": self._stats.misses,
                "hit_rate": f"{self._stats.hit_rate():.1f}%",
                "entries": self._stats.entries,
                "evictions": self._stats.evictions,
                "max_entries": self._max_entries,
            }


# Global cache instance
_cache: Optional[ResponseCache] = None


def get_cache() -> ResponseCache:
    """Get the global cache instance."""
    global _cache
    if _cache is None:
        redis_url = os.getenv("MCP_REDIS_URL") or os.getenv("REDIS_URL")
        _cache = ResponseCache(redis_url=redis_url)
    return _cache


async def cached_call(
    tool_name: str,
    args: Dict[str, Any],
    fn: Callable[..., Any],
) -> Any:
    """Execute function with caching.

    The args dict is used for cache key generation only. The function
    should be a closure that captures its parameters from the outer scope.

    Args:
        tool_name: Name of the tool (for TTL lookup)
        args: Dict used for cache key (NOT passed to fn)
        fn: Async function to call (zero-argument closure)

    Returns:
        Cached or fresh result
    """
    cache = get_cache()

    # Try cache first
    cached = await cache.get(tool_name, args)
    if cached is not None:
        return cached

    # Execute and cache - fn is a closure, don't pass args
    result = await fn()
    await cache.set(tool_name, args, result)
    return result
