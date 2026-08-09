"""
AI Insight Generation Service.
Generates contextual insights from compliance records, tasks, documents, and risks.
Insight categories: compliance, accounting, document, risk, performance
Note: Uses MOCK_AI_INSIGHTS_V2 — separate from MOCK_AI_INSIGHTS in mock_data.py.
Serves from /api/ai-insights (new router) — does not conflict with /api/insights.
"""
from datetime import date, timedelta, datetime
from typing import Optional
import uuid

today = date.today()

MOCK_AI_INSIGHTS_V2: list[dict] = [
    {
        "id": "aiv2-001",
        "client_id": "c-003",
        "client_name": "Mehta Consulting",
        "category": "compliance",
        "severity": "critical",
        "title": "GSTR-3B Overdue — Immediate Action Required",
        "description": "GSTR-3B for previous period is 10 days overdue. Late fee ₹50/day accruing under CGST Act Section 47.",
        "recommendation": "File GSTR-3B immediately to stop late fee accumulation. Estimated late fee ₹500 so far.",
        "status": "open",
        "created_at": (today - timedelta(days=10)).isoformat(),
    },
    {
        "id": "aiv2-002",
        "client_id": "c-005",
        "client_name": "Joshi Textiles",
        "category": "document",
        "severity": "critical",
        "title": "TDS Mismatch — ITR Filing Blocked",
        "description": "Form 16 TDS ₹1.8L vs 26AS TDS ₹1.4L. ITR filing should be blocked until reconciled.",
        "recommendation": "Contact employer to rectify Form 16 or file revised TDS return before ITR due date.",
        "status": "open",
        "created_at": (today - timedelta(days=10)).isoformat(),
    },
    {
        "id": "aiv2-003",
        "client_id": "c-001",
        "client_name": "Sharma Enterprises",
        "category": "compliance",
        "severity": "high",
        "title": "GSTR-1 Due in 3 Days",
        "description": "GSTR-1 due " + (today + timedelta(days=3)).strftime("%d %b %Y") + ". Filing not yet initiated. Sales data collection pending.",
        "recommendation": "Begin GSTR-1 preparation today. Collect all B2B and B2C sales invoices.",
        "status": "open",
        "created_at": today.isoformat(),
    },
    {
        "id": "aiv2-004",
        "client_id": "c-002",
        "client_name": "Patel & Sons",
        "category": "document",
        "severity": "high",
        "title": "Bank Statement Extraction Failed",
        "description": "Bank statement for Apr 2025 could not be extracted (confidence 41%). Manual data entry required.",
        "recommendation": "Obtain clearer PDF from bank and re-upload, or enter data manually for reconciliation.",
        "status": "open",
        "created_at": (today - timedelta(days=3)).isoformat(),
    },
    {
        "id": "aiv2-005",
        "client_id": "c-003",
        "client_name": "Mehta Consulting",
        "category": "risk",
        "severity": "high",
        "title": "AIS Income Discrepancy — Scrutiny Risk",
        "description": "AIS shows income ₹8.5L vs books ₹7.3L. Unexplained gap may attract IT scrutiny under Section 143(3).",
        "recommendation": "Identify source of additional income in AIS. Reconcile before ITR filing.",
        "status": "open",
        "created_at": (today - timedelta(days=7)).isoformat(),
    },
    {
        "id": "aiv2-006",
        "client_id": "c-004",
        "client_name": "Desai Traders",
        "category": "compliance",
        "severity": "high",
        "title": "Advance Tax Instalment Due",
        "description": "15% advance tax instalment due 15 Jun 2025. Interest under Section 234C if missed.",
        "recommendation": "Calculate advance tax liability and pay by 15 Jun 2025 via Challan 280.",
        "status": "open",
        "created_at": (today - timedelta(days=2)).isoformat(),
    },
    {
        "id": "aiv2-007",
        "client_id": "c-005",
        "client_name": "Joshi Textiles",
        "category": "compliance",
        "severity": "medium",
        "title": "Tax Audit Threshold — Monitor Turnover",
        "description": "Projected annual turnover ₹98L. Tax audit mandatory above ₹1Cr under Section 44AB of IT Act 1961.",
        "recommendation": "Monitor Q4 sales. Begin audit preparation if turnover crosses ₹1Cr.",
        "status": "acknowledged",
        "created_at": (today - timedelta(days=15)).isoformat(),
    },
    {
        "id": "aiv2-008",
        "client_id": "c-001",
        "client_name": "Sharma Enterprises",
        "category": "document",
        "severity": "medium",
        "title": "Missing GST Input Invoices — ITC at Risk",
        "description": "4 supplier invoices in GSTR-2B but only 2 in purchase register. ITC ₹45,000 unmatched.",
        "recommendation": "Obtain invoices from suppliers and update purchase register before GSTR-3B filing.",
        "status": "open",
        "created_at": (today - timedelta(days=5)).isoformat(),
    },
    {
        "id": "aiv2-009",
        "client_id": "c-004",
        "client_name": "Desai Traders",
        "category": "performance",
        "severity": "info",
        "title": "GSTR-3B Filed Successfully",
        "description": "GSTR-3B for previous period filed on time. Good compliance track record maintained.",
        "recommendation": "Continue timely filing. Consider quarterly filing if eligible to reduce compliance burden.",
        "status": "acknowledged",
        "created_at": (today - timedelta(days=11)).isoformat(),
    },
    {
        "id": "aiv2-010",
        "client_id": "c-002",
        "client_name": "Patel & Sons",
        "category": "accounting",
        "severity": "medium",
        "title": "ITC Mismatch Detected in GSTR-2B",
        "description": "GSTR-2B ITC ₹45,000 vs purchase register ₹38,000. Gap ₹7,000 needs reconciliation before GSTR-3B.",
        "recommendation": "Reconcile purchase register with GSTR-2B. Identify missing supplier invoices.",
        "status": "open",
        "created_at": (today - timedelta(days=4)).isoformat(),
    },
]

