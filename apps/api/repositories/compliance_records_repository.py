import os
import uuid
from datetime import date
from typing import Optional
from core.db_paging import fetch_all
from repositories.base import BaseRepository

_USE_MOCK = not os.environ.get("SUPABASE_URL")

if _USE_MOCK:
    from mock_data import MOCK_COMPLIANCE_RECORDS


def _get_db():
    from core.supabase_client import get_supabase
    return get_supabase()


class ComplianceRecordsRepository(BaseRepository[dict]):

    def find_by_id(self, id: str) -> Optional[dict]:
        if _USE_MOCK:
            return next((r for r in MOCK_COMPLIANCE_RECORDS
                        if r["id"] == id and not r.get("deleted_at")), None)
        result = _get_db().table("compliance_records").select("*").eq("id", id).is_("deleted_at", "null").maybe_single().execute()
        return result.data

    def find_all(
        self,
        firm_id: Optional[str] = None,
        client_id: Optional[str] = None,
        status: Optional[str] = None,
        compliance_type: Optional[str] = None,
        exclude_statuses: Optional[list[str]] = None,
    ) -> list[dict]:
        if _USE_MOCK:
            # Mirrors the real branch's unconditional `.is_("deleted_at",
            # "null")` — a soft-deleted row (compliance_obligation_service's
            # GST-frequency reconciliation is the first writer) must not keep
            # reappearing as "existing" on the next generation run, in mock
            # mode any more than in production.
            records = [r for r in MOCK_COMPLIANCE_RECORDS if not r.get("deleted_at")]
            if firm_id:
                records = [r for r in records if r.get("firm_id") == firm_id]
            if client_id:
                records = [r for r in records if r["client_id"] == client_id]
            if status:
                records = [r for r in records if r["status"] == status]
            if compliance_type:
                records = [r for r in records if r["compliance_type"] == compliance_type]
            if exclude_statuses:
                records = [r for r in records if r.get("status") not in exclude_statuses]
            return records

        def make_query():
            q = _get_db().table("compliance_records").select("*").is_("deleted_at", "null")
            if firm_id:
                q = q.eq("firm_id", firm_id)
            if client_id:
                q = q.eq("client_id", client_id)
            if status:
                q = q.eq("status", status)
            if compliance_type:
                q = q.eq("compliance_type", compliance_type)
            if exclude_statuses:
                q = q.not_.in_("status", exclude_statuses)
            return q

        # PostgREST caps an unpaged read at ~1000 rows with no signal that it
        # did — a firm-wide read (no client_id) crosses that silently once a
        # practice's compliance_records history is large enough, and every
        # caller (the firm GST/compliance tracker, risk scoring, the AI
        # copilot's own reads) would then work from a truncated set with no
        # indication anything was missing. core.db_paging.fetch_all reads every
        # matching row in keyset pages instead. It orders by `key` internally,
        # so the caller's own `due_date` ordering is restored here, over the
        # complete result rather than inside the paged query.
        rows = fetch_all(make_query, key="id", label="compliance_records.find_all")
        rows.sort(key=lambda r: (str(r.get("due_date") or ""), r.get("id") or ""))
        return rows

    def count_all(self, firm_id: Optional[str] = None, client_id: Optional[str] = None) -> int:
        """Lightweight row count (no full-row fetch) — for metrics that need a
        total across the firm's entire history without paying to transfer it."""
        if _USE_MOCK:
            return len(self.find_all(firm_id=firm_id, client_id=client_id))
        query = _get_db().table("compliance_records").select("id", count="exact").is_("deleted_at", "null")
        if firm_id:
            query = query.eq("firm_id", firm_id)
        if client_id:
            query = query.eq("client_id", client_id)
        result = query.execute()
        return result.count or 0

    def create(self, data: dict) -> dict:
        if _USE_MOCK:
            record = {"id": str(uuid.uuid4()), **data, "created_at": self.now_iso(), "updated_at": self.now_iso()}
            MOCK_COMPLIANCE_RECORDS.append(record)
            return record
        payload = {k: v for k, v in data.items() if v is not None}
        payload.setdefault("created_at", self.now_iso())
        payload.setdefault("updated_at", self.now_iso())
        result = _get_db().table("compliance_records").insert(payload).execute()
        return result.data[0]

    def update(self, id: str, data: dict) -> Optional[dict]:
        if _USE_MOCK:
            record = self.find_by_id(id)
            if not record:
                return None
            record.update({**data, "updated_at": self.now_iso()})
            return record
        payload = {k: v for k, v in data.items() if v is not None}
        payload["updated_at"] = self.now_iso()
        result = _get_db().table("compliance_records").update(payload).eq("id", id).execute()
        return result.data[0] if result.data else None

    def soft_delete(self, id: str) -> bool:
        """Mark one obligation deleted without erasing it — the row the audit
        trail and any reconciliation gap still name stays readable by id, it
        simply stops being "existing" for find_all/find_by_id and stops
        occupying migrations 108/168's partial unique index (`WHERE
        deleted_at IS NULL`). Used by
        compliance_obligation_service._reconcile_stale_gst_obligations to
        free a stale monthly obligation's period_start so the correctly
        shaped quarterly (or vice versa) one can be inserted there."""
        now = self.now_iso()
        if _USE_MOCK:
            record = next((r for r in MOCK_COMPLIANCE_RECORDS if r["id"] == id), None)
            if not record:
                return False
            record["deleted_at"] = now
            record["updated_at"] = now
            return True
        result = (
            _get_db().table("compliance_records")
            .update({"deleted_at": now, "updated_at": now})
            .eq("id", id)
            .execute()
        )
        return bool(result.data)


compliance_records_repo = ComplianceRecordsRepository()
