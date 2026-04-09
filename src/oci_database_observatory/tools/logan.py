"""OCI Logging Analytics (Logan) tools.

Enhanced module providing:
- Tier 1: Cache-based instant lookups (<100ms)
- Tier 2: Logan API queries (1-5s)
- Tier 3: Analysis and detection (5-30s)
- Security Skills: MITRE, anomaly detection, threat hunting

Multi-tenancy: All tools accept optional 'profile' parameter.
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

from src.core import settings

from ..cache import cached_call

CANONICAL_EXECUTION_NOTE = (
    "Executed via the canonical OCI Log Analytics MCP server. "
    "This path is restricted to real OCI Log Analytics data."
)


def _minutes_to_time_range(minutes: int) -> str:
    total_minutes = max(minutes, 1)
    if total_minutes % 1440 == 0:
        return f"{total_minutes // 1440}d"
    if total_minutes % 60 == 0:
        return f"{total_minutes // 60}h"
    return f"{total_minutes}m"


def _canonical_args(profile: Optional[str] = None, **kwargs: Any) -> Dict[str, Any]:
    """Build canonical Logan RPC arguments with explicit tenancy scoping."""
    arguments = dict(kwargs)
    arguments["profile"] = profile or "DEFAULT"
    return arguments


async def _call_canonical(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Call the canonical Logan MCP server over HTTP and normalize the result."""
    import httpx

    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments,
        },
        "id": 1,
    }

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0)) as client:
            response = await client.post(settings.logan_http_url.rstrip("/"), json=payload)
            response.raise_for_status()
    except Exception as exc:
        return {"success": False, "error": f"Canonical Logan MCP request failed: {exc}"}

    result = response.json()
    if "error" in result:
        return {"success": False, "error": f"Canonical Logan MCP error: {result['error']}"}

    content = result.get("result", {}).get("content", [])
    text = None
    if isinstance(content, list):
        text = next((item.get("text") for item in content if item.get("type") == "text"), None)
    if text is None:
        raw_result = result.get("result")
        if isinstance(raw_result, dict):
            return raw_result
        return {"success": False, "error": "Canonical Logan MCP returned no text payload"}

    try:
        parsed = json.loads(text)
    except Exception:
        return {"success": True, "raw": text}

    if isinstance(parsed, dict):
        return parsed
    return {"success": True, "result": parsed}


def _rows_from_results(
    results: List[Dict[str, Any]], max_count: int
) -> tuple[List[str], List[List[Any]]]:
    columns: List[str] = []
    for item in results:
        for key in item:
            if key not in columns:
                columns.append(key)
    rows = [[item.get(column) for column in columns] for item in results[:max_count]]
    return columns, rows


# Security query templates for common use cases
SECURITY_QUERIES = {
    "failed_logins": "Severity = 'error' AND Message =~ 'login|authentication|auth' AND Message =~ 'fail|denied|invalid' | stats count as failures by 'Entity Name', 'Log Source' | sort -failures",
    "privileged_operations": "'Log Source' IN ('OCI Audit Logs', 'Linux Secure Logs') AND Message =~ 'sudo|root|admin|privilege' | stats count by 'Entity Name', Message | top 20 count",
    "network_anomalies": "'Log Source' =~ 'Network|Firewall|VCN' AND (Severity = 'warning' OR Severity = 'error') | stats count by 'Entity Name', 'Log Source' | sort -count",
    "database_errors": "'Log Source' =~ 'Oracle|Database|DB' AND Severity IN ('error', 'critical') | stats count by 'Entity Name', Message | top 20 count",
    "audit_trail": "'Log Source' = 'OCI Audit Logs' | stats count by 'User Name', 'Request Action' | sort -count",
}

