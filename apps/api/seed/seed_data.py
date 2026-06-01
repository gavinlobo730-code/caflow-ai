"""
Realistic demo seed data for CAflow AI.
20 clients, 100 tasks, 100 compliance records, 50 documents.
All linked to a single demo firm.
All monetary values in paise (integer).
"""
from datetime import date, timedelta
from services.compliance_engine import enrich_compliance_task

today = date.today()

DEMO_FIRM = {
    "id": "firm-001",
    "name": "Gavin Lobo & Associates",
    "email": "gavin@calobo.in",
    "phone": "+91 98765 43210",
    "address_line1": "12, MG Road",
    "city": "Mumbai",
    "state": "Maharashtra",
    "pincode": "400001",
    "gst_number": "27ABCGL1234D1ZB",
    "icai_mrn": "ICAI-MRN-123456",
    "plan": "professional",
}

DEMO_USERS = [
    {"id": "u-001", "firm_id": "firm-001", "full_name": "Gavin Lobo", "email": "gavin@calobo.in", "role": "Partner", "status": "active"},
    {"id": "u-002", "firm_id": "firm-001", "full_name": "Priya Sharma", "email": "priya@calobo.in", "role": "Manager", "status": "active"},
    {"id": "u-003", "firm_id": "firm-001", "full_name": "Rahul Mehta", "email": "rahul@calobo.in", "role": "Executive", "status": "active"},
    {"id": "u-004", "firm_id": "firm-001", "full_name": "Deepa Nair", "email": "deepa@calobo.in", "role": "Executive", "status": "active"},
    {"id": "u-005", "firm_id": "firm-001", "full_name": "Sanjay Joshi", "email": "sanjay@calobo.in", "role": "Reviewer", "status": "active"},
]

# 20 realistic Indian CA firm clients
SEED_CLIENTS = [
    {"id": f"sc-{i:03d}", "firm_id": "firm-001", "client_name": name, "entity_type": etype,
     "pan": pan, "gstin": gstin, "city": city, "state": "Maharashtra",
     "state_code": "27", "gst_filing_frequency": freq, "status": "active",
     "email": email, "mobile": mobile,
     "created_at": (today - timedelta(days=days)).isoformat()}
    for i, (name, etype, pan, gstin, city, email, mobile, freq, days) in enumerate([
        ("Sharma Enterprises", "Proprietorship", "AABCS1429B", "27AABCS1429B1ZB", "Mumbai", "sharma@sharmaenterprises.in", "+91 98765 43210", "monthly", 180),
        ("Patel & Sons", "Partnership", "AAPCS4229B", "27AAPCS4229B1ZC", "Pune", "patel@patelandsons.in", "+91 98765 43211", "monthly", 120),
        ("Mehta Consulting LLP", "LLP", "AACCS7829B", "27AACCS7829B1ZD", "Mumbai", "mehta@mehtaconsulting.in", "+91 98765 43212", "monthly", 90),
        ("Desai Traders", "Proprietorship", "AADCS9929B", "27AADCS9929B1ZE", "Mumbai", "desai@desaitraders.in", "+91 98765 43213", "monthly", 60),
        ("Joshi Textiles Pvt Ltd", "Private Limited", "AAJCS3329B", "27AAJCS3329B1ZF", "Nashik", "joshi@joshitextiles.in", "+91 98765 43214", "monthly", 45),
        ("Kapoor Industries", "Private Limited", "AAKCS2219B", "27AAKCS2219B1ZG", "Pune", "kapoor@kapoorindustries.in", "+91 98765 43215", "monthly", 200),
        ("Rao & Partners", "Partnership", "AARCS5549B", "27AARCS5549B1ZH", "Nagpur", "rao@raopartners.in", "+91 98765 43216", "quarterly", 150),
        ("Singh Constructions", "Proprietorship", "AASCS8879B", "27AASCS8879B1ZI", "Mumbai", "singh@singhconstructions.in", "+91 98765 43217", "monthly", 300),
        ("Gupta Pharmaceuticals", "Private Limited", "AAGCS1119B", "27AAGCS1119B1ZJ", "Pune", "gupta@guptapharma.in", "+91 98765 43218", "monthly", 365),
        ("Nair Exports LLP", "LLP", "AANCS4449B", "27AANCS4449B1ZK", "Mumbai", "nair@nairexports.in", "+91 98765 43219", "monthly", 280),
        ("Verma & Associates", "Proprietorship", "AAVCS7779B", "27AAVCS7779B1ZL", "Nashik", "verma@vermaassoc.in", "+91 98765 43220", "quarterly", 100),
        ("Iyer Consulting", "Proprietorship", "AAICS3339B", "27AAICS3339B1ZM", "Mumbai", "iyer@iyerconsulting.in", "+91 98765 43221", "monthly", 75),
        ("Bose Trading Co", "Partnership", "AABCS6669B", "27AABCS6669B1ZN", "Pune", "bose@bosetrading.in", "+91 98765 43222", "quarterly", 240),
        ("Reddy Agro Pvt Ltd", "Private Limited", "AARCS9999B", "27AARCS9999B1ZO", "Nagpur", "reddy@reddyagro.in", "+91 98765 43223", "monthly", 160),
        ("Krishnan IT Services", "Private Limited", "AAKCS2229B", "27AAKCS2229B1ZP", "Mumbai", "krishnan@krishnanit.in", "+91 98765 43224", "monthly", 50),
        ("Malhotra Real Estate", "Partnership", "AAMCS5559B", "27AAMCS5559B1ZQ", "Mumbai", "malhotra@malhotrare.in", "+91 98765 43225", "quarterly", 400),
        ("Tiwari Logistics", "Proprietorship", "AATCS8889B", "27AATCS8889B1ZR", "Pune", "tiwari@tiwarilogistics.in", "+91 98765 43226", "monthly", 190),
        ("Banerjee & Sons", "Partnership", "AABCS1119B", "27AABCS1119B1ZS", "Mumbai", "banerjee@banerjeesons.in", "+91 98765 43227", "monthly", 130),
        ("Pillai Textiles", "Proprietorship", "AAPCS4449B", "27AAPCS4449B1ZT", "Nashik", "pillai@pillaitextiles.in", "+91 98765 43228", "quarterly", 220),
        ("Chakraborty Foods", "Private Limited", "AACCS7779B", "27AACCS7779B1ZU", "Pune", "chakraborty@chakrafoods.in", "+91 98765 43229", "monthly", 85),
    ], start=0)
]


