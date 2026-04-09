"""ISO/IEC 42001:2023 AI Management System compliance tools v2.

MCP tools for querying ISO 42001 AI governance compliance results
including cross-framework mapping, certification roadmap, and gap analysis.
Communicates with the OCI Compliance Scanner instance.
"""

import os
from collections import defaultdict
from typing import TYPE_CHECKING, Any, Dict, Optional

import httpx

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

from ..cache import cached_call

SCANNER_URL = os.getenv("OCI_COMPLIANCE_SCANNER_URL", "http://130.61.112.14:8080")
SUMMARY_DERIVED_NOTE = (
    "Derived locally from /api/iso42001/summary because the configured "
    "scanner does not expose dedicated ISO 42001 roadmap/gap/framework/"
    "evidence/classification endpoints."
)

DOMAIN_DEFINITIONS = [
    {
        "id": "GOV",
        "name": "Governance",
        "phase": "Preparation",
        "keywords": (
            "governance",
            "leadership",
            "oversight",
            "policy",
            "accountability",
            "roles",
        ),
        "evidence": ["AI governance policy", "assigned oversight roles"],
    },
    {
        "id": "SCOPE",
        "name": "Context and Scope",
        "phase": "Preparation",
        "keywords": (
            "scope",
            "context",
            "boundary",
            "interested party",
            "objective",
        ),
        "evidence": ["AI management system scope", "stakeholder register"],
    },
    {
        "id": "RISK",
        "name": "Risk Assessment",
        "phase": "Preparation",
        "keywords": (
            "risk",
            "impact",
            "assessment",
            "hazard",
            "mitigation",
        ),
        "evidence": ["risk register", "impact assessment"],
    },
    {
        "id": "INVENTORY",
        "name": "AI System Inventory",
        "phase": "Implementation",
        "keywords": (
            "inventory",
            "register",
            "use case",
            "system list",
            "asset",
        ),
        "evidence": ["AI system inventory", "use-case catalog"],
    },
    {
        "id": "LIFECYCLE",
        "name": "Lifecycle Controls",
        "phase": "Implementation",
        "keywords": (
            "lifecycle",
            "design",
            "development",
            "deployment",
            "validation",
            "testing",
        ),
        "evidence": ["SDLC controls", "validation records"],
    },
    {
        "id": "DATA",
        "name": "Data and Governance",
        "phase": "Implementation",
        "keywords": (
            "data",
            "dataset",
            "privacy",
            "quality",
            "retention",
            "lineage",
        ),
        "evidence": ["data quality checks", "dataset lineage"],
    },
    {
        "id": "ACCESS",
        "name": "Access and Security",
        "phase": "Implementation",
        "keywords": (
            "access",
            "identity",
            "authentication",
            "authorization",
            "security",
            "privilege",
        ),
        "evidence": ["access reviews", "segregation of duties"],
    },
    {
        "id": "TRANSPARENCY",
        "name": "Transparency",
        "phase": "Implementation",
        "keywords": (
            "transparency",
            "explainability",
            "documentation",
            "disclosure",
            "traceability",
        ),
        "evidence": ["model cards", "user disclosures"],
    },
    {
        "id": "MONITORING",
        "name": "Monitoring and Incidents",
        "phase": "Verification",
        "keywords": (
            "monitoring",
            "logging",
            "incident",
            "alert",
            "observability",
            "drift",
        ),
        "evidence": ["monitoring dashboards", "incident procedures"],
    },
    {
        "id": "THIRDPARTY",
        "name": "Third-Party Management",
        "phase": "Verification",
        "keywords": (
            "supplier",
            "vendor",
            "third-party",
            "outsourcing",
            "procurement",
        ),
        "evidence": ["supplier due diligence", "contract controls"],
    },
    {
        "id": "PERFORMANCE",
        "name": "Performance and Robustness",
        "phase": "Certification",
        "keywords": (
            "performance",
            "accuracy",
            "robustness",
            "resilience",
            "benchmark",
        ),
        "evidence": ["performance benchmarks", "robustness tests"],
    },
    {
        "id": "IMPROVEMENT",
        "name": "Continuous Improvement",
        "phase": "Certification",
        "keywords": (
            "improvement",
            "audit",
            "review",
            "corrective",
            "nonconformity",
        ),
        "evidence": ["internal audits", "corrective action log"],
    },
]
DOMAIN_INDEX = {domain["id"]: domain for domain in DOMAIN_DEFINITIONS}

