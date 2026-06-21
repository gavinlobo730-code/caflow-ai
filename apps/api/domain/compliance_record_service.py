"""
Compliance Record Engine.
Manages compliance records lifecycle: Not Started → Filed.
Risk scoring and client health scores.
"""
from datetime import date, timedelta
from typing import Optional

from core.exceptions import ValidationError, NotFoundError
from repositories.compliance_records_repository import compliance_records_repo
from repositories.client_repository import client_repo

# Valid status transitions. Phase 4.4 adds the terminal Filed -> Completed step
# (Module D progression: ... -> Ready To File -> Filed -> Completed).
VALID_TRANSITIONS: dict[str, list[str]] = {
    "Not Started": ["Awaiting Documents", "In Progress", "Overdue"],
    "Awaiting Documents": ["In Progress", "Overdue"],
    "In Progress": ["Ready For Review", "Awaiting Documents", "Overdue"],
    "Ready For Review": ["Ready To File", "In Progress"],
    "Ready To File": ["Filed"],
    "Filed": ["Completed"],
    "Completed": [],
    "Overdue": ["In Progress", "Awaiting Documents"],
}


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
    due_d = date.fromisoformat(due[:10])
    days_until_due = (due_d - today_d).days

    if status == "Overdue" or days_until_due < 0:
        return 90  # CRITICAL

    if days_until_due <= 7:
        return 75  # HIGH

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


def _audit_transition(record: dict, old_status: str, new_status: str,
                      firm_id: Optional[str], actor: Optional[dict]) -> None:
    """Record a compliance status transition in the firm audit log + client timeline.
    Best-effort: never raises (compliance work must not be blocked by logging)."""
    actor = actor or {}
    try:
        from services.audit_service import log_event
        log_event(firm_id or record.get("firm_id") or "", "compliance_record", record["id"],
                  "status_change", actor_id=actor.get("auth_user_id"), actor_email=actor.get("email"),
                  old_data={"status": old_status}, new_data={"status": new_status},
                  metadata={"compliance_type": record.get("compliance_type"),
                            "obligation_type": record.get("obligation_type")})
    except Exception:  # pragma: no cover - audit is non-fatal
        pass
    try:
        from services.timeline_service import timeline_service
        timeline_service.log(record.get("client_id", ""), "compliance",
                             f"Compliance {new_status}",
                             f"{record.get('obligation_type') or record.get('compliance_type','')} "
                             f"{record.get('period_label','')}: {old_status} → {new_status}",
                             "success" if new_status in ("Filed", "Completed") else "info",
                             firm_id=firm_id or record.get("firm_id", ""),
                             entity_type="compliance_record", entity_id=record["id"])
    except Exception:  # pragma: no cover
        pass


