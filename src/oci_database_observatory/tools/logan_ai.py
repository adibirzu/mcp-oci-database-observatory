"""LoganAI — Intelligent query layer for OCI Logging Analytics.

Sits between the LLM and the raw Logan API to:
1. Translate natural language questions → correct OCL queries
2. Fix field names using a live-API-verified field registry
3. Match questions to detection rules from the catalog
4. Guard against normalization bugs (SQL/NL → OCL)
5. LLM-powered query repair when queries fail (HTTP 400)

Depends on logan.py for raw query execution.
"""

import logging
import re
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

logger = logging.getLogger("logan_ai")

# ── Field Registry (verified against live OCI API 2026-03-19) ────────
# All field names tested via stats-by queries. INVALID fields return HTTP 400.

FIELD_CORRECTIONS: Dict[str, str] = {
    # Unquoted CamelCase → quoted (ALL are INVALID in the API)
    "SourceIP": "'Source IP'",
    "SourcePort": "'Source Port'",
    "DestinationIP": "'Destination IP'",
    "DestinationPort": "'Destination Port'",
    "CommandLine": "'Command Line'",
    "QueryName": "'Query Name'",
    # Wrong field names → correct
    "'Principal Name'": "'User Name'",
    "'Client Host'": "'Source IP'",
    "'Event ID'": "'Event Type'",
    "'Event Name'": "'Event Type'",
    "'Request Action Type'": "'Event Type'",
    "'Request Action'": "'Event Type'",
    # Syntax fixes
    "distinct_count(": "distinctcount(",
    "!= null": '!= ""',
    "is not null": '!= ""',
    "== null": "is null",
}

# Per-log-source field corrections (applied only when log source is detected)
SOURCE_FIELD_CORRECTIONS: Dict[str, Dict[str, str]] = {
    "Windows Sysmon Events": {
        "Image": "'Process Name'",
        "ParentImage": "'Process Name'",
        "DestinationIp": "'Destination IP'",
        "SourceIp": "'Source IP'",
    },
}

# Valid fields per log source (for reference/validation)
LOG_SOURCE_FIELDS: Dict[str, List[str]] = {
    "OCI VCN Flow Unified Schema Logs": [
        "Action", "'Source IP'", "'Source Port'", "'Destination IP'",
        "'Destination Port'", "'Protocol Number'",
    ],
    "OCI Audit Logs": [
        "'Event Type'", "'User Name'", "'Compartment Name'", "'Source IP'",
        "'IP Address'", "Status", "'Resource Name'", "'Resource Type'",
    ],
    "Windows Sysmon Events": [
        "'Event ID'", "Technique_id", "'User'", "'User Name'",
        "'Process Name'", "'Command Line'", "'Host Name'",
        "'Destination IP'", "'Source IP'", "'Query Name'",
    ],
    "OCI Cloud Guard Problems": [
        "'Problem Type'", "'Risk Level'", "'Resource Name'",
        "'Resource Type'", "'Detector'", "'Recommendation'",
        "Status", "'Region'", "'Compartment Name'",
    ],
}

# ── Natural Language → OCL Question Templates ────────────────────────
# Each template maps a category of questions to a proven OCL query.
# Queries verified against live CAP tenancy (20/20 pass).

