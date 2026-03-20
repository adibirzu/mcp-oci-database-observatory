"""Compliance scanning routes.

Provides endpoints for CIS benchmark scanning and compliance reporting.
Communicates with the OCI Compliance Scanner instance via HTTP API.
Extensible for additional compliance frameworks.
"""

import os
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from fastapi import APIRouter, HTTPException, Query

from src.core import get_logger

logger = get_logger("api.routes.compliance")

router = APIRouter(prefix="/compliance", tags=["compliance"])

SCANNER_URL = os.getenv("OCI_COMPLIANCE_SCANNER_URL", "http://130.61.112.14:8080")
SCANNER_TIMEOUT = 30

# Registry of available compliance frameworks
FRAMEWORKS = {
    "cis_oci_3.0": {
        "name": "CIS OCI Foundation Benchmark 3.0.0",
        "description": "CIS-certified assessment for OCI platform (Level 1 & 2)",
        "scanner": "oci-security-health-check-standard",
        "enabled": True,
    },
}


async def _scanner_get(path: str) -> dict[str, Any]:
    """Fetch data from the compliance scanner API."""
    try:
        async with httpx.AsyncClient(timeout=SCANNER_TIMEOUT) as client:
            resp = await client.get(f"{SCANNER_URL}{path}")
            resp.raise_for_status()
            return resp.json()
    except httpx.ConnectError:
        raise HTTPException(503, "Compliance scanner unreachable")
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, f"Scanner error: {e}")
    except Exception as e:
        raise HTTPException(502, f"Scanner communication error: {e}")


async def _scanner_post(path: str) -> dict[str, Any]:
    """Send command to the compliance scanner API."""
    try:
        async with httpx.AsyncClient(timeout=SCANNER_TIMEOUT) as client:
            resp = await client.post(f"{SCANNER_URL}{path}")
            resp.raise_for_status()
            return resp.json()
    except httpx.ConnectError:
        raise HTTPException(503, "Compliance scanner unreachable")
    except Exception as e:
        raise HTTPException(502, f"Scanner communication error: {e}")


@router.get("")
async def compliance_overview() -> dict[str, Any]:
    """Get compliance overview with latest results from all frameworks."""
    results = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "frameworks": FRAMEWORKS,
        "scanner_url": SCANNER_URL,
        "scans": {},
    }

    # Fetch latest CIS scan
    try:
        summary = await _scanner_get("/api/summary")
        results["scans"]["cis_oci_3.0"] = summary
    except HTTPException:
        results["scans"]["cis_oci_3.0"] = {"error": "Scanner unreachable"}

    return results


@router.get("/summary")
async def compliance_summary() -> dict[str, Any]:
    """Get latest CIS compliance summary with score and categories."""
    return await _scanner_get("/api/summary")


@router.get("/history")
async def compliance_history() -> dict[str, Any]:
    """Get historical scan results."""
    return await _scanner_get("/api/history")


@router.get("/report")
async def compliance_report_url(
    scan_date: Optional[str] = Query(None, description="Scan date (latest if omitted)"),
) -> dict[str, Any]:
    """Get the URL to the full HTML compliance report."""
    summary = await _scanner_get("/api/summary")
    report_file = summary.get("report_file")
    if not report_file:
        raise HTTPException(404, "No report available")

    date_dir = scan_date or "latest"
    return {
        "report_url": f"{SCANNER_URL}/reports/{date_dir}/{report_file}",
        "scan_date": summary.get("scan_date"),
        "score": summary.get("score"),
    }


@router.get("/findings")
async def compliance_findings(
    status: Optional[str] = Query(None, description="Filter: PASS or FAIL"),
    category: Optional[str] = Query(None, description="Filter by CIS section"),
) -> dict[str, Any]:
    """Get CIS compliance findings with optional filters."""
    summary = await _scanner_get("/api/summary")
    by_cat = summary.get("by_category", {})

    findings = []
    for cat, counts in by_cat.items():
        if category and category.lower() not in cat.lower():
            continue
        entry = {"category": cat, **counts, "total": counts["pass"] + counts["fail"]}
        entry["compliance_pct"] = (
            round(counts["pass"] / entry["total"] * 100) if entry["total"] else 0
        )
        if status == "PASS" and counts["fail"] == 0:
            findings.append(entry)
        elif status == "FAIL" and counts["fail"] > 0:
            findings.append(entry)
        elif status is None:
            findings.append(entry)

    return {
        "total_findings": len(findings),
        "overall_score": summary.get("score"),
        "findings": findings,
    }


@router.post("/scan")
async def trigger_scan(
    framework: str = Query("cis_oci_3.0", description="Compliance framework to run"),
) -> dict[str, Any]:
    """Trigger a new compliance scan.

    Currently supports: cis_oci_3.0
    The scan runs in background on the scanner instance (~10-15 min).
    """
    if framework not in FRAMEWORKS:
        raise HTTPException(400, f"Unknown framework: {framework}. Available: {list(FRAMEWORKS.keys())}")

    if not FRAMEWORKS[framework]["enabled"]:
        raise HTTPException(400, f"Framework {framework} is not enabled")

    return await _scanner_post("/api/scan")


@router.get("/frameworks")
async def list_frameworks() -> dict[str, Any]:
    """List available compliance frameworks and their status."""
    return {
        "frameworks": FRAMEWORKS,
        "active_scanner": SCANNER_URL,
    }
