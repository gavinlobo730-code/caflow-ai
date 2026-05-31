"""
Single source of truth for all mock data.
All pages and routers import from here — no duplicated mocks.
All monetary values in paise (integer). Never float.
"""
from datetime import date, timedelta
from services.compliance_engine import enrich_compliance_task

today = date.today()

MOCK_TEAM_MEMBERS = [
    {
        "id": "tm-001",
        "name": "Gavin Lobo",
        "email": "gavin@caflow.in",
        "role": "owner",
        "is_active": True,
    }
]

MOCK_CLIENTS = [
    {
        "id": "c-001",
        "client_name": "Sharma Enterprises",
        "entity_type": "Proprietorship",
        "pan": "AABCS1429B",
        "gstin": "27AABCS1429B1ZB",
        "mobile": "+91 98765 43210",
        "email": "sharma@sharmaenterprises.in",
        "address_line1": "12, MG Road",
        "city": "Mumbai",
        "state": "Maharashtra",
        "pincode": "400001",
        "state_code": "27",
        "gst_filing_frequency": "monthly",
        "status": "active",
        "assigned_to": "tm-001",
        "created_at": (today - timedelta(days=180)).isoformat(),
    },
    {
        "id": "c-002",
        "client_name": "Patel & Sons",
        "entity_type": "Partnership",
        "pan": "AAPCS4229B",
        "gstin": "27AAPCS4229B1ZC",
        "mobile": "+91 98765 43211",
        "email": "patel@patelandsons.in",
        "address_line1": "45, Nehru Nagar",
        "city": "Pune",
        "state": "Maharashtra",
        "pincode": "411001",
        "state_code": "27",
        "gst_filing_frequency": "monthly",
        "status": "active",
        "assigned_to": "tm-001",
        "created_at": (today - timedelta(days=120)).isoformat(),
    },
    {
        "id": "c-003",
        "client_name": "Mehta Consulting",
        "entity_type": "LLP",
        "pan": "AACCS7829B",
        "gstin": "27AACCS7829B1ZD",
        "mobile": "+91 98765 43212",
        "email": "mehta@mehtaconsulting.in",
        "address_line1": "78, Bandra West",
        "city": "Mumbai",
        "state": "Maharashtra",
        "pincode": "400050",
        "state_code": "27",
        "gst_filing_frequency": "monthly",
        "status": "active",
        "assigned_to": "tm-001",
        "created_at": (today - timedelta(days=90)).isoformat(),
    },
    {
        "id": "c-004",
        "client_name": "Desai Traders",
        "entity_type": "Proprietorship",
        "pan": "AADCS9929B",
        "gstin": "27AADCS9929B1ZE",
        "mobile": "+91 98765 43213",
        "email": "desai@desaitraders.in",
        "address_line1": "33, Dadar East",
        "city": "Mumbai",
        "state": "Maharashtra",
        "pincode": "400014",
        "state_code": "27",
        "gst_filing_frequency": "monthly",
        "status": "active",
        "assigned_to": "tm-001",
        "created_at": (today - timedelta(days=60)).isoformat(),
    },
    {
        "id": "c-005",
        "client_name": "Joshi Textiles",
        "entity_type": "Private Limited",
        "pan": "AAJCS3329B",
        "gstin": "27AAJCS3329B1ZF",
        "mobile": "+91 98765 43214",
        "email": "joshi@joshitextiles.in",
        "address_line1": "90, MIDC Industrial Area",
        "city": "Nashik",
        "state": "Maharashtra",
        "pincode": "422010",
        "state_code": "27",
        "gst_filing_frequency": "monthly",
        "status": "active",
        "assigned_to": "tm-001",
        "created_at": (today - timedelta(days=45)).isoformat(),
    },
]

def _make_tasks() -> list[dict]:
    raw = [
        {
            "id": "ct-001", "client_id": "c-001",
            "compliance_type": "GSTR1", "period_start": (today.replace(day=1) - timedelta(days=1)).replace(day=1).isoformat(),
            "period_end": (today.replace(day=1) - timedelta(days=1)).isoformat(),
            "due_date": (today + timedelta(days=3)).isoformat(),
            "status": "pending", "assigned_to": "tm-001",
        },
        {
            "id": "ct-002", "client_id": "c-001",
            "compliance_type": "GSTR3B", "period_start": (today.replace(day=1) - timedelta(days=1)).replace(day=1).isoformat(),
            "period_end": (today.replace(day=1) - timedelta(days=1)).isoformat(),
            "due_date": (today + timedelta(days=18)).isoformat(),
            "status": "pending", "assigned_to": "tm-001",
        },
        {
            "id": "ct-003", "client_id": "c-002",
            "compliance_type": "GSTR3B", "period_start": (today.replace(day=1) - timedelta(days=1)).replace(day=1).isoformat(),
            "period_end": (today.replace(day=1) - timedelta(days=1)).isoformat(),
            "due_date": (today + timedelta(days=8)).isoformat(),
            "status": "pending", "assigned_to": "tm-001",
        },
        {
            "id": "ct-004", "client_id": "c-003",
            "compliance_type": "GSTR1", "period_start": (today.replace(day=1) - timedelta(days=32)).replace(day=1).isoformat(),
            "period_end": (today.replace(day=1) - timedelta(days=32)).isoformat(),
            "due_date": (today - timedelta(days=2)).isoformat(),
            "status": "overdue", "assigned_to": "tm-001",
        },
        {
            "id": "ct-005", "client_id": "c-003",
            "compliance_type": "GSTR3B", "period_start": (today.replace(day=1) - timedelta(days=32)).replace(day=1).isoformat(),
            "period_end": (today.replace(day=1) - timedelta(days=32)).isoformat(),
            "due_date": (today - timedelta(days=10)).isoformat(),
            "status": "overdue", "assigned_to": "tm-001",
        },
        {
            "id": "ct-006", "client_id": "c-005",
            "compliance_type": "ITR", "period_start": "2024-04-01",
            "period_end": "2025-03-31",
            "due_date": (today + timedelta(days=12)).isoformat(),
            "status": "pending", "assigned_to": "tm-001",
        },
        {
            "id": "ct-007", "client_id": "c-004",
            "compliance_type": "GSTR1", "period_start": (today.replace(day=1) - timedelta(days=32)).replace(day=1).isoformat(),
            "period_end": (today.replace(day=1) - timedelta(days=32)).isoformat(),
            "due_date": (today - timedelta(days=15)).isoformat(),
            "status": "filed", "assigned_to": "tm-001",
        },
    ]
    return [enrich_compliance_task(t) for t in raw]

