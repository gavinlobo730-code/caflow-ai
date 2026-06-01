"""
Reusable Risk Engine.
Aggregates risks from: documents, compliance records, tasks, deadlines.
Severity: critical | high | medium | low | info
Risk score: 0–100 (critical=100, high=75, medium=50, low=25, info=10)
"""
from datetime import date, timedelta
from typing import Optional

today = date.today()

_SEVERITY_SCORE = {"critical": 100, "high": 75, "medium": 50, "low": 25, "info": 10}

# ---------------------------------------------------------------------------
# Base risks — seeded from document risks + compliance-derived
# ---------------------------------------------------------------------------

MOCK_RISKS: list[dict] = [
    # Critical — TDS mismatch (from doc)
    {
        "id": "eng-risk-001",
        "source": "document",
        "client_id": "c-005",
        "client_name": "Joshi Textiles",
        "severity": "critical",
        "category": "TDS_MISMATCH",
        "title": "Form 16 TDS vs 26AS Mismatch",
        "description": "Form 16 shows TDS ₹1.8L but 26AS shows ₹1.4L. Reconciliation required before ITR filing.",
        "resolution_status": "open",
        "created_at": (today - timedelta(days=10)).isoformat(),
    },
    {
        "id": "eng-risk-002",
        "source": "compliance",
        "client_id": "c-003",
        "client_name": "Mehta Consulting",
        "severity": "critical",
        "category": "OTHER",
        "title": "GSTR-3B Overdue — Penalty Accruing",
        "description": "GSTR-3B for previous month is 10 days overdue. Late fee accruing at ₹50/day under CGST Act Section 47.",
        "resolution_status": "open",
        "created_at": (today - timedelta(days=10)).isoformat(),
    },
    {
        "id": "eng-risk-003",
        "source": "compliance",
        "client_id": "c-003",
        "client_name": "Mehta Consulting",
        "severity": "critical",
        "category": "OTHER",
        "title": "GSTR-1 Overdue — Outward Supply Penalty",
        "description": "GSTR-1 for previous period overdue. Late filing blocks recipient's ITC claims under CGST Act Section 16.",
        "resolution_status": "open",
        "created_at": (today - timedelta(days=8)).isoformat(),
    },
    # High
    {
        "id": "eng-risk-004",
        "source": "document",
        "client_id": "c-003",
        "client_name": "Mehta Consulting",
        "severity": "high",
        "category": "AIS_MISMATCH",
        "title": "AIS Income vs Book Income Mismatch",
        "description": "AIS shows total income ₹8.5L but books show ₹7.3L. Difference ₹1.2L may attract IT scrutiny.",
        "resolution_status": "open",
        "created_at": (today - timedelta(days=7)).isoformat(),
    },
    {
        "id": "eng-risk-005",
        "source": "document",
        "client_id": "c-002",
        "client_name": "Patel & Sons",
        "severity": "high",
        "category": "CLASSIFICATION_ERROR",
        "title": "Document Extraction Failed — Low Confidence",
        "description": "Bank statement extraction confidence 41%. Document may be misclassified or corrupted.",
        "resolution_status": "open",
        "created_at": (today - timedelta(days=3)).isoformat(),
    },
    {
        "id": "eng-risk-006",
        "source": "document",
        "client_id": "c-005",
        "client_name": "Joshi Textiles",
        "severity": "high",
        "category": "HIGH_LIABILITY",
        "title": "Unusually High TDS Liability",
        "description": "TDS deducted ₹1.8L significantly higher than prior year ₹1.1L. Verify one-time payments.",
        "resolution_status": "open",
        "created_at": (today - timedelta(days=9)).isoformat(),
    },
    {
        "id": "eng-risk-007",
        "source": "compliance",
        "client_id": "c-004",
        "client_name": "Desai Traders",
        "severity": "high",
        "category": "OTHER",
        "title": "Advance Tax Deadline Approaching",
        "description": "15% advance tax instalment due 15 Jun 2025. Non-payment attracts interest under Section 234C of IT Act 1961.",
        "resolution_status": "open",
        "created_at": (today - timedelta(days=2)).isoformat(),
    },
    # Medium
    {
        "id": "eng-risk-008",
        "source": "document",
        "client_id": "c-001",
        "client_name": "Sharma Enterprises",
        "severity": "medium",
        "category": "MISSING_INVOICE",
        "title": "Missing GST Input Invoices",
        "description": "GSTR-2B shows 4 supplier invoices but only 2 in purchase register. Missing ITC ₹45,000.",
        "resolution_status": "acknowledged",
        "created_at": (today - timedelta(days=5)).isoformat(),
    },
    {
        "id": "eng-risk-009",
        "source": "document",
        "client_id": "c-001",
        "client_name": "Sharma Enterprises",
        "severity": "medium",
        "category": "BANK_RECONCILIATION",
        "title": "Bank Statement — Unreconciled Entries",
        "description": "5 debit entries totalling ₹2.3L not matched in books. Potential unreported income or expense.",
        "resolution_status": "open",
        "created_at": (today - timedelta(days=2)).isoformat(),
    },
    {
        "id": "eng-risk-010",
        "source": "document",
        "client_id": "c-003",
        "client_name": "Mehta Consulting",
        "severity": "medium",
        "category": "MISSING_FORM16",
        "title": "Missing Form 16 from Second Employer",
        "description": "AIS shows TDS from 2 deductors but only 1 Form 16 submitted. Obtain Form 16 from second employer.",
        "resolution_status": "open",
        "created_at": (today - timedelta(days=6)).isoformat(),
    },
    # Resolved
    {
        "id": "eng-risk-011",
        "source": "document",
        "client_id": "c-001",
        "client_name": "Sharma Enterprises",
        "severity": "low",
        "category": "GST_MISMATCH",
        "title": "GST Rate Classification — Resolved",
        "description": "Invoice 18% GST rate confirmed correct after HSN verification.",
        "resolution_status": "resolved",
        "created_at": (today - timedelta(days=5)).isoformat(),
    },
]