def _compliance_tasks() -> list[dict]:
    tasks = []
    types = ["GSTR1", "GSTR3B", "ITR", "TDS26Q"]
    statuses = ["pending", "in_progress", "filed", "overdue", "pending", "pending"]
    i = 0
    for client in SEED_CLIENTS[:10]:  # 10 tasks each for first 10 clients
        for ct in types[:2]:
            offset = (i % 6) - 2
            tasks.append(enrich_compliance_task({
                "id": f"sct-{i:03d}",
                "client_id": client["id"],
                "compliance_type": ct,
                "period_start": (today.replace(day=1) - timedelta(days=1)).replace(day=1).isoformat(),
                "period_end": (today.replace(day=1) - timedelta(days=1)).isoformat(),
                "due_date": (today + timedelta(days=offset * 3)).isoformat(),
                "status": statuses[i % len(statuses)],
                "assigned_to": DEMO_USERS[i % 3]["id"],
            }))
            i += 1
    # Fill to 100
    for j in range(i, 100):
        client = SEED_CLIENTS[j % 20]
        ct = types[j % len(types)]
        tasks.append(enrich_compliance_task({
            "id": f"sct-{j:03d}",
            "client_id": client["id"],
            "compliance_type": ct,
            "period_start": (today - timedelta(days=60)).isoformat(),
            "period_end": (today - timedelta(days=30)).isoformat(),
            "due_date": (today + timedelta(days=(j % 30) - 10)).isoformat(),
            "status": statuses[j % len(statuses)],
            "assigned_to": DEMO_USERS[j % 3]["id"],
        }))
    return tasks


def _tasks() -> list[dict]:
    titles = [
        "Collect invoices", "Verify GSTR-2B", "Prepare return data",
        "CA review", "Tax payment", "File return", "E-verify",
        "Issue TDS certificate", "Reconcile books", "Client confirmation",
    ]
    statuses = ["todo", "in_progress", "waiting_client", "review_required", "completed"]
    priorities = ["critical", "high", "medium", "low"]
    tasks = []
    for i in range(100):
        client = SEED_CLIENTS[i % 20]
        tasks.append({
            "id": f"st-{i:03d}",
            "client_id": client["id"],
            "title": f"{titles[i % len(titles)]} — {client['client_name']}",
            "description": f"Seed task {i} for {client['client_name']}",
            "status": statuses[i % len(statuses)],
            "priority": priorities[i % len(priorities)],
            "assigned_to": DEMO_USERS[i % 3]["id"],
            "due_date": (today + timedelta(days=(i % 30) - 5)).isoformat(),
            "completed_at": (today - timedelta(days=1)).isoformat() if statuses[i % len(statuses)] == "completed" else None,
            "created_at": (today - timedelta(days=30)).isoformat(),
            "updated_at": (today - timedelta(days=i % 10)).isoformat(),
        })
    return tasks


def _documents() -> list[dict]:
    doc_types = ["FORM16", "GST_INVOICE", "BANK_STATEMENT", "AIS", "FORM26AS", "TDS_CERTIFICATE"]
    review_statuses = ["pending_review", "approved", "approved", "rejected"]
    docs = []
    for i in range(50):
        client = SEED_CLIENTS[i % 20]
        dt = doc_types[i % len(doc_types)]
        docs.append({
            "id": f"sd-{i:03d}",
            "client_id": client["id"],
            "document_type": dt,
            "file_name": f"{dt.lower()}_{client['id']}_{i}.pdf",
            "file_path": f"/uploads/{client['id']}/{dt.lower()}_{i}.pdf",
            "financial_year": "2024-25",
            "review_status": review_statuses[i % len(review_statuses)],
            "confidence_score": round(0.75 + (i % 25) * 0.01, 2),
            "upload_date": (today - timedelta(days=i % 60)).isoformat(),
            "extracted_json": {"seed": True, "doc_type": dt},
        })
    return docs


SEED_COMPLIANCE_TASKS = _compliance_tasks()
SEED_TASKS = _tasks()
SEED_DOCUMENTS = _documents()


def get_seed_summary() -> dict:
    return {
        "firm": DEMO_FIRM["name"],
        "users": len(DEMO_USERS),
        "clients": len(SEED_CLIENTS),
        "compliance_tasks": len(SEED_COMPLIANCE_TASKS),
        "tasks": len(SEED_TASKS),
        "documents": len(SEED_DOCUMENTS),
    }