# SKP APM security presets — auto-generated from Seven Kingdoms Portal detection rules
# 44 rules covering 12 MITRE tactics, 28 techniques (OWASP Top 10 + AD attacks)
# Source: scripts/generate_mcp_observatory_presets.py in OCI-DEMO
_SKP_SECURITY_QUERIES = {
    # --- OWASP: Injection (A03) ---
    "skp_sqli": "'Log Source' = 'OCI APM Trace' | where security_attack_type = 'sqli' | where security_attack_payload like '%OR%1%=%1%' or security_attack_payload like '%UNION%SELECT%' | stats count as sqli_count by security_source_ip",
    "skp_nosql_injection": "'Log Source' = 'OCI APM Trace' | where nosql_injection_detected = 'true' | stats count by security_source_ip, nosql_filter",
    "skp_ldap_injection": "'Log Source' = 'OCI APM Trace' | where security_attack_type = 'ldap_injection' | stats count by security_source_ip, security_username",
    "skp_ssti": "'Log Source' = 'OCI APM Trace' | where security_attack_type = 'ssti' | stats count by security_source_ip",
    "skp_rce": "'Log Source' = 'OCI APM Trace' | where security_attack_type = 'rce' | stats count as rce_count by security_attack_payload, security_source_ip",
    "skp_xss": "'Log Source' = 'OCI APM Trace' | where security_attack_type = 'xss' | where security_attack_payload like '%<script%' or security_attack_payload like '%onerror%' | stats count by security_source_ip",
    "skp_xxe": "'Log Source' = 'OCI APM Trace' | where security_attack_type = 'xxe' | stats count by security_source_ip",
    "skp_log_injection": "'Log Source' = 'OCI APM Trace' | where security_attack_type = 'log_injection' | stats count by security_source_ip",
    "skp_header_injection": "'Log Source' = 'OCI APM Trace' | where header_injection_crlf_detected = 'true' | stats count by security_source_ip",
    # --- OWASP: Broken Access Control (A01) ---
    "skp_idor": "'Log Source' = 'OCI APM Trace' | where security_attack_type = 'idor' | stats count as attack_count by security_source_ip, security_username | where attack_count > 3",
    "skp_path_traversal": "'Log Source' = 'OCI APM Trace' | where security_attack_type = 'path_traversal' | stats count as traversal_count by security_source_ip",
    "skp_privilege_escalation": "'Log Source' = 'OCI APM Trace' | where security_attack_type = 'privilege_escalation' | stats count by security_source_ip, security_escalation_role",
    "skp_mass_assignment": "'Log Source' = 'OCI APM Trace' | where security_attack_type = 'mass_assignment' | stats count by security_username",
    "skp_csrf": "'Log Source' = 'OCI APM Trace' | where security_attack_type = 'csrf' | stats count by security_source_ip, security_csrf_referer",
    "skp_forged_identity": "'Log Source' = 'OCI APM Trace' | where security_attack_type = 'forged_identity' | stats count by security_actual_user, security_claimed_user",
    # --- OWASP: Auth Failures (A07) ---
    "skp_auth_bypass": "'Log Source' = 'OCI APM Trace' | where security_attack_type = 'auth_bypass' | stats count by security_username, security_source_ip",
    "skp_brute_force": "'Log Source' = 'OCI APM Trace' | where security_attack_type = 'brute_force' | stats count as attempts by security_source_ip | where attempts >= 5",
    "skp_jwt_manipulation": "'Log Source' = 'OCI APM Trace' | where security_attack_type = 'jwt_manipulation' | stats count by security_source_ip",
    "skp_credential_leak": "'Log Source' = 'OCI APM Trace' | where security_attack_type = 'credential_leak' | stats earliest(security_attack_timestamp) as first_seen, count as leak_count by security_source_ip",
    "skp_credential_config_leak": "'Log Source' = 'OCI APM Trace' | where security_attack_type = 'credential_leak' | stats count as access_count by security_source_ip | where access_count > 1",
    "skp_credential_api_key_leak": "'Log Source' = 'OCI APM Trace' | where security_attack_type = 'credential_leak' | where credential_type = 'api_key' | stats count as access_count by security_source_ip | where access_count >= 1",
    "skp_security_question_bypass": "'Log Source' = 'OCI APM Trace' | where security_attack_type = 'security_question_bypass' or security_attack_type = 'password_reset_osint' | stats count by security_source_ip, security_username",
    "skp_captcha_bypass": "'Log Source' = 'OCI APM Trace' | where security_attack_type = 'captcha_bypass' | stats count by security_source_ip",
    # --- OWASP: Insecure Design (A04) / Deserialization (A08) ---
    "skp_deserialization": "'Log Source' = 'OCI APM Trace' | where security_attack_type = 'deserialization' | stats count by security_source_ip",
    "skp_prototype_pollution": "'Log Source' = 'OCI APM Trace' | where security_attack_type = 'prototype_pollution' | stats count by security_source_ip",
    "skp_open_redirect": "'Log Source' = 'OCI APM Trace' | where security_attack_type = 'open_redirect' | stats count by security_attack_payload",
    "skp_webshell_upload": "'Log Source' = 'OCI APM Trace' | where upload_is_webshell = 'true' or upload_has_script_content = 'true' | stats count by security_source_ip, upload_filename",
    # --- OWASP: SSRF (A10) ---
    "skp_ssrf": "'Log Source' = 'OCI APM Trace' | where security_attack_type = 'ssrf' | where security_attack_payload like '%169.254%' or security_attack_payload like '%127.0.0%' or security_attack_payload like '%10.0.%' | stats count by security_attack_payload, security_source_ip",
    "skp_internal_recon": "'Log Source' = 'OCI APM Trace' | where security_attack_type = 'internal_recon' | stats count as probe_count by security_source_ip, recon_target_url | where probe_count >= 3",
    # --- Business Logic Abuse ---
    "skp_coupon_forge": "'Log Source' = 'OCI APM Trace' | where security_attack_type = 'coupon_forge' | stats count as forge_count by security_source_ip",
    "skp_negative_quantity": "'Log Source' = 'OCI APM Trace' | where security_attack_type = 'negative_quantity' or security_attack_type = 'negative_transfer' | stats count by security_source_ip",
    "skp_price_tampering": "'Log Source' = 'OCI APM Trace' | where security_attack_type = 'price_tampering' | stats count by security_source_ip, shop_original_price, shop_tampered_price",
    # --- Active Directory Attacks ---
    "skp_kerberoasting": "'Log Source' = 'OCI APM Trace' | where security_attack_detected = 'true' | where security_attack_mitre_id = 'T1558.003' | stats count as kerberoast_count, distinctcount(security_kerberos_spn) as unique_spns, earliest(TimeGenerated) as first_seen, latest(TimeGenerated) as last_seen by security_source_ip | where kerberoast_count >= 1 | sort -kerberoast_count",
    "skp_dcsync": "'Log Source' = 'OCI APM Trace' | where security_attack_detected = 'true' | where security_attack_mitre_id = 'T1003.006' | stats count as dcsync_count, distinctcount(security_dcsync_target_user) as unique_targets, values(security_dcsync_target_user) as targeted_users, earliest(TimeGenerated) as first_seen, latest(TimeGenerated) as last_seen by security_source_ip, security_dcsync_domain | where dcsync_count >= 1 | sort -dcsync_count",
    "skp_adcs_enumerate": "'Log Source' = 'OCI APM Trace' | where security_attack_detected = 'true' | where security_attack_type = 'adcs_enumerate' | eval vuln_count = tonumber(security_adcs_vulnerable_templates) | stats count as enum_attempts, max(vuln_count) as max_vuln_templates, values(security_adcs_ca_name) as target_cas, earliest(TimeGenerated) as first_seen, latest(TimeGenerated) as last_seen by security_source_ip | where enum_attempts >= 1 | sort -enum_attempts",
    "skp_adcs_esc1": "'Log Source' = 'OCI APM Trace' | where security_attack_detected = 'true' | where security_attack_type = 'adcs_esc1' | stats count as esc1_requests, distinctcount(security_adcs_requested_san) as unique_impersonations, values(security_adcs_requested_san) as impersonated_users, values(security_adcs_template) as templates_used, earliest(TimeGenerated) as first_seen, latest(TimeGenerated) as last_seen by security_source_ip | where esc1_requests >= 1 | sort -esc1_requests",
    "skp_adcs_esc4": "'Log Source' = 'OCI APM Trace' | where security_attack_detected = 'true' | where security_attack_type = 'adcs_esc4' | stats count as template_mods, values(security_adcs_template_modified) as modified_templates, values(security_adcs_acl_change) as acl_changes, earliest(TimeGenerated) as first_seen, latest(TimeGenerated) as last_seen by security_source_ip | where template_mods >= 1 | sort -template_mods",
    "skp_adcs_esc8": "'Log Source' = 'OCI APM Trace' | where security_attack_detected = 'true' | where security_attack_type = 'adcs_esc8' | stats count as relay_attempts, distinctcount(security_adcs_relay_source) as unique_sources, values(security_adcs_relay_source) as relayed_hosts, values(security_adcs_relay_target) as target_cas, earliest(TimeGenerated) as first_seen, latest(TimeGenerated) as last_seen by security_source_ip | where relay_attempts >= 1 | sort -relay_attempts",
    "skp_adcs_ca_exploit": "'Log Source' = 'OCI APM Trace' | where security_attack_detected = 'true' | where security_attack_type = 'adcs_ca_exploit' | stats count as ca_exploit_attempts, values(security_adcs_ca_flags) as exposed_flags, earliest(TimeGenerated) as first_seen, latest(TimeGenerated) as last_seen by security_source_ip | where ca_exploit_attempts >= 1 | sort -ca_exploit_attempts",
    "skp_adcs_chain": "'Log Source' = 'OCI APM Trace' | where security_attack_detected = 'true' | where security_attack_type like 'adcs_%' | stats distinctcount(security_attack_type) as adcs_attack_stages, values(security_attack_type) as attack_types_seen, values(security_adcs_requested_san) as impersonated_users, values(security_adcs_relay_target) as relay_targets, values(security_adcs_template_modified) as modified_templates, count as total_adcs_events, earliest(TimeGenerated) as chain_start, latest(TimeGenerated) as chain_end by security_source_ip | where adcs_attack_stages >= 2 | sort -adcs_attack_stages",
    # --- Multi-Stage / Kill Chain ---
    "skp_multi_stage": "'Log Source' = 'OCI APM Trace' | where security_attack_detected = 'true' | stats distinctcount(security_attack_type) as attack_types, count as total_attacks by security_source_ip | where attack_types >= 3",
    "skp_c2_exfiltration": "'Log Source' = 'OCI APM Trace' | where security_attack_type = 'c2_exfiltration' | stats sum(exfiltration_bytes) as total_bytes, count as upload_count by security_source_ip | where upload_count >= 2",
    "skp_data_collection": "'Log Source' = 'OCI APM Trace' | where security_attack_type = 'data_collection' | stats count as collection_count by security_source_ip | where collection_count >= 1",
    "skp_service_persistence": "'Log Source' = 'OCI APM Trace' | where security_attack_type = 'service_persistence' | where persistence_exec_path like '%/tmp/%' or persistence_exec_path like '%/dev/shm/%' | stats count by security_source_ip, persistence_service_name",
}