MOCK_COMPLIANCE_TASKS = _make_tasks()

MOCK_DOCUMENTS = [
    {
        "id": "doc-001",
        "client_id": "c-001",
        "document_type": "GST_INVOICE",
        "file_name": "invoice_march_2024.pdf",
        "file_path": "/uploads/c-001/invoice_march_2024.pdf",
        "financial_year": "2024-25",
        "review_status": "approved",
        "confidence_score": 0.97,
        "upload_date": (today - timedelta(days=5)).isoformat(),
        "extracted_json": {
            "supplier_name": "Hindustan Goods Suppliers Pvt Ltd",
            "gstin": "27AABCH1234B1ZA",
            "invoice_number": "HGS/2024-25/001234",
            "taxable_value_paise": 10000000,
            "total_amount_paise": 11800000,
        },
    },
    {
        "id": "doc-002",
        "client_id": "c-001",
        "document_type": "FORM16",
        "file_name": "form16_2024_25.pdf",
        "file_path": "/uploads/c-001/form16_2024_25.pdf",
        "financial_year": "2024-25",
        "review_status": "pending_review",
        "confidence_score": 0.91,
        "upload_date": (today - timedelta(days=2)).isoformat(),
        "extracted_json": None,
    },
]

MOCK_ACTIVITY_LOGS = [
    {
        "id": "al-001", "client_id": "c-001", "actor_id": "tm-001",
        "action": "document_uploaded",
        "description": "GST invoice uploaded: invoice_march_2024.pdf",
        "entity_type": "document", "entity_id": "doc-001",
        "created_at": (today - timedelta(days=5)).isoformat(),
    },
    {
        "id": "al-002", "client_id": "c-001", "actor_id": "tm-001",
        "action": "compliance_task_created",
        "description": "GSTR-1 task created for current period",
        "entity_type": "compliance_task", "entity_id": "ct-001",
        "created_at": (today - timedelta(days=10)).isoformat(),
    },
    {
        "id": "al-003", "client_id": "c-001", "actor_id": "tm-001",
        "action": "reminder_sent",
        "description": "WhatsApp compliance reminder sent to Sharma Enterprises",
        "entity_type": None, "entity_id": None,
        "created_at": (today - timedelta(days=1)).isoformat(),
    },
]

MOCK_AI_INSIGHTS = [
    {
        "id": "ai-001",
        "client_id": "c-001",
        "insight_type": "DEADLINE_APPROACHING",
        "severity": "high",
        "title": "GSTR-1 due in 3 days",
        "description": "GSTR-1 for the current period is due on "
                       + (today + timedelta(days=3)).strftime("%d %b %Y")
                       + ". Filing not yet initiated.",
        "recommended_action": "Begin GSTR-1 preparation immediately. Reconcile sales invoices.",
        "status": "open",
        "created_at": today.isoformat(),
    },
    {
        "id": "ai-002",
        "client_id": "c-003",
        "insight_type": "ITC_MISMATCH",
        "severity": "critical",
        "title": "Potential ITC mismatch detected",
        "description": "GSTR-2B data shows ITC of ₹45,000 but purchase register shows ₹38,000. Gap: ₹7,000.",
        "recommended_action": "Reconcile purchase register with GSTR-2B before filing GSTR-3B.",
        "status": "open",
        "created_at": (today - timedelta(days=3)).isoformat(),
    },
    {
        "id": "ai-003",
        "client_id": "c-005",
        "insight_type": "TURNOVER_THRESHOLD",
        "severity": "medium",
        "title": "Approaching tax audit threshold",
        "description": "Projected annual turnover is ₹98L. Tax audit under Section 44AB applies above ₹1Cr.",
        "recommended_action": "Monitor Q4 sales closely. Begin audit preparation if turnover exceeds ₹1Cr.",
        "status": "acknowledged",
        "created_at": (today - timedelta(days=7)).isoformat(),
    },
]

CLIENT_INDEX = {c["id"]: c for c in MOCK_CLIENTS}
