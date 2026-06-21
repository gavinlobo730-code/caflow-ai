"""
Journal posting service (Phase 3.5) — the single Draft → Approve → Post path.

A journal lives as a DRAFT (is_posted=false, off-books) until a human with the
'approve' permission posts it. Posting enforces the FY lock, flips is_posted via
the DB-immutable transition (prevent_posted_journal_update allows draft→posted
exactly once), writes the audit trail, and fires any DEFERRED downstream action
recorded on the draft's source (e.g. bank settlement). Reports/Ledger key off
is_posted, so drafts never touch the books. Integer paise; firm-scoped.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from services.period_validation_service import period_validation_service
from services.timeline_service import timeline_service

_logger = logging.getLogger("caflow.journal_posting")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JournalPostingService:

    _SELECT = ("id, entry_date, reference_no, narration, entry_type, is_posted, status, "
               "source_type, source_id, created_by, created_at, posted_at, posted_by, "
               "journal_lines(account_id, debit_paise, credit_paise)")

    # ── Approval queue (Draft / Posted) ───────────────────────────────────────
    def list_journals(self, db, firm_id: str, client_id: Optional[str],
                      status: str = "draft") -> list[dict]:
        q = db.table("journal_entries").select(self._SELECT).eq("firm_id", firm_id).is_("deleted_at", "null")
        if client_id:
            q = q.eq("client_id", client_id)
        if status == "draft":
            q = q.eq("is_posted", False)
        elif status == "posted":
            q = q.eq("is_posted", True)
        rows = q.order("created_at", desc=True).execute().data or []
        return [self._summarise(r) for r in rows]

    def _summarise(self, r: dict) -> dict:
        lines = r.get("journal_lines") or []
        total_debit = sum(int(l.get("debit_paise") or 0) for l in lines)
        total_credit = sum(int(l.get("credit_paise") or 0) for l in lines)
        return {
            "id": r["id"], "entry_date": r.get("entry_date"),
            "reference_no": r.get("reference_no"), "narration": r.get("narration"),
            "entry_type": r.get("entry_type"),
            "source_type": r.get("source_type"), "source_id": r.get("source_id"),
            "created_by": r.get("created_by"), "created_at": r.get("created_at"),
            "is_posted": bool(r.get("is_posted")),
            "posted_at": r.get("posted_at"), "posted_by": r.get("posted_by"),
            "total_debit_paise": total_debit, "total_credit_paise": total_credit,
            "line_count": len(lines),
        }

    # ── Approve & post a draft ─────────────────────────────────────────────────
    def post_draft(self, db, firm_id: str, journal_id: str, actor_id: Optional[str] = None) -> dict:
        res = (db.table("journal_entries").select(self._SELECT)
               .eq("id", journal_id).eq("firm_id", firm_id).single().execute())
        je = res.data
        if not je:
            raise HTTPException(status_code=404, detail="Journal entry not found.")
        if je.get("deleted_at"):
            raise HTTPException(status_code=409, detail="Journal entry has been deleted.")
        if je.get("is_posted"):
            raise HTTPException(status_code=409, detail="Journal entry is already posted.")

        lines = je.get("journal_lines") or []
        total_debit = sum(int(l.get("debit_paise") or 0) for l in lines)
        total_credit = sum(int(l.get("credit_paise") or 0) for l in lines)
        if total_debit == 0 or total_debit != total_credit:
            raise HTTPException(status_code=422,
                                detail="Cannot post an unbalanced or empty journal entry.")

        entry_date = str(je["entry_date"])[:10]
        # FY lock (Companies Act §128 / firm policy) — never post into a closed period.
        period_validation_service.validate_posting_date(firm_id, entry_date)

        now = _now()
        db.table("journal_entries").update({
            "is_posted": True, "status": "posted", "posted_at": now,
            "posted_by": actor_id, "updated_at": now,
        }).eq("id", journal_id).eq("firm_id", firm_id).execute()

        self._audit(firm_id, journal_id, "approve", actor_id, {
            "is_posted": True, "source_type": je.get("source_type"),
            "source_id": je.get("source_id"),
        })
        try:
            timeline_service.log(je.get("client_id"), "accounting", "Journal Posted",
                                 f"Draft {je.get('reference_no') or journal_id[:8]} approved and posted to the ledger",
                                 "success", firm_id=firm_id, entity_type="journal_entry",
                                 entity_id=journal_id, actor_id=actor_id)
        except Exception:  # pragma: no cover - timeline must never block posting
            pass

        # Deferred downstream action — runs only now that the journal is on the books.
        settlement = self._dispatch_deferred(db, firm_id, je, journal_id, actor_id)
        return {"id": journal_id, "is_posted": True, "posted_at": now, "settlement": settlement}

    def _dispatch_deferred(self, db, firm_id, je, journal_id, actor_id) -> Optional[dict]:
        if je.get("source_type") == "bank_transaction" and je.get("source_id"):
            # Lazy import avoids a circular dependency (bank posting → this service).
            from services.bank_posting_service import bank_posting_service
            return bank_posting_service.settle_on_post(db, firm_id, je["source_id"], journal_id, actor_id)
        return None

    # ── Audit ───────────────────────────────────────────────────────────────────
    def _audit(self, firm_id, journal_id, action, actor_id, new_data) -> None:
        try:
            from services.audit_service import log_event
            log_event(firm_id, "journal_entry", journal_id, action, actor_id=actor_id,
                      new_data=new_data, metadata={"source": "journal_workflow"})
        except Exception:  # pragma: no cover - audit must never block
            pass


journal_posting_service = JournalPostingService()
