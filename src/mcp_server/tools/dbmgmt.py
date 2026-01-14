"""OCI Database Management MCP Tools.

Provides tools for interacting with OCI Database Management Service:
- List and get managed databases
- AWR report generation (HTML/TEXT)
- AWR snapshot management
- Fleet health metrics
- SQL Tuning Advisor

These tools work with databases registered in DB Management service.
"""

import asyncio
import base64
import json
import os
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

from ..clients import get_oci_manager


async def _get_dbmgmt_compartment(profile: str = "DEFAULT") -> str:
    """Get the DB Management compartment for a profile.

    Uses the profile-specific compartment from environment variables,
    loaded via OCIConfig.

    Args:
        profile: OCI profile name

    Returns:
        Compartment OCID for DB Management operations
    """
    manager = get_oci_manager()
    config = await manager.get_config(profile)
    return config.dbmgmt_compartment_id


def _get_region(profile: str = "DEFAULT", region_override: str | None = None) -> str:
    """Get the region for DB Management operations.

    Args:
        profile: OCI profile name
        region_override: Optional explicit region

    Returns:
        Region identifier
    """
    if region_override:
        return region_override

    # Try profile-specific region, then generic, then default
    profile_upper = profile.upper().replace("-", "_")
    return (
        os.getenv(f"OCI_{profile_upper}_DBMGMT_REGION") or
        os.getenv("OCI_DBMGMT_REGION") or
        os.getenv("OCI_REGION") or
        "us-ashburn-1"
    )


