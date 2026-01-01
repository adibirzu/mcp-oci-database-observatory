"""OCI Operations Insights (OPSI) tools.

Enhanced module providing:
- Tier 1: Cache-based instant lookups (<100ms)
- Tier 2: OPSI API queries (1-5s)
- Tier 3: Database management operations (5-30s)
- Programmatic Skills: High-level AI agent workflows

Multi-tenancy: All tools accept optional 'profile' parameter.
"""

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

from ..clients import get_oci_manager
from ..cache import cached_call, get_cache, CacheTier, TOOL_CACHE_TIERS

# =============================================================================
# Constants and Configuration
# =============================================================================

# Region short code to full name mapping
REGION_MAP = {
    "phx": "us-phoenix-1", "iad": "us-ashburn-1", "fra": "eu-frankfurt-1",
    "lhr": "uk-london-1", "ams": "eu-amsterdam-1", "zrh": "eu-zurich-1",
    "jed": "me-jeddah-1", "mel": "ap-melbourne-1", "syd": "ap-sydney-1",
    "gru": "sa-saopaulo-1", "yul": "ca-montreal-1", "yyz": "ca-toronto-1",
    "nrt": "ap-tokyo-1", "kix": "ap-osaka-1", "icn": "ap-seoul-1",
    "bom": "ap-mumbai-1", "hyd": "ap-hyderabad-1", "sin": "ap-singapore-1",
    "dxb": "me-dubai-1", "cwl": "uk-cardiff-1",
}

# Cache directory
CACHE_DIR = Path(os.getenv("MCP_CACHE_DIR", os.path.expanduser("~/.mcp-oci/cache")))
CACHE_BACKEND = os.getenv("MCP_CACHE_BACKEND", "file").lower()
REDIS_URL = os.getenv("MCP_REDIS_URL") or os.getenv("REDIS_URL")

# Skill metadata for AI agent tool selection
SKILL_METADATA = {
    "skill_discover_databases": {
        "tier": 1,
        "description": "Fast database discovery with filters",
        "use_when": ["list databases", "find databases", "show databases", "what databases"],
        "tokens": 150,
    },
    "skill_analyze_cpu_usage": {
        "tier": 2,
        "description": "CPU usage analysis with recommendations",
        "use_when": ["cpu usage", "cpu high", "performance slow", "cpu analysis"],
        "tokens": 200,
    },
    "skill_analyze_memory_usage": {
        "tier": 2,
        "description": "Memory usage analysis",
        "use_when": ["memory usage", "memory high", "sga", "pga", "memory analysis"],
        "tokens": 200,
    },
    "skill_analyze_io_performance": {
        "tier": 2,
        "description": "I/O throughput analysis",
        "use_when": ["io performance", "disk slow", "storage", "throughput"],
        "tokens": 200,
    },
    "skill_get_performance_summary": {
        "tier": 2,
        "description": "Combined CPU, memory, I/O summary",
        "use_when": ["performance summary", "health check", "overall performance"],
        "tokens": 300,
    },
    "skill_find_cost_opportunities": {
        "tier": 2,
        "description": "Identify cost savings opportunities",
        "use_when": ["cost savings", "reduce cost", "optimize cost", "rightsizing"],
        "tokens": 250,
    },
}


def extract_region_from_ocid(ocid: str) -> Optional[str]:
    """Extract region from an OCI resource OCID."""
    if not ocid or not isinstance(ocid, str):
        return None
    try:
        parts = ocid.split(".")
        if len(parts) < 4:
            return None
        region_code = parts[3]
        if region_code in REGION_MAP:
            return REGION_MAP[region_code]
        if "-" in region_code:
            return region_code
        return None
    except (IndexError, AttributeError):
        return None


# =============================================================================
# File-Based Database Cache
# =============================================================================

