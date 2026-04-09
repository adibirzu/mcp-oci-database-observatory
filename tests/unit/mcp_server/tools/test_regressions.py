"""Regression tests for reviewed coordinator and MCP tool fixes."""

import pytest

from src.oci_database_observatory.tools import compliance, iso42001, logan, logan_ai


class FakeMCP:
    """Minimal FastMCP stand-in that captures registered tools."""

    def __init__(self) -> None:
        self.tools = {}

    def tool(self, name: str, annotations: dict | None = None):
        del annotations

        def decorator(func):
            self.tools[name] = func
            return func

        return decorator


async def _run_uncached(tool_name, args, fn):
    del tool_name, args
    return await fn()


SAMPLE_SUMMARY = {
    "success": True,
    "score": 78,
    "clause_score": 81,
    "annex_score": 74,
    "scan_date": "2026-03-22T00:00:00Z",
    "checks": [
        {
            "control_id": "CL.5.1",
            "section": "Cl.5 Leadership",
            "title": "Governance roles assigned",
            "compliant": "Yes",
            "clause_type": "clause",
        },
        {
            "control_id": "CL.6.1",
            "section": "Cl.6 Risk Management",
            "title": "AI risk register maintained",
            "compliant": "No",
            "clause_type": "clause",
        },
        {
            "control_id": "A.9.2",
            "section": "A.9 Monitoring",
            "title": "Monitoring alerts configured",
            "compliant": "No",
            "clause_type": "annex_a",
        },
        {
            "control_id": "A.7.3",
            "section": "A.7 Data Governance",
            "title": "Dataset lineage documented",
            "compliant": "Pending",
            "clause_type": "annex_a",
        },
    ],
}


@pytest.mark.asyncio
async def test_logan_execute_query_forwards_profile_and_compartment(monkeypatch):
    """Canonical Logan query calls should preserve caller scoping."""
    fake_mcp = FakeMCP()
    logan.register_tools(fake_mcp)

    captured = {}

    async def fake_call(tool_name, arguments):
        captured["tool_name"] = tool_name
        captured["arguments"] = arguments
        return {"results": []}

    monkeypatch.setattr(logan, "_call_canonical", fake_call)
    monkeypatch.setattr(logan_ai, "fix_query_fields", lambda query: query)

    result = await fake_mcp.tools["oci_logan_execute_query"](
        query="Severity = 'error'",
        compartment_id="ocid1.compartment.oc1..demo",
        profile="OCI-DEMO",
    )

    assert captured["tool_name"] == "oci_logan_execute_query"
    assert captured["arguments"]["profile"] == "OCI-DEMO"
    assert captured["arguments"]["compartmentId"] == "ocid1.compartment.oc1..demo"
    assert result["profile"] == "OCI-DEMO"


@pytest.mark.asyncio
async def test_logan_summary_forwards_profile_and_compartment(monkeypatch):
    """Summary requests should keep profile and compartment filters."""
    fake_mcp = FakeMCP()
    logan.register_tools(fake_mcp)

    captured = {}

    async def fake_call(tool_name, arguments):
        captured["tool_name"] = tool_name
        captured["arguments"] = arguments
        return {"results": [], "summary": {"total_logs": 12}}

    monkeypatch.setattr(logan, "_call_canonical", fake_call)

    result = await fake_mcp.tools["oci_logan_get_summary"](
        time_range_minutes=60,
        compartment_id="ocid1.compartment.oc1..demo",
        profile="PRODUCTION",
    )

    assert captured["tool_name"] == "oci_logan_get_summary"
    assert captured["arguments"]["profile"] == "PRODUCTION"
    assert captured["arguments"]["compartmentId"] == "ocid1.compartment.oc1..demo"
    assert result["profile"] == "PRODUCTION"


class _MockResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _MockAsyncClient:
    def __init__(self, *args, **kwargs):
        del args, kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        del exc_type, exc, tb
        return False

    async def get(self, url):
        del url
        return _MockResponse({"error": "history unavailable"})


@pytest.mark.asyncio
async def test_compliance_history_preserves_failure(monkeypatch):
    """Compliance history should not rewrite scanner failures into success."""
    fake_mcp = FakeMCP()
    compliance.register_tools(fake_mcp)

    monkeypatch.setattr(compliance, "cached_call", _run_uncached)
    monkeypatch.setattr(compliance.httpx, "AsyncClient", _MockAsyncClient)

    result = await fake_mcp.tools["oci_compliance_get_history"]()

    assert result["success"] is False
    assert "history unavailable" in result["error"]


@pytest.mark.asyncio
async def test_iso42001_tools_derive_from_summary(monkeypatch):
    """Roadmap, gaps, frameworks, and evidence should work from summary data."""
    fake_mcp = FakeMCP()
    iso42001.register_tools(fake_mcp)

    async def fake_summary():
        return SAMPLE_SUMMARY

    monkeypatch.setattr(iso42001, "_get_summary_data", fake_summary)
    monkeypatch.setattr(iso42001, "cached_call", _run_uncached)

    roadmap = await fake_mcp.tools["oci_iso42001_get_roadmap"]()
    gaps = await fake_mcp.tools["oci_iso42001_get_gaps"]()
    frameworks = await fake_mcp.tools["oci_iso42001_get_frameworks"]()
    evidence = await fake_mcp.tools["oci_iso42001_get_evidence"]()

    assert roadmap["success"] is True
    assert roadmap["derived_from_summary"] is True
    assert any(step["id"] == "RISK" for step in roadmap["steps"])

    assert gaps["success"] is True
    assert gaps["derived_from_summary"] is True
    assert any(domain["id"] == "RISK" and domain["open"] == 1 for domain in gaps["domains"])

    assert frameworks["success"] is True
    assert frameworks["derived_from_summary"] is True
    assert frameworks["eu_ai_act"]["articles"]
    assert frameworks["nist_ai_rmf"]["functions"]

    assert evidence["success"] is True
    assert evidence["derived_from_summary"] is True
    assert evidence["count"] == len(SAMPLE_SUMMARY["checks"])


@pytest.mark.asyncio
async def test_iso42001_classification_is_local(monkeypatch):
    """Risk classification should not depend on a remote scanner route."""
    fake_mcp = FakeMCP()
    iso42001.register_tools(fake_mcp)

    class FailingAsyncClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("classification should not create an HTTP client")

    monkeypatch.setattr(iso42001.httpx, "AsyncClient", FailingAsyncClient)

    result = await fake_mcp.tools["oci_iso42001_classify_risk"](
        domain="employment_workers",
        purpose="AI system for hiring decisions",
        affects_fundamental_rights=True,
    )

    assert result["success"] is True
    assert result["derived_locally"] is True
    assert result["risk_tier"] == "high_risk"