NIST_RMF_FUNCTIONS = {
    "GOVERN": ["GOV", "SCOPE", "THIRDPARTY", "IMPROVEMENT"],
    "MAP": ["INVENTORY", "RISK", "TRANSPARENCY"],
    "MEASURE": ["DATA", "PERFORMANCE", "MONITORING"],
    "MANAGE": ["ACCESS", "LIFECYCLE", "IMPROVEMENT"],
}

EU_AI_ACT_CROSSWALK = [
    {
        "article": "Art. 9",
        "topic": "Risk management system",
        "domains": ["RISK", "LIFECYCLE", "MONITORING"],
    },
    {
        "article": "Art. 10",
        "topic": "Data and data governance",
        "domains": ["DATA", "INVENTORY"],
    },
    {
        "article": "Art. 13",
        "topic": "Transparency and information",
        "domains": ["TRANSPARENCY", "INVENTORY"],
    },
    {
        "article": "Art. 14",
        "topic": "Human oversight",
        "domains": ["GOV", "ACCESS", "MONITORING"],
    },
    {
        "article": "Art. 15",
        "topic": "Accuracy, robustness, and cybersecurity",
        "domains": ["PERFORMANCE", "ACCESS", "MONITORING"],
    },
    {
        "article": "Art. 17",
        "topic": "Quality management system",
        "domains": ["GOV", "SCOPE", "THIRDPARTY", "IMPROVEMENT"],
    },
]

HIGH_RISK_DOMAINS = {
    "critical_infrastructure",
    "education_vocational",
    "employment_workers",
    "essential_services",
    "justice_democracy",
    "law_enforcement",
    "migration_border",
}
PROHIBITED_KEYWORDS = {
    "social scoring": "Art. 5 prohibited social scoring",
    "exploit vulnerabilities": "Art. 5 prohibited exploitation of vulnerabilities",
    "untargeted facial recognition": "Art. 5 prohibited untargeted facial image scraping",
}
TRANSPARENCY_KEYWORDS = {
    "chatbot": "Art. 50 chatbot disclosure",
    "deepfake": "Art. 50 synthetic content disclosure",
    "emotion recognition": "Art. 50 emotion recognition notice",
}


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


async def _fetch_summary() -> Dict[str, Any]:
    return await _scanner_get("/api/iso42001/summary")


async def _get_summary_data() -> Dict[str, Any]:
    return await cached_call("get_iso42001_summary", {}, _fetch_summary)


def _is_compliant(check: Dict[str, Any]) -> bool:
    value = check.get("compliant")
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"yes", "true", "pass", "passed", "compliant"}


def _is_manual(check: Dict[str, Any]) -> bool:
    status = str(check.get("status", "")).strip().lower()
    compliant = str(check.get("compliant", "")).strip().lower()
    return status in {"manual", "pending", "needs_manual_review"} or compliant in {
        "manual",
        "pending",
        "n/a",
        "na",
    }


def _check_identifier(check: Dict[str, Any], fallback_index: int = 0) -> str:
    return str(
        check.get("control_id")
        or check.get("id")
        or check.get("check_id")
        or check.get("section")
        or f"ISO42001-{fallback_index}"
    )


def _check_title(check: Dict[str, Any]) -> str:
    return str(
        check.get("title")
        or check.get("name")
        or check.get("claim")
        or check.get("description")
        or check.get("section")
        or "Unnamed control"
    )


def _check_text(check: Dict[str, Any]) -> str:
    parts = [
        check.get("section"),
        check.get("title"),
        check.get("name"),
        check.get("description"),
        check.get("claim"),
        check.get("control_id"),
        check.get("domain"),
    ]
    return " ".join(str(part).lower() for part in parts if part)