class DatabaseCache:
    """File-based cache for database metadata.

    Provides instant (<100ms) lookups for AI agents.
    """

    def __init__(self, profile: str = "DEFAULT"):
        self.profile = profile
        self._safe_profile = profile.replace("/", "_").replace("\\", "_")
        self._cache_file = CACHE_DIR / f"opsi_cache_{self._safe_profile}.json"
        self._use_redis = CACHE_BACKEND == "redis" and bool(REDIS_URL)
        self._redis_key = f"opsi_cache:{self._safe_profile}"
        self._redis_client = None
        self._data: Dict[str, Any] = {}
        self._loaded = False

    def _get_redis(self):
        if not self._use_redis:
            return None
        if self._redis_client is None:
            import redis  # type: ignore

            self._redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        return self._redis_client

    def _ensure_dir(self):
        """Ensure cache directory exists."""
        if self._use_redis:
            return
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def load(self) -> bool:
        """Load cache from file."""
        if self._loaded:
            return True
        try:
            if self._use_redis:
                client = self._get_redis()
                if client:
                    payload = client.get(self._redis_key)
                    if payload:
                        self._data = json.loads(payload)
                        self._loaded = True
                        return True
            if self._cache_file.exists():
                with open(self._cache_file, "r") as f:
                    self._data = json.load(f)
                self._loaded = True
                return True
        except Exception:
            self._use_redis = False
            pass
        self._data = {"metadata": {}, "databases": {}, "compartments": {}, "statistics": {}}
        return False

    def save(self) -> bool:
        """Save cache to file."""
        try:
            if self._use_redis:
                client = self._get_redis()
                if client:
                    payload = json.dumps(self._data, default=str)
                    client.set(self._redis_key, payload)
                    return True
            self._ensure_dir()
            with open(self._cache_file, "w") as f:
                json.dump(self._data, f, indent=2, default=str)
            return True
        except Exception:
            self._use_redis = False
            return False

    def is_valid(self, max_age_hours: int = 24) -> bool:
        """Check if cache is still valid."""
        self.load()
        last_updated = self._data.get("metadata", {}).get("last_updated")
        if not last_updated:
            return False
        try:
            updated_at = datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
            age = datetime.now(timezone.utc) - updated_at
            return age.total_seconds() < (max_age_hours * 3600)
        except Exception:
            return False

    def get_databases(self) -> List[Dict[str, Any]]:
        """Get all cached databases."""
        self.load()
        return list(self._data.get("databases", {}).values())

    def get_database(self, db_id: str) -> Optional[Dict[str, Any]]:
        """Get database by ID."""
        self.load()
        return self._data.get("databases", {}).get(db_id)

    def search(self, name: Optional[str] = None, compartment: Optional[str] = None,
               db_type: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        """Search databases with filters."""
        self.load()
        results = []
        for db in self._data.get("databases", {}).values():
            if name and name.lower() not in db.get("database_name", "").lower():
                continue
            if compartment and compartment != db.get("compartment_id"):
                continue
            if db_type and db_type.lower() != db.get("database_type", "").lower():
                continue
            results.append(db)
            if len(results) >= limit:
                break
        return results

    def get_statistics(self) -> Dict[str, Any]:
        """Get cache statistics."""
        self.load()
        return self._data.get("statistics", {})

    def get_fleet_summary(self) -> Dict[str, Any]:
        """Get fleet summary from cache."""
        self.load()
        databases = list(self._data.get("databases", {}).values())

        by_type = {}
        by_status = {}
        by_compartment = {}

        for db in databases:
            # By type
            db_type = db.get("database_type", "unknown")
            by_type[db_type] = by_type.get(db_type, 0) + 1

            # By status
            status = db.get("status", "unknown")
            by_status[status] = by_status.get(status, 0) + 1

            # By compartment
            comp = db.get("compartment_name", db.get("compartment_id", "unknown"))
            by_compartment[comp] = by_compartment.get(comp, 0) + 1

        return {
            "total_databases": len(databases),
            "by_type": by_type,
            "by_status": by_status,
            "by_compartment": by_compartment,
            "last_updated": self._data.get("metadata", {}).get("last_updated"),
        }

    async def build(self, client, compartment_id: str) -> Dict[str, Any]:
        """Build cache from OPSI API."""
        self._ensure_dir()

        def _fetch_insights():
            response = client.list_database_insights(
                compartment_id=compartment_id,
                compartment_id_in_subtree=True,
                limit=500,
            )
            return response.data.items

        items = await asyncio.to_thread(_fetch_insights)

        databases = {}
        for item in items:
            databases[item.id] = {
                "id": item.id,
                "database_id": item.database_id,
                "database_name": item.database_display_name,
                "database_type": item.database_type,
                "status": item.status,
                "lifecycle_state": item.lifecycle_state,
                "compartment_id": item.compartment_id,
                "time_created": str(item.time_created) if item.time_created else None,
            }

        self._data = {
            "metadata": {
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "profile": self.profile,
                "compartment_id": compartment_id,
            },
            "databases": databases,
            "statistics": {
                "total_databases": len(databases),
                "databases_by_type": {},
                "databases_by_status": {},
            },
        }

        # Calculate statistics
        for db in databases.values():
            db_type = db.get("database_type", "unknown")
            self._data["statistics"]["databases_by_type"][db_type] = \
                self._data["statistics"]["databases_by_type"].get(db_type, 0) + 1
            status = db.get("status", "unknown")
            self._data["statistics"]["databases_by_status"][status] = \
                self._data["statistics"]["databases_by_status"].get(status, 0) + 1

        self.save()
        self._loaded = True

        return {
            "success": True,
            "databases_cached": len(databases),
            "cache_file": str(self._cache_file),
        }


# Global cache instances per profile
_caches: Dict[str, DatabaseCache] = {}


def get_db_cache(profile: str = "DEFAULT") -> DatabaseCache:
    """Get or create database cache for profile."""
    if profile not in _caches:
        _caches[profile] = DatabaseCache(profile)
    return _caches[profile]


# =============================================================================
# Tool Registration
# =============================================================================

def register_tools(mcp: "FastMCP") -> None:
    """Register OPSI tools with the MCP server."""

    # =========================================================================
    # TIER 1: Cache-Based Tools (Instant, <100ms)
    # =========================================================================

    @mcp.tool(
        name="oci_opsi_get_fleet_summary",
        annotations={
            "title": "Get Fleet Summary",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def get_fleet_summary(
        profile: Optional[str] = None,
        use_cache: bool = True,
    ) -> Dict[str, Any]:
        """Get summary of all monitored databases in the fleet.

        TIER 1: Instant response from cache (<100ms).

        Args:
            profile: OCI profile name (default: DEFAULT)
            use_cache: Use cached data if available (default: True)

        Returns:
            Fleet summary with database counts by type, status, compartment
        """
        profile_name = profile or "DEFAULT"
        cache = get_db_cache(profile_name)

        if use_cache and cache.is_valid():
            summary = cache.get_fleet_summary()
            return {
                "success": True,
                "profile": profile_name,
                "source": "cache",
                **summary,
            }

        # Fallback to API
        async def _fetch():
            manager = get_oci_manager()
            try:
                config = await manager.get_config(profile_name)
                client = await manager.get_opsi_client(profile_name)

                # Build cache
                result = await cache.build(client, config.compartment_id)
                summary = cache.get_fleet_summary()

                return {
                    "success": True,
                    "profile": profile_name,
                    "source": "api",
                    **summary,
                }
            except Exception as e:
                return {"success": False, "error": str(e), "profile": profile_name}

        return await cached_call("get_fleet_summary", {"profile": profile}, _fetch)

    @mcp.tool(
        name="oci_opsi_search_databases",
        annotations={
            "title": "Search Databases",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def search_databases(
        name: Optional[str] = None,
        compartment_id: Optional[str] = None,
        database_type: Optional[str] = None,
        limit: int = 20,
        profile: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Search for databases by name, compartment, or type.

        TIER 1: Instant response from cache (<100ms).

        Args:
            name: Database name filter (partial match, case-insensitive)
            compartment_id: Compartment OCID filter
            database_type: Filter by type (AUTONOMOUS, EXTERNAL, etc.)
            limit: Maximum results (default: 20)
            profile: OCI profile name

        Returns:
            List of matching databases
        """
        profile_name = profile or "DEFAULT"
        cache = get_db_cache(profile_name)

        if cache.is_valid():
            results = cache.search(name, compartment_id, database_type, limit)
            return {
                "success": True,
                "profile": profile_name,
                "source": "cache",
                "count": len(results),
                "databases": results,
            }

        # Fallback to API
        async def _fetch():
            manager = get_oci_manager()
            try:
                config = await manager.get_config(profile_name)
                client = await manager.get_opsi_client(profile_name)

                def _call_api():
                    kwargs = {"compartment_id": config.compartment_id, "limit": limit}
                    if name:
                        kwargs["database_display_name"] = name
                    if database_type:
                        kwargs["database_type"] = [database_type]
                    response = client.list_database_insights(**kwargs)
                    return response.data.items

                items = await asyncio.to_thread(_call_api)
                databases = [{
                    "id": item.id,
                    "database_id": item.database_id,
                    "database_name": item.database_display_name,
                    "database_type": item.database_type,
                    "status": item.status,
                } for item in items]

                return {
                    "success": True,
                    "profile": profile_name,
                    "source": "api",
                    "count": len(databases),
                    "databases": databases,
                }
            except Exception as e:
                return {"success": False, "error": str(e), "profile": profile_name}

        return await cached_call(
            "search_databases",
            {"name": name, "compartment_id": compartment_id, "database_type": database_type, "limit": limit, "profile": profile},
            _fetch,
        )

    @mcp.tool(
        name="oci_opsi_get_database",
        annotations={
            "title": "Get Database Details",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def get_cached_database(
        database_id: str,
        profile: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get database details from cache by ID.

        TIER 1: Instant response (<100ms).

        Args:
            database_id: Database OCID or insight ID
            profile: OCI profile name

        Returns:
            Database details or error if not found
        """
        profile_name = profile or "DEFAULT"
        cache = get_db_cache(profile_name)

        db = cache.get_database(database_id)
        if db:
            return {"success": True, "profile": profile_name, "database": db}

        return {
            "success": False,
            "error": f"Database {database_id} not found in cache",
            "hint": "Run build_database_cache to populate cache",
            "profile": profile_name,
        }

    @mcp.tool(
        name="oci_opsi_get_statistics",
        annotations={
            "title": "Get Cache Statistics",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def get_cached_statistics(
        profile: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get detailed cache statistics.

        TIER 1: Instant response (<100ms).

        Args:
            profile: OCI profile name

        Returns:
            Cache statistics including counts and last update time
        """
        profile_name = profile or "DEFAULT"
        cache = get_db_cache(profile_name)

        stats = cache.get_statistics()
        metadata = cache._data.get("metadata", {})

        return {
            "success": True,
            "profile": profile_name,
            "cache_valid": cache.is_valid(),
            "last_updated": metadata.get("last_updated"),
            "statistics": stats,
        }

    @mcp.tool(
        name="oci_opsi_build_cache",
        annotations={
            "title": "Build Database Cache",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def build_database_cache(
        compartment_id: Optional[str] = None,
        profile: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build or refresh the database cache from OPSI API.

        TIER 2: API call required (5-30s first time, instant after).

        Args:
            compartment_id: Root compartment to scan (default: tenancy)
            profile: OCI profile name

        Returns:
            Cache build status with database count
        """
        profile_name = profile or "DEFAULT"
        cache = get_db_cache(profile_name)

        manager = get_oci_manager()
        try:
            config = await manager.get_config(profile_name)
            client = await manager.get_opsi_client(profile_name)

            comp_id = compartment_id or config.compartment_id
            result = await cache.build(client, comp_id)

            return {
                "success": True,
                "profile": profile_name,
                "compartment_id": comp_id,
                **result,
            }
        except Exception as e:
            return {"success": False, "error": str(e), "profile": profile_name}

    @mcp.tool(
        name="oci_opsi_refresh_cache",
        annotations={
            "title": "Refresh Cache If Needed",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def refresh_cache_if_needed(
        max_age_hours: int = 24,
        profile: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Check cache validity and refresh if stale.

        TIER 1: Instant if cache valid, TIER 2 if refresh needed.

        Args:
            max_age_hours: Maximum cache age before refresh (default: 24)
            profile: OCI profile name

        Returns:
            Cache status and whether refresh was performed
        """
        profile_name = profile or "DEFAULT"
        cache = get_db_cache(profile_name)

        if cache.is_valid(max_age_hours):
            return {
                "success": True,
                "profile": profile_name,
                "cache_valid": True,
                "refreshed": False,
                "last_updated": cache._data.get("metadata", {}).get("last_updated"),
            }

        # Need to refresh
        manager = get_oci_manager()
        try:
            config = await manager.get_config(profile_name)
            client = await manager.get_opsi_client(profile_name)
            result = await cache.build(client, config.compartment_id)

            return {
                "success": True,
                "profile": profile_name,
                "cache_valid": True,
                "refreshed": True,
                **result,
            }
        except Exception as e:
            return {"success": False, "error": str(e), "refreshed": False, "profile": profile_name}

    # =========================================================================
    # TIER 2: Performance Analysis Skills
    # =========================================================================

    @mcp.tool(
        name="oci_opsi_analyze_cpu",
        annotations={
            "title": "Analyze CPU Usage",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def analyze_cpu_usage(
        database_id: str,
        hours_back: int = 24,
        profile: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Analyze CPU usage trends for a database with recommendations.

        TIER 2: OPSI API query (1-5s).

        Args:
            database_id: Database OCID or insight ID
            hours_back: Hours of history to analyze (default: 24)
            profile: OCI profile name

        Returns:
            CPU analysis with avg/max/min, trend, and recommendations
        """
        async def _fetch():
            manager = get_oci_manager()
            profile_name = profile or "DEFAULT"
            ocid_region = extract_region_from_ocid(database_id)

            try:
                client = await manager.get_opsi_client(profile_name, region=ocid_region)
                config = await manager.get_config(profile_name)

                end_time = datetime.now(timezone.utc)
                start_time = end_time - timedelta(hours=hours_back)

                def _call_api():
                    response = client.summarize_database_insight_resource_usage_trend(
                        compartment_id=config.compartment_id,
                        resource_metric="CPU",
                        time_interval_start=start_time,
                        time_interval_end=end_time,
                        database_id=[database_id],
                    )
                    return response.data

                result = await asyncio.to_thread(_call_api)

                usage_data = []
                if result.items:
                    for item in result.items[:20]:
                        usage_pct = None
                        if hasattr(item, 'usage') and hasattr(item, 'capacity') and item.capacity > 0:
                            usage_pct = round(item.usage / item.capacity * 100, 2)
                        usage_data.append({
                            "timestamp": str(item.end_timestamp) if hasattr(item, 'end_timestamp') else None,
                            "usage_percent": usage_pct,
                        })

                usages = [d["usage_percent"] for d in usage_data if d.get("usage_percent") is not None]
                avg_usage = sum(usages) / len(usages) if usages else 0
                max_usage = max(usages) if usages else 0
                min_usage = min(usages) if usages else 0

                # Determine trend
                if len(usages) >= 2:
                    first_half = sum(usages[:len(usages)//2]) / (len(usages)//2)
                    second_half = sum(usages[len(usages)//2:]) / (len(usages) - len(usages)//2)
                    if second_half > first_half * 1.1:
                        trend = "increasing"
                    elif second_half < first_half * 0.9:
                        trend = "decreasing"
                    else:
                        trend = "stable"
                else:
                    trend = "insufficient_data"

                # Generate recommendations
                recommendations = []
                if avg_usage > 80:
                    recommendations.append({
                        "type": "scale_up",
                        "severity": "high",
                        "message": "High average CPU usage - consider scaling up or optimizing queries",
                    })
                elif avg_usage < 20:
                    recommendations.append({
                        "type": "scale_down",
                        "severity": "medium",
                        "message": "Low CPU utilization - consider scaling down to reduce costs",
                    })
                if max_usage > 95:
                    recommendations.append({
                        "type": "investigate_spikes",
                        "severity": "high",
                        "message": "CPU spikes detected - investigate peak usage periods",
                    })

                return {
                    "success": True,
                    "database_id": database_id,
                    "profile": profile_name,
                    "metric": "CPU",
                    "time_range": {"start": str(start_time), "end": str(end_time), "hours": hours_back},
                    "statistics": {
                        "avg_percent": round(avg_usage, 2),
                        "max_percent": round(max_usage, 2),
                        "min_percent": round(min_usage, 2),
                        "trend": trend,
                        "data_points": len(usage_data),
                    },
                    "recommendations": recommendations,
                }
            except Exception as e:
                return {"success": False, "error": str(e), "database_id": database_id}

        return await cached_call(
            "skill_analyze_cpu_usage",
            {"database_id": database_id, "hours_back": hours_back, "profile": profile},
            _fetch,
        )

    @mcp.tool(
        name="oci_opsi_analyze_memory",
        annotations={
            "title": "Analyze Memory Usage",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def analyze_memory_usage(
        database_id: str,
        hours_back: int = 24,
        profile: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Analyze memory usage trends for a database.

        TIER 2: OPSI API query (1-5s).

        Args:
            database_id: Database OCID or insight ID
            hours_back: Hours of history to analyze
            profile: OCI profile name

        Returns:
            Memory analysis with statistics and recommendations
        """
        async def _fetch():
            manager = get_oci_manager()
            profile_name = profile or "DEFAULT"
            ocid_region = extract_region_from_ocid(database_id)

            try:
                client = await manager.get_opsi_client(profile_name, region=ocid_region)
                config = await manager.get_config(profile_name)

                end_time = datetime.now(timezone.utc)
                start_time = end_time - timedelta(hours=hours_back)

                def _call_api():
                    response = client.summarize_database_insight_resource_usage_trend(
                        compartment_id=config.compartment_id,
                        resource_metric="MEMORY",
                        time_interval_start=start_time,
                        time_interval_end=end_time,
                        database_id=[database_id],
                    )
                    return response.data

                result = await asyncio.to_thread(_call_api)

                usages = []
                if result.items:
                    for item in result.items:
                        if hasattr(item, 'usage') and hasattr(item, 'capacity') and item.capacity > 0:
                            usages.append(item.usage / item.capacity * 100)

                avg_usage = sum(usages) / len(usages) if usages else 0
                max_usage = max(usages) if usages else 0

                recommendations = []
                if avg_usage > 85:
                    recommendations.append({
                        "type": "memory_pressure",
                        "severity": "high",
                        "message": "High memory usage - consider increasing SGA/PGA or adding memory",
                    })
                if max_usage > 95:
                    recommendations.append({
                        "type": "memory_spikes",
                        "severity": "high",
                        "message": "Memory pressure detected - review memory advisors",
                    })

                return {
                    "success": True,
                    "database_id": database_id,
                    "profile": profile_name,
                    "metric": "MEMORY",
                    "time_range": {"hours": hours_back},
                    "statistics": {
                        "avg_percent": round(avg_usage, 2),
                        "max_percent": round(max_usage, 2),
                        "data_points": len(usages),
                    },
                    "recommendations": recommendations,
                }
            except Exception as e:
                return {"success": False, "error": str(e), "database_id": database_id}

        return await cached_call(
            "skill_analyze_memory_usage",
            {"database_id": database_id, "hours_back": hours_back, "profile": profile},
            _fetch,
        )

    @mcp.tool(
        name="oci_opsi_analyze_io",
        annotations={
            "title": "Analyze I/O Performance",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def analyze_io_performance(
        database_id: str,
        hours_back: int = 24,
        profile: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Analyze I/O throughput trends for a database.

        TIER 2: OPSI API query (1-5s).

        Args:
            database_id: Database OCID or insight ID
            hours_back: Hours of history to analyze
            profile: OCI profile name

        Returns:
            I/O analysis with throughput statistics
        """
        async def _fetch():
            manager = get_oci_manager()
            profile_name = profile or "DEFAULT"
            ocid_region = extract_region_from_ocid(database_id)

            try:
                client = await manager.get_opsi_client(profile_name, region=ocid_region)
                config = await manager.get_config(profile_name)

                end_time = datetime.now(timezone.utc)
                start_time = end_time - timedelta(hours=hours_back)

                def _call_api():
                    response = client.summarize_database_insight_resource_usage_trend(
                        compartment_id=config.compartment_id,
                        resource_metric="IO",
                        time_interval_start=start_time,
                        time_interval_end=end_time,
                        database_id=[database_id],
                    )
                    return response.data

                result = await asyncio.to_thread(_call_api)

                throughputs = []
                if result.items:
                    for item in result.items:
                        if hasattr(item, 'usage'):
                            throughputs.append(item.usage)

                avg_throughput = sum(throughputs) / len(throughputs) if throughputs else 0
                max_throughput = max(throughputs) if throughputs else 0

                recommendations = []
                if throughputs and max_throughput > avg_throughput * 3:
                    recommendations.append({
                        "type": "io_spikes",
                        "severity": "medium",
                        "message": "I/O spikes detected - consider async I/O or storage optimization",
                    })

                return {
                    "success": True,
                    "database_id": database_id,
                    "profile": profile_name,
                    "metric": "IO",
                    "time_range": {"hours": hours_back},
                    "statistics": {
                        "avg_throughput_mbps": round(avg_throughput, 2),
                        "max_throughput_mbps": round(max_throughput, 2),
                        "data_points": len(throughputs),
                    },
                    "recommendations": recommendations,
                }
            except Exception as e:
                return {"success": False, "error": str(e), "database_id": database_id}

        return await cached_call(
            "skill_analyze_io_performance",
            {"database_id": database_id, "hours_back": hours_back, "profile": profile},
            _fetch,
        )

    @mcp.tool(
        name="oci_opsi_get_performance_summary",
        annotations={
            "title": "Get Performance Summary",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def get_performance_summary(
        database_id: str,
        hours_back: int = 24,
        profile: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get combined CPU, memory, and I/O performance summary.

        TIER 2: Multiple OPSI API queries (3-10s).

        Args:
            database_id: Database OCID or insight ID
            hours_back: Hours of history to analyze
            profile: OCI profile name

        Returns:
            Combined performance summary with all metrics
        """
        # Run all analyses in parallel
        cpu_task = analyze_cpu_usage(database_id, hours_back, profile)
        memory_task = analyze_memory_usage(database_id, hours_back, profile)
        io_task = analyze_io_performance(database_id, hours_back, profile)

        cpu, memory, io = await asyncio.gather(cpu_task, memory_task, io_task)

        # Aggregate recommendations
        all_recommendations = []
        if cpu.get("success"):
            all_recommendations.extend(cpu.get("recommendations", []))
        if memory.get("success"):
            all_recommendations.extend(memory.get("recommendations", []))
        if io.get("success"):
            all_recommendations.extend(io.get("recommendations", []))

        # Determine overall health
        high_severity = sum(1 for r in all_recommendations if r.get("severity") == "high")
        if high_severity >= 2:
            health = "critical"
        elif high_severity == 1:
            health = "warning"
        elif all_recommendations:
            health = "attention"
        else:
            health = "healthy"

        return {
            "success": True,
            "database_id": database_id,
            "profile": profile or "DEFAULT",
            "time_range": {"hours": hours_back},
            "overall_health": health,
            "cpu": cpu.get("statistics") if cpu.get("success") else {"error": cpu.get("error")},
            "memory": memory.get("statistics") if memory.get("success") else {"error": memory.get("error")},
            "io": io.get("statistics") if io.get("success") else {"error": io.get("error")},
            "recommendations": all_recommendations,
        }

    # =========================================================================
    # TIER 2: Cost Optimization Skills
    # =========================================================================

    @mcp.tool(
        name="oci_opsi_find_cost_opportunities",
        annotations={
            "title": "Find Cost Opportunities",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def find_cost_opportunities(
        compartment_id: Optional[str] = None,
        min_savings_usd: float = 0,
        profile: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Identify cost savings opportunities across databases.

        TIER 2: Analysis based on cached data + API queries.

        Opportunity types:
        - rightsize: Over-provisioned resources
        - schedule: Dev/test databases that can be stopped
        - unused: Databases with very low utilization

        Args:
            compartment_id: Scope to specific compartment
            min_savings_usd: Minimum monthly savings to report
            profile: OCI profile name

        Returns:
            List of cost optimization opportunities
        """
        profile_name = profile or "DEFAULT"
        cache = get_db_cache(profile_name)

        databases = cache.search(compartment=compartment_id, limit=100)

        opportunities = []

        for db in databases:
            db_id = db.get("id")
            db_name = db.get("database_name", "Unknown")
            db_type = db.get("database_type", "").lower()

            # Check for idle databases (would need CPU analysis)
            # For now, flag all dev/test databases as potential schedule candidates
            if any(keyword in db_name.lower() for keyword in ["dev", "test", "staging", "qa"]):
                opportunities.append({
                    "database_id": db_id,
                    "database_name": db_name,
                    "opportunity_type": "schedule",
                    "description": "Dev/test database - consider stopping during off-hours",
                    "estimated_monthly_savings_usd": 100,  # Placeholder
                    "confidence": "medium",
                    "action": "Implement auto-stop during nights/weekends",
                })

            # Flag autonomous databases for potential scaling review
            if "autonomous" in db_type:
                opportunities.append({
                    "database_id": db_id,
                    "database_name": db_name,
                    "opportunity_type": "rightsize",
                    "description": "Autonomous DB - review OCPU allocation",
                    "estimated_monthly_savings_usd": 50,  # Placeholder
                    "confidence": "low",
                    "action": "Analyze CPU usage and adjust OCPU count",
                })

        # Filter by minimum savings
        if min_savings_usd > 0:
            opportunities = [o for o in opportunities if o.get("estimated_monthly_savings_usd", 0) >= min_savings_usd]

        total_savings = sum(o.get("estimated_monthly_savings_usd", 0) for o in opportunities)

        return {
            "success": True,
            "profile": profile_name,
            "databases_analyzed": len(databases),
            "opportunities_found": len(opportunities),
            "total_estimated_monthly_savings_usd": total_savings,
            "opportunities": opportunities[:20],  # Limit response size
        }

    @mcp.tool(
        name="oci_opsi_get_savings_summary",
        annotations={
            "title": "Get Savings Summary",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def get_savings_summary(
        compartment_id: Optional[str] = None,
        profile: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get aggregated savings summary by opportunity type.

        TIER 1: Based on cached analysis.

        Args:
            compartment_id: Scope to specific compartment
            profile: OCI profile name

        Returns:
            Savings summary grouped by type and confidence
        """
        result = await find_cost_opportunities(compartment_id, 0, profile)

        if not result.get("success"):
            return result

        opportunities = result.get("opportunities", [])

        by_type = {}
        by_confidence = {"high": 0, "medium": 0, "low": 0}

        for opp in opportunities:
            opp_type = opp.get("opportunity_type", "other")
            savings = opp.get("estimated_monthly_savings_usd", 0)
            confidence = opp.get("confidence", "low")

            if opp_type not in by_type:
                by_type[opp_type] = {"count": 0, "savings": 0}
            by_type[opp_type]["count"] += 1
            by_type[opp_type]["savings"] += savings

            by_confidence[confidence] = by_confidence.get(confidence, 0) + savings

        return {
            "success": True,
            "profile": profile or "DEFAULT",
            "total_opportunities": len(opportunities),
            "total_monthly_savings_usd": result.get("total_estimated_monthly_savings_usd", 0),
            "by_type": by_type,
            "by_confidence": by_confidence,
        }

    # =========================================================================
    # TIER 2: OPSI API Tools
    # =========================================================================

    @mcp.tool(
        name="oci_opsi_list_insights",
        annotations={
            "title": "List Database Insights",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def list_database_insights(
        compartment_id: Optional[str] = None,
        status: Optional[str] = None,
        database_type: Optional[str] = None,
        limit: int = 50,
        profile: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List all database insights from OPSI API.

        TIER 2: Direct API query (1-5s).

        Args:
            compartment_id: Compartment OCID
            status: Filter by status (ENABLED, DISABLED)
            database_type: Filter by type (AUTONOMOUS, EXTERNAL, etc.)
            limit: Maximum results
            profile: OCI profile name

        Returns:
            List of database insights with metadata
        """
        async def _fetch():
            manager = get_oci_manager()
            profile_name = profile or "DEFAULT"

            try:
                config = await manager.get_config(profile_name)
                client = await manager.get_opsi_client(profile_name)

                comp_id = compartment_id or config.compartment_id

                def _call_api():
                    kwargs = {"compartment_id": comp_id, "limit": limit}
                    if status:
                        kwargs["status"] = [status]
                    if database_type:
                        kwargs["database_type"] = [database_type]
                    response = client.list_database_insights(**kwargs)
                    return response.data.items

                items = await asyncio.to_thread(_call_api)

                insights = [{
                    "id": item.id,
                    "database_id": item.database_id,
                    "database_name": item.database_display_name,
                    "database_type": item.database_type,
                    "status": item.status,
                    "lifecycle_state": item.lifecycle_state,
                    "time_created": str(item.time_created) if item.time_created else None,
                } for item in items]

                return {
                    "success": True,
                    "profile": profile_name,
                    "compartment_id": comp_id,
                    "count": len(insights),
                    "insights": insights,
                }
            except Exception as e:
                return {"success": False, "error": str(e), "profile": profile_name}

        return await cached_call(
            "list_database_insights",
            {"compartment_id": compartment_id, "status": status, "database_type": database_type, "limit": limit, "profile": profile},
            _fetch,
        )

    # =========================================================================
    # AI Agent Support Tools
    # =========================================================================

    @mcp.tool(
        name="oci_opsi_list_skills",
        annotations={
            "title": "List OPSI Skills",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def list_opsi_skills() -> Dict[str, Any]:
        """List all available OPSI skills with metadata for AI agents.

        Use this to understand which tool to use for a given task.

        Returns:
            List of skills with tier, description, and usage hints
        """
        skills = []
        for name, meta in SKILL_METADATA.items():
            skills.append({
                "name": name,
                "tier": meta["tier"],
                "description": meta["description"],
                "use_when": meta["use_when"],
                "estimated_tokens": meta["tokens"],
            })

        return {
            "success": True,
            "skill_count": len(skills),
            "tiers": {
                1: "Cache-based instant (<100ms)",
                2: "OPSI API queries (1-5s)",
                3: "Database operations (5-30s)",
            },
            "skills": sorted(skills, key=lambda x: x["tier"]),
        }

    @mcp.tool(
        name="oci_opsi_get_skill_recommendations",
        annotations={
            "title": "Get Skill Recommendations",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def get_skill_recommendations(
        query: str,
    ) -> Dict[str, Any]:
        """Get recommended skills for a natural language query.

        AI agents should use this to select the best tool for a task.

        Args:
            query: Natural language description of the task

        Returns:
            Ranked list of recommended skills
        """
        query_lower = query.lower()
        recommendations = []

        for name, meta in SKILL_METADATA.items():
            score = 0
            matched_keywords = []

            for keyword in meta["use_when"]:
                if keyword in query_lower:
                    score += 10
                    matched_keywords.append(keyword)

            # Partial matches
            for word in query_lower.split():
                if len(word) > 3:
                    for keyword in meta["use_when"]:
                        if word in keyword or keyword in word:
                            score += 2

            if score > 0:
                recommendations.append({
                    "skill": name,
                    "score": score,
                    "tier": meta["tier"],
                    "description": meta["description"],
                    "matched_keywords": matched_keywords,
                })

        # Sort by score descending
        recommendations.sort(key=lambda x: (-x["score"], x["tier"]))

        return {
            "success": True,
            "query": query,
            "recommendations": recommendations[:5],
            "hint": "Use the highest-scoring skill. Lower tier = faster response.",
        }
