"""OCI Compliance scanning tools.

Provides MCP tools for CIS benchmark scanning and compliance reporting.
Communicates with the OCI Compliance Scanner instance via HTTP API.
Extensible for additional compliance frameworks.
"""

import os
from typing import TYPE_CHECKING, Any, Dict, Optional

import httpx

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

from ..cache import cached_call

SCANNER_URL = os.getenv("OCI_COMPLIANCE_SCANNER_URL", "http://130.61.112.14:8080")


def register_tools(mcp: "FastMCP") -> None:
    """Register compliance tools with the MCP server."""

    async def _scanner_get(path: str) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(f"{SCANNER_URL}{path}")
                resp.raise_for_status()
                data = resp.json()
                data["success"] = "error" not in data
                return data
        except Exception as e:
            return {"success": False, "error": f"Scanner unreachable: {e}"}

    @mcp.tool(
        name="oci_compliance_get_latest",
        annotations={
            "title": "Get Compliance Summary",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def get_compliance_latest() -> Dict[str, Any]:
        """Get latest CIS OCI compliance scan results.

        Returns score, pass/fail counts, and breakdown by category.
        The scan runs daily against the tenancy.

        Returns:
            Compliance summary with score and category breakdown
        """

        async def _fetch():
            data = await _scanner_get("/api/summary")
            if not data.get("success"):
                return data
            data["success"] = True
            data["framework"] = "CIS OCI Foundation Benchmark 3.0.0"
            return data

        return await cached_call(
            "get_compliance_latest",
            {},
            _fetch,
        )

    @mcp.tool(
        name="oci_compliance_get_findings",
        annotations={
            "title": "Get Compliance Findings",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def get_compliance_findings(
        category: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get CIS compliance findings by category.

        Args:
            category: Filter by section (e.g. 'IAM', 'Networking', 'Logging')

        Returns:
            Detailed findings per category
        """
        data = await _scanner_get("/api/summary")
        if not data.get("success"):
            return {"success": False, "error": data.get("error", "Scanner returned an error")}

        by_cat = data.get("by_category", {})
        findings = []
        for cat, counts in by_cat.items():
            if category and category.lower() not in cat.lower():
                continue
            total = counts["pass"] + counts["fail"]
            findings.append(
                {
                    "category": cat,
                    "passed": counts["pass"],
                    "failed": counts["fail"],
                    "total": total,
                    "compliance_pct": round(counts["pass"] / total * 100) if total else 0,
                }
            )

        findings.sort(key=lambda x: x["compliance_pct"])
        return {
            "success": True,
            "score": data.get("score"),
            "finding_count": len(findings),
            "findings": findings,
        }

    @mcp.tool(
        name="oci_compliance_run_scan",
        annotations={
            "title": "Trigger Compliance Scan",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    async def run_compliance_scan() -> Dict[str, Any]:
        """Trigger a new CIS compliance scan.

        The scan runs in background on the scanner instance (~10-15 min).
        Use oci_compliance_get_latest to check results after completion.

        Returns:
            Scan trigger status
        """
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(f"{SCANNER_URL}/api/scan")
                resp.raise_for_status()
                data = resp.json()
                data["success"] = True
                return data
        except Exception as e:
            return {"success": False, "error": f"Failed to trigger scan: {e}"}

    @mcp.tool(
        name="oci_compliance_get_history",
        annotations={
            "title": "Get Compliance History",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def get_compliance_history() -> Dict[str, Any]:
        """Get historical compliance scan results.

        Returns:
            List of past scans with dates and scores
        """

        async def _fetch():
            data = await _scanner_get("/api/history")
            if not data.get("success"):
                return data
            data["success"] = True
            return data

        return await cached_call(
            "get_compliance_history",
            {},
            _fetch,
        )