_insight_index = {i["id"]: i for i in MOCK_AI_INSIGHTS_V2}


def generate_insights_for_client(client_id: str, firm_id: Optional[str] = None) -> list[dict]:
    """Analyze client records and generate insights, persisting via repo."""
    from repositories.ai_insights_repository import ai_insights_repo
    from domain.compliance_record_service import compliance_record_service
    from domain.document_intelligence_service import MOCK_DOCUMENT_RISKS
    from repositories.client_repository import client_repo

    clients = client_repo.find_all(firm_id=firm_id)
    client_map = {c["id"]: c["client_name"] for c in clients}
    client_name = client_map.get(client_id, "Unknown Client")

    new_insights: list[dict] = []
    records = compliance_record_service.list_records(client_id=client_id, firm_id=firm_id)

    for record in records:
        if record["status"] == "Overdue":
            insight = ai_insights_repo.create({
                "client_id": client_id,
                "client_name": client_name,
                "firm_id": firm_id,
                "category": "compliance",
                "severity": "critical",
                "title": f"Overdue Filing: {record['period_label']}",
                "description": f"{record['compliance_type']} for {record['period_label']} is overdue. Penalties may apply.",
                "recommendation": "File immediately to avoid further penalties.",
                "status": "open",
            })
            new_insights.append(insight)

        try:
            due = datetime.fromisoformat(record["due_date"]).date()
            days_left = (due - today).days
            if 0 <= days_left <= 7 and record["status"] not in ("Filed",):
                insight = ai_insights_repo.create({
                    "client_id": client_id,
                    "client_name": client_name,
                    "firm_id": firm_id,
                    "category": "compliance",
                    "severity": "high",
                    "title": f"Deadline Approaching: {record['period_label']}",
                    "description": f"{record['compliance_type']} due in {days_left} day(s). Current status: {record['status']}.",
                    "recommendation": "Expedite filing process to avoid late fees.",
                    "status": "open",
                })
                new_insights.append(insight)
        except Exception:
            pass

    health = compliance_record_service.get_client_health_score(client_id, firm_id=firm_id)
    if health["health_score"] < 50:
        insight = ai_insights_repo.create({
            "client_id": client_id,
            "client_name": client_name,
            "firm_id": firm_id,
            "category": "performance",
            "severity": "high",
            "title": "Low Health Score — Compliance Intervention Needed",
            "description": f"Health score {health['health_score']}/100. Multiple overdue items reducing score.",
            "recommendation": "Review and resolve overdue compliance records and pending tasks.",
            "status": "open",
        })
        new_insights.append(insight)

    old_risks = [
        r for r in MOCK_DOCUMENT_RISKS
        if r["client_id"] == client_id
        and r["resolution_status"] == "open"
        and (today - date.fromisoformat(r["created_at"][:10])).days > 7
    ]
    if old_risks:
        insight = ai_insights_repo.create({
            "client_id": client_id,
            "client_name": client_name,
            "firm_id": firm_id,
            "category": "risk",
            "severity": "medium",
            "title": f"{len(old_risks)} Unresolved Document Risk(s) Over 7 Days",
            "description": f"{len(old_risks)} document risk(s) have been open for more than 7 days without resolution.",
            "recommendation": "Review and resolve or acknowledge outstanding document risks.",
            "status": "open",
        })
        new_insights.append(insight)

    return new_insights


