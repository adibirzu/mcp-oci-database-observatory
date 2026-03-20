"""ISO/IEC 42001:2023 AI Management System compliance tools v2.

MCP tools for querying ISO 42001 AI governance compliance results
including cross-framework mapping, certification roadmap, and gap analysis.
Communicates with the OCI Compliance Scanner instance.
"""

import os
from typing import Any, Dict, Optional, TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

from ..cache import cached_call

SCANNER_URL = os.getenv("OCI_COMPLIANCE_SCANNER_URL", "http://130.61.112.14:8080")


async def _scanner_get(path: str) -> Dict[str, Any]:
    """Fetch data from the scanner HTTP API."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{SCANNER_URL}{path}")
            resp.raise_for_status()
            data = resp.json()
            data["success"] = "error" not in data
            return data
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _scanner_post(path: str) -> Dict[str, Any]:
    """POST to the scanner HTTP API."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{SCANNER_URL}{path}")
            resp.raise_for_status()
            data = resp.json()
            data["success"] = True
            return data
    except Exception as e:
        return {"success": False, "error": str(e)}


def register_tools(mcp: "FastMCP") -> None:
    """Register ISO 42001 compliance tools."""

    @mcp.tool(
        name="oci_iso42001_get_summary",
        annotations={
            "title": "Get ISO 42001 AI Compliance Summary",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def get_iso42001_summary() -> Dict[str, Any]:
        """Get latest ISO/IEC 42001:2023 AI governance compliance results.

        Returns score and breakdown by section, covering both management
        system Clauses 4-10 and Annex A normative controls (A.2-A.10).
        v2 scanner runs 65 checks total.

        Returns:
            ISO 42001 compliance summary with clause/annex scores and per-section breakdown
        """
        async def _fetch():
            return await _scanner_get("/api/iso42001/summary")

        return await cached_call("get_iso42001_summary", {}, _fetch)

    @mcp.tool(
        name="oci_iso42001_get_findings",
        annotations={
            "title": "Get ISO 42001 Failed Checks",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def get_iso42001_findings(
        section: Optional[str] = None,
        clause_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get ISO 42001 compliance findings, optionally filtered.

        Args:
            section: Filter by section (e.g. 'A.7', 'Cl.9', 'Lifecycle', 'Data')
            clause_type: Filter by type: 'clause' (Clauses 4-10) or 'annex_a' (Annex A)

        Returns:
            List of failed and passed checks with details, cross-framework refs
        """
        data = await _scanner_get("/api/iso42001/summary")
        if not data.get("success"):
            return data

        checks = data.get("checks", [])
        if section:
            checks = [c for c in checks if section.lower() in c.get("section", "").lower()]
        if clause_type:
            checks = [c for c in checks if c.get("clause_type") == clause_type]

        return {
            "success": True,
            "score": data.get("score"),
            "clause_score": data.get("clause_score"),
            "annex_score": data.get("annex_score"),
            "total": len(checks),
            "failed": [c for c in checks if c["compliant"] == "No"],
            "passed": [c for c in checks if c["compliant"] == "Yes"],
        }

    @mcp.tool(
        name="oci_iso42001_run_scan",
        annotations={
            "title": "Trigger ISO 42001 AI Scan",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    async def run_iso42001_scan() -> Dict[str, Any]:
        """Trigger an ISO 42001 AI governance compliance scan.

        v2 scanner runs 65 checks: 20 management system Clauses (4-10) and
        45 Annex A normative controls. Also generates cross-framework mapping
        (EU AI Act + NIST AI RMF), certification roadmap, and gap analysis.
        Takes ~2-5 minutes.

        Returns:
            Scan trigger status
        """
        return await _scanner_post("/api/iso42001/scan")

    @mcp.tool(
        name="oci_iso42001_get_roadmap",
        annotations={
            "title": "Get ISO 42001 Certification Roadmap",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def get_iso42001_roadmap() -> Dict[str, Any]:
        """Get 12-step ISO 42001 certification roadmap with progress tracking.

        Returns readiness percentage, phase breakdown (Preparation,
        Implementation, Verification, Certification), and per-step
        progress based on automated check results.

        Returns:
            Certification roadmap with step-by-step progress and evidence needed
        """
        async def _fetch():
            return await _scanner_get("/api/iso42001/roadmap")

        return await cached_call("get_iso42001_roadmap", {}, _fetch)

    @mcp.tool(
        name="oci_iso42001_get_gaps",
        annotations={
            "title": "Get ISO 42001 Gap Analysis",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def get_iso42001_gaps(
        domain: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get ISO 42001 gap analysis across 12 domains.

        Domains: GOV (governance), SCOPE (context), RISK (assessment),
        INVENTORY (AI systems), LIFECYCLE, DATA, ACCESS, TRANSPARENCY,
        MONITORING, THIRDPARTY, PERFORMANCE, IMPROVEMENT.

        Args:
            domain: Filter by domain ID (e.g. 'GOV', 'DATA', 'RISK')

        Returns:
            Gap analysis with open/closed/manual items per domain
        """
        data = await _scanner_get("/api/iso42001/gaps")
        if not data.get("success"):
            return data

        if domain:
            domains = [d for d in data.get("domains", [])
                       if d.get("id", "").upper() == domain.upper()]
            data["domains"] = domains

        return data

    @mcp.tool(
        name="oci_iso42001_get_frameworks",
        annotations={
            "title": "Get Cross-Framework Mapping",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def get_iso42001_frameworks() -> Dict[str, Any]:
        """Get cross-framework mapping: ISO 42001 to EU AI Act and NIST AI RMF.

        Returns EU AI Act readiness score, risk tier definitions,
        enforcement timeline, article coverage, and NIST AI RMF
        function scores (GOVERN, MAP, MEASURE, MANAGE).

        Returns:
            Unified cross-framework compliance matrix
        """
        async def _fetch():
            return await _scanner_get("/api/iso42001/frameworks")

        return await cached_call("get_iso42001_frameworks", {}, _fetch)

    @mcp.tool(
        name="oci_iso42001_get_evidence",
        annotations={
            "title": "Get Evidence Register",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def get_iso42001_evidence() -> Dict[str, Any]:
        """Get evidence register with automated and manual evidence tracking.

        Returns structured evidence entries for each control: control_id,
        claim, owner, source, status (verified/finding_open/pending),
        evidence_type (automated/manual), review_date, expiry.

        Returns:
            Evidence register with automated scan evidence and manual placeholders
        """
        return await _scanner_get("/api/iso42001/evidence")

    @mcp.tool(
        name="oci_iso42001_classify_risk",
        annotations={
            "title": "Classify EU AI Act Risk Tier",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def classify_iso42001_risk(
        domain: str = "other",
        purpose: str = "",
        uses_biometric: bool = False,
        public_sector: bool = False,
        safety_component: bool = False,
        affects_fundamental_rights: bool = False,
    ) -> Dict[str, Any]:
        """Classify an AI system's EU AI Act risk tier using deterministic rules.

        Decision sequence: Art.5 prohibited -> Art.6+Annex III high-risk ->
        Art.50 transparency -> minimal risk. Always requires human legal review.

        Args:
            domain: High-risk domain (e.g. 'employment_workers', 'law_enforcement',
                    'critical_infrastructure', 'education_vocational', 'essential_services')
            purpose: Description of AI system purpose
            uses_biometric: Whether system uses biometric data
            public_sector: Whether system is used in public sector
            safety_component: Whether system is a safety component
            affects_fundamental_rights: Whether system affects fundamental rights

        Returns:
            Risk tier classification with legal basis, required controls, confidence
        """
        payload = {
            "domain": domain, "purpose": purpose,
            "uses_biometric": uses_biometric, "public_sector": public_sector,
            "safety_component": safety_component,
            "affects_fundamental_rights": affects_fundamental_rights,
            "prohibited_indicators": [],
            "transparency_triggers": [],
        }
        return await _scanner_post_json("/api/iso42001/classify", payload)


async def _scanner_post_json(path: str, payload: dict) -> Dict[str, Any]:
    """POST JSON to the scanner HTTP API."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{SCANNER_URL}{path}", json=payload)
            resp.raise_for_status()
            data = resp.json()
            data["success"] = True
            return data
    except Exception as e:
        return {"success": False, "error": str(e)}
