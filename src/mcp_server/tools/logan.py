"""OCI Logging Analytics (Logan) tools.

Enhanced module providing:
- Tier 1: Cache-based instant lookups (<100ms)
- Tier 2: Logan API queries (1-5s)
- Tier 3: Analysis and detection (5-30s)
- Security Skills: MITRE, anomaly detection, threat hunting

Multi-tenancy: All tools accept optional 'profile' parameter.
"""

import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

from ..clients import get_oci_manager
from ..cache import cached_call

# Security query templates for common use cases
SECURITY_QUERIES = {
    "failed_logins": "Severity = 'error' AND Message =~ 'login|authentication|auth' AND Message =~ 'fail|denied|invalid' | stats count as failures by 'Entity Name', 'Log Source' | sort -failures",
    "privileged_operations": "'Log Source' IN ('OCI Audit Logs', 'Linux Secure Logs') AND Message =~ 'sudo|root|admin|privilege' | stats count by 'Entity Name', Message | top 20 count",
    "network_anomalies": "'Log Source' =~ 'Network|Firewall|VCN' AND (Severity = 'warning' OR Severity = 'error') | stats count by 'Entity Name', 'Log Source' | sort -count",
    "database_errors": "'Log Source' =~ 'Oracle|Database|DB' AND Severity IN ('error', 'critical') | stats count by 'Entity Name', Message | top 20 count",
    "audit_trail": "'Log Source' = 'OCI Audit Logs' | stats count by 'User Name', 'Request Action' | sort -count",
}

# Common query patterns for suggestions
QUERY_PATTERNS = {
    "count_by_source": "* | stats count as logrecords by 'Log Source' | sort -logrecords",
    "errors_by_entity": "Severity = 'error' | stats count by 'Entity Name' | sort -count",
    "top_messages": "* | stats count by Message | top 20 count",
    "time_distribution": "* | timecluster span=1h | stats count by 'Log Source'",
}


