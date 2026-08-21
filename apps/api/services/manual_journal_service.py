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


    # ── read one ─────────────────────────────────────────────────────────────

    def get(self, db, firm_id: str, entry_id: str) -> dict:
        """One entry with its lines, plus whether it may still be edited.

        `lock_reason` is the whole point of returning more than the row: the
        editor has to know BEFORE the CA types anything whether this period is
        still open, and "why not" is more use than "no". It is resolved by the
        same database function the write path enforces with, so the screen and
        the ledger cannot disagree about what is editable.
        """
        rows = (db.table("journal_entries")
                .select("id, client_id, entry_date, reference_no, narration, entry_type, "
                        "is_posted, is_reversed, source_type, created_at, "
                        "lines:journal_lines(id, account_id, debit_paise, credit_paise, narration)")
                .eq("id", entry_id).eq("firm_id", firm_id)
                .is_("deleted_at", None).limit(1).execute().data) or []
        if not rows:
            raise HTTPException(status_code=404, detail="Journal entry not found.")
        entry = rows[0]

        lines = entry.get("lines") or []
        entry["total_debit_paise"] = sum(int(l.get("debit_paise") or 0) for l in lines)
        entry["total_credit_paise"] = sum(int(l.get("credit_paise") or 0) for l in lines)
        entry["status"] = "posted" if entry.get("is_posted") else "draft"
        entry["lock_reason"] = self._lock_reason(
            db, firm_id, entry.get("client_id"), entry.get("entry_date"))
        entry["editable"] = entry["lock_reason"] is None and not entry.get("is_reversed")
        return entry

    def _lock_reason(self, db, firm_id: str, client_id: Optional[str],
                     entry_date: Optional[str]) -> Optional[str]:
        if not client_id or not entry_date:
            return None
        try:
            res = db.rpc("journal_period_lock_reason", {
                "p_firm": firm_id, "p_client": client_id, "p_date": entry_date,
            }).execute()
        except Exception as e:
            # Fail CLOSED. If we cannot establish that the period is open, we do
            # not get to assume it is — an edit wrongly allowed into a filed
            # period is not recoverable from the UI.
            _logger.warning("journal_period_lock_reason unavailable (%s) — treating as locked", e)
            return "Could not confirm this period is open for editing. Try again."
        return res.data or None

    # ── edit ─────────────────────────────────────────────────────────────────

    def update(self, db, firm_id: str, entry_id: str, data: dict,
               actor_id: Optional[str] = None) -> dict:
        """Correct an entry, posted or draft.

        WHY A POSTED ENTRY MAY BE EDITED AT ALL
            The proviso to Rule 3(1) of the Companies (Accounts) Rules 2014
            requires an edit log of each change made in books of account — which
            presumes changes happen. Nothing in the Companies Act or the IT Act
            forbids correcting a posted entry; what ends the right is the CA
            locking the year or a return being filed for the period. See
            migration 266 for the full reasoning.

        DRAFTS take the ordinary path: nothing is on the books yet, so the rows
        are rewritten directly and the immutability triggers never fire.

        POSTED entries go through edit_posted_journal, which is the only thing
        allowed to move them. It re-checks the period, enforces Dr = Cr in
        integer paise, rewrites the lines, rebuilds the reporting passbook for
        the client and asserts no drift — atomically, so a failure anywhere
        leaves the ledger exactly as it was. Doing any of that here in Python
        would be several statements with no transaction around them, which is
        how the passbook drifted the last time.
        """
        entry = self.get(db, firm_id, entry_id)

        if entry.get("is_reversed"):
            raise HTTPException(
                status_code=422,
                detail="This entry has been reversed and can no longer be edited.")
        if entry["lock_reason"]:
            raise HTTPException(status_code=422, detail=entry["lock_reason"])

        lines = data.get("lines")
        if lines is not None:
            if len(lines) < 2:
                raise HTTPException(status_code=422, detail="A journal entry must have at least 2 lines.")
            total_debit = sum(int(l.get("debit_paise") or 0) for l in lines)
            total_credit = sum(int(l.get("credit_paise") or 0) for l in lines)
            if total_debit == 0:
                raise HTTPException(status_code=422, detail="A journal entry cannot be empty (zero value).")
            if total_debit != total_credit:
                raise HTTPException(
                    status_code=422,
                    detail=f"Unbalanced entry: debit {total_debit} paise != credit {total_credit} paise.")
        else:
            total_debit = entry["total_debit_paise"]
            total_credit = entry["total_credit_paise"]

        new_date = data.get("entry_date") or entry["entry_date"]
        # Moving an entry INTO a locked period is as much a change to that
        # period as editing one already there. The RPC checks this too; checking
        # here as well gives the CA the reason rather than a database error.
        if new_date != entry["entry_date"]:
            moved_into = self._lock_reason(db, firm_id, entry["client_id"], new_date)
            if moved_into:
                raise HTTPException(status_code=422, detail=moved_into)

        if entry.get("is_posted"):
            if lines is None:
                raise HTTPException(
                    status_code=422,
                    detail="Editing a posted entry must send its full set of lines.")
            period_validation_service.validate_posting_date(firm_id, new_date)
            try:
                db.rpc("edit_posted_journal", {
                    "p_firm": firm_id,
                    "p_client": entry["client_id"],
                    "p_entry_id": entry_id,
                    "p_lines": [{
                        "account_id": l["account_id"],
                        "debit_paise": int(l.get("debit_paise") or 0),
                        "credit_paise": int(l.get("credit_paise") or 0),
                        "narration": l.get("narration") or "",
                    } for l in lines],
                    "p_narration": data.get("narration"),
                    "p_reference_no": data.get("reference_no"),
                    "p_entry_date": new_date,
                    "p_actor": actor_id,
                }).execute()
            except HTTPException:
                raise
            except Exception as e:
                # The RPC raises for a locked period, an unbalanced entry and
                # passbook drift alike. Its message is written for the CA, so it
                # is surfaced rather than replaced with something vaguer.
                _logger.exception("edit_posted_journal failed for %s", entry_id)
                from core.exceptions import postgres_message
                raise HTTPException(status_code=422, detail=postgres_message(e))
        else:
            header = {k: v for k, v in {
                "entry_date": data.get("entry_date"),
                "narration": data.get("narration"),
                "reference_no": data.get("reference_no"),
                "entry_type": data.get("entry_type"),
            }.items() if v is not None}
            if header.get("entry_type") and header["entry_type"] not in ALLOWED_ENTRY_TYPES:
                raise HTTPException(status_code=422, detail=f"Invalid entry_type '{header['entry_type']}'.")
            if header:
                db.table("journal_entries").update(header).eq("id", entry_id).eq("firm_id", firm_id).execute()
            if lines is not None:
                db.table("journal_lines").delete().eq("journal_entry_id", entry_id).execute()
                db.table("journal_lines").insert([{
                    "journal_entry_id": entry_id,
                    "account_id": l["account_id"],
                    "debit_paise": int(l.get("debit_paise") or 0),
                    "credit_paise": int(l.get("credit_paise") or 0),
                    "narration": l.get("narration") or "",
                } for l in lines]).execute()

        return self.get(db, firm_id, entry_id)


manual_journal_service = ManualJournalService()
