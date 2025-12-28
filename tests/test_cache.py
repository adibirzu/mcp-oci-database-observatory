"""Tests for caching module."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_cache_set_get(mock_redis):
    """Test cache set and get."""
    from src.cache.tool_cache import ToolResultCache

    cache = ToolResultCache("redis://localhost:6379")
    cache._client = mock_redis

    # Test set
    result = await cache.set("test_key", {"data": "value"}, ttl_seconds=60)
    assert result is True
    mock_redis.setex.assert_called_once()

    # Test get (cache miss)
    value = await cache.get("test_key")
    assert value is None

    # Test get (cache hit)
    mock_redis.get = AsyncMock(
        return_value=json.dumps({"data": "value"}).encode()
    )
    value = await cache.get("test_key")
    assert value == {"data": "value"}


@pytest.mark.asyncio
async def test_cache_delete(mock_redis):
    """Test cache delete."""
    from src.cache.tool_cache import ToolResultCache

    cache = ToolResultCache("redis://localhost:6379")
    cache._client = mock_redis

    result = await cache.delete("test_key")
    assert result is True
    mock_redis.delete.assert_called_once_with("test_key")


@pytest.mark.asyncio
async def test_cache_health_check(mock_redis):
    """Test cache health check."""
    from src.cache.tool_cache import ToolResultCache

    cache = ToolResultCache("redis://localhost:6379")
    cache._client = mock_redis

    health = await cache.health_check()
    assert health["status"] == "healthy"
    assert "used_memory" in health


@pytest.mark.asyncio
async def test_cache_no_client():
    """Test cache behavior when client is None."""
    from src.cache.tool_cache import ToolResultCache

    cache = ToolResultCache("redis://localhost:6379")

    # Bypass lazy loading by setting _client to None explicitly
    cache._client = None

    # Mock the client property to return None
    with patch.object(
        ToolResultCache, 'client', new_callable=lambda: property(lambda self: None)
    ):
        cache_with_no_client = ToolResultCache("redis://localhost:6379")
        cache_with_no_client._client = None

        # All operations should return gracefully when client is None
        assert await cache_with_no_client.get("key") is None


@pytest.mark.asyncio
async def test_cache_operations_with_mock():
    """Test all cache operations with mocked client."""
    from src.cache.tool_cache import ToolResultCache

    # Create cache with mocked client
    cache = ToolResultCache("redis://localhost:6379")
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=None)
    mock_client.setex = AsyncMock(return_value=True)
    mock_client.delete = AsyncMock(return_value=1)
    mock_client.ping = AsyncMock(return_value=True)
    mock_client.info = AsyncMock(return_value={"used_memory_human": "1M"})

    cache._client = mock_client

    # Test get miss
    result = await cache.get("missing_key")
    assert result is None

    # Test get hit
    mock_client.get = AsyncMock(
        return_value=json.dumps({"found": True}).encode()
    )
    result = await cache.get("existing_key")
    assert result == {"found": True}

    # Test set
    result = await cache.set("key", {"value": 1})
    assert result is True

    # Test delete
    result = await cache.delete("key")
    assert result is True

    # Test health check
    health = await cache.health_check()
    assert health["status"] == "healthy"


@pytest.mark.asyncio
async def test_cache_clear_prefix(mock_redis):
    """Test clearing keys by prefix."""
    from src.cache.tool_cache import ToolResultCache

    cache = ToolResultCache("redis://localhost:6379")
    cache._client = mock_redis

    # Mock scan_iter to return some keys
    async def mock_scan_iter(*args, **kwargs):
        for key in [b"prefix:key1", b"prefix:key2"]:
            yield key

    mock_redis.scan_iter = mock_scan_iter
    mock_redis.delete = AsyncMock(return_value=2)

    deleted = await cache.clear_prefix("prefix:")
    assert deleted == 2