def register_tools(mcp: "FastMCP") -> None:
    """Register Logan tools with the MCP server."""

    async def _get_namespace(profile: str) -> str:
        """Get tenancy namespace for Logan queries."""
        manager = get_oci_manager()
        return await manager.get_namespace(profile)

    @mcp.tool()
    async def execute_logan_query(
        query: str,
        time_range_minutes: int = 1440,
        max_count: int = 200,
        compartment_id: Optional[str] = None,
        profile: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute a Logging Analytics query.

        IMPORTANT: Use proper OCI Logging Analytics syntax, NOT SQL!

        Examples:
        - List log sources: * | stats count as logrecords by 'Log Source' | sort -logrecords
        - Find errors: Severity = 'error'
        - Top errors: Severity = 'error' | stats count by Message | top 10 count

        Args:
            query: Logan query string
            time_range_minutes: Time range in minutes (default: 24h, max: 30 days)
            max_count: Maximum rows to return (default: 200)
            compartment_id: Optional compartment override
            profile: OCI profile name

        Returns:
            Query results or error
        """
        # Note: Logging Analytics queries are always fresh, minimal caching
        manager = get_oci_manager()
        profile_name = profile or "DEFAULT"

        try:
            config = await manager.get_config(profile_name)
            client = await manager.get_logan_client(profile_name)
            namespace = await _get_namespace(profile_name)

            comp_id = compartment_id or config.compartment_id

            # Calculate time range
            end_time = datetime.now(timezone.utc)
            start_time = end_time - timedelta(minutes=time_range_minutes)

            def _call_api():
                # Build query details
                query_details = {
                    "compartment_id": comp_id,
                    "compartment_id_in_subtree": True,
                    "query_string": query,
                    "sub_system": "LOG",
                    "max_total_count": max_count,
                    "time_filter": {
                        "time_start": start_time.isoformat().replace('+00:00', 'Z'),
                        "time_end": end_time.isoformat().replace('+00:00', 'Z'),
                        "time_zone": "UTC",
                    },
                }

                # Use the SDK's query method
                from oci.log_analytics.models import QueryDetails

                qd = QueryDetails(**query_details)
                response = client.query(
                    namespace_name=namespace,
                    query_details=qd,
                )
                return response.data

            result = await asyncio.to_thread(_call_api)

            # Parse query results
            columns = []
            rows = []

            if hasattr(result, 'columns') and result.columns:
                columns = [col.display_name for col in result.columns]

            if hasattr(result, 'items') and result.items:
                for item in result.items[:max_count]:
                    if hasattr(item, 'row'):
                        rows.append(item.row)
                    elif isinstance(item, dict):
                        rows.append(item)

            return {
                "success": True,
                "profile": profile_name,
                "query": query,
                "time_range": {
                    "start": str(start_time),
                    "end": str(end_time),
                    "minutes": time_range_minutes,
                },
                "result_count": len(rows),
                "columns": columns,
                "rows": rows[:50],  # Limit response size
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "query": query,
                "hint": "Check query syntax. Use Logan syntax like: * | stats count by 'Log Source'",
            }

    @mcp.tool()
    async def list_log_sources(
        display_name: Optional[str] = None,
        source_type: Optional[str] = None,
        is_system: Optional[bool] = None,
        limit: int = 100,
        compartment_id: Optional[str] = None,
        profile: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List available log sources from Logging Analytics.

        Args:
            display_name: Filter by display name
            source_type: Filter by source type
            is_system: Filter system/user sources
            limit: Maximum results
            compartment_id: Compartment OCID
            profile: OCI profile name

        Returns:
            List of log sources
        """

        async def _fetch():
            manager = get_oci_manager()
            profile_name = profile or "DEFAULT"

            try:
                config = await manager.get_config(profile_name)
                client = await manager.get_logan_client(profile_name)
                namespace = await _get_namespace(profile_name)

                comp_id = compartment_id or config.compartment_id

                def _call_api():
                    kwargs = {
                        "namespace_name": namespace,
                        "compartment_id": comp_id,
                        "limit": limit,
                    }

                    if display_name:
                        kwargs["name"] = display_name
                    if source_type:
                        kwargs["source_type"] = source_type
                    if is_system is not None:
                        kwargs["is_system"] = "SYSTEM" if is_system else "CUSTOM"

                    response = client.list_sources(**kwargs)
                    return response.data.items

                items = await asyncio.to_thread(_call_api)

                sources = []
                for item in items:
                    sources.append({
                        "name": item.name,
                        "display_name": item.display_name,
                        "description": item.description[:200] if item.description else None,
                        "source_type": item.source_type,
                        "is_system": item.is_system,
                        "time_updated": str(item.time_updated) if item.time_updated else None,
                    })

                return {
                    "success": True,
                    "profile": profile_name,
                    "count": len(sources),
                    "sources": sources,
                }

            except Exception as e:
                return {
                    "success": False,
                    "error": str(e),
                    "profile": profile_name,
                }

        return await cached_call(
            "list_log_sources",
            {"display_name": display_name, "source_type": source_type, "is_system": is_system, "limit": limit, "profile": profile},
            _fetch,
        )

    @mcp.tool()
    async def list_entities(
        entity_type: Optional[str] = None,
        name: Optional[str] = None,
        limit: int = 100,
        compartment_id: Optional[str] = None,
        profile: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List log analytics entities (hosts, databases, etc).

        Args:
            entity_type: Filter by entity type
            name: Filter by entity name
            limit: Maximum results
            compartment_id: Compartment OCID
            profile: OCI profile name

        Returns:
            List of entities
        """

        async def _fetch():
            manager = get_oci_manager()
            profile_name = profile or "DEFAULT"

            try:
                config = await manager.get_config(profile_name)
                client = await manager.get_logan_client(profile_name)
                namespace = await _get_namespace(profile_name)

                comp_id = compartment_id or config.compartment_id

                def _call_api():
                    kwargs = {
                        "namespace_name": namespace,
                        "compartment_id": comp_id,
                        "limit": limit,
                    }

                    if entity_type:
                        kwargs["entity_type_name"] = [entity_type]
                    if name:
                        kwargs["name"] = name

                    response = client.list_log_analytics_entities(**kwargs)
                    return response.data.items

                items = await asyncio.to_thread(_call_api)

                entities = []
                for item in items:
                    entities.append({
                        "id": item.id,
                        "name": item.name,
                        "entity_type_name": item.entity_type_name,
                        "lifecycle_state": item.lifecycle_state,
                        "management_agent_id": item.management_agent_id,
                        "cloud_resource_id": item.cloud_resource_id,
                        "time_created": str(item.time_created) if item.time_created else None,
                    })

                return {
                    "success": True,
                    "profile": profile_name,
                    "count": len(entities),
                    "entities": entities,
                }

            except Exception as e:
                return {
                    "success": False,
                    "error": str(e),
                    "profile": profile_name,
                }

        return await cached_call(
            "list_entities",
            {"entity_type": entity_type, "name": name, "limit": limit, "profile": profile},
            _fetch,
        )

    @mcp.tool()
    async def list_parsers(
        parser_name: Optional[str] = None,
        is_system: Optional[bool] = None,
        limit: int = 100,
        profile: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List available log parsers.

        Args:
            parser_name: Filter by parser name
            is_system: Filter system/user parsers
            limit: Maximum results
            profile: OCI profile name

        Returns:
            List of parsers
        """

        async def _fetch():
            manager = get_oci_manager()
            profile_name = profile or "DEFAULT"

            try:
                client = await manager.get_logan_client(profile_name)
                namespace = await _get_namespace(profile_name)

                def _call_api():
                    kwargs = {
                        "namespace_name": namespace,
                        "limit": limit,
                    }

                    if parser_name:
                        kwargs["parser_name"] = parser_name
                    if is_system is not None:
                        kwargs["is_system"] = "SYSTEM" if is_system else "CUSTOM"

                    response = client.list_parsers(**kwargs)
                    return response.data.items

                items = await asyncio.to_thread(_call_api)

                parsers = []
                for item in items:
                    parsers.append({
                        "name": item.name,
                        "display_name": item.display_name,
                        "type": item.type,
                        "is_system": item.is_system,
                        "description": item.description[:200] if item.description else None,
                    })

                return {
                    "success": True,
                    "profile": profile_name,
                    "count": len(parsers),
                    "parsers": parsers,
                }

            except Exception as e:
                return {
                    "success": False,
                    "error": str(e),
                    "profile": profile_name,
                }

        return await cached_call(
            "list_parsers",
            {"parser_name": parser_name, "is_system": is_system, "limit": limit, "profile": profile},
            _fetch,
        )

    @mcp.tool()
    async def list_labels(
        label_name: Optional[str] = None,
        limit: int = 100,
        profile: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List available log labels.

        Args:
            label_name: Filter by label name
            limit: Maximum results
            profile: OCI profile name

        Returns:
            List of labels
        """

        async def _fetch():
            manager = get_oci_manager()
            profile_name = profile or "DEFAULT"

            try:
                client = await manager.get_logan_client(profile_name)
                namespace = await _get_namespace(profile_name)

                def _call_api():
                    kwargs = {
                        "namespace_name": namespace,
                        "limit": limit,
                    }

                    if label_name:
                        kwargs["label_display_text"] = label_name

                    response = client.list_labels(**kwargs)
                    return response.data.items

                items = await asyncio.to_thread(_call_api)

                labels = []
                for item in items:
                    labels.append({
                        "name": item.name,
                        "display_name": item.display_name,
                        "type": item.type,
                        "is_system": item.is_system,
                        "description": item.description[:200] if item.description else None,
                    })

                return {
                    "success": True,
                    "profile": profile_name,
                    "count": len(labels),
                    "labels": labels,
                }

            except Exception as e:
                return {
                    "success": False,
                    "error": str(e),
                    "profile": profile_name,
                }

        return await cached_call(
            "list_labels",
            {"label_name": label_name, "limit": limit, "profile": profile},
            _fetch,
        )

    @mcp.tool()
    async def list_log_groups(
        limit: int = 100,
        compartment_id: Optional[str] = None,
        profile: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List log groups in a compartment.

        Args:
            limit: Maximum results
            compartment_id: Compartment OCID
            profile: OCI profile name

        Returns:
            List of log groups
        """

        async def _fetch():
            manager = get_oci_manager()
            profile_name = profile or "DEFAULT"

            try:
                config = await manager.get_config(profile_name)
                client = await manager.get_logan_client(profile_name)
                namespace = await _get_namespace(profile_name)

                comp_id = compartment_id or config.compartment_id

                def _call_api():
                    response = client.list_log_analytics_log_groups(
                        namespace_name=namespace,
                        compartment_id=comp_id,
                        limit=limit,
                    )
                    return response.data.items

                items = await asyncio.to_thread(_call_api)

                groups = []
                for item in items:
                    groups.append({
                        "id": item.id,
                        "display_name": item.display_name,
                        "description": item.description[:200] if item.description else None,
                        "time_created": str(item.time_created) if item.time_created else None,
                    })

                return {
                    "success": True,
                    "profile": profile_name,
                    "count": len(groups),
                    "log_groups": groups,
                }

            except Exception as e:
                return {
                    "success": False,
                    "error": str(e),
                    "profile": profile_name,
                }

        return await cached_call(
            "list_log_groups",
            {"limit": limit, "compartment_id": compartment_id, "profile": profile},
            _fetch,
        )

    # =========================================================================
    # TIER 2: Security Analysis Skills
    # =========================================================================

    @mcp.tool()
    async def run_security_query(
        query_type: str,
        time_range_minutes: int = 1440,
        compartment_id: Optional[str] = None,
        profile: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run a predefined security analysis query.

        Available query types:
        - failed_logins: Detect failed authentication attempts
        - privileged_operations: Track sudo/root/admin actions
        - network_anomalies: Find network/firewall warnings/errors
        - database_errors: Database-related errors
        - audit_trail: OCI audit log summary

        Args:
            query_type: One of the predefined security query types
            time_range_minutes: Time range in minutes (default: 24h)
            compartment_id: Optional compartment override
            profile: OCI profile name

        Returns:
            Security analysis results
        """
        if query_type not in SECURITY_QUERIES:
            return {
                "success": False,
                "error": f"Unknown query type: {query_type}",
                "available_types": list(SECURITY_QUERIES.keys()),
            }

        query = SECURITY_QUERIES[query_type]
        result = await execute_logan_query(
            query=query,
            time_range_minutes=time_range_minutes,
            max_count=100,
            compartment_id=compartment_id,
            profile=profile,
        )

        if result.get("success"):
            result["query_type"] = query_type
            result["description"] = {
                "failed_logins": "Failed authentication attempts detected",
                "privileged_operations": "Privileged operation activity",
                "network_anomalies": "Network-related warnings and errors",
                "database_errors": "Database error events",
                "audit_trail": "OCI audit log activity summary",
            }.get(query_type, "Security analysis")

        return result

    @mcp.tool()
    async def detect_anomalies(
        baseline_hours: int = 168,
        detection_hours: int = 24,
        threshold_multiplier: float = 3.0,
        compartment_id: Optional[str] = None,
        profile: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Detect log volume anomalies by comparing recent activity to baseline.

        Compares log volumes in the detection window against a baseline period
        to identify unusual spikes or drops in logging activity.

        Args:
            baseline_hours: Hours for baseline calculation (default: 7 days)
            detection_hours: Recent hours to check for anomalies (default: 24h)
            threshold_multiplier: Standard deviations for anomaly (default: 3.0)
            compartment_id: Optional compartment override
            profile: OCI profile name

        Returns:
            Anomaly detection results with affected log sources
        """
        profile_name = profile or "DEFAULT"

        # Get baseline data
        baseline_query = "* | stats count as baseline_count by 'Log Source'"
        baseline_result = await execute_logan_query(
            query=baseline_query,
            time_range_minutes=baseline_hours * 60,
            max_count=500,
            compartment_id=compartment_id,
            profile=profile_name,
        )

        # Get recent data
        recent_query = "* | stats count as recent_count by 'Log Source'"
        recent_result = await execute_logan_query(
            query=recent_query,
            time_range_minutes=detection_hours * 60,
            max_count=500,
            compartment_id=compartment_id,
            profile=profile_name,
        )

        if not baseline_result.get("success") or not recent_result.get("success"):
            return {
                "success": False,
                "error": "Failed to retrieve log data for anomaly detection",
                "baseline_error": baseline_result.get("error"),
                "recent_error": recent_result.get("error"),
            }

        # Calculate anomalies
        anomalies = []
        baseline_data = {row[0]: int(row[1]) for row in baseline_result.get("rows", []) if len(row) >= 2}
        recent_data = {row[0]: int(row[1]) for row in recent_result.get("rows", []) if len(row) >= 2}

        # Normalize baseline to hourly rate
        baseline_rate = {k: v / baseline_hours for k, v in baseline_data.items()}

        for source, recent_count in recent_data.items():
            recent_rate = recent_count / detection_hours
            expected_rate = baseline_rate.get(source, 0)

            if expected_rate > 0:
                deviation = (recent_rate - expected_rate) / expected_rate
                if abs(deviation) >= (threshold_multiplier - 1):
                    anomalies.append({
                        "log_source": source,
                        "recent_count": recent_count,
                        "expected_count": int(expected_rate * detection_hours),
                        "deviation_percent": round(deviation * 100, 1),
                        "anomaly_type": "spike" if deviation > 0 else "drop",
                        "severity": "high" if abs(deviation) > 5 else "medium",
                    })
            elif recent_count > 100:
                # New high-volume source
                anomalies.append({
                    "log_source": source,
                    "recent_count": recent_count,
                    "expected_count": 0,
                    "deviation_percent": None,
                    "anomaly_type": "new_source",
                    "severity": "medium",
                })

        # Sort by severity and count
        anomalies.sort(key=lambda x: (-{"high": 2, "medium": 1}.get(x["severity"], 0), -x["recent_count"]))

        return {
            "success": True,
            "profile": profile_name,
            "baseline_hours": baseline_hours,
            "detection_hours": detection_hours,
            "threshold_multiplier": threshold_multiplier,
            "anomalies_found": len(anomalies),
            "anomalies": anomalies[:20],
            "sources_analyzed": len(recent_data),
        }

    @mcp.tool()
    async def get_log_summary(
        time_range_minutes: int = 1440,
        compartment_id: Optional[str] = None,
        profile: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get a comprehensive log summary for the time period.

        Provides overview of log activity including:
        - Total log count
        - Logs by source
        - Logs by severity
        - Top entities
        - Error summary

        Args:
            time_range_minutes: Time range in minutes (default: 24h)
            compartment_id: Optional compartment override
            profile: OCI profile name

        Returns:
            Comprehensive log summary
        """
        profile_name = profile or "DEFAULT"

        # Run multiple queries in parallel
        queries = {
            "by_source": "* | stats count as logs by 'Log Source' | sort -logs | head 10",
            "by_severity": "* | stats count as logs by Severity | sort -logs",
            "by_entity": "* | stats count as logs by 'Entity Name' | sort -logs | head 10",
            "errors": "Severity IN ('error', 'critical') | stats count as errors by 'Log Source' | sort -errors | head 10",
        }

        results = {}
        for name, query in queries.items():
            result = await execute_logan_query(
                query=query,
                time_range_minutes=time_range_minutes,
                max_count=100,
                compartment_id=compartment_id,
                profile=profile_name,
            )
            results[name] = result

        # Parse results
        summary = {
            "success": True,
            "profile": profile_name,
            "time_range_minutes": time_range_minutes,
            "by_source": [],
            "by_severity": {},
            "by_entity": [],
            "error_summary": [],
            "total_logs": 0,
            "total_errors": 0,
        }

        # Process by_source
        if results["by_source"].get("success"):
            for row in results["by_source"].get("rows", []):
                if len(row) >= 2:
                    summary["by_source"].append({"source": row[0], "count": int(row[1])})
                    summary["total_logs"] += int(row[1])

        # Process by_severity
        if results["by_severity"].get("success"):
            for row in results["by_severity"].get("rows", []):
                if len(row) >= 2:
                    summary["by_severity"][row[0]] = int(row[1])

        # Process by_entity
        if results["by_entity"].get("success"):
            for row in results["by_entity"].get("rows", []):
                if len(row) >= 2:
                    summary["by_entity"].append({"entity": row[0], "count": int(row[1])})

        # Process errors
        if results["errors"].get("success"):
            for row in results["errors"].get("rows", []):
                if len(row) >= 2:
                    summary["error_summary"].append({"source": row[0], "errors": int(row[1])})
                    summary["total_errors"] += int(row[1])

        return summary

    @mcp.tool()
    async def suggest_query(
        intent: str,
    ) -> Dict[str, Any]:
        """Suggest a Logan query based on natural language intent.

        Analyzes the intent and suggests appropriate Logan query syntax.

        Args:
            intent: Natural language description of what you want to find

        Returns:
            Suggested query with explanation
        """
        intent_lower = intent.lower()
        suggestions = []

        # Pattern matching for common intents
        patterns = [
            (["error", "fail", "exception"], "Severity = 'error' | stats count by 'Log Source', Message | top 20 count"),
            (["login", "auth", "authentication"], "Message =~ 'login|auth|credential' | stats count by 'Entity Name', Message | top 20 count"),
            (["database", "oracle", "db"], "'Log Source' =~ 'Oracle|Database|DB' | stats count by 'Log Source', Severity | sort -count"),
            (["security", "threat", "attack"], "Severity IN ('error', 'critical', 'warning') AND Message =~ 'attack|threat|malicious|unauthorized' | stats count by Message | top 20 count"),
            (["network", "connection", "firewall"], "'Log Source' =~ 'Network|Firewall|VCN' | stats count by 'Entity Name', Severity | sort -count"),
            (["audit", "compliance", "activity"], "'Log Source' = 'OCI Audit Logs' | stats count by 'User Name', 'Request Action' | sort -count"),
            (["performance", "slow", "latency"], "Message =~ 'slow|timeout|latency|performance' | stats count by 'Log Source', 'Entity Name' | sort -count"),
            (["top", "most", "volume"], "* | stats count as logs by 'Log Source' | sort -logs | head 20"),
        ]

        for keywords, query in patterns:
            if any(kw in intent_lower for kw in keywords):
                suggestions.append({
                    "query": query,
                    "matched_keywords": [kw for kw in keywords if kw in intent_lower],
                    "description": f"Query matching: {', '.join(keywords)}",
                })

        # Add generic suggestions if no specific match
        if not suggestions:
            suggestions = [
                {
                    "query": "* | stats count by 'Log Source' | sort -count",
                    "description": "Count logs by source",
                },
                {
                    "query": f"Message =~ '{intent.split()[0]}' | stats count by Message | top 20 count",
                    "description": f"Search for '{intent.split()[0]}' in messages",
                },
            ]

        return {
            "success": True,
            "intent": intent,
            "suggestions": suggestions[:5],
            "syntax_help": {
                "filter": "Use = for exact match, =~ for regex",
                "aggregate": "Use | stats count by 'Field Name'",
                "sort": "Use | sort -field for descending",
                "limit": "Use | head N or | top N field",
            },
        }

    @mcp.tool()
    async def list_active_log_sources(
        time_range_minutes: int = 1440,
        min_count: int = 1,
        compartment_id: Optional[str] = None,
        profile: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List log sources that have received logs in the time period.

        Args:
            time_range_minutes: Time range in minutes (default: 24h)
            min_count: Minimum log count to include (default: 1)
            compartment_id: Optional compartment override
            profile: OCI profile name

        Returns:
            List of active log sources with counts
        """
        profile_name = profile or "DEFAULT"

        query = f"* | stats count as logs by 'Log Source' | where logs >= {min_count} | sort -logs"

        result = await execute_logan_query(
            query=query,
            time_range_minutes=time_range_minutes,
            max_count=200,
            compartment_id=compartment_id,
            profile=profile_name,
        )

        if not result.get("success"):
            return result

        active_sources = []
        total_logs = 0

        for row in result.get("rows", []):
            if len(row) >= 2:
                count = int(row[1])
                active_sources.append({
                    "source": row[0],
                    "count": count,
                })
                total_logs += count

        return {
            "success": True,
            "profile": profile_name,
            "time_range_minutes": time_range_minutes,
            "active_source_count": len(active_sources),
            "total_logs": total_logs,
            "sources": active_sources,
        }

    @mcp.tool()
    async def get_entity_logs(
        entity_name: str,
        time_range_minutes: int = 1440,
        severity: Optional[str] = None,
        max_count: int = 100,
        profile: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get logs for a specific entity (host, database, etc).

        Args:
            entity_name: Name of the entity to search
            time_range_minutes: Time range in minutes (default: 24h)
            severity: Optional severity filter (error, warning, info)
            max_count: Maximum logs to return
            profile: OCI profile name

        Returns:
            Logs for the specified entity
        """
        profile_name = profile or "DEFAULT"

        # Build query
        query = f"'Entity Name' = '{entity_name}'"
        if severity:
            query += f" AND Severity = '{severity}'"
        query += " | head " + str(max_count)

        result = await execute_logan_query(
            query=query,
            time_range_minutes=time_range_minutes,
            max_count=max_count,
            profile=profile_name,
        )

        if result.get("success"):
            result["entity_name"] = entity_name

        return result

    @mcp.tool()
    async def list_logan_skills() -> Dict[str, Any]:
        """List all available Logan skills with usage hints.

        Returns:
            List of Logan tools with descriptions
        """
        skills = [
            {
                "name": "execute_logan_query",
                "tier": 2,
                "description": "Execute custom Logan queries",
                "use_when": ["custom query", "specific search", "advanced analysis"],
            },
            {
                "name": "run_security_query",
                "tier": 2,
                "description": "Run predefined security analysis queries",
                "use_when": ["security audit", "failed logins", "privileged operations"],
            },
            {
                "name": "detect_anomalies",
                "tier": 3,
                "description": "Detect log volume anomalies",
                "use_when": ["anomaly detection", "unusual activity", "volume spikes"],
            },
            {
                "name": "get_log_summary",
                "tier": 2,
                "description": "Get comprehensive log overview",
                "use_when": ["log summary", "overview", "status check"],
            },
            {
                "name": "suggest_query",
                "tier": 1,
                "description": "Get query suggestions from natural language",
                "use_when": ["help with query", "how to search", "query syntax"],
            },
            {
                "name": "list_active_log_sources",
                "tier": 2,
                "description": "List sources with recent activity",
                "use_when": ["active sources", "what's logging", "log volume"],
            },
            {
                "name": "get_entity_logs",
                "tier": 2,
                "description": "Get logs for specific entity",
                "use_when": ["host logs", "entity logs", "specific server"],
            },
            {
                "name": "list_log_sources",
                "tier": 1,
                "description": "List available log sources",
                "use_when": ["list sources", "available sources", "source types"],
            },
            {
                "name": "list_entities",
                "tier": 1,
                "description": "List log analytics entities",
                "use_when": ["list entities", "hosts", "databases"],
            },
        ]

        return {
            "success": True,
            "skill_count": len(skills),
            "tiers": {
                1: "Cache-based instant (<100ms)",
                2: "Logan API queries (1-5s)",
                3: "Analysis workflows (5-30s)",
            },
            "security_queries": list(SECURITY_QUERIES.keys()),
            "query_patterns": list(QUERY_PATTERNS.keys()),
            "skills": skills,
        }
