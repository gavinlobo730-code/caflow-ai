"""
Manual Journal service (Phase 0.5 hardening).

Production manual journals post through the SAME posting kernel as every other
accounting workflow — phase2_journal_service._create_journal — so there is no
alternative posting path. Double-entry balance, the journal_entries CHECK
constraint, and FY-lock validation all apply identically.

Capabilities:
  * unlimited balanced lines (validated by the model + re-checked here + asserted
    by the kernel),
  * draft (off-books) or posted (to the ledger) status,
  * narration + per-line narration,
  * attachments (supporting documents) persisted on the entry,
  * audit trail (the router emits log_event; posting/approval go through
    journal_posting_service which audits too),
  * approval-ready: a draft is later posted via journal_posting_service.post_draft
    (accounting.approve), and any posted manual journal can be reversed via the
    shared reversal endpoint.

Integer paise only; firm-scoped; never auto-submits anything externally.
"""
from __future__ import annotations

import uuid
import logging
from typing import Optional

from fastapi import HTTPException

from services.phase2_journal_service import phase2_journal_service
from services.period_validation_service import period_validation_service

_logger = logging.getLogger("caflow.manual_journal")

# Identifies entries created through the manual-journal workflow (vs auto-posted
# invoices/receipts/bank/etc.) for the approval queue and audit.
MANUAL_SOURCE = "manual"

ALLOWED_ENTRY_TYPES = {
    "Journal", "Contra", "Payment", "Receipt", "Sales", "Purchase", "Opening",
}


class ManualJournalService:
    """Create manual journal entries via the single posting kernel."""

    def create(self, db, firm_id: str, data: dict, actor_id: Optional[str] = None) -> dict:
        """Create a manual journal (draft or posted) through _create_journal.

        Args:
            db:       Supabase client (production).
            firm_id:  Tenant firm id.
            data:     {client_id, entry_date, reference_no?, narration?, entry_type?,
                       status?, attachments?, lines:[{account_id,debit_paise,credit_paise,narration?}]}
            actor_id: INTERNAL users.id (journal_entries.created_by FKs to users.id),
                      never the Supabase auth id.

        Returns a summary of the created entry. Raises HTTPException(422) on invalid
        input and HTTPException(422) (via period validation) on a locked FY.
        """
        client_id = data.get("client_id")
        entry_date = data.get("entry_date")
        if not client_id or not entry_date:
            raise HTTPException(status_code=422, detail="client_id and entry_date are required.")

        entry_type = data.get("entry_type") or "Journal"
        if entry_type not in ALLOWED_ENTRY_TYPES:
            raise HTTPException(status_code=422, detail=f"Invalid entry_type '{entry_type}'.")

        status = (data.get("status") or "draft").lower()
        if status not in ("draft", "posted"):
            raise HTTPException(status_code=422, detail="status must be 'draft' or 'posted'.")
        is_posted = status == "posted"

        lines = data.get("lines") or []
        if len(lines) < 2:
            raise HTTPException(status_code=422, detail="A journal entry must have at least 2 lines.")
        total_debit = sum(int(l.get("debit_paise") or 0) for l in lines)
        total_credit = sum(int(l.get("credit_paise") or 0) for l in lines)
        if total_debit == 0:
            raise HTTPException(status_code=422, detail="A journal entry cannot be empty (zero value).")
        if total_debit != total_credit:
            raise HTTPException(
                status_code=422,
                detail=f"Unbalanced entry: debit {total_debit} paise != credit {total_credit} paise.",
            )

        # FY lock only bites when the entry actually goes onto the books now. A draft
        # is validated later, when it is approved/posted (journal_posting_service).
        if is_posted:
            period_validation_service.validate_posting_date(firm_id, entry_date)

        # A stable, unique reference keeps the kernel's dedup (ref+date+client) from
        # ever collapsing two distinct manual journals that share a blank reference.
        reference_no = data.get("reference_no") or f"MJ-{uuid.uuid4().hex[:8].upper()}"

        kernel_lines = [{
            "account_id": l["account_id"],
            "debit_paise": int(l.get("debit_paise") or 0),
            "credit_paise": int(l.get("credit_paise") or 0),
            "narration": l.get("narration") or "",
        } for l in lines]

        entry_id = phase2_journal_service._create_journal(
            db=db,
            firm_id=firm_id,
            client_id=client_id,
            entry_date=entry_date,
            reference_no=reference_no,
            narration=data.get("narration") or "",
            entry_type=entry_type,
            lines=kernel_lines,
            is_posted=is_posted,
            source_type=MANUAL_SOURCE,
            created_by=actor_id,
            attachments=data.get("attachments") or [],
        )

        return {
            "id": entry_id,
            "client_id": client_id,
            "entry_date": entry_date,
            "reference_no": reference_no,
            "narration": data.get("narration") or "",
            "entry_type": entry_type,
            "is_posted": is_posted,
            "status": "posted" if is_posted else "draft",
            "source_type": MANUAL_SOURCE,
            "attachments": data.get("attachments") or [],
            "total_debit_paise": total_debit,
            "total_credit_paise": total_credit,
            "line_count": len(kernel_lines),
        }


manual_journal_service = ManualJournalService()
