"""OCI tenancy and profile management tools.

Provides multi-tenancy support:
- Profile discovery and listing
- Tenancy information
- Compartment browsing
- Cache management
"""

import asyncio
import os
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

from ..config import get_tenancy_manager
from ..clients import get_oci_manager, get_sqlcl_client
from ..cache import get_cache, cached_call


def register_tools(mcp: "FastMCP") -> None:
    """Register tenancy management tools with the MCP server."""

    @mcp.tool(
        name="oci_tenancy_list_profiles",
        annotations={
            "title": "List OCI Profiles",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def list_oci_profiles() -> Dict[str, Any]:
        """List all available OCI profiles from ~/.oci/config.

        Returns:
            List of profile names with regions and active status
        """

        async def _fetch():
            manager = get_tenancy_manager()
            profiles = manager.list_profiles()

            # Discover profiles if not already done
            if not profiles:
                await asyncio.to_thread(manager.discover_profiles)
                profiles = manager.list_profiles()

            return {
                "success": True,
                "config_file": manager.config_file,
                "profile_count": len(profiles),
                "profiles": profiles,
            }

        return await cached_call("list_oci_profiles", {}, _fetch)

    @mcp.tool(
        name="oci_tenancy_get_profile",
        annotations={
            "title": "Get Profile Info",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def get_profile_info(
        profile_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get detailed information about an OCI profile.

        Args:
            profile_name: Profile name (default: active profile)

        Returns:
            Profile configuration details
        """

        async def _fetch():
            manager = get_tenancy_manager()

            if profile_name:
                profile = manager.get_profile(profile_name)
            else:
                profile = manager.get_active_profile()

            if not profile:
                return {
                    "success": False,
                    "error": f"Profile '{profile_name or 'DEFAULT'}' not found",
                    "available_profiles": [p["name"] for p in manager.list_profiles()],
                }

            return {
                "success": True,
                "profile": profile.to_dict(),
                "is_active": profile.name == manager._active_profile,
            }

        return await cached_call(
            "get_profile_info",
            {"profile_name": profile_name},
            _fetch,
        )

    @mcp.tool(
        name="oci_tenancy_set_profile",
        annotations={
            "title": "Set Active Profile",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def set_active_profile(
        profile_name: str,
    ) -> Dict[str, Any]:
        """Set the active OCI profile for operations.

        Args:
            profile_name: Profile name to activate

        Returns:
            Activation status
        """
        manager = get_tenancy_manager()

        success = manager.set_active_profile(profile_name)

        if success:
            # Invalidate cache since profile changed
            cache = get_cache()
            await cache.invalidate()

            return {
                "success": True,
                "message": f"Active profile set to '{profile_name}'",
                "profile": manager.get_profile(profile_name).to_dict(),
            }
        else:
            return {
                "success": False,
                "error": f"Profile '{profile_name}' not found",
                "available_profiles": [p["name"] for p in manager.list_profiles()],
            }

    @mcp.tool(
        name="oci_tenancy_list_compartments",
        annotations={
            "title": "List Compartments",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def list_compartments(
        compartment_id: Optional[str] = None,
        profile: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List compartments in a tenancy.

        Args:
            compartment_id: Parent compartment (default: tenancy root)
            profile: OCI profile name

        Returns:
            List of compartments
        """

        async def _fetch():
            manager = get_oci_manager()
            profile_name = profile or "DEFAULT"

            try:
                config = await manager.get_config(profile_name)

                # Get identity client
                import oci

                def _get_identity_client():
                    return oci.identity.IdentityClient(
                        config.config,
                        retry_strategy=oci.retry.DEFAULT_RETRY_STRATEGY,
                    )

                identity = await asyncio.to_thread(_get_identity_client)

                # Use tenancy as root if no compartment specified
                root_id = compartment_id or config.tenancy_id

                def _list_compartments():
                    response = identity.list_compartments(
                        compartment_id=root_id,
                        compartment_id_in_subtree=True,
                        lifecycle_state="ACTIVE",
                        limit=200,
                    )
                    return response.data

                compartments = await asyncio.to_thread(_list_compartments)

                result = []
                for c in compartments:
                    result.append({
                        "id": c.id,
                        "name": c.name,
                        "description": c.description[:100] if c.description else None,
                        "lifecycle_state": c.lifecycle_state,
                    })

                return {
                    "success": True,
                    "profile": profile_name,
                    "root_compartment": root_id,
                    "count": len(result),
                    "compartments": result,
                }

            except Exception as e:
                return {
                    "success": False,
                    "error": str(e),
                    "profile": profile_name,
                }

        return await cached_call(
            "list_compartments",
            {"compartment_id": compartment_id, "profile": profile},
            _fetch,
        )

    @mcp.tool(
        name="oci_database_health_check",
        annotations={
            "title": "Health Check",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def health_check() -> Dict[str, Any]:
        """Check health of OCI Database Observatory MCP server.

        Returns:
            Health status of MCP server components
        """
        from ..tools.sqlcl import get_public_ip

        status = {
            "mcp_server": "healthy",
            "oci_sdk": "unknown",
            "sqlcl": "unknown",
            "cache": "unknown",
            "public_ip": None,
        }

        # Get public IP for ACL reference
        try:
            status["public_ip"] = get_public_ip()
        except Exception:
            status["public_ip"] = "unable to determine"

        # Check OCI SDK
        try:
            import oci

            status["oci_sdk"] = f"available (v{oci.__version__})"
        except ImportError:
            status["oci_sdk"] = "not installed"

        # Check SQLcl
        try:
            sqlcl_path = os.getenv("SQLCL_PATH", "/Applications/sqlcl/bin/sql")
            if os.path.exists(sqlcl_path):
                status["sqlcl"] = "available"
            else:
                status["sqlcl"] = f"not_found at {sqlcl_path}"
        except Exception as e:
            status["sqlcl"] = f"error: {str(e)[:50]}"

        # Check Java
        java_home = os.getenv("JAVA_HOME", "")
        if java_home and os.path.exists(java_home):
            status["java"] = "configured"
        else:
            status["java"] = "JAVA_HOME not set or invalid"

        # Check cache
        try:
            cache = get_cache()
            cache_stats = await cache.get_stats()
            status["cache"] = f"healthy ({cache_stats['entries']} entries, {cache_stats['hit_rate']} hit rate)"
        except Exception as e:
            status["cache"] = f"error: {str(e)[:50]}"

        # Check OCI profiles
        try:
            manager = get_tenancy_manager()
            profiles = manager.list_profiles()
            status["oci_profiles"] = f"{len(profiles)} profiles available"
            active = manager.get_active_profile()
            if active:
                status["active_profile"] = active.name
        except Exception as e:
            status["oci_profiles"] = f"error: {str(e)[:50]}"

        return {
            "success": True,
            "status": status,
            "acl_note": f"Ensure IP {status['public_ip']} is in database ACL" if status["public_ip"] else None,
        }

    @mcp.tool(
        name="oci_database_cache_status",
        annotations={
            "title": "Cache Status",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def cache_status() -> Dict[str, Any]:
        """Get cache statistics and status.

        Returns:
            Cache statistics including hit rate and entry count
        """
        cache = get_cache()
        stats = await cache.get_stats()

        return {
            "success": True,
            "cache": stats,
        }

    @mcp.tool(
        name="oci_database_clear_cache",
        annotations={
            "title": "Clear Cache",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def clear_cache() -> Dict[str, Any]:
        """Clear all cached responses.

        Returns:
            Number of entries cleared
        """
        cache = get_cache()
        count = await cache.invalidate()

        return {
            "success": True,
            "message": f"Cleared {count} cache entries",
            "entries_cleared": count,
        }

    @mcp.tool(
        name="oci_database_ping",
        annotations={
            "title": "Ping",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def ping() -> Dict[str, Any]:
        """Simple ping to check if MCP server is responding.

        Returns:
            Pong response with timestamp
        """
        from datetime import datetime, timezone

        return {
            "success": True,
            "message": "pong",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "server": "oci-database-observatory",
            "version": "0.2.0",
        }