# Merge SKP presets into main SECURITY_QUERIES
SECURITY_QUERIES.update(_SKP_SECURITY_QUERIES)

# Human-readable descriptions for security query types
_SECURITY_QUERY_DESCRIPTIONS = {
    # Infrastructure queries
    "failed_logins": "Failed authentication attempts detected",
    "privileged_operations": "Privileged operation activity",
    "network_anomalies": "Network-related warnings and errors",
    "database_errors": "Database error events",
    "audit_trail": "OCI audit log activity summary",
    # SKP APM queries — Injection
    "skp_sqli": "SQL injection attempts via APM traces",
    "skp_nosql_injection": "NoSQL operator injection via JSON filters",
    "skp_ldap_injection": "LDAP directory query manipulation",
    "skp_ssti": "Server-side template injection",
    "skp_rce": "OS command injection / remote code execution",
    "skp_xss": "Cross-site scripting payload injection",
    "skp_xxe": "XML external entity injection",
    "skp_log_injection": "Log forging / injection attacks",
    "skp_header_injection": "HTTP header CRLF response splitting",
    # SKP APM queries — Access Control
    "skp_idor": "Insecure direct object reference (IDOR)",
    "skp_path_traversal": "Directory traversal / path escape",
    "skp_privilege_escalation": "Hidden role privilege escalation",
    "skp_mass_assignment": "Mass assignment via registration",
    "skp_csrf": "Cross-site request forgery",
    "skp_forged_identity": "Review submitted as another user",
    # SKP APM queries — Authentication
    "skp_auth_bypass": "Default/well-known credential login",
    "skp_brute_force": "Multiple failed login attempts",
    "skp_jwt_manipulation": "JWT none-algorithm signature bypass",
    "skp_credential_leak": "Debug endpoint credential exposure",
    "skp_credential_config_leak": "Crypto config disclosure",
    "skp_credential_api_key_leak": "Unsecured API key endpoint",
    "skp_security_question_bypass": "OSINT-based password reset bypass",
    "skp_captcha_bypass": "Anti-automation CAPTCHA defeated",
    # SKP APM queries — Design / Deserialization
    "skp_deserialization": "Insecure deserialization (pickle/JSON)",
    "skp_prototype_pollution": "Config deep merge prototype pollution",
    "skp_open_redirect": "URL manipulation open redirect",
    "skp_webshell_upload": "Web shell / script content upload",
    # SKP APM queries — SSRF
    "skp_ssrf": "Server-side request forgery to internal IPs",
    "skp_internal_recon": "Internal network reconnaissance via SSRF",
    # SKP APM queries — Business Logic
    "skp_coupon_forge": "Weak-encoding coupon forgery",
    "skp_negative_quantity": "Reverse purchase fraud via negative qty",
    "skp_price_tampering": "Client-side price override",
    # SKP APM queries — Active Directory
    "skp_kerberoasting": "SPN ticket extraction (Kerberoasting)",
    "skp_dcsync": "Domain controller replication attack (DCSync)",
    "skp_adcs_enumerate": "ADCS vulnerable template discovery",
    "skp_adcs_esc1": "ADCS ESC1 certificate SAN impersonation",
    "skp_adcs_esc4": "ADCS ESC4 template ACL modification",
    "skp_adcs_esc8": "ADCS ESC8 NTLM relay to cert enrollment",
    "skp_adcs_ca_exploit": "ADCS ESC6/7 CA configuration exploit",
    "skp_adcs_chain": "ADCS multi-stage attack chain",
    # SKP APM queries — Kill Chain
    "skp_multi_stage": "Multi-stage attack chain (3+ attack types)",
    "skp_c2_exfiltration": "Data exfiltration over C2 channel",
    "skp_data_collection": "Sensitive file aggregation/collection",
    "skp_service_persistence": "Malicious system service persistence",
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

    @mcp.tool(
        name="oci_logan_execute_query",
        annotations={
            "title": "Execute Logan Query",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
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
        profile_name = profile or "DEFAULT"
        from .logan_ai import fix_query_fields

        query = fix_query_fields(query)

        try:
            canonical = await _call_canonical(
                "oci_logan_execute_query",
                _canonical_args(
                    profile,
                    query=query,
                    timeRange=_minutes_to_time_range(time_range_minutes),
                    limit=max_count,
                    compartmentId=compartment_id or "",
                    format="json",
                ),
            )
            if canonical.get("error"):
                return {
                    "success": False,
                    "error": canonical["error"],
                    "query": query,
                    "hint": "Ensure the canonical Logan MCP server is reachable at LOGAN_HTTP_URL.",
                }

            results = canonical.get("results", []) or []
            columns, rows = _rows_from_results(results, max_count)
            end_time = datetime.now(timezone.utc)
            start_time = end_time - timedelta(minutes=time_range_minutes)

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
                "rows": rows[:50],
                "canonical_server": settings.logan_http_url,
                "execution_note": CANONICAL_EXECUTION_NOTE,
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "query": query,
                "hint": "Check canonical Logan MCP connectivity or query syntax.",
            }

    globals()["execute_logan_query"] = execute_logan_query

    @mcp.tool(
        name="oci_logan_list_sources",
        annotations={
            "title": "List Log Sources",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
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
            profile_name = profile or "DEFAULT"
            canonical = await _call_canonical(
                "oci_logan_list_log_sources",
                _canonical_args(
                    profile,
                    compartmentId=compartment_id or "",
                    displayName=display_name or "",
                    isSystem=(
                        "true" if is_system is True else "false" if is_system is False else ""
                    ),
                    limit=limit,
                    format="json",
                ),
            )
            if canonical.get("error"):
                return {"success": False, "error": canonical["error"], "profile": profile_name}

            sources = canonical.get("results", []) or []
            if source_type:
                sources = [
                    item
                    for item in sources
                    if (item.get("source_type") or "").lower() == source_type.lower()
                ]
            return {
                "success": True,
                "profile": profile_name,
                "count": len(sources),
                "sources": sources[:limit],
                "canonical_server": settings.logan_http_url,
            }

        return await cached_call(
            "list_log_sources",
            {
                "display_name": display_name,
                "source_type": source_type,
                "is_system": is_system,
                "limit": limit,
                "compartment_id": compartment_id,
                "profile": profile,
            },
            _fetch,
        )

    @mcp.tool(
        name="oci_logan_list_entities",
        annotations={
            "title": "List Entities",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
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
            profile_name = profile or "DEFAULT"
            canonical = await _call_canonical(
                "oci_logan_list_entities",
                _canonical_args(
                    profile,
                    entityType=entity_type or "all",
                    compartmentId=compartment_id or "",
                    limit=limit,
                    format="json",
                ),
            )
            if canonical.get("error"):
                return {"success": False, "error": canonical["error"], "profile": profile_name}

            entities = canonical.get("results", []) or []
            if name:
                entities = [
                    item for item in entities if name.lower() in (item.get("name") or "").lower()
                ]
            return {
                "success": True,
                "profile": profile_name,
                "count": len(entities),
                "entities": entities[:limit],
                "canonical_server": settings.logan_http_url,
            }

        return await cached_call(
            "list_entities",
            {
                "entity_type": entity_type,
                "name": name,
                "limit": limit,
                "compartment_id": compartment_id,
                "profile": profile,
            },
            _fetch,
        )

    @mcp.tool(
        name="oci_logan_list_parsers",
        annotations={
            "title": "List Parsers",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
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
            profile_name = profile or "DEFAULT"
            canonical = await _call_canonical(
                "oci_logan_list_parsers",
                _canonical_args(
                    profile,
                    limit=limit,
                    format="json",
                ),
            )
            if canonical.get("error"):
                return {"success": False, "error": canonical["error"], "profile": profile_name}

            parsers = canonical.get("results", []) or []
            if parser_name:
                parsers = [
                    item
                    for item in parsers
                    if parser_name.lower() in (item.get("name") or "").lower()
                    or parser_name.lower() in (item.get("display_name") or "").lower()
                ]
            if is_system is not None:
                parsers = [item for item in parsers if bool(item.get("is_system")) is is_system]

            return {
                "success": True,
                "profile": profile_name,
                "count": len(parsers),
                "parsers": parsers[:limit],
                "canonical_server": settings.logan_http_url,
            }

        return await cached_call(
            "list_parsers",
            {
                "parser_name": parser_name,
                "is_system": is_system,
                "limit": limit,
                "profile": profile,
            },
            _fetch,
        )

    @mcp.tool(
        name="oci_logan_list_labels",
        annotations={
            "title": "List Labels",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
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
            profile_name = profile or "DEFAULT"
            canonical = await _call_canonical(
                "oci_logan_list_labels",
                _canonical_args(
                    profile,
                    limit=limit,
                    format="json",
                ),
            )
            if canonical.get("error"):
                return {"success": False, "error": canonical["error"], "profile": profile_name}

            labels = canonical.get("results", []) or []
            if label_name:
                labels = [
                    item
                    for item in labels
                    if label_name.lower() in (item.get("name") or "").lower()
                    or label_name.lower() in (item.get("display_name") or "").lower()
                ]

            return {
                "success": True,
                "profile": profile_name,
                "count": len(labels),
                "labels": labels[:limit],
                "canonical_server": settings.logan_http_url,
            }

        return await cached_call(
            "list_labels",
            {"label_name": label_name, "limit": limit, "profile": profile},
            _fetch,
        )

    @mcp.tool(
        name="oci_logan_list_groups",
        annotations={
            "title": "List Log Groups",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
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
            profile_name = profile or "DEFAULT"
            canonical = await _call_canonical(
                "oci_logan_list_log_groups",
                _canonical_args(
                    profile,
                    compartmentId=compartment_id or "",
                    limit=limit,
                    format="json",
                ),
            )
            if canonical.get("error"):
                return {"success": False, "error": canonical["error"], "profile": profile_name}

            groups = canonical.get("results", []) or []
            return {
                "success": True,
                "profile": profile_name,
                "count": len(groups),
                "log_groups": groups[:limit],
                "canonical_server": settings.logan_http_url,
            }

        return await cached_call(
            "list_log_groups",
            {"limit": limit, "compartment_id": compartment_id, "profile": profile},
            _fetch,
        )

    # =========================================================================
    # TIER 2: Security Analysis Skills
    # =========================================================================

    @mcp.tool(
        name="oci_logan_run_security_query",
        annotations={
            "title": "Run Security Query",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def run_security_query(
        query_type: str,
        time_range_minutes: int = 1440,
        compartment_id: Optional[str] = None,
        profile: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run a predefined security analysis query.

        Available query types (infrastructure):
        - failed_logins: Detect failed authentication attempts
        - privileged_operations: Track sudo/root/admin actions
        - network_anomalies: Find network/firewall warnings/errors
        - database_errors: Database-related errors
        - audit_trail: OCI audit log summary

        SKP APM queries (prefix 'skp_') — 44 APM-based detection rules:
        - skp_sqli, skp_nosql_injection, skp_xss, skp_xxe, skp_ssti, skp_rce: Injection attacks
        - skp_idor, skp_path_traversal, skp_privilege_escalation, skp_csrf: Access control
        - skp_auth_bypass, skp_brute_force, skp_jwt_manipulation, skp_credential_leak: Auth failures
        - skp_ssrf, skp_internal_recon: SSRF / network probing
        - skp_kerberoasting, skp_dcsync, skp_adcs_*: Active Directory attacks
        - skp_multi_stage, skp_c2_exfiltration, skp_service_persistence: Kill chain
        - skp_coupon_forge, skp_negative_quantity, skp_price_tampering: Business logic abuse

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
            result["description"] = _SECURITY_QUERY_DESCRIPTIONS.get(
                query_type, "SKP APM security analysis" if query_type.startswith("skp_") else "Security analysis"
            )

        return result

    @mcp.tool(
        name="oci_logan_detect_anomalies",
        annotations={
            "title": "Detect Anomalies",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
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

        baseline_query = "* | stats count as baseline_count by 'Log Source'"
        recent_query = "* | stats count as recent_count by 'Log Source'"
        baseline_result, recent_result = await asyncio.gather(
            execute_logan_query(
                query=baseline_query,
                time_range_minutes=baseline_hours * 60,
                max_count=500,
                compartment_id=compartment_id,
                profile=profile_name,
            ),
            execute_logan_query(
                query=recent_query,
                time_range_minutes=detection_hours * 60,
                max_count=500,
                compartment_id=compartment_id,
                profile=profile_name,
            ),
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
        baseline_data = {
            row[0]: int(row[1]) for row in baseline_result.get("rows", []) if len(row) >= 2
        }
        recent_data = {
            row[0]: int(row[1]) for row in recent_result.get("rows", []) if len(row) >= 2
        }

        # Normalize baseline to hourly rate
        baseline_rate = {k: v / baseline_hours for k, v in baseline_data.items()}

        for source, recent_count in recent_data.items():
            recent_rate = recent_count / detection_hours
            expected_rate = baseline_rate.get(source, 0)

            if expected_rate > 0:
                deviation = (recent_rate - expected_rate) / expected_rate
                if abs(deviation) >= (threshold_multiplier - 1):
                    anomalies.append(
                        {
                            "log_source": source,
                            "recent_count": recent_count,
                            "expected_count": int(expected_rate * detection_hours),
                            "deviation_percent": round(deviation * 100, 1),
                            "anomaly_type": "spike" if deviation > 0 else "drop",
                            "severity": "high" if abs(deviation) > 5 else "medium",
                        }
                    )
            elif recent_count > 100:
                # New high-volume source
                anomalies.append(
                    {
                        "log_source": source,
                        "recent_count": recent_count,
                        "expected_count": 0,
                        "deviation_percent": None,
                        "anomaly_type": "new_source",
                        "severity": "medium",
                    }
                )

        # Sort by severity and count
        anomalies.sort(
            key=lambda x: (-{"high": 2, "medium": 1}.get(x["severity"], 0), -x["recent_count"])
        )

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

    @mcp.tool(
        name="oci_logan_get_summary",
        annotations={
            "title": "Get Log Summary",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
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
        canonical = await _call_canonical(
            "oci_logan_get_summary",
            _canonical_args(
                profile,
                timeRange=_minutes_to_time_range(time_range_minutes),
                compartmentId=compartment_id or "",
                format="json",
            ),
        )
        if canonical.get("error"):
            return {"success": False, "error": canonical["error"], "profile": profile_name}
        canonical["success"] = True
        canonical["profile"] = profile_name
        canonical["time_range_minutes"] = time_range_minutes
        return canonical

    @mcp.tool(
        name="oci_logan_suggest_query",
        annotations={
            "title": "Suggest Query",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
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
        from .logan_ai import NL_TEMPLATES, match_nl_question

        intent_lower = intent.lower()
        suggestions = []

        # Use LoganAI templates (verified against live API)
        match = match_nl_question(intent)
        if match:
            suggestions.append(
                {
                    "query": match["query"],
                    "matched_keywords": [kw for kw in match["keywords"] if kw in intent_lower],
                    "description": match["description"],
                    "time_range": match.get("time_range", "24h"),
                }
            )

        # Also check other templates for related suggestions
        for template in NL_TEMPLATES:
            if template == match:
                continue
            score = sum(1 for kw in template["keywords"] if kw in intent_lower)
            if score > 0:
                suggestions.append(
                    {
                        "query": template["query"],
                        "matched_keywords": [
                            kw for kw in template["keywords"] if kw in intent_lower
                        ],
                        "description": template["description"],
                        "time_range": template.get("time_range", "24h"),
                    }
                )

        # Fallback suggestions
        if not suggestions:
            suggestions = [
                {
                    "query": "* | stats count as logrecords by 'Log Source' | sort -logrecords",
                    "description": "Count logs by source",
                },
                {
                    "query": f"Message like '%{intent.split()[0]}%' | stats count by 'Log Source' | sort -count",
                    "description": f"Search for '{intent.split()[0]}' in messages",
                },
            ]

        return {
            "success": True,
            "intent": intent,
            "suggestions": suggestions[:5],
            "hint": "Use oci_logan_ask to execute these queries directly with natural language",
            "syntax_help": {
                "filter": "Use = for exact, like '%pattern%' for wildcard",
                "aggregate": "Use | stats count by 'Field Name'",
                "sort": "Use | sort -field for descending",
                "limit": "Use | head N for top results",
                "important": "ALL fields with spaces MUST be single-quoted: 'Source IP' not SourceIP",
            },
        }

    @mcp.tool(
        name="oci_logan_list_active_sources",
        annotations={
            "title": "List Active Sources",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
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
        canonical = await _call_canonical(
            "oci_logan_list_active_log_sources",
            _canonical_args(
                profile,
                timeRange=_minutes_to_time_range(time_range_minutes),
                compartmentId=compartment_id or "",
                limit=200,
                format="json",
            ),
        )
        if canonical.get("error"):
            return {
                "success": False,
                "error": canonical["error"],
                "profile": profile_name,
            }

        raw_sources = canonical.get("results", []) or []
        active_sources = []
        total_logs = 0
        for item in raw_sources:
            count = int(item.get("log_count", 0) or 0)
            if count < min_count:
                continue
            active_sources.append(
                {
                    "source": item.get("display_name") or item.get("name"),
                    "count": count,
                    "has_data": item.get("has_data", count > 0),
                }
            )
            total_logs += count

        return {
            "success": True,
            "profile": profile_name,
            "time_range_minutes": time_range_minutes,
            "active_source_count": len(active_sources),
            "total_logs": total_logs,
            "sources": active_sources,
            "canonical_server": settings.logan_http_url,
        }

    @mcp.tool(
        name="oci_logan_get_entity_logs",
        annotations={
            "title": "Get Entity Logs",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
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
        canonical = await _call_canonical(
            "oci_logan_get_entity_logs",
            _canonical_args(
                profile,
                entityName=entity_name,
                timeRange=_minutes_to_time_range(time_range_minutes),
                severity=severity or "",
                limit=max_count,
                format="json",
            ),
        )
        if canonical.get("error"):
            return {"success": False, "error": canonical["error"], "profile": profile_name}
        canonical["success"] = True
        canonical["profile"] = profile_name
        canonical["entity_name"] = entity_name
        return canonical

    @mcp.tool(
        name="oci_logan_list_skills",
        annotations={
            "title": "List Logan Skills",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
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