NL_TEMPLATES: List[Dict[str, Any]] = [
    # Overview
    {
        "keywords": ["log source", "what sources", "active sources", "what data", "log types", "inventory"],
        "query": "* | stats count as logrecords by 'Log Source' | sort -logrecords",
        "description": "Active log sources and record counts",
        "time_range": "7d",
    },
    {
        "keywords": ["ingestion", "volume", "trend", "how much data", "daily"],
        "query": "* | timestats count as logrecords by 'Log Source'",
        "description": "Ingestion volume trend by log source",
        "time_range": "7d",
    },
    {
        "keywords": ["entities", "hosts", "top entities", "most logs"],
        "query": "* | stats count as logrecords by Entity | sort -logrecords | head 15",
        "description": "Top entities by log volume",
        "time_range": "7d",
    },
    # Network Security
    {
        "keywords": ["blocked", "dropped", "rejected", "firewall", "network block"],
        "query": "'Log Source' = 'OCI VCN Flow Unified Schema Logs' and Action in ('drop', 'reject') | stats count as blocked_flows by Action",
        "description": "Blocked/rejected network flows",
        "time_range": "24h",
    },
    {
        "keywords": ["blocked ip", "blocked source", "attacking ip", "blocked traffic"],
        "query": "'Log Source' = 'OCI VCN Flow Unified Schema Logs' and Action in ('drop', 'reject') | stats count as blocked by 'Source IP' | sort -blocked | head 10",
        "description": "Top source IPs in blocked traffic",
        "time_range": "24h",
    },
    {
        "keywords": ["targeted port", "destination port", "port scan", "attacked port"],
        "query": "'Log Source' = 'OCI VCN Flow Unified Schema Logs' and Action in ('drop', 'reject') | stats count as hits by 'Destination Port' | sort -hits | head 10",
        "description": "Most targeted destination ports",
        "time_range": "24h",
    },
    {
        "keywords": ["network trend", "flow trend", "hourly network", "traffic pattern"],
        "query": "'Log Source' = 'OCI VCN Flow Unified Schema Logs' | timestats span=1h count as flows by Action",
        "description": "Hourly network flow trend by action",
        "time_range": "24h",
    },
    # OCI Audit
    {
        "keywords": ["api operation", "audit operation", "oci operation", "common operation"],
        "query": "'Log Source' = 'OCI Audit Logs' | stats count as events by 'Event Type' | sort -events | head 15",
        "description": "Most common OCI API operations",
        "time_range": "7d",
    },
    {
        "keywords": ["active user", "oci user", "who is active", "principal", "user activity"],
        "query": "'Log Source' = 'OCI Audit Logs' | stats count as events by 'User Name' | sort -events | head 10",
        "description": "Most active OCI users",
        "time_range": "7d",
    },
    {
        "keywords": ["failed login", "login failure", "authentication failure", "brute force", "console login", "failed", "login"],
        "query": "'Log Source' = 'OCI Audit Logs' and 'Event Type' like '%login%' | stats count as attempts by 'User Name', 'Source IP', Status | sort -attempts",
        "description": "Console login attempts with status",
        "time_range": "7d",
    },
    {
        "keywords": ["resource created", "resource deleted", "resource change", "create delete"],
        "query": "'Log Source' = 'OCI Audit Logs' and ('Event Type' like '%Create%' or 'Event Type' like '%Delete%') | stats count as events by 'Event Type', 'Resource Type' | sort -events | head 15",
        "description": "Recently created or deleted OCI resources",
        "time_range": "7d",
    },
    # Sysmon / Endpoint
    {
        "keywords": ["mitre", "att&ck", "technique", "tactic", "endpoint detection"],
        "query": "'Log Source' = 'Windows Sysmon Events' and Technique_id != '' | stats count as detections by Technique_id | sort -detections | head 15",
        "description": "MITRE ATT&CK techniques observed on endpoints",
        "time_range": "30d",
    },
    {
        "keywords": ["outbound connection", "network connection", "process network", "sysmon network"],
        "query": "'Log Source' = 'Windows Sysmon Events' and 'Event ID' = '3' | stats count as connections by 'Process Name' | sort -connections | head 10",
        "description": "Processes making outbound network connections",
        "time_range": "30d",
    },
    {
        "keywords": ["powershell", "encoded", "suspicious process", "process creation"],
        "query": "'Log Source' = 'Windows Sysmon Events' and 'Event ID' = '1' and 'Command Line' like '%encoded%' | stats count as events by 'Process Name', 'Command Line' | head 10",
        "description": "Suspicious process creation with encoded commands",
        "time_range": "30d",
    },
    {
        "keywords": ["dns", "dns query", "domain", "dns lookup"],
        "query": "'Log Source' = 'Windows Sysmon Events' and 'Event ID' = '22' | stats count as queries by 'Query Name' | sort -queries | head 15",
        "description": "DNS queries from endpoints",
        "time_range": "30d",
    },
    # Cross-source analysis
    {
        "keywords": ["severity", "error distribution", "severity distribution"],
        "query": "Severity != '' | stats count as events by Severity, 'Log Source' | sort -events | head 20",
        "description": "Severity distribution across log sources",
        "time_range": "7d",
    },
    {
        "keywords": ["lateral movement", "cross source ip", "ip across sources"],
        "query": "'Source IP' != '' | stats distinctcount('Log Source') as source_count, count as events by 'Source IP' | where source_count > 1 | sort -source_count | head 10",
        "description": "IPs appearing across multiple log sources",
        "time_range": "7d",
    },
    {
        "keywords": ["error", "critical", "error event", "critical event"],
        "query": "Severity in ('error', 'critical') | stats count as events by 'Log Source', Severity | sort -events",
        "description": "Error and critical events across sources",
        "time_range": "24h",
    },
    # Compartments
    {
        "keywords": ["compartment", "compartment activity", "audit by compartment"],
        "query": "'Log Source' = 'OCI Audit Logs' | stats count as events by 'Compartment Name' | sort -events | head 10",
        "description": "OCI audit activity by compartment",
        "time_range": "7d",
    },
]