def get_all_insights(
    firm_id: Optional[str] = None,
    client_id: Optional[str] = None,
    status: Optional[str] = None,
    category: Optional[str] = None,
) -> list[dict]:
    from repositories.ai_insights_repository import ai_insights_repo
    return ai_insights_repo.find_all(firm_id=firm_id, client_id=client_id, status=status, category=category)


def acknowledge_insight(insight_id: str, firm_id: Optional[str] = None) -> dict | None:
    from repositories.ai_insights_repository import ai_insights_repo
    return ai_insights_repo.update_status(insight_id, "acknowledged", firm_id=firm_id)


def dismiss_insight(insight_id: str, firm_id: Optional[str] = None) -> dict | None:
    from repositories.ai_insights_repository import ai_insights_repo
    return ai_insights_repo.update_status(insight_id, "dismissed", firm_id=firm_id)


def get_cross_client_patterns(firm_id: Optional[str] = None) -> list[dict]:
    """
    Detect cross-client intelligence patterns: shared directors with compliance risk,
    industry-wide issues, group-wide cash flow signals, and correlated deadline spikes.
    Returns mock patterns when SUPABASE_URL is not set.
    """
    # In production this would query the DB for shared directors, related entities,
    # and correlated compliance failures across clients in the same firm.
    # For now return realistic mock patterns.
    return [
        {
            "pattern_type": "shared_director_compliance_risk",
            "title": "Director appears in multiple clients with compliance issues",
            "description": (
                "Rajesh Mehta is listed as director for 3 clients. "
                "2 of those clients have overdue TDS returns (26Q). "
                "This may indicate a group-wide cash flow issue affecting timely payment."
            ),
            "evidence": ["Mehta Consulting", "Mehta Infra Pvt Ltd", "RM Holdings"],
            "affected_clients": ["c-003", "c-007", "c-011"],
            "confidence": 72,
            "severity": "high",
            "recommended_action": (
                "Schedule a group-level review with Rajesh Mehta to assess liquidity. "
                "File overdue 26Q TDS returns immediately to stop interest under Section 201(1A) of IT Act."
            ),
        },
        {
            "pattern_type": "same_issue_multiple_clients",
            "title": "GSTR-2B ITC mismatch appearing across 4 clients simultaneously",
            "description": (
                "4 clients all show ITC mismatch between GSTR-2B and purchase register this month. "
                "Likely a common supplier (Priya Traders GSTIN 27AADCP...) not filing GSTR-1 on time, "
                "which blocks ITC claims under CGST Act Section 16(2)(aa)."
            ),
            "evidence": ["Patel & Sons", "Sharma Enterprises", "Desai Traders", "Joshi Textiles"],
            "affected_clients": ["c-002", "c-001", "c-004", "c-005"],
            "confidence": 85,
            "severity": "high",
            "recommended_action": (
                "Identify the common non-compliant supplier and escalate to all 4 clients. "
                "Consider switching supplier or adjusting ITC claims pending supplier's GSTR-1."
            ),
        },
        {
            "pattern_type": "group_advance_tax_risk",
            "title": "Advance tax instalment risk across Desai Group entities",
            "description": (
                "15 Jun 2025 advance tax deadline (15% instalment) is approaching. "
                "2 Desai Group entities have no advance tax challan recorded yet. "
                "Interest under Section 234C of IT Act 1961 will apply if missed."
            ),
            "evidence": ["Desai Traders", "Desai Real Estate LLP"],
            "affected_clients": ["c-004", "c-009"],
            "confidence": 68,
            "severity": "medium",
            "recommended_action": (
                "Calculate advance tax for both entities and pay via Challan 280 before 15 Jun 2025. "
                "Group payment can be coordinated to reduce CA effort."
            ),
        },
    ]


def get_insight_feed(
    firm_id: Optional[str] = None,
    limit: int = 20,
    allowed_client_ids: Optional[set[str]] = None,
) -> list[dict]:
    """allowed_client_ids=None means firm-wide (a firm-wide caller, or
    mock/dev — see core.authz.effective_client_ids); otherwise only insights
    for a client in that set are returned, so a non-firm-wide caller's feed
    never surfaces another staff member's assigned client."""
    from repositories.ai_insights_repository import ai_insights_repo
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    open_insights = ai_insights_repo.find_all(firm_id=firm_id, status="open")
    if allowed_client_ids is not None:
        open_insights = [i for i in open_insights if i.get("client_id") in allowed_client_ids]
    sorted_insights = sorted(
        open_insights,
        key=lambda i: (severity_order.get(i["severity"], 5), i["created_at"]),
    )
    return sorted_insights[:limit]