class ComplianceRecordService:

    def list_records(
        self,
        firm_id: Optional[str] = None,
        client_id: Optional[str] = None,
        status: Optional[str] = None,
        compliance_type: Optional[str] = None,
    ) -> list[dict]:
        records = compliance_records_repo.find_all(
            firm_id=firm_id,
            client_id=client_id,
            status=status,
            compliance_type=compliance_type,
        )
        return [{**r, "risk_score": _compute_risk_score(r)} for r in records]

    def get_record(self, record_id: str, firm_id: Optional[str] = None) -> dict:
        r = compliance_records_repo.find_by_id(record_id)
        if not r:
            raise NotFoundError("ComplianceRecord", record_id)
        # Tenant isolation: reject cross-firm access
        if firm_id and r.get("firm_id") and r["firm_id"] != firm_id:
            raise NotFoundError("ComplianceRecord", record_id)
        return {**r, "risk_score": _compute_risk_score(r)}

    def create_record(self, data: dict, firm_id: str) -> dict:
        payload = {
            "firm_id": firm_id,  # Always from current_user, never from request body
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
        }
        record = compliance_records_repo.create(payload)
        return {**record, "risk_score": _compute_risk_score(record)}

    def update_record(self, record_id: str, data: dict, firm_id: Optional[str] = None,
                      actor: Optional[dict] = None) -> dict:
        record = self.get_record(record_id, firm_id=firm_id)
        updates: dict = {}
        old_status = record["status"]
        new_status = None

        if "status" in data:
            new_status = data["status"]
            allowed = VALID_TRANSITIONS.get(old_status, [])
            if new_status not in allowed:
                raise ValidationError(
                    "status",
                    f"Cannot transition from '{old_status}' to '{new_status}'. Allowed: {allowed}"
                )
            updates["status"] = new_status
            if new_status == "Filed" and not record.get("filed_date"):
                updates["filed_date"] = date.today().isoformat()
            if new_status == "Completed" and not record.get("completed_at"):
                updates["completed_at"] = date.today().isoformat()

        for field in ("notes", "assigned_to", "priority", "acknowledgement_no"):
            if field in data:
                updates[field] = data[field]

        updated = compliance_records_repo.update(record_id, updates)
        if not updated:
            raise NotFoundError("ComplianceRecord", record_id)

        # Module D/H: every status transition is audited + timelined (best-effort,
        # never blocks the mutation). Reuses the firm-wide audit_log + client timeline.
        if new_status and new_status != old_status:
            _audit_transition(record, old_status, new_status, firm_id, actor)
        return {**updated, "risk_score": _compute_risk_score(updated)}

    def get_client_health_score(self, client_id: str, firm_id: Optional[str] = None) -> dict:
        """Client health score 0-100. Start at 100, subtract for risks. Integer arithmetic only."""
        client = client_repo.find_by_id(client_id)
        if not client:
            raise NotFoundError("Client", client_id)
        # Tenant isolation
        if firm_id and client.get("firm_id") and client["firm_id"] != firm_id:
            raise NotFoundError("Client", client_id)

        records = self.list_records(client_id=client_id, firm_id=firm_id)
        overdue_records = [r for r in records if r["status"] == "Overdue"]
        high_risk_records = [r for r in records if r["risk_score"] >= 70 and r["status"] != "Overdue"]
        missing_docs = len([r for r in records if r["status"] == "Awaiting Documents"])

        score: int = 100
        breakdown = []

        for _ in overdue_records:
            score -= 20
            breakdown.append({"label": "Overdue compliance record", "deduction": 20})

        for _ in high_risk_records:
            score -= 10
            breakdown.append({"label": "High-risk compliance record", "deduction": 10})

        for _ in range(missing_docs):
            score -= 5
            breakdown.append({"label": "Missing/awaited document", "deduction": 5})

        score = max(0, score)
        risk_level = (
            "critical" if score < 40 else
            "high" if score < 60 else
            "medium" if score < 80 else
            "low"
        )

        return {
            "client_id": client_id,
            "client_name": client["client_name"],
            "health_score": score,
            "risk_level": risk_level,
            "overdue_records": len(overdue_records),
            "missing_documents": missing_docs,
            "breakdown": breakdown,
        }

    def get_firm_summary(self, firm_id: Optional[str] = None, allowed_client_ids: Optional[set] = None) -> dict:
        """Firm-wide compliance summary. F2: when allowed_client_ids is provided
        (a non firm-wide caller), aggregate only over those assigned clients;
        None ⇒ firm-wide (unscoped). Default None preserves existing callers."""
        all_records = self.list_records(firm_id=firm_id)
        if allowed_client_ids is not None:
            all_records = [r for r in all_records if str(r.get("client_id")) in allowed_client_ids]
        today_d = date.today()
        week_end = (today_d + timedelta(days=7)).isoformat()
        today_str = today_d.isoformat()
        this_month_start = today_d.replace(day=1).isoformat()

        due_this_week = len([
            r for r in all_records
            if r["status"] != "Filed" and today_str <= r["due_date"] <= week_end
        ])
        overdue = len([r for r in all_records if r["status"] == "Overdue"])
        ready_for_review = len([r for r in all_records if r["status"] == "Ready For Review"])
        ready_to_file = len([r for r in all_records if r["status"] == "Ready To File"])
        filed_this_month = len([
            r for r in all_records
            if r["status"] == "Filed" and (r.get("filed_date") or "") >= this_month_start
        ])

        clients = client_repo.find_all(firm_id=firm_id)
        if allowed_client_ids is not None:
            clients = [c for c in clients if str(c.get("id")) in allowed_client_ids]
        high_risk_clients = sum(
            1 for c in clients
            if self.get_client_health_score(c["id"], firm_id=firm_id)["health_score"] < 50
        )

        return {
            "due_this_week": due_this_week,
            "overdue": overdue,
            "ready_for_review": ready_for_review,
            "ready_to_file": ready_to_file,
            "filed_this_month": filed_this_month,
            "high_risk_clients": high_risk_clients,
        }


compliance_record_service = ComplianceRecordService()