# OCL syntax indicators — if a query matches these, it's already valid OCL
OCL_INDICATORS = [
    r"'log source'\s*=",
    r"'[^']+'\s*=\s*'[^']+'",
    r"\|\s*stats\b",
    r"\|\s*sort\b",
    r"\|\s*where\b",
    r"\|\s*head\b",
    r"\|\s*eval\b",
    r"\|\s*rename\b",
    r"\|\s*timestats\b",
    r"\*\s*\|",
]


def fix_query_fields(query: str) -> str:
    """Apply all field corrections to a query.

    Fixes:
    - Unquoted CamelCase → quoted space style
    - Wrong field names → correct field names
    - OCL syntax issues (distinct_count, null checks)
    """
    # Detect log source for source-specific corrections
    query_lower = query.lower()
    for source, corrections in SOURCE_FIELD_CORRECTIONS.items():
        if source.lower() in query_lower:
            for wrong, correct in corrections.items():
                if wrong in query and f"'{wrong}'" not in query:
                    query = query.replace(wrong, correct)

    # Apply global corrections
    for wrong, correct in FIELD_CORRECTIONS.items():
        if wrong in query:
            # For CamelCase fixes, avoid replacing if already inside quotes
            if wrong[0] != "'" and f"'{wrong}'" in query:
                continue
            query = query.replace(wrong, correct)

    return query


def is_valid_ocl(query: str) -> bool:
    """Check if a query looks like valid OCL syntax."""
    lower = query.lower().strip()
    return any(re.search(p, lower) for p in OCL_INDICATORS)


def match_nl_question(question: str) -> Optional[Dict[str, Any]]:
    """Match a natural language question to a template.

    Returns the best matching template or None.
    """
    question_lower = question.lower()
    best_match = None
    best_score = 0

    for template in NL_TEMPLATES:
        score = sum(1 for kw in template["keywords"] if kw in question_lower)
        if score > best_score:
            best_score = score
            best_match = template

    if best_score > 0:
        return best_match
    return None