def get_all_risks(
    firm_id: Optional[str] = None,
    client_id: Optional[str] = None,
    severity: Optional[str] = None,
    status: str = "open",
) -> list[dict]:
    """Aggregate from document risks + derived from compliance records."""
    from domain.document_intelligence_service import MOCK_DOCUMENT_RISKS
    from mock_data import MOCK_CLIENTS
    client_map = {c["id"]: c["client_name"] for c in MOCK_CLIENTS}

    # Combine engine risks + document risks (deduplicate by id)
    combined: dict[str, dict] = {r["id"]: r for r in MOCK_RISKS}
    for dr in MOCK_DOCUMENT_RISKS:
        if dr["id"] not in combined:
            combined[dr["id"]] = {
                **dr,
                "source": "document",
                "client_name": client_map.get(dr["client_id"], "Unknown"),
            }

    risks = list(combined.values())

    if client_id:
        risks = [r for r in risks if r["client_id"] == client_id]
    if severity:
        risks = [r for r in risks if r["severity"] == severity]
    if status:
        risks = [r for r in risks if r["resolution_status"] == status]

    # Enrich client names
    for r in risks:
        if "client_name" not in r:
            r["client_name"] = client_map.get(r["client_id"], "Unknown")

    return sorted(risks, key=lambda r: _SEVERITY_SCORE.get(r["severity"], 0), reverse=True)


def get_risk_dashboard_stats() -> dict:
    """Return counts by severity."""
    all_risks = get_all_risks(status="open")
    resolved = len([r for r in MOCK_RISKS if r["resolution_status"] == "resolved"])
    return {
        "critical": len([r for r in all_risks if r["severity"] == "critical"]),
        "high": len([r for r in all_risks if r["severity"] == "high"]),
        "medium": len([r for r in all_risks if r["severity"] == "medium"]),
        "low": len([r for r in all_risks if r["severity"] == "low"]),
        "info": len([r for r in all_risks if r["severity"] == "info"]),
        "resolved": resolved,
        "total_open": len(all_risks),
    }


def get_client_risk_summary(client_id: str) -> dict:
    """Return risk_score, risks_by_severity, top_risks for a client."""
    client_risks = get_all_risks(client_id=client_id, status="open")
    risks_by_severity = {
        "critical": len([r for r in client_risks if r["severity"] == "critical"]),
        "high": len([r for r in client_risks if r["severity"] == "high"]),
        "medium": len([r for r in client_risks if r["severity"] == "medium"]),
        "low": len([r for r in client_risks if r["severity"] == "low"]),
        "info": len([r for r in client_risks if r["severity"] == "info"]),
    }
    # Score: weighted average
    total_weight = sum(_SEVERITY_SCORE.get(r["severity"], 0) for r in client_risks)
    risk_score = min(100, total_weight // max(len(client_risks), 1)) if client_risks else 0
    return {
        "risk_score": risk_score,
        "risks_by_severity": risks_by_severity,
        "top_risks": client_risks[:5],
    }


def compute_firm_risk_score() -> int:
    """Aggregate 0-100 score for the firm."""
    open_risks = get_all_risks(status="open")
    if not open_risks:
        return 0
    total_weight = sum(_SEVERITY_SCORE.get(r["severity"], 0) for r in open_risks)
    return min(100, total_weight // max(len(open_risks), 1))


def update_risk(risk_id: str, resolution_status: str) -> dict | None:
    """Update a risk's resolution status."""
    from datetime import datetime
    from domain.document_intelligence_service import MOCK_DOCUMENT_RISKS
    for risk in MOCK_RISKS:
        if risk["id"] == risk_id:
            risk["resolution_status"] = resolution_status
            if resolution_status == "resolved":
                risk["resolved_at"] = datetime.utcnow().isoformat()
            return risk
    for risk in MOCK_DOCUMENT_RISKS:
        if risk["id"] == risk_id:
            risk["resolution_status"] = resolution_status
            if resolution_status == "resolved":
                risk["resolved_at"] = datetime.utcnow().isoformat()
            return risk
    return None
