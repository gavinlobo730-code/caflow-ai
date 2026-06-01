"""
Compliance Record Engine.
Manages compliance records lifecycle: Not Started → Filed.
Risk scoring and client health scores.
"""
from datetime import date, timedelta, datetime
from typing import Optional
import uuid as _uuid

from core.exceptions import ValidationError, NotFoundError
from mock_data import MOCK_CLIENTS, MOCK_TASKS

# Valid status transitions
VALID_TRANSITIONS: dict[str, list[str]] = {
    "Not Started": ["Awaiting Documents", "In Progress", "Overdue"],
    "Awaiting Documents": ["In Progress", "Overdue"],
    "In Progress": ["Ready For Review", "Awaiting Documents", "Overdue"],
    "Ready For Review": ["Ready To File", "In Progress"],
    "Ready To File": ["Filed"],
    "Filed": [],
    "Overdue": ["In Progress", "Awaiting Documents"],
}

today = date.today()

# Seed: each client gets GST, Income Tax, TDS records
def _seed_records() -> list[dict]:
    records = []
    client_ids = [c["id"] for c in MOCK_CLIENTS]
    client_names = {c["id"]: c["client_name"] for c in MOCK_CLIENTS}

    # c-001 Sharma Enterprises
    records += [
        {
            "id": "cr-001", "firm_id": "firm-001", "client_id": "c-001",
            "client_name": "Sharma Enterprises", "compliance_type": "GST",
            "period_label": "Apr 2025", "period_start": "2025-04-01", "period_end": "2025-04-30",
            "status": "In Progress", "due_date": (today + timedelta(days=3)).isoformat(),
            "assigned_to": "tm-001", "priority": "critical", "notes": None,
            "filed_date": None, "acknowledgement_no": None,
            "created_at": (today - timedelta(days=10)).isoformat(),
            "updated_at": (today - timedelta(days=1)).isoformat(),
        },
        {
            "id": "cr-002", "firm_id": "firm-001", "client_id": "c-001",
            "client_name": "Sharma Enterprises", "compliance_type": "Income Tax",
            "period_label": "FY 2024-25", "period_start": "2024-04-01", "period_end": "2025-03-31",
            "status": "Awaiting Documents", "due_date": "2025-07-31",
            "assigned_to": "tm-001", "priority": "medium", "notes": None,
            "filed_date": None, "acknowledgement_no": None,
            "created_at": (today - timedelta(days=20)).isoformat(),
            "updated_at": (today - timedelta(days=5)).isoformat(),
        },
        {
            "id": "cr-003", "firm_id": "firm-001", "client_id": "c-001",
            "client_name": "Sharma Enterprises", "compliance_type": "TDS",
            "period_label": "Q4 FY 2024-25", "period_start": "2025-01-01", "period_end": "2025-03-31",
            "status": "Filed", "due_date": "2025-05-31",
            "assigned_to": "tm-001", "priority": "low", "notes": None,
            "filed_date": "2025-05-28", "acknowledgement_no": "TDS/2025/001",
            "created_at": (today - timedelta(days=60)).isoformat(),
            "updated_at": (today - timedelta(days=3)).isoformat(),
        },
    ]

    # c-002 Patel & Sons
    records += [
        {
            "id": "cr-004", "firm_id": "firm-001", "client_id": "c-002",
            "client_name": "Patel & Sons", "compliance_type": "GST",
            "period_label": "Apr 2025", "period_start": "2025-04-01", "period_end": "2025-04-30",
            "status": "Awaiting Documents", "due_date": (today + timedelta(days=8)).isoformat(),
            "assigned_to": "tm-001", "priority": "high", "notes": "Waiting for purchase invoices",
            "filed_date": None, "acknowledgement_no": None,
            "created_at": (today - timedelta(days=8)).isoformat(),
            "updated_at": (today - timedelta(days=2)).isoformat(),
        },
        {
            "id": "cr-005", "firm_id": "firm-001", "client_id": "c-002",
            "client_name": "Patel & Sons", "compliance_type": "Income Tax",
            "period_label": "FY 2024-25", "period_start": "2024-04-01", "period_end": "2025-03-31",
            "status": "Not Started", "due_date": "2025-07-31",
            "assigned_to": "tm-001", "priority": "medium", "notes": None,
            "filed_date": None, "acknowledgement_no": None,
            "created_at": (today - timedelta(days=15)).isoformat(),
            "updated_at": (today - timedelta(days=15)).isoformat(),
        },
        {
            "id": "cr-006", "firm_id": "firm-001", "client_id": "c-002",
            "client_name": "Patel & Sons", "compliance_type": "TDS",
            "period_label": "Q4 FY 2024-25", "period_start": "2025-01-01", "period_end": "2025-03-31",
            "status": "Filed", "due_date": "2025-05-31",
            "assigned_to": "tm-001", "priority": "low", "notes": None,
            "filed_date": "2025-05-30", "acknowledgement_no": "TDS/2025/002",
            "created_at": (today - timedelta(days=70)).isoformat(),
            "updated_at": (today - timedelta(days=1)).isoformat(),
        },
    ]

    # c-003 Mehta Consulting
    records += [
        {
            "id": "cr-007", "firm_id": "firm-001", "client_id": "c-003",
            "client_name": "Mehta Consulting", "compliance_type": "GST",
            "period_label": "Mar 2025", "period_start": "2025-03-01", "period_end": "2025-03-31",
            "status": "Overdue", "due_date": (today - timedelta(days=15)).isoformat(),
            "assigned_to": "tm-001", "priority": "critical", "notes": "ITC mismatch needs resolution",
            "filed_date": None, "acknowledgement_no": None,
            "created_at": (today - timedelta(days=30)).isoformat(),
            "updated_at": (today - timedelta(days=5)).isoformat(),
        },
        {
            "id": "cr-008", "firm_id": "firm-001", "client_id": "c-003",
            "client_name": "Mehta Consulting", "compliance_type": "Income Tax",
            "period_label": "FY 2024-25", "period_start": "2024-04-01", "period_end": "2025-03-31",
            "status": "Awaiting Documents", "due_date": "2025-07-31",
            "assigned_to": "tm-001", "priority": "medium", "notes": "Waiting for bank statements",
            "filed_date": None, "acknowledgement_no": None,
            "created_at": (today - timedelta(days=25)).isoformat(),
            "updated_at": (today - timedelta(days=16)).isoformat(),  # 16 days waiting
        },
        {
            "id": "cr-009", "firm_id": "firm-001", "client_id": "c-003",
            "client_name": "Mehta Consulting", "compliance_type": "TDS",
            "period_label": "Q4 FY 2024-25", "period_start": "2025-01-01", "period_end": "2025-03-31",
            "status": "Overdue", "due_date": (today - timedelta(days=10)).isoformat(),
            "assigned_to": "tm-001", "priority": "critical", "notes": None,
            "filed_date": None, "acknowledgement_no": None,
            "created_at": (today - timedelta(days=40)).isoformat(),
            "updated_at": (today - timedelta(days=10)).isoformat(),
        },
    ]

    # c-004 Desai Traders
    records += [
        {
            "id": "cr-010", "firm_id": "firm-001", "client_id": "c-004",
            "client_name": "Desai Traders", "compliance_type": "GST",
            "period_label": "Apr 2025", "period_start": "2025-04-01", "period_end": "2025-04-30",
            "status": "Ready To File", "due_date": (today + timedelta(days=5)).isoformat(),
            "assigned_to": "tm-001", "priority": "high", "notes": None,
            "filed_date": None, "acknowledgement_no": None,
            "created_at": (today - timedelta(days=12)).isoformat(),
            "updated_at": (today - timedelta(days=1)).isoformat(),
        },
        {
            "id": "cr-011", "firm_id": "firm-001", "client_id": "c-004",
            "client_name": "Desai Traders", "compliance_type": "Income Tax",
            "period_label": "FY 2024-25", "period_start": "2024-04-01", "period_end": "2025-03-31",
            "status": "Ready For Review", "due_date": "2025-07-31",
            "assigned_to": "tm-001", "priority": "medium", "notes": None,
            "filed_date": None, "acknowledgement_no": None,
            "created_at": (today - timedelta(days=18)).isoformat(),
            "updated_at": (today - timedelta(days=2)).isoformat(),
        },
        {
            "id": "cr-012", "firm_id": "firm-001", "client_id": "c-004",
            "client_name": "Desai Traders", "compliance_type": "TDS",
            "period_label": "Q4 FY 2024-25", "period_start": "2025-01-01", "period_end": "2025-03-31",
            "status": "Filed",
            "due_date": "2025-05-31",
            "assigned_to": "tm-001", "priority": "low", "notes": None,
            "filed_date": "2025-05-20", "acknowledgement_no": "TDS/2025/004",
            "created_at": (today - timedelta(days=65)).isoformat(),
            "updated_at": (today - timedelta(days=11)).isoformat(),
        },
    ]

    # c-005 Joshi Textiles
    records += [
        {
            "id": "cr-013", "firm_id": "firm-001", "client_id": "c-005",
            "client_name": "Joshi Textiles", "compliance_type": "GST",
            "period_label": "Apr 2025", "period_start": "2025-04-01", "period_end": "2025-04-30",
            "status": "In Progress", "due_date": (today + timedelta(days=6)).isoformat(),
            "assigned_to": "tm-001", "priority": "high", "notes": None,
            "filed_date": None, "acknowledgement_no": None,
            "created_at": (today - timedelta(days=9)).isoformat(),
            "updated_at": (today - timedelta(days=1)).isoformat(),
        },
        {
            "id": "cr-014", "firm_id": "firm-001", "client_id": "c-005",
            "client_name": "Joshi Textiles", "compliance_type": "Income Tax",
            "period_label": "FY 2024-25", "period_start": "2024-04-01", "period_end": "2025-03-31",
            "status": "Awaiting Documents", "due_date": (today + timedelta(days=12)).isoformat(),
            "assigned_to": "tm-001", "priority": "high", "notes": "Form 16 pending",
            "filed_date": None, "acknowledgement_no": None,
            "created_at": (today - timedelta(days=14)).isoformat(),
            "updated_at": (today - timedelta(days=7)).isoformat(),
        },
        {
            "id": "cr-015", "firm_id": "firm-001", "client_id": "c-005",
            "client_name": "Joshi Textiles", "compliance_type": "TDS",
            "period_label": "Q4 FY 2024-25", "period_start": "2025-01-01", "period_end": "2025-03-31",
            "status": "Filed", "due_date": "2025-05-31",
            "assigned_to": "tm-001", "priority": "low", "notes": None,
            "filed_date": "2025-05-25", "acknowledgement_no": "TDS/2025/005",
            "created_at": (today - timedelta(days=60)).isoformat(),
            "updated_at": (today - timedelta(days=6)).isoformat(),
        },
    ]
    return records