def _infer_domain_id(check: Dict[str, Any]) -> str:
    explicit = str(check.get("domain_id") or check.get("domain") or "").upper()
    if explicit in DOMAIN_INDEX:
        return explicit

    text = _check_text(check)
    for domain in DOMAIN_DEFINITIONS:
        if any(keyword in text for keyword in domain["keywords"]):
            return str(domain["id"])

    section = str(check.get("section", "")).upper()
    if section.startswith(("CL.4", "CLAUSE 4")):
        return "SCOPE"
    if section.startswith(("CL.5", "CLAUSE 5", "A.2")):
        return "GOV"
    if section.startswith(("CL.6", "CLAUSE 6")):
        return "RISK"
    if section.startswith(("CL.8", "CLAUSE 8")):
        return "LIFECYCLE"
    if section.startswith(("CL.9", "CLAUSE 9")):
        return "MONITORING"
    if section.startswith(("CL.10", "CLAUSE 10")):
        return "IMPROVEMENT"
    return "GOV"


def _build_domain_summaries(checks: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    grouped: Dict[str, list[Dict[str, Any]]] = defaultdict(list)
    for check in checks:
        grouped[_infer_domain_id(check)].append(check)

    summaries: list[Dict[str, Any]] = []
    for domain in DOMAIN_DEFINITIONS:
        domain_id = str(domain["id"])
        domain_checks = grouped.get(domain_id, [])
        open_checks = [
            check for check in domain_checks if not _is_compliant(check) and not _is_manual(check)
        ]
        closed_checks = [check for check in domain_checks if _is_compliant(check)]
        manual_checks = [check for check in domain_checks if _is_manual(check)]
        total = len(domain_checks)
        progress = round(len(closed_checks) / total * 100) if total else 0
        summaries.append(
            {
                "id": domain_id,
                "name": domain["name"],
                "phase": domain["phase"],
                "description": f"{domain['name']} controls derived from scanner summary",
                "total": total,
                "open": len(open_checks),
                "closed": len(closed_checks),
                "manual": len(manual_checks),
                "progress": progress,
                "top_findings": [
                    {
                        "control_id": _check_identifier(check, index + 1),
                        "section": check.get("section"),
                        "title": _check_title(check),
                    }
                    for index, check in enumerate(open_checks[:5])
                ],
            }
        )
    return summaries


def _average_progress(domain_ids: list[str], domain_map: Dict[str, Dict[str, Any]]) -> int:
    if not domain_ids:
        return 0
    values = [int(domain_map.get(domain_id, {}).get("progress", 0)) for domain_id in domain_ids]
    return round(sum(values) / len(values)) if values else 0


def _risk_controls(tier: str) -> list[str]:
    controls = {
        "prohibited": [
            "Do not deploy without legal remediation and executive sign-off",
            "Document why the use case falls under Art. 5 and stop rollout",
        ],
        "high_risk": [
            "Maintain risk management, data governance, logging, and human oversight",
            "Retain technical documentation, post-market monitoring, and incident response evidence",
        ],
        "transparency": [
            "Provide user-facing disclosures for AI interaction or generated content",
            "Maintain provenance and labeling controls for synthetic output",
        ],
        "minimal_risk": [
            "Apply baseline AI governance controls and document intended use",
            "Review for data protection, security, and consumer transparency obligations",
        ],
    }
    return controls[tier]


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
        return await _get_summary_data()

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
        data = await _get_summary_data()
        if not data.get("success"):
            return data

        checks = data.get("checks", [])
        if section:
            checks = [c for c in checks if section.lower() in c.get("section", "").lower()]
        if clause_type:
            checks = [c for c in checks if c.get("clause_type") == clause_type]

        return {
            "success": True,
            "derived_from_summary": True,
            "score": data.get("score"),
            "clause_score": data.get("clause_score"),
            "annex_score": data.get("annex_score"),
            "total": len(checks),
            "failed": [c for c in checks if not _is_compliant(c) and not _is_manual(c)],
            "passed": [c for c in checks if _is_compliant(c)],
            "manual_review": [c for c in checks if _is_manual(c)],
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
            data = await _get_summary_data()
            if not data.get("success"):
                return data

            domain_summaries = _build_domain_summaries(data.get("checks", []))
            domain_map = {domain["id"]: domain for domain in domain_summaries}

            steps = []
            for index, domain in enumerate(DOMAIN_DEFINITIONS, start=1):
                summary = domain_map[domain["id"]]
                progress = int(summary["progress"])
                if summary["open"] == 0 and summary["total"] > 0:
                    status = "complete"
                elif progress > 0 or summary["manual"] > 0:
                    status = "in_progress"
                else:
                    status = "not_started"

                steps.append(
                    {
                        "step": index,
                        "id": domain["id"],
                        "title": domain["name"],
                        "phase": domain["phase"],
                        "status": status,
                        "progress": progress,
                        "open_findings": summary["open"],
                        "manual_checks": summary["manual"],
                        "evidence_needed": domain["evidence"],
                    }
                )

            phase_breakdown = []
            for phase in ("Preparation", "Implementation", "Verification", "Certification"):
                phase_steps = [step for step in steps if step["phase"] == phase]
                readiness = (
                    round(sum(step["progress"] for step in phase_steps) / len(phase_steps))
                    if phase_steps
                    else 0
                )
                phase_breakdown.append(
                    {
                        "phase": phase,
                        "progress": readiness,
                        "steps": len(phase_steps),
                        "open_findings": sum(step["open_findings"] for step in phase_steps),
                    }
                )

            readiness_pct = data.get("score")
            if not isinstance(readiness_pct, (int, float)):
                readiness_pct = (
                    round(sum(step["progress"] for step in steps) / len(steps)) if steps else 0
                )

            return {
                "success": True,
                "derived_from_summary": True,
                "note": SUMMARY_DERIVED_NOTE,
                "readiness_pct": readiness_pct,
                "phase_breakdown": phase_breakdown,
                "steps": steps,
            }

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
        data = await _get_summary_data()
        if not data.get("success"):
            return data

        domains = _build_domain_summaries(data.get("checks", []))
        if domain:
            domains = [item for item in domains if item["id"] == domain.upper()]

        return {
            "success": True,
            "derived_from_summary": True,
            "note": SUMMARY_DERIVED_NOTE,
            "score": data.get("score"),
            "domain_count": len(domains),
            "domains": domains,
        }

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
            data = await _get_summary_data()
            if not data.get("success"):
                return data

            domain_summaries = _build_domain_summaries(data.get("checks", []))
            domain_map = {domain["id"]: domain for domain in domain_summaries}

            eu_ai_act_articles = []
            for mapping in EU_AI_ACT_CROSSWALK:
                score = _average_progress(mapping["domains"], domain_map)
                eu_ai_act_articles.append(
                    {
                        "article": mapping["article"],
                        "topic": mapping["topic"],
                        "score": score,
                        "mapped_domains": mapping["domains"],
                        "open_findings": sum(
                            int(domain_map.get(domain_id, {}).get("open", 0))
                            for domain_id in mapping["domains"]
                        ),
                    }
                )

            nist_functions = []
            for function_name, domain_ids in NIST_RMF_FUNCTIONS.items():
                nist_functions.append(
                    {
                        "function": function_name,
                        "score": _average_progress(domain_ids, domain_map),
                        "mapped_domains": domain_ids,
                        "open_findings": sum(
                            int(domain_map.get(domain_id, {}).get("open", 0))
                            for domain_id in domain_ids
                        ),
                    }
                )

            return {
                "success": True,
                "derived_from_summary": True,
                "note": SUMMARY_DERIVED_NOTE,
                "iso42001_score": data.get("score"),
                "eu_ai_act": {
                    "readiness_score": round(
                        sum(article["score"] for article in eu_ai_act_articles)
                        / len(eu_ai_act_articles)
                    )
                    if eu_ai_act_articles
                    else 0,
                    "risk_tiers": [
                        {"tier": "prohibited", "trigger": "Art. 5 prohibited practices"},
                        {"tier": "high_risk", "trigger": "Art. 6 and Annex III systems"},
                        {"tier": "transparency", "trigger": "Art. 50 disclosure obligations"},
                        {"tier": "minimal_risk", "trigger": "General law only"},
                    ],
                    "articles": eu_ai_act_articles,
                },
                "nist_ai_rmf": {
                    "functions": nist_functions,
                },
            }

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
        data = await _get_summary_data()
        if not data.get("success"):
            return data

        checks = data.get("checks", [])
        evidence = []
        for index, check in enumerate(checks, start=1):
            evidence.append(
                {
                    "control_id": _check_identifier(check, index),
                    "section": check.get("section"),
                    "claim": _check_title(check),
                    "owner": f"{DOMAIN_INDEX[_infer_domain_id(check)]['name']} owner",
                    "source": "oci-compliance-scanner",
                    "status": (
                        "verified"
                        if _is_compliant(check)
                        else "pending"
                        if _is_manual(check)
                        else "finding_open"
                    ),
                    "evidence_type": "manual" if _is_manual(check) else "automated",
                    "review_date": (
                        check.get("review_date")
                        or check.get("last_checked")
                        or data.get("scan_date")
                    ),
                    "expiry": check.get("expiry"),
                }
            )

        return {
            "success": True,
            "derived_from_summary": True,
            "note": SUMMARY_DERIVED_NOTE,
            "count": len(evidence),
            "evidence": evidence,
        }

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
        normalized_domain = domain.strip().lower()
        normalized_purpose = purpose.strip().lower()

        prohibited_indicators = [
            explanation
            for keyword, explanation in PROHIBITED_KEYWORDS.items()
            if keyword in normalized_purpose
        ]
        transparency_triggers = [
            explanation
            for keyword, explanation in TRANSPARENCY_KEYWORDS.items()
            if keyword in normalized_purpose
        ]

        if "emotion recognition" in normalized_purpose and normalized_domain in {
            "employment_workers",
            "education_vocational",
        }:
            prohibited_indicators.append(
                "Art. 5 prohibited emotion recognition in workplace or education contexts"
            )

        if prohibited_indicators:
            risk_tier = "prohibited"
            legal_basis = prohibited_indicators
            confidence = "high"
            reasoning = "Purpose matches prohibited-practice indicators."
        elif (
            normalized_domain in HIGH_RISK_DOMAINS
            or safety_component
            or (public_sector and affects_fundamental_rights)
            or (uses_biometric and normalized_domain in {"law_enforcement", "migration_border"})
        ):
            risk_tier = "high_risk"
            legal_basis = ["Art. 6 high-risk system or safety-component trigger"]
            confidence = "medium"
            reasoning = "Domain and deployment context trigger high-risk obligations."
        elif transparency_triggers or uses_biometric:
            risk_tier = "transparency"
            legal_basis = transparency_triggers or ["Art. 50 transparency obligations"]
            confidence = "medium"
            reasoning = "Use case requires transparency disclosures."
        else:
            risk_tier = "minimal_risk"
            legal_basis = ["No Art. 5, Art. 6, or Art. 50 trigger detected from provided inputs"]
            confidence = "low"
            reasoning = "No prohibited, high-risk, or transparency trigger was identified."

        return {
            "success": True,
            "derived_locally": True,
            "note": SUMMARY_DERIVED_NOTE,
            "domain": domain,
            "purpose": purpose,
            "risk_tier": risk_tier,
            "legal_basis": legal_basis,
            "required_controls": _risk_controls(risk_tier),
            "confidence": confidence,
            "manual_review_required": True,
            "prohibited_indicators": prohibited_indicators,
            "transparency_triggers": transparency_triggers,
            "reasoning": reasoning,
        }