def register_tools(mcp: "FastMCP") -> None:
    """Register Database Management tools with the MCP server.

    Args:
        mcp: FastMCP server instance
    """

    @mcp.tool()
    async def list_managed_databases(
        compartment_id: Optional[str] = None,
        profile: str = "DEFAULT",
        region: Optional[str] = None,
        limit: int = 50,
    ) -> str:
        """List databases registered in OCI Database Management.

        Args:
            compartment_id: Compartment OCID (uses profile-specific default if not provided)
            profile: OCI profile (default: DEFAULT - uses env-configured compartments)
            region: Region override (uses profile-specific default if not provided)
            limit: Maximum databases to return

        Returns:
            JSON with list of managed databases
        """
        manager = get_oci_manager()
        resolved_region = _get_region(profile, region)
        client = await manager.get_dbm_client(
            profile=profile,
            region=resolved_region
        )

        # Use profile-specific compartment from env vars if not explicitly provided
        comp_id = compartment_id or await _get_dbmgmt_compartment(profile)

        try:
            def _list():
                response = client.list_managed_databases(
                    compartment_id=comp_id,
                    limit=limit,
                )
                return response.data

            databases = await asyncio.to_thread(_list)

            result = []
            for db in databases:
                result.append({
                    "id": db.id,
                    "name": db.name,
                    "database_type": db.database_type,
                    "database_sub_type": db.database_sub_type,
                    "deployment_type": getattr(db, "deployment_type", None),
                    "management_option": getattr(db, "management_option", None),
                    "workload_type": getattr(db, "workload_type", None),
                    "is_cluster": getattr(db, "is_cluster", False),
                    "time_created": str(db.time_created) if db.time_created else None,
                })

            return json.dumps({
                "success": True,
                "databases": result,
                "count": len(result),
                "compartment_id": comp_id,
                "profile": profile,
            }, indent=2)

        except Exception as e:
            return json.dumps({
                "success": False,
                "error": str(e),
                "compartment_id": comp_id,
            })

    @mcp.tool()
    async def get_managed_database(
        managed_database_id: str,
        profile: str = "DEFAULT",
        region: Optional[str] = None,
    ) -> str:
        """Get details of a managed database.

        Args:
            managed_database_id: The OCID of the managed database
            profile: OCI profile (default: DEFAULT)
            region: Region override (uses profile-specific default if not provided)

        Returns:
            JSON with database details
        """
        manager = get_oci_manager()
        resolved_region = _get_region(profile, region)
        client = await manager.get_dbm_client(
            profile=profile,
            region=resolved_region
        )

        try:
            def _get():
                return client.get_managed_database(
                    managed_database_id=managed_database_id
                ).data

            db = await asyncio.to_thread(_get)

            return json.dumps({
                "success": True,
                "database": {
                    "id": db.id,
                    "name": db.name,
                    "database_type": db.database_type,
                    "database_sub_type": db.database_sub_type,
                    "deployment_type": getattr(db, "deployment_type", None),
                    "management_option": getattr(db, "management_option", None),
                    "workload_type": getattr(db, "workload_type", None),
                    "is_cluster": getattr(db, "is_cluster", False),
                    "db_system_id": getattr(db, "db_system_id", None),
                    "storage_system_id": getattr(db, "storage_system_id", None),
                    "time_created": str(db.time_created) if db.time_created else None,
                    "database_version": getattr(db, "database_version", None),
                    "compartment_id": db.compartment_id,
                    "parent_container_id": getattr(db, "parent_container_id", None),
                    "additional_details": getattr(db, "additional_details", {}),
                },
            }, indent=2)

        except Exception as e:
            return json.dumps({
                "success": False,
                "error": str(e),
                "managed_database_id": managed_database_id,
            })

    @mcp.tool()
    async def list_awr_db_snapshots(
        managed_database_id: str,
        profile: str = "DEFAULT",
        region: Optional[str] = None,
        hours_back: int = 24,
        limit: int = 100,
    ) -> str:
        """List AWR snapshots for a managed database.

        Args:
            managed_database_id: The OCID of the managed database
            profile: OCI profile (default: DEFAULT)
            region: Region override (uses profile-specific default if not provided)
            hours_back: How many hours of snapshots to retrieve
            limit: Maximum snapshots to return

        Returns:
            JSON with list of AWR snapshots
        """
        manager = get_oci_manager()
        resolved_region = _get_region(profile, region)
        client = await manager.get_dbm_client(
            profile=profile,
            region=resolved_region
        )

        # Calculate time range
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=hours_back)

        try:
            # First, get the AWR DB ID
            def _get_awr_db_id():
                response = client.list_awr_dbs(
                    managed_database_id=managed_database_id,
                    limit=1
                )
                if not response.data.items:
                    raise ValueError("No AWR database found for this managed database")
                return response.data.items[0].awr_db_id

            awr_db_id = await asyncio.to_thread(_get_awr_db_id)

            def _list():
                response = client.list_awr_db_snapshots(
                    managed_database_id=managed_database_id,
                    awr_db_id=awr_db_id,
                    time_greater_than_or_equal_to=start_time,
                    time_less_than_or_equal_to=end_time,
                    limit=limit,
                    sort_order="DESC",
                )
                return response.data

            snapshots_response = await asyncio.to_thread(_list)

            snapshots = []
            for item in snapshots_response.items:
                snapshots.append({
                    "snapshot_id": item.snapshot_id,
                    "instance_number": getattr(item, "instance_number", 1),
                    "time_db_startup": str(item.time_db_startup) if item.time_db_startup else None,
                    "time_snapshot_begin": str(item.time_begin) if item.time_begin else None,
                    "time_snapshot_end": str(item.time_end) if item.time_end else None,
                    "snapshot_identifier": getattr(item, "snapshot_identifier", None),
                })

            return json.dumps({
                "success": True,
                "snapshots": snapshots,
                "count": len(snapshots),
                "managed_database_id": managed_database_id,
                "time_range": {
                    "start": start_time.isoformat(),
                    "end": end_time.isoformat(),
                    "hours_back": hours_back,
                },
            }, indent=2)

        except Exception as e:
            return json.dumps({
                "success": False,
                "error": str(e),
                "managed_database_id": managed_database_id,
            })

    @mcp.tool()
    async def get_awr_db_report(
        managed_database_id: str,
        begin_snapshot_id: int,
        end_snapshot_id: int,
        profile: str = "DEFAULT",
        region: Optional[str] = None,
        report_format: str = "HTML",
        report_type: str = "AWR",
        instance_number: int = 1,
    ) -> str:
        """Generate AWR report for a managed database.

        This is the primary tool for getting AWR HTML reports that can be
        attached to Slack messages.

        Args:
            managed_database_id: The OCID of the managed database
            begin_snapshot_id: Starting AWR snapshot ID
            end_snapshot_id: Ending AWR snapshot ID
            profile: OCI profile (default: DEFAULT)
            region: Region override (uses profile-specific default if not provided)
            report_format: HTML or TEXT (default: HTML)
            report_type: AWR, ASH, or ADDM (default: AWR)
            instance_number: RAC instance number (default: 1)

        Returns:
            JSON with AWR report content (base64 encoded for HTML)
        """
        manager = get_oci_manager()
        resolved_region = _get_region(profile, region)
        client = await manager.get_dbm_client(
            profile=profile,
            region=resolved_region
        )

        try:
            def _get_report():
                # First, get the AWR DB ID from list_awr_dbs
                awr_dbs_response = client.list_awr_dbs(
                    managed_database_id=managed_database_id,
                    limit=1
                )
                if not awr_dbs_response.data.items:
                    raise ValueError("No AWR database found for this managed database")

                awr_db_id = awr_dbs_response.data.items[0].awr_db_id

                # Use the get_awr_db_report API
                # Note: inst_nums causes 500 errors, omit it for now
                response = client.get_awr_db_report(
                    managed_database_id=managed_database_id,
                    awr_db_id=awr_db_id,
                    begin_sn_id_greater_than_or_equal_to=begin_snapshot_id,
                    end_sn_id_less_than_or_equal_to=end_snapshot_id,
                    report_type=report_type,
                    report_format=report_format,
                )
                return response.data

            report_data = await asyncio.to_thread(_get_report)

            # Extract report content
            report_content = None
            if hasattr(report_data, "content"):
                report_content = report_data.content
            elif hasattr(report_data, "items") and report_data.items:
                # Some APIs return items list
                report_content = report_data.items[0].content if report_data.items else None

            if not report_content:
                return json.dumps({
                    "success": False,
                    "error": "No report content returned",
                    "managed_database_id": managed_database_id,
                })

            # For HTML, base64 encode to safely transport
            if report_format.upper() == "HTML":
                report_base64 = base64.b64encode(report_content.encode()).decode()
                return json.dumps({
                    "success": True,
                    "report_format": "HTML",
                    "report_type": report_type,
                    "report_base64": report_base64,
                    "report_size_bytes": len(report_content),
                    "managed_database_id": managed_database_id,
                    "snapshot_range": {
                        "begin": begin_snapshot_id,
                        "end": end_snapshot_id,
                    },
                    "instance_number": instance_number,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
            else:
                # For TEXT, include directly
                return json.dumps({
                    "success": True,
                    "report_format": "TEXT",
                    "report_type": report_type,
                    "report_text": report_content,
                    "report_size_bytes": len(report_content),
                    "managed_database_id": managed_database_id,
                    "snapshot_range": {
                        "begin": begin_snapshot_id,
                        "end": end_snapshot_id,
                    },
                    "instance_number": instance_number,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

        except Exception as e:
            return json.dumps({
                "success": False,
                "error": str(e),
                "managed_database_id": managed_database_id,
                "snapshot_range": {
                    "begin": begin_snapshot_id,
                    "end": end_snapshot_id,
                },
            })

    @mcp.tool()
    async def get_awr_db_report_auto(
        managed_database_id: str,
        profile: str = "DEFAULT",
        region: Optional[str] = None,
        hours_back: int = 1,
        report_format: str = "HTML",
    ) -> str:
        """Generate AWR report using latest available snapshots.

        Automatically finds the most recent snapshots within the time range
        and generates an AWR report. This is a convenience wrapper around
        list_awr_db_snapshots + get_awr_db_report.

        Args:
            managed_database_id: The OCID of the managed database
            profile: OCI profile (default: DEFAULT)
            region: Region override (uses profile-specific default if not provided)
            hours_back: Time range for report (default: 1 hour)
            report_format: HTML or TEXT (default: HTML)

        Returns:
            JSON with AWR report content
        """
        manager = get_oci_manager()
        resolved_region = _get_region(profile, region)
        client = await manager.get_dbm_client(
            profile=profile,
            region=resolved_region
        )

        # Calculate time range
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=hours_back)

        try:
            # First, get the AWR DB ID
            def _get_awr_db_id():
                response = client.list_awr_dbs(
                    managed_database_id=managed_database_id,
                    limit=1
                )
                if not response.data.items:
                    raise ValueError("No AWR database found for this managed database")
                return response.data.items[0].awr_db_id

            awr_db_id = await asyncio.to_thread(_get_awr_db_id)

            # Get available snapshots
            def _list_snapshots():
                response = client.list_awr_db_snapshots(
                    managed_database_id=managed_database_id,
                    awr_db_id=awr_db_id,
                    time_greater_than_or_equal_to=start_time,
                    time_less_than_or_equal_to=end_time,
                    limit=50,
                    sort_order="DESC",
                )
                return response.data

            snapshots_response = await asyncio.to_thread(_list_snapshots)

            if not snapshots_response.items or len(snapshots_response.items) < 2:
                return json.dumps({
                    "success": False,
                    "error": f"Need at least 2 snapshots for AWR report. Found: {len(snapshots_response.items) if snapshots_response.items else 0}",
                    "managed_database_id": managed_database_id,
                    "time_range": {
                        "start": start_time.isoformat(),
                        "end": end_time.isoformat(),
                    },
                    "hint": "Try increasing hours_back parameter",
                })

            # Get latest and earliest snapshots for the range
            snapshots = sorted(
                snapshots_response.items,
                key=lambda x: x.snapshot_id
            )
            begin_snapshot_id = snapshots[0].snapshot_id
            end_snapshot_id = snapshots[-1].snapshot_id

            # Generate report (omit inst_nums to avoid 500 errors)
            def _get_report():
                response = client.get_awr_db_report(
                    managed_database_id=managed_database_id,
                    awr_db_id=awr_db_id,
                    begin_sn_id_greater_than_or_equal_to=begin_snapshot_id,
                    end_sn_id_less_than_or_equal_to=end_snapshot_id,
                    report_type="AWR",
                    report_format=report_format,
                )
                return response.data

            report_data = await asyncio.to_thread(_get_report)

            # Extract report content
            report_content = None
            if hasattr(report_data, "content"):
                report_content = report_data.content
            elif hasattr(report_data, "items") and report_data.items:
                report_content = report_data.items[0].content if report_data.items else None

            if not report_content:
                return json.dumps({
                    "success": False,
                    "error": "No report content returned",
                    "managed_database_id": managed_database_id,
                })

            # Encode and return
            if report_format.upper() == "HTML":
                report_base64 = base64.b64encode(report_content.encode()).decode()
                return json.dumps({
                    "success": True,
                    "report_format": "HTML",
                    "report_type": "AWR",
                    "report_base64": report_base64,
                    "report_size_bytes": len(report_content),
                    "managed_database_id": managed_database_id,
                    "snapshot_range": {
                        "begin": begin_snapshot_id,
                        "end": end_snapshot_id,
                        "count": len(snapshots),
                    },
                    "time_range": {
                        "start": start_time.isoformat(),
                        "end": end_time.isoformat(),
                        "hours_back": hours_back,
                    },
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
            else:
                return json.dumps({
                    "success": True,
                    "report_format": "TEXT",
                    "report_type": "AWR",
                    "report_text": report_content,
                    "report_size_bytes": len(report_content),
                    "managed_database_id": managed_database_id,
                    "snapshot_range": {
                        "begin": begin_snapshot_id,
                        "end": end_snapshot_id,
                    },
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

        except Exception as e:
            return json.dumps({
                "success": False,
                "error": str(e),
                "managed_database_id": managed_database_id,
            })

    @mcp.tool()
    async def get_database_fleet_health(
        compartment_id: Optional[str] = None,
        profile: str = "DEFAULT",
        region: Optional[str] = None,
    ) -> str:
        """Get fleet health metrics for managed databases.

        Args:
            compartment_id: Compartment OCID (uses profile-specific default if not provided)
            profile: OCI profile (default: DEFAULT)
            region: Region override (uses profile-specific default if not provided)

        Returns:
            JSON with fleet health metrics
        """
        manager = get_oci_manager()
        resolved_region = _get_region(profile, region)
        client = await manager.get_dbm_client(
            profile=profile,
            region=resolved_region
        )

        # Use profile-specific compartment from env vars if not explicitly provided
        comp_id = compartment_id or await _get_dbmgmt_compartment(profile)

        try:
            def _get_health():
                response = client.get_database_fleet_health_metrics(
                    compartment_id=comp_id,
                )
                return response.data

            metrics = await asyncio.to_thread(_get_health)

            return json.dumps({
                "success": True,
                "fleet_health": {
                    "compare_baseline_time": str(metrics.compare_baseline_time) if metrics.compare_baseline_time else None,
                    "compare_target_time": str(metrics.compare_target_time) if metrics.compare_target_time else None,
                    "compare_type": getattr(metrics, "compare_type", None),
                    "fleet_summary": [
                        {
                            "aggregated_metric_name": s.aggregated_metric_name,
                            "aggregated_metric_value": s.aggregated_metric_value,
                            "previous_aggregated_metric_value": getattr(s, "previous_aggregated_metric_value", None),
                            "dimensions": getattr(s, "dimensions", []),
                        }
                        for s in (metrics.fleet_summary or [])
                    ] if metrics.fleet_summary else [],
                    "fleet_databases": [
                        {
                            "db_id": db.db_id,
                            "db_name": db.db_name,
                            "db_type": db.db_type,
                            "db_sub_type": db.db_sub_type,
                            "metrics": db.metrics,
                        }
                        for db in (metrics.fleet_databases or [])
                    ] if metrics.fleet_databases else [],
                },
                "compartment_id": comp_id,
            }, indent=2)

        except Exception as e:
            return json.dumps({
                "success": False,
                "error": str(e),
                "compartment_id": comp_id,
            })

    @mcp.tool()
    async def search_managed_databases(
        name_contains: str,
        compartment_id: Optional[str] = None,
        profile: str = "DEFAULT",
        region: Optional[str] = None,
        limit: int = 20,
    ) -> str:
        """Search for managed databases by name.

        Args:
            name_contains: Substring to search for in database name
            compartment_id: Compartment OCID (uses profile-specific default if not provided)
            profile: OCI profile (default: DEFAULT)
            region: Region override (uses profile-specific default if not provided)
            limit: Maximum results

        Returns:
            JSON with matching databases
        """
        manager = get_oci_manager()
        resolved_region = _get_region(profile, region)
        client = await manager.get_dbm_client(
            profile=profile,
            region=resolved_region
        )

        # Use profile-specific compartment from env vars if not explicitly provided
        comp_id = compartment_id or await _get_dbmgmt_compartment(profile)

        try:
            def _search():
                # List all and filter by name
                response = client.list_managed_databases(
                    compartment_id=comp_id,
                    limit=500,  # Get more to filter
                )
                return response.data

            databases = await asyncio.to_thread(_search)

            # Filter by name
            name_lower = name_contains.lower()
            matches = [
                db for db in databases
                if name_lower in db.name.lower()
            ][:limit]

            result = []
            for db in matches:
                result.append({
                    "id": db.id,
                    "name": db.name,
                    "database_type": db.database_type,
                    "database_sub_type": db.database_sub_type,
                    "deployment_type": getattr(db, "deployment_type", None),
                    "management_option": getattr(db, "management_option", None),
                })

            return json.dumps({
                "success": True,
                "databases": result,
                "count": len(result),
                "search_term": name_contains,
                "compartment_id": comp_id,
            }, indent=2)

        except Exception as e:
            return json.dumps({
                "success": False,
                "error": str(e),
                "search_term": name_contains,
            })