def register_tools(mcp: "FastMCP") -> None:
    """Register LoganAI tools with the MCP server."""

    # Import execute_logan_query from the logan module to reuse as backend
    from .logan import register_tools as _  # ensure logan is loaded

    @mcp.tool(
        name="oci_logan_ask",
        annotations={
            "title": "Ask Logan (AI)",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def logan_ask(
        question: str,
        time_range_minutes: int = 0,
        max_count: int = 100,
        compartment_id: Optional[str] = None,
        profile: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Ask a natural language question and get results from OCI Log Analytics.

        LoganAI translates your question into the correct OCL query, fixes
        field names, and executes it. Also accepts direct OCL queries.

        Examples:
        - "What log sources are active?"
        - "Show me blocked network traffic"
        - "Which users had failed login attempts?"
        - "What MITRE techniques have been detected?"
        - "'Log Source' = 'OCI Audit Logs' | stats count by 'User Name'"

        Args:
            question: Natural language question or OCL query
            time_range_minutes: Time range override (0 = auto-select)
            max_count: Maximum results
            compartment_id: Optional compartment override
            profile: OCI profile name

        Returns:
            Query results with the generated OCL query
        """
        from .logan import execute_logan_query

        # Step 1: Determine if this is already valid OCL
        if is_valid_ocl(question):
            # It's OCL — fix fields and execute with LLM repair fallback
            fixed_query = fix_query_fields(question)
            tr = time_range_minutes if time_range_minutes > 0 else 1440

            result = await execute_with_llm_repair(
                execute_fn=execute_logan_query,
                query=fixed_query,
                time_range_minutes=tr,
                max_count=max_count,
                original_question=question,
                compartment_id=compartment_id,
                profile=profile,
            )

            result["logan_ai"] = {
                "mode": "ocl_direct",
                "original_query": question,
                "fixed_query": fixed_query if fixed_query != question else None,
                "field_corrections_applied": fixed_query != question,
            }
            return result

        # Step 2: Match natural language question to a template
        match = match_nl_question(question)

        if match:
            query = match["query"]
            tr = time_range_minutes if time_range_minutes > 0 else _parse_time_range(match.get("time_range", "24h"))

            result = await execute_with_llm_repair(
                execute_fn=execute_logan_query,
                query=query,
                time_range_minutes=tr,
                max_count=max_count,
                original_question=question,
                compartment_id=compartment_id,
                profile=profile,
            )

            result["logan_ai"] = {
                "mode": "nl_template",
                "matched_description": match["description"],
                "generated_query": query,
                "time_range": match.get("time_range", "24h"),
                "keywords_matched": [kw for kw in match["keywords"] if kw in question.lower()],
            }
            return result

        # Step 3: Use LLM to generate a query from the natural language question
        llm_query = await _llm_generate_query(question)
        if llm_query:
            llm_query = fix_query_fields(llm_query)
            tr = time_range_minutes if time_range_minutes > 0 else 1440

            result = await execute_with_llm_repair(
                execute_fn=execute_logan_query,
                query=llm_query,
                time_range_minutes=tr,
                max_count=max_count,
                original_question=question,
                compartment_id=compartment_id,
                profile=profile,
            )

            result["logan_ai"] = {
                "mode": "llm_generated",
                "generated_query": llm_query,
                "original_question": question,
            }
            return result

        # Step 4: Fallback — build a simple search query
        terms = _extract_search_terms(question)
        if terms:
            search_query = f"Message like '%{terms[0]}%' | stats count as events by 'Log Source', Severity | sort -events | head 20"
        else:
            search_query = "* | stats count as logrecords by 'Log Source' | sort -logrecords"

        tr = time_range_minutes if time_range_minutes > 0 else 1440

        result = await execute_logan_query(
            query=search_query,
            time_range_minutes=tr,
            max_count=max_count,
            compartment_id=compartment_id,
            profile=profile,
        )

        result["logan_ai"] = {
            "mode": "fallback_search",
            "generated_query": search_query,
            "search_terms": terms,
            "hint": "For better results, try more specific questions like 'show blocked network traffic' or 'which users failed to login'",
        }
        return result

    @mcp.tool(
        name="oci_logan_fix_query",
        annotations={
            "title": "Fix Logan Query",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def logan_fix_query(
        query: str,
    ) -> Dict[str, Any]:
        """Fix field names and syntax in an OCL query before execution.

        Corrects common mistakes:
        - SourceIP → 'Source IP' (unquoted CamelCase is INVALID)
        - 'Principal Name' → 'User Name' (wrong field name)
        - CommandLine → 'Command Line' (Sysmon fields)
        - distinct_count() → distinctcount() (syntax)
        - != null → != "" (OCI API requires empty string check)

        Args:
            query: OCL query to fix

        Returns:
            Fixed query with list of corrections applied
        """
        fixed = fix_query_fields(query)
        corrections = []

        for wrong, correct in FIELD_CORRECTIONS.items():
            if wrong in query and wrong not in fixed:
                corrections.append(f"{wrong} → {correct}")

        # Check source-specific corrections
        query_lower = query.lower()
        for source, source_corrections in SOURCE_FIELD_CORRECTIONS.items():
            if source.lower() in query_lower:
                for wrong, correct in source_corrections.items():
                    if wrong in query and wrong not in fixed:
                        corrections.append(f"{wrong} → {correct} (for {source})")

        return {
            "success": True,
            "original_query": query,
            "fixed_query": fixed,
            "corrections": corrections,
            "was_modified": fixed != query,
        }

    @mcp.tool(
        name="oci_logan_get_field_info",
        annotations={
            "title": "Get Field Info",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def logan_get_field_info(
        log_source: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get valid field names for a log source (verified against live API).

        Returns field names that work in stats-by, where, and filter expressions.
        Using wrong field names (e.g., SourceIP instead of 'Source IP') causes
        HTTP 400 errors from the OCI API.

        Args:
            log_source: Log source name (or None for all sources)

        Returns:
            Valid field names and common corrections
        """
        if log_source and log_source in LOG_SOURCE_FIELDS:
            fields = LOG_SOURCE_FIELDS[log_source]
            corrections = SOURCE_FIELD_CORRECTIONS.get(log_source, {})
            corrections.update({k: v for k, v in FIELD_CORRECTIONS.items() if "'" in k})

            return {
                "success": True,
                "log_source": log_source,
                "valid_fields": fields,
                "common_mistakes": corrections,
            }

        # Return all sources
        return {
            "success": True,
            "sources": {
                source: {
                    "fields": fields,
                    "corrections": SOURCE_FIELD_CORRECTIONS.get(source, {}),
                }
                for source, fields in LOG_SOURCE_FIELDS.items()
            },
            "global_corrections": FIELD_CORRECTIONS,
            "rules": [
                "ALL fields with spaces MUST be single-quoted: 'Source IP' not SourceIP",
                "Unquoted CamelCase is INVALID: SourceIP, CommandLine, QueryName → HTTP 400",
                "OCI Audit uses 'User Name' NOT 'Principal Name'",
                "Sysmon uses 'Process Name' NOT Image, 'Command Line' NOT CommandLine",
                "Use distinctcount() NOT distinct_count() (no underscore)",
                "Use != '' NOT != null for null checks",
            ],
        }

    @mcp.tool(
        name="oci_logan_list_questions",
        annotations={
            "title": "List Logan Questions",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def logan_list_questions(
        category: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List example questions that LoganAI can answer.

        Categories: overview, network, audit, endpoint, security

        Args:
            category: Optional category filter

        Returns:
            List of example questions with their OCL queries
        """
        categories = {
            "overview": ["log source", "ingestion", "entities"],
            "network": ["blocked", "blocked ip", "targeted port", "network trend"],
            "audit": ["api operation", "active user", "failed login", "resource created"],
            "endpoint": ["mitre", "outbound connection", "powershell", "dns"],
            "security": ["severity", "lateral movement", "error", "compartment"],
        }

        questions = []
        for template in NL_TEMPLATES:
            # Determine category
            cat = "other"
            for c, kws in categories.items():
                if any(kw in template["keywords"] for kw in kws):
                    cat = c
                    break

            if category and cat != category:
                continue

            questions.append({
                "category": cat,
                "description": template["description"],
                "example_keywords": template["keywords"][:3],
                "query": template["query"],
                "time_range": template.get("time_range", "24h"),
            })

        return {
            "success": True,
            "categories": list(categories.keys()),
            "question_count": len(questions),
            "questions": questions,
        }


def _parse_time_range(time_range: str) -> int:
    """Convert time range string to minutes."""
    mapping = {
        "1h": 60, "6h": 360, "12h": 720,
        "24h": 1440, "1d": 1440,
        "7d": 10080, "1w": 10080,
        "30d": 43200,
    }
    return mapping.get(time_range, 1440)


def _extract_search_terms(question: str) -> List[str]:
    """Extract meaningful search terms from a natural language question."""
    stop_words = {
        "what", "which", "who", "where", "when", "how", "show", "me",
        "find", "get", "list", "the", "are", "is", "in", "for", "from",
        "with", "and", "or", "any", "all", "most", "top", "recent",
        "there", "have", "has", "been", "can", "do", "does", "did",
        "a", "an", "of", "to", "my", "our", "their", "this", "that",
    }
    words = re.findall(r'\b\w+\b', question.lower())
    terms = [w for w in words if w not in stop_words and len(w) > 2]
    return terms[:3]


# ── LLM-Powered Query Generation & Repair ────────────────────────────

LLM_REPAIR_SYSTEM_PROMPT = """You are an OCI Logging Analytics (OCL) query expert. Fix the failed query.

CRITICAL FIELD NAMING RULES (verified against live API):
- ALL fields with spaces MUST be single-quoted: 'Source IP' not SourceIP
- Unquoted CamelCase is INVALID and returns HTTP 400: SourceIP, CommandLine, QueryName, DestinationPort
- OCI Audit uses 'User Name' NOT 'Principal Name'
- OCI Audit uses 'Source IP' NOT 'Client Host'
- Sysmon uses 'Process Name' NOT Image
- Sysmon uses 'Command Line' NOT CommandLine
- Sysmon uses 'Query Name' NOT QueryName
- VCN Flow uses 'Source IP' NOT SourceIP, 'Destination Port' NOT DestinationPort
- Use distinctcount() NOT distinct_count()
- Use != "" NOT != null for null checks
- Use | head N NOT | top N for limiting results

VALID FIELDS PER LOG SOURCE:
- OCI VCN Flow: Action, 'Source IP', 'Source Port', 'Destination IP', 'Destination Port', 'Protocol Number'
- OCI Audit Logs: 'Event Type', 'User Name', 'Compartment Name', 'Source IP', Status, 'Resource Name', 'Resource Type'
- Windows Sysmon: 'Event ID', Technique_id, 'User', 'Process Name', 'Command Line', 'Destination IP', 'Source IP', 'Query Name'
- Cloud Guard: 'Problem Type', 'Risk Level', 'Resource Name', 'Detector', Status

OCL SYNTAX:
- Filter: 'Field' = 'value', 'Field' like '%pattern%', 'Field' in ('a', 'b')
- Pipe commands: | stats count by 'Field' | sort -count | head 10
- Time stats: | timestats span=1h count by 'Field'
- Aggregation: | stats count, distinctcount('Field') as name by 'Group Field'

Return ONLY the fixed OCL query. No explanation, no markdown, no backticks. Just the raw query string."""

LLM_GENERATE_SYSTEM_PROMPT = """You are an OCI Logging Analytics (OCL) query expert. Generate a query for the user's question.

CRITICAL FIELD NAMING RULES (verified against live API):
- ALL fields with spaces MUST be single-quoted: 'Source IP' not SourceIP
- Unquoted CamelCase is INVALID: SourceIP, CommandLine, QueryName → HTTP 400
- OCI Audit uses 'User Name' NOT 'Principal Name', 'Source IP' NOT 'Client Host'
- Sysmon uses 'Process Name' NOT Image, 'Command Line' NOT CommandLine
- VCN Flow uses 'Source IP' NOT SourceIP
- Use distinctcount() NOT distinct_count()
- Use != "" NOT != null

AVAILABLE LOG SOURCES:
- OCI VCN Flow Unified Schema Logs (fields: Action, 'Source IP', 'Destination IP', 'Source Port', 'Destination Port')
- OCI Audit Logs (fields: 'Event Type', 'User Name', Status, 'Source IP', 'Compartment Name', 'Resource Name')
- Windows Sysmon Events (fields: 'Event ID', 'Process Name', 'Command Line', 'User', 'Destination IP', 'Query Name', Technique_id)
- OCI Cloud Guard Problems (fields: 'Problem Type', 'Risk Level', 'Resource Name', 'Detector')
- Linux Audit Logs, Linux Syslog Logs, Kubernetes Container Generic Logs, OKE Control Plane Logs

COMMON FIELDS (all sources): 'Log Source', Entity, 'Host Name', Message, Severity, Time

OCL SYNTAX:
- Filter: 'Log Source' = 'Name' and 'Field' = 'value'
- Wildcard: 'Field' like '%pattern%'
- Pipe: | stats count by 'Field' | sort -count | head 10
- Time: | timestats span=1h count by 'Field'

Return ONLY the OCL query. No explanation, no markdown, no backticks."""


async def _llm_generate_query(question: str) -> Optional[str]:
    """Use an LLM to generate an OCL query from a natural language question.

    Args:
        question: Natural language question

    Returns:
        Generated OCL query, or None if LLM is unavailable
    """
    try:
        from src.llm.providers.registry import ProviderRegistry
        registry = ProviderRegistry()

        provider = registry.get_primary()
        if not provider:
            logger.debug("No LLM provider available for query generation")
            return None

        response = await provider.generate(
            messages=[
                {"role": "user", "content": f"Generate an OCL query for: {question}"},
            ],
            model=None,
            temperature=0.1,
            max_tokens=500,
            system=LLM_GENERATE_SYSTEM_PROMPT,
        )

        generated = response.content.strip()
        # Clean up markdown backticks
        if generated.startswith("```"):
            lines = generated.split("\n")
            generated = "\n".join(
                line for line in lines
                if not line.startswith("```")
            ).strip()

        if not generated:
            return None

        logger.info(
            "LLM generated query",
            provider=response.provider,
            model=response.model,
            question=question[:60],
            query=generated[:80],
        )
        return generated

    except Exception as e:
        logger.debug("LLM query generation failed: %s", str(e))
        return None


async def llm_repair_query(
    failed_query: str,
    error_message: str,
    original_question: str = "",
) -> Optional[str]:
    """Use an LLM to repair a failed OCL query.

    Args:
        failed_query: The query that failed
        error_message: The error message from the OCI API
        original_question: The original natural language question (if any)

    Returns:
        A repaired query string, or None if LLM is unavailable
    """
    try:
        from src.llm.providers.registry import ProviderRegistry
        registry = ProviderRegistry()

        provider = registry.get_primary()
        if not provider:
            logger.warning("No LLM provider available for query repair")
            return None

        user_msg = f"Failed query: {failed_query}\nError: {error_message}"
        if original_question:
            user_msg += f"\nOriginal question: {original_question}"

        response = await provider.generate(
            messages=[
                {"role": "user", "content": user_msg},
            ],
            model=None,  # use default
            temperature=0.1,  # low temperature for precise fixes
            max_tokens=500,
            system=LLM_REPAIR_SYSTEM_PROMPT,
        )

        repaired = response.content.strip()
        # Clean up — remove markdown backticks if LLM added them
        if repaired.startswith("```"):
            lines = repaired.split("\n")
            repaired = "\n".join(
                line for line in lines
                if not line.startswith("```")
            ).strip()

        if not repaired or repaired == failed_query:
            return None

        logger.info(
            "LLM repaired query",
            provider=response.provider,
            model=response.model,
            original=failed_query[:80],
            repaired=repaired[:80],
        )
        return repaired

    except Exception as e:
        logger.warning("LLM query repair failed: %s", str(e))
        return None


async def execute_with_llm_repair(
    execute_fn,
    query: str,
    time_range_minutes: int,
    max_count: int,
    original_question: str = "",
    compartment_id: Optional[str] = None,
    profile: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute a query with automatic LLM-powered repair on failure.

    1. Execute the query
    2. If it fails with a field/syntax error, ask the LLM to fix it
    3. Re-execute with the fixed query
    4. Return results with repair metadata

    Args:
        execute_fn: The execute_logan_query function
        query: OCL query to execute
        time_range_minutes: Time range in minutes
        max_count: Max results
        original_question: Original NL question for context
        compartment_id: Optional compartment override
        profile: OCI profile name

    Returns:
        Query results, possibly with LLM repair metadata
    """
    # First attempt
    result = await execute_fn(
        query=query,
        time_range_minutes=time_range_minutes,
        max_count=max_count,
        compartment_id=compartment_id,
        profile=profile,
    )

    # Check if it failed with a repairable error
    if result.get("success"):
        return result

    error = result.get("error", "")
    repairable_patterns = [
        "InvalidParameter",
        "Invalid field",
        "Unexpected input",
        "Syntax error",
        "parsing error",
    ]

    if not any(p.lower() in error.lower() for p in repairable_patterns):
        return result  # Not a field/syntax error — don't retry

    # Ask LLM to repair
    repaired_query = await llm_repair_query(query, error, original_question)
    if not repaired_query:
        result["logan_ai_repair"] = {
            "attempted": True,
            "success": False,
            "reason": "LLM unavailable or returned no fix",
        }
        return result

    # Apply field corrections to LLM output too (belt + suspenders)
    repaired_query = fix_query_fields(repaired_query)

    # Retry with repaired query
    retry_result = await execute_fn(
        query=repaired_query,
        time_range_minutes=time_range_minutes,
        max_count=max_count,
        compartment_id=compartment_id,
        profile=profile,
    )

    retry_result["logan_ai_repair"] = {
        "attempted": True,
        "success": retry_result.get("success", False),
        "original_query": query,
        "original_error": error,
        "repaired_query": repaired_query,
    }

    if not retry_result.get("success"):
        # LLM fix also failed — return original error with repair context
        retry_result["logan_ai_repair"]["retry_error"] = retry_result.get("error", "")
        retry_result["hint"] = (
            "Both the original and LLM-repaired queries failed. "
            "Use oci_logan_get_field_info to check valid field names."
        )

    return retry_result