MOCK_COMPLIANCE_RECORDS: list[dict] = _seed_records()
COMPLIANCE_RECORD_INDEX: dict[str, dict] = {r["id"]: r for r in MOCK_COMPLIANCE_RECORDS}


def _compute_risk_score(record: dict) -> int:
    """Compute risk score (0-100) integer. Never float."""
    status = record["status"]
    due = record["due_date"]
    updated = record.get("updated_at", record["created_at"])

    if status == "Filed":
        return 0
    if status == "Ready To File":
        return 20

    today_d = date.today()
    due_d = date.fromisoformat(due)
    days_until_due = (due_d - today_d).days

    if status == "Overdue" or days_until_due < 0:
        return 90  # CRITICAL

    if days_until_due <= 7:
        return 75  # HIGH

    # Check how long it's been in Awaiting Documents
    if status == "Awaiting Documents":
        try:
            updated_d = date.fromisoformat(updated[:10])
            days_waiting = (today_d - updated_d).days
            if days_waiting >= 14:
                return 60  # AT RISK
        except (ValueError, TypeError):
            pass

    if status in ("Not Started", "In Progress"):
        if days_until_due <= 14:
            return 50
        return 25

    return 30


class ComplianceRecordService:

    def list_records(
        self,
        client_id: Optional[str] = None,
        status: Optional[str] = None,
        compliance_type: Optional[str] = None,
    ) -> list[dict]:
        records = list(MOCK_COMPLIANCE_RECORDS)
        if client_id:
            records = [r for r in records if r["client_id"] == client_id]
        if status:
            records = [r for r in records if r["status"] == status]
        if compliance_type:
            records = [r for r in records if r["compliance_type"] == compliance_type]
        return [{**r, "risk_score": _compute_risk_score(r)} for r in records]

    def get_record(self, record_id: str) -> dict:
        if record_id not in COMPLIANCE_RECORD_INDEX:
            raise NotFoundError("ComplianceRecord", record_id)
        r = COMPLIANCE_RECORD_INDEX[record_id]
        return {**r, "risk_score": _compute_risk_score(r)}

    def create_record(self, data: dict) -> dict:
        record_id = f"cr-{_uuid.uuid4().hex[:8]}"
        now = datetime.now().isoformat()
        record = {
            "id": record_id,
            "firm_id": data.get("firm_id", "firm-001"),
            "client_id": data["client_id"],
            "client_name": data.get("client_name"),
            "compliance_type": data["compliance_type"],
            "period_label": data.get("period_label", ""),
            "period_start": data.get("period_start", ""),
            "period_end": data.get("period_end", ""),
            "status": data.get("status", "Not Started"),
            "due_date": data["due_date"],
            "assigned_to": data.get("assigned_to"),
            "priority": data.get("priority", "medium"),
            "notes": data.get("notes"),
            "filed_date": None,
            "acknowledgement_no": None,
            "created_at": now,
            "updated_at": now,
        }
        MOCK_COMPLIANCE_RECORDS.append(record)
        COMPLIANCE_RECORD_INDEX[record_id] = record
        return {**record, "risk_score": _compute_risk_score(record)}

    def update_record(self, record_id: str, data: dict) -> dict:
        record = self.get_record(record_id)
        raw = COMPLIANCE_RECORD_INDEX[record_id]

        if "status" in data:
            new_status = data["status"]
            current_status = raw["status"]
            allowed = VALID_TRANSITIONS.get(current_status, [])
            if new_status not in allowed:
                raise ValidationError(
                    "status",
                    f"Cannot transition from '{current_status}' to '{new_status}'. Allowed: {allowed}"
                )
            raw["status"] = new_status
            if new_status == "Filed" and not raw.get("filed_date"):
                raw["filed_date"] = date.today().isoformat()

        for field in ("notes", "assigned_to", "priority", "acknowledgement_no"):
            if field in data:
                raw[field] = data[field]

        raw["updated_at"] = datetime.now().isoformat()
        return {**raw, "risk_score": _compute_risk_score(raw)}

    def get_client_health_score(self, client_id: str) -> dict:
        """Client health score 0-100. Start at 100, subtract for risks."""
        # Find client
        client = next((c for c in MOCK_CLIENTS if c["id"] == client_id), None)
        if not client:
            raise NotFoundError("Client", client_id)

        records = self.list_records(client_id=client_id)
        overdue_records = [r for r in records if r["status"] == "Overdue"]
        high_risk_records = [r for r in records if r["risk_score"] >= 70 and r["status"] != "Overdue"]

        # Count missing documents: records in Awaiting Documents status
        missing_docs = len([r for r in records if r["status"] == "Awaiting Documents"])

        # Count overdue tasks for this client
        overdue_tasks = [t for t in MOCK_TASKS if t.get("client_id") == client_id and
                         t.get("due_date", "9999") < date.today().isoformat() and
                         t.get("status") != "completed"]

        breakdown = []
        score: int = 100  # Start at 100, subtract integers only

        for _ in overdue_records:
            score -= 20
            breakdown.append({"label": "Overdue compliance record", "deduction": 20})

        for _ in high_risk_records:
            score -= 10
            breakdown.append({"label": "High-risk compliance record", "deduction": 10})

        for _ in range(missing_docs):
            score -= 5
            breakdown.append({"label": "Missing/awaited document", "deduction": 5})

        for _ in overdue_tasks:
            score -= 5
            breakdown.append({"label": "Overdue task", "deduction": 5})

        score = max(0, score)

        risk_level = (
            "critical" if score < 40
            else "high" if score < 60
            else "medium" if score < 80
            else "low"
        )

        return {
            "client_id": client_id,
            "client_name": client["client_name"],
            "health_score": score,
            "risk_level": risk_level,
            "overdue_records": len(overdue_records),
            "overdue_tasks": len(overdue_tasks),
            "missing_documents": missing_docs,
            "breakdown": breakdown,
        }

    def get_firm_summary(self) -> dict:
        """Firm-wide compliance summary."""
        all_records = self.list_records()
        today_d = date.today()
        week_end = (today_d + timedelta(days=7)).isoformat()
        today_str = today_d.isoformat()
        this_month_start = today_d.replace(day=1).isoformat()

        due_this_week = len([
            r for r in all_records
            if r["status"] not in ("Filed",) and today_str <= r["due_date"] <= week_end
        ])
        overdue = len([r for r in all_records if r["status"] == "Overdue"])
        ready_for_review = len([r for r in all_records if r["status"] == "Ready For Review"])
        ready_to_file = len([r for r in all_records if r["status"] == "Ready To File"])
        filed_this_month = len([
            r for r in all_records
            if r["status"] == "Filed" and r.get("filed_date", "") >= this_month_start
        ])

        # High-risk clients: health_score < 50
        high_risk_clients = 0
        for client in MOCK_CLIENTS:
            hs = self.get_client_health_score(client["id"])
            if hs["health_score"] < 50:
                high_risk_clients += 1

        return {
            "due_this_week": due_this_week,
            "overdue": overdue,
            "ready_for_review": ready_for_review,
            "ready_to_file": ready_to_file,
            "filed_this_month": filed_this_month,
            "high_risk_clients": high_risk_clients,
        }


compliance_record_service = ComplianceRecordService()
