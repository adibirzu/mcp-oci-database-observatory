"""Unit tests for the modular MCP server."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestMCPServerConfig:
    """Test tenancy configuration."""

    def test_tenancy_profile_dataclass(self):
        """Test TenancyProfile dataclass."""
        from src.mcp_server.config import TenancyProfile

        profile = TenancyProfile(
            name="test",
            region="us-phoenix-1",
            tenancy_id="ocid1.tenancy.oc1..test",
        )

        assert profile.name == "test"
        assert profile.region == "us-phoenix-1"
        assert profile.tenancy_id == "ocid1.tenancy.oc1..test"

    def test_tenancy_profile_to_dict(self):
        """Test TenancyProfile.to_dict()."""
        from src.mcp_server.config import TenancyProfile

        profile = TenancyProfile(
            name="test",
            region="us-phoenix-1",
            tenancy_id="ocid1.tenancy.oc1..test",
            compartment_id="ocid1.compartment.oc1..test",
        )

        d = profile.to_dict()
        assert d["name"] == "test"
        assert d["region"] == "us-phoenix-1"
        assert d["tenancy_id"] == "ocid1.tenancy.oc1..test"
        assert d["compartment_id"] == "ocid1.compartment.oc1..test"

    def test_tenancy_manager_init(self):
        """Test TenancyManager initialization."""
        from src.mcp_server.config import TenancyManager

        manager = TenancyManager(config_file="/tmp/test-oci-config")
        assert manager.config_file == "/tmp/test-oci-config"
        assert manager._profiles == {}
        assert manager._active_profile is None


class TestMCPServerCache:
    """Test response caching."""

    def test_cache_tier_values(self):
        """Test cache tier TTL values."""
        from src.mcp_server.cache import CacheTier

        assert CacheTier.STATIC.value == 3600  # 1 hour
        assert CacheTier.STABLE.value == 1800  # 30 min
        assert CacheTier.INFRASTRUCTURE.value == 600  # 10 min
        assert CacheTier.ANALYSIS.value == 120  # 2 min
        assert CacheTier.REAL_TIME.value == 0  # No caching

    def test_tool_cache_tiers_mapping(self):
        """Test tool-to-tier mapping."""
        from src.mcp_server.cache import TOOL_CACHE_TIERS, CacheTier

        # Static tools
        assert TOOL_CACHE_TIERS["list_oci_profiles"] == CacheTier.STATIC
        assert TOOL_CACHE_TIERS["list_parsers"] == CacheTier.STATIC

        # Stable tools
        assert TOOL_CACHE_TIERS["list_compartments"] == CacheTier.STABLE
        assert TOOL_CACHE_TIERS["list_log_sources"] == CacheTier.STABLE

        # Infrastructure tools
        assert TOOL_CACHE_TIERS["get_fleet_summary"] == CacheTier.INFRASTRUCTURE
        assert TOOL_CACHE_TIERS["search_databases"] == CacheTier.INFRASTRUCTURE

        # Analysis tools
        assert TOOL_CACHE_TIERS["skill_analyze_cpu_usage"] == CacheTier.ANALYSIS
        assert TOOL_CACHE_TIERS["execute_logan_query"] == CacheTier.ANALYSIS

        # Real-time tools
        assert TOOL_CACHE_TIERS["health_check"] == CacheTier.REAL_TIME
        assert TOOL_CACHE_TIERS["ping"] == CacheTier.REAL_TIME

    @pytest.mark.asyncio
    async def test_cache_set_get(self):
        """Test cache set and get operations."""
        from src.mcp_server.cache import ResponseCache

        cache = ResponseCache()

        # Set a value
        await cache.set("test_tool", {"arg": "value"}, {"result": "data"}, ttl=60)

        # Get the value back
        result = await cache.get("test_tool", {"arg": "value"})
        assert result == {"result": "data"}

    @pytest.mark.asyncio
    async def test_cache_miss(self):
        """Test cache miss returns None."""
        from src.mcp_server.cache import ResponseCache

        cache = ResponseCache()
        result = await cache.get("nonexistent", {})
        assert result is None

    @pytest.mark.asyncio
    async def test_cache_stats(self):
        """Test cache statistics."""
        from src.mcp_server.cache import ResponseCache

        cache = ResponseCache()

        # Generate some hits and misses
        await cache.set("tool1", {}, "value1", ttl=60)
        await cache.get("tool1", {})  # Hit
        await cache.get("tool2", {})  # Miss

        stats = await cache.get_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert "hit_rate" in stats


class TestMCPServerClients:
    """Test OCI client management."""

    def test_oci_config_dataclass(self):
        """Test OCIConfig dataclass."""
        from src.mcp_server.clients import OCIConfig

        config = OCIConfig(
            config={"tenancy": "test"},
            profile="DEFAULT",
            region="us-phoenix-1",
            tenancy_id="ocid1.tenancy.oc1..test",
        )

        assert config.profile == "DEFAULT"
        assert config.region == "us-phoenix-1"
        assert config.tenancy_id == "ocid1.tenancy.oc1..test"

    def test_oci_client_manager_init(self):
        """Test OCIClientManager initialization."""
        from src.mcp_server.clients import OCIClientManager

        manager = OCIClientManager()
        assert manager._configs == {}
        assert manager._opsi_clients == {}
        assert manager._logan_clients == {}


class TestToolModules:
    """Test tool module structure."""

    def test_sqlcl_acl_patterns(self):
        """Test ACL error patterns are defined."""
        from src.mcp_server.tools.sqlcl import ACL_ERROR_PATTERNS

        assert "ORA-12170" in ACL_ERROR_PATTERNS  # TNS:Connect timeout
        assert "ORA-12541" in ACL_ERROR_PATTERNS  # TNS:no listener
        assert "connection refused" in ACL_ERROR_PATTERNS

    def test_opsi_region_map(self):
        """Test OPSI region code mapping."""
        from src.mcp_server.tools.opsi import REGION_MAP, extract_region_from_ocid

        assert REGION_MAP["phx"] == "us-phoenix-1"
        assert REGION_MAP["lhr"] == "uk-london-1"
        assert REGION_MAP["fra"] == "eu-frankfurt-1"

        # Test OCID region extraction
        ocid = "ocid1.database.oc1.phx.abcdef"
        assert extract_region_from_ocid(ocid) == "us-phoenix-1"

    def test_extract_region_invalid_ocid(self):
        """Test region extraction with invalid OCID."""
        from src.mcp_server.tools.opsi import extract_region_from_ocid

        assert extract_region_from_ocid("") is None
        assert extract_region_from_ocid("invalid") is None
        assert extract_region_from_ocid(None) is None


class TestToolRegistration:
    """Test tool registration with FastMCP."""

    def test_register_all_tools_function_exists(self):
        """Test register_all_tools function exists."""
        from src.mcp_server.tools import register_all_tools

        assert callable(register_all_tools)

    def test_individual_register_functions_exist(self):
        """Test each module has register_tools function."""
        from src.mcp_server.tools import sqlcl, opsi, logan, tenancy

        assert callable(sqlcl.register_tools)
        assert callable(opsi.register_tools)
        assert callable(logan.register_tools)
        assert callable(tenancy.register_tools)


class TestPackageExports:
    """Test package-level exports."""

    def test_exports_available(self):
        """Test all exports are importable."""
        from src.mcp_server import (
            TenancyProfile,
            TenancyManager,
            get_tenancy_manager,
            get_oci_manager,
            get_sqlcl_client,
            disconnect_sqlcl,
            ResponseCache,
            get_cache,
            cached_call,
        )

        # All should be importable
        assert TenancyProfile is not None
        assert TenancyManager is not None
        assert callable(get_tenancy_manager)
        assert callable(get_oci_manager)
        assert callable(get_sqlcl_client)
        assert callable(disconnect_sqlcl)
        assert ResponseCache is not None
        assert callable(get_cache)
        assert callable(cached_call)

    def test_version(self):
        """Test version is defined."""
        from src.mcp_server import __version__

        assert __version__ == "0.2.0"
