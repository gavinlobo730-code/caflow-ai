"""
Accounting router — Chart of Accounts, Journal Entries, Ledger, Trial Balance, P&L, Balance Sheet.
"""
import os
import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone
from models.common import api_response
from models.accounting import AccountIn, AccountUpdateIn, JournalEntryIn, JournalEntryUpdateIn, JournalReversalIn
from domain.accounting_service import accounting_service
from domain.reporting import ReportingService, SupabaseLedgerSource, mock_ledger_source
from services.journal_posting_service import journal_posting_service
from core.exceptions import NotFoundError, ValidationError
from core.observability import capture_posting_failure
from core.permissions import rbac
from core.authz import assert_client_access, can_access_client, filter_by_client, effective_client_ids
from services.audit_service import log_event
from services.timeline_service import timeline_service
from services.period_validation_service import period_validation_service


def _reporting_service() -> ReportingService:
    """
    Trial Balance / P&L / Balance Sheet engine. Reads the production ledger via
    Supabase when configured (firm- and client-scoped), else the in-memory seed
    for dev/demo. Cash and accrual are computed by one code path over one source
    — IT Act §145; cash basis is management reporting only (GST stays invoice-based).
    """
    if os.environ.get("SUPABASE_URL"):
        from core.supabase_client import get_supabase
        return ReportingService(SupabaseLedgerSource(get_supabase()))
    return ReportingService(mock_ledger_source())


def _current_fy_long() -> str:
    """Return full financial year string like '2025-26'. Indian FY: April 1 – March 31."""
    now = datetime.now(timezone.utc)
    start = now.year if now.month >= 4 else now.year - 1
    return f"{start}-{str(start + 1)[2:]}"

router = APIRouter(prefix="/api/accounting", tags=["accounting"])
_logger = logging.getLogger("caflow.accounting")


@router.get("/accounts")
def list_accounts(current_user: dict = Depends(rbac("accounting", "read"))):
    return api_response(True, accounting_service.list_accounts())


@router.post("/accounts")
def create_account(data: AccountIn, current_user: dict = Depends(rbac("accounting", "write"))):
    try:
        account = accounting_service.create_account(data.model_dump())
        return api_response(True, account)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))


def _assert_account_scope(current_user: dict, account_id: str) -> dict:
    """Resolve a Chart-of-Accounts row and check the caller may reach its client.

    chart_of_accounts.client_id is NULLABLE (migration 003: NULL = firm-level
    template) — can_access_client(user, None) is always True, so a firm-level
    account is never refused. ONE fixed message covers missing and hidden alike
    (year_end.py's `_assert_engagement_scope` shape), not the id-embedded
    NotFoundError text this endpoint used before.
    """
    try:
        account = accounting_service.get_account(account_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Account not found.")
    if not can_access_client(current_user, account.get("client_id")):
        raise HTTPException(status_code=404, detail="Account not found.")
    return account


@router.patch("/accounts/{account_id}")
def update_account(account_id: str, data: AccountUpdateIn, current_user: dict = Depends(rbac("accounting", "write"))):
    _assert_account_scope(current_user, account_id)
    try:
        account = accounting_service.update_account(account_id, data.model_dump(exclude_none=True))
        return api_response(True, account)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/journal")
def list_journal_entries(
    client_id: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    if client_id:
        assert_client_access(current_user, client_id)
    entries = accounting_service.list_journal_entries(
        client_id=client_id,
        start_date=start_date,
        end_date=end_date,
        firm_id=current_user["firm_id"],
    )
    # journal_entries.client_id is NOT NULL (migration 003) — every row names a
    # client, so an omitted client_id must be narrowed to the caller's own
    # assigned book rather than returned firm-wide (the tally_migration.py
    # list_jobs shape).
    return api_response(True, filter_by_client(current_user, entries))


@router.post("/journal")
def create_journal_entry(data: JournalEntryIn, current_user: dict = Depends(rbac("accounting", "write"))):
    """Create a manual journal entry (draft or posted).

    Production posts through the SINGLE posting kernel (manual_journal_service →
    phase2_journal_service._create_journal) — the same engine every other workflow
    uses (no alternative posting path). Dev/demo (no SUPABASE_URL) keeps the
    in-memory engine so existing tests are unaffected.
    """
    assert_client_access(current_user, data.client_id)
    try:
        payload = data.model_dump()
        payload["firm_id"] = current_user["firm_id"]
        db = _prod_db()
        if db is None:
            entry = accounting_service.create_journal_entry(payload)  # dev/demo in-memory
        else:
            from services.manual_journal_service import manual_journal_service
            # created_by FKs to public.users.id (internal id), not the Supabase auth id.
            entry = manual_journal_service.create(
                db, current_user["firm_id"], payload, actor_id=current_user.get("id")
            )
    except HTTPException:
        raise
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as exc:
        # Anything else is a server-side failure the CA cannot act on, and until
        # now it reached them as a bare 500 "Internal server error" with nothing
        # logged beyond the traceback. That is what made the 42501 permission
        # error behind task #270 cost a database-log dive to identify: the API
        # said nothing, and the one tool built to catch exactly this class of
        # failure was never called.
        #
        # capture_posting_failure tags the Sentry event with the document, so
        # the next one is traceable to the entry that caused it rather than to
        # a stack trace alone.
        capture_posting_failure(
            exc, operation="create_journal_entry",
            firm_id=current_user.get("firm_id"), client_id=data.client_id,
            reference_no=data.reference_no, entry_date=data.entry_date,
            status=data.status,
        )
        # MUST stay a non-2xx. lib/api/index.ts request() only throws on !res.ok,
        # so the 200 + {"success": false} shape used elsewhere in this codebase
        # would leave the journal editor reporting "Journal entry posted",
        # writing a timeline event and navigating away, having posted nothing.
        #
        # "was not written" is safe to assert: the kernel's insert goes through
        # post_journal_atomic, which is one transaction — it either wrote the
        # entry and every line, or nothing at all.
        raise HTTPException(
            status_code=500,
            detail="Could not post this journal entry — nothing was written to the "
                   "ledger. The failure has been logged for the team.",
        )

    # Audit deliberately sits OUTSIDE the block above. It is not part of the
    # posting transaction, and a failed audit write must never be reported to
    # the CA as a failed post: the entry is on the books by this point, and
    # telling them otherwise invites a retry of something that already happened.
    try:
        log_event(current_user["firm_id"], "journal_entry", entry.get("id", ""), "create",
                  actor_id=current_user.get("auth_user_id"), actor_email=current_user.get("email"),
                  new_data=entry)
    except Exception as exc:  # noqa: BLE001 — never fail a completed post on its audit
        capture_posting_failure(
            exc, operation="create_journal_entry.audit",
            firm_id=current_user.get("firm_id"), client_id=data.client_id,
            journal_entry_id=entry.get("id"),
        )
    return api_response(True, entry)


def _prod_db():
    """Production Supabase client, or None in mock/dev (no SUPABASE_URL)."""
    if not os.environ.get("SUPABASE_URL"):
        return None
    from core.supabase_client import get_supabase
    return get_supabase()


class OpeningBalancePostIn(BaseModel):
    client_id: str
    opening_date: Optional[str] = None  # defaults to the client's FY start


@router.post("/opening-balances")
def post_opening_balances_endpoint(
    data: OpeningBalancePostIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Internal/backfill: (re)post a client's opening-balance journal from master
    records. Opening balances now post AUTOMATICALLY when a customer/vendor/bank
    opening balance is created or edited; this endpoint is retained only for
    one-off backfill of records entered before auto-posting existed. Idempotent;
    refuses to write into a locked financial year."""
    assert_client_access(current_user, data.client_id)
    from services.opening_balance_service import post_opening_balances
    try:
        result = post_opening_balances(
            firm_id=current_user["firm_id"],
            client_id=data.client_id,
            opening_date=data.opening_date,
            # created_by FKs to public.users.id (internal), not the Supabase auth id.
            created_by=current_user.get("id"),
        )
        if result.get("posted") and result.get("journal_entry_id"):
            log_event(
                current_user["firm_id"], "journal_entry", result["journal_entry_id"],
                "opening_balance_post", actor_id=current_user.get("auth_user_id"),
                actor_email=current_user.get("email"), new_data=result,
            )
        return api_response(True, result)
    except HTTPException:
        raise
    except ValueError as e:
        # e.g. required COA account missing
        raise HTTPException(status_code=422, detail=str(e))


class TrialBalanceRowIn(BaseModel):
    account_name: str
    account_type: str
    debit_paise: int
    credit_paise: int
    account_code: Optional[str] = None


class TrialBalanceImportIn(BaseModel):
    client_id: str
    rows: list[TrialBalanceRowIn]
    opening_date: Optional[str] = None   # defaults to the client's FY start
    preview: bool = False                # validate only; post nothing


def _tb_rows(data: "TrialBalanceImportIn"):
    from domain.accounting.trial_balance import TrialBalanceRow
    return [TrialBalanceRow(account_name=r.account_name, account_type=r.account_type,
                            debit_paise=r.debit_paise, credit_paise=r.credit_paise,
                            account_code=r.account_code) for r in data.rows]


@router.post("/trial-balance/import")
def import_trial_balance_endpoint(
    data: TrialBalanceImportIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Bring an imported trial balance into the client's ledger as ONE balanced
    opening journal entry.

    A trial balance only means anything once it is in the General Ledger — the
    reporting engine reads journals, not account-master fields. Refuses an
    unbalanced trial balance rather than posting lopsided lines, and refuses to
    write into a locked financial year. Idempotent: re-importing an unchanged
    trial balance posts nothing.

    preview=true validates and returns the totals without touching the database,
    so the wizard can show what is wrong before anything is committed."""
    assert_client_access(current_user, data.client_id)
    from domain.accounting.trial_balance import TrialBalanceError
    from services.trial_balance_import_service import (
        import_trial_balance, preview_trial_balance,
    )
    try:
        if data.preview:
            return api_response(True, preview_trial_balance(_tb_rows(data)))
        result = import_trial_balance(
            firm_id=current_user["firm_id"],
            client_id=data.client_id,
            rows=_tb_rows(data),
            opening_date=data.opening_date,
            # created_by FKs to public.users.id (internal), not the Supabase auth id.
            created_by=current_user.get("id"),
        )
        if result.get("posted") and result.get("journal_entry_id"):
            log_event(
                current_user["firm_id"], "journal_entry", result["journal_entry_id"],
                "trial_balance_import", actor_id=current_user.get("auth_user_id"),
                actor_email=current_user.get("email"), new_data=result,
            )
        return api_response(True, result)
    except HTTPException:
        raise
    except TrialBalanceError as e:
        # The trial balance itself is inadmissible — the message names the row
        # and the problem, and is meant to be shown to the CA verbatim.
        raise HTTPException(status_code=422, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


class YearLockIn(BaseModel):
    financial_year: str           # e.g. "2025-26"
    lock: bool                    # True = lock, False = unlock
    pin: Optional[str] = None     # firm lock PIN (verified server-side)


@router.get("/journal/{entry_id}")
def get_journal_entry(
    entry_id: str,
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """One entry with its lines, and whether it may still be edited.

    The response carries `editable` and `lock_reason` so the editor can show the
    CA why a period is closed instead of only refusing the save. Both come from
    the same database function the write path enforces with, so the screen and
    the ledger cannot disagree.
    """
    db = _prod_db()
    if not db:
        raise HTTPException(404, detail="Journal entry not found.")
    _assert_journal_scope_db(db, current_user, entry_id)
    from services.manual_journal_service import manual_journal_service
    return api_response(True, manual_journal_service.get(
        db, current_user["firm_id"], entry_id))


@router.patch("/journal/{entry_id}")
def update_journal_entry(
    entry_id: str,
    data: JournalEntryUpdateIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Correct a journal entry — draft or posted.

    A POSTED entry may be corrected until the CA locks the financial year or a
    return covering the period has been filed. That is what the proviso to Rule
    3(1) of the Companies (Accounts) Rules 2014 contemplates: an edit log of
    each change made in books of account, not a book that cannot change. See
    migration 266.

    The correction goes through edit_posted_journal, which re-checks the period,
    enforces Dr = Cr in integer paise, rewrites the lines, rebuilds the
    reporting passbook and asserts no drift — atomically. Every change lands in
    audit_log via the table triggers, header and lines alike.

    Deleting a posted entry remains impossible; that is still a reversal.
    """
    db = _prod_db()
    if not db:
        raise HTTPException(404, detail="Journal entry not found.")
    _assert_journal_scope_db(db, current_user, entry_id)
    from services.manual_journal_service import manual_journal_service

    before = manual_journal_service.get(db, current_user["firm_id"], entry_id)
    entry = manual_journal_service.update(
        db, current_user["firm_id"], entry_id,
        data.model_dump(exclude_none=True), actor_id=current_user.get("id"),
    )
    # The DB triggers write the row-level edit log; this records the request
    # that caused it, with the actor's email — the two together answer "who
    # changed what, when" without joining across systems.
    log_event(current_user["firm_id"], "journal_entry", entry_id, "update",
              actor_id=current_user.get("auth_user_id"), actor_email=current_user.get("email"),
              old_data=before, new_data=entry)
    return api_response(True, entry)


@router.get("/year-lock")
def get_year_lock(current_user: dict = Depends(rbac("accounting", "read"))):
    """Current year-lock state for the firm: {locked_financial_years, pin_set}.
    The PIN itself is never returned to the client."""
    db = _prod_db()
    if not db:
        return api_response(True, {"locked_financial_years": [], "pin_set": False})
    from services.year_lock_service import get_state
    return api_response(True, get_state(db, current_user["firm_id"]))


@router.post("/year-lock")
def set_year_lock(data: YearLockIn, current_user: dict = Depends(rbac("accounting", "approve"))):
    """Lock / unlock a financial year — Partner only (accounting.approve), audited.
    The ONLY sanctioned writer of firms.locked_financial_years; a DB trigger
    (migration 136) blocks every other session from changing it directly."""
    db = _prod_db()
    if not db:
        return api_response(True, {
            "locked_financial_years": [data.financial_year] if data.lock else [],
            "pin_set": bool(data.pin),
        })
    from services.year_lock_service import set_lock
    state = set_lock(
        db, current_user["firm_id"], data.financial_year, data.lock,
        pin=data.pin, actor_id=current_user.get("auth_user_id"),
        actor_email=current_user.get("email"),
    )
    return api_response(True, state)


@router.get("/journals")
def list_journals_queue(
    client_id: Optional[str] = Query(None),
    status: str = Query("draft", pattern="^(draft|posted|all)$"),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Phase 3.5 journal approval queue — Draft / Posted, with source + totals.
    Backed by the production ledger (real journal_entries), the single source for
    both manual and auto-generated (e.g. bank) drafts."""
    if client_id:
        assert_client_access(current_user, client_id)
    db = _prod_db()
    if not db:
        return api_response(True, [])
    return api_response(True, journal_posting_service.list_journals(
        db, current_user["firm_id"], client_id, status,
        allowed_client_ids=effective_client_ids(current_user)))


def _assert_journal_scope_db(db, current_user: dict, entry_id: str) -> None:
    """Row-addressed by entry_id, so M2 assignment scope has to be checked here.

    ONE fixed message for missing-row, wrong-firm and right-firm-but-unassigned
    alike — the same convention _assert_draft_scope uses, so a hidden entry and
    a non-existent one are indistinguishable from outside.

    The _db suffix is load-bearing. This module guards journal entries against
    TWO different engines — this one reads the production Supabase ledger, while
    _assert_journal_scope below reads the legacy in-memory accounting_service —
    and they take different arguments. Both were briefly called
    _assert_journal_scope; Python bound the name to whichever was defined last,
    so GET and PATCH /journal/{entry_id} raised TypeError on every request while
    the whole suite stayed green, because nothing exercised those two routes
    through the router. Keep the names distinct.
    """
    row = (db.table("journal_entries").select("client_id")
           .eq("id", entry_id).eq("firm_id", current_user["firm_id"])
           .is_("deleted_at", None).limit(1).execute().data or [None])[0]
    if not row or not can_access_client(current_user, row.get("client_id")):
        raise HTTPException(status_code=404, detail="Journal entry not found.")


def _assert_draft_scope(db, current_user: dict, journal_id: str) -> None:
    """Row-addressed by journal_id. `approve` is Partner-only by RBAC (the sole
    firm-wide role — core.authz._FIRMWIDE_ROLES), so M2 cannot be bypassed by
    construction; this closes the firm-BOUNDARY half only, the same convention
    billing.py's record_fee_receipt used despite billing also being Partner-only.
    Same fixed text journal_posting_service.post_draft already uses for its own
    missing-row branch, so a hidden vs. missing journal reads identically."""
    row = (db.table("journal_entries").select("client_id")
           .eq("id", journal_id).eq("firm_id", current_user["firm_id"])
           .limit(1).execute().data or [None])[0]
    if row and not can_access_client(current_user, row.get("client_id")):
        raise HTTPException(status_code=404, detail="Journal entry not found.")


@router.post("/journals/{journal_id}/post")
def post_draft_journal(journal_id: str, current_user: dict = Depends(rbac("accounting", "approve"))):
    """Approve & post a DRAFT journal to the ledger (Phase 3.5) — approve permission
    (Partner) only, FY-lock enforced, audited. Fires deferred downstream actions
    (e.g. bank settlement) only after the journal is on the books.
    CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT"""
    db = _prod_db()
    if not db:
        return api_response(True, {"id": journal_id, "is_posted": True})
    _assert_draft_scope(db, current_user, journal_id)
    return api_response(True, journal_posting_service.post_draft(
        db, current_user["firm_id"], journal_id, actor_id=current_user.get("auth_user_id")))


def _assert_journal_scope(current_user: dict, entry_id: str) -> dict:
    """Row-addressed by entry_id, against the legacy in-memory engine (never
    Supabase-backed, regardless of SUPABASE_URL — see the module note above
    create_journal_entry). ONE fixed message covers missing and hidden alike,
    replacing the id-embedded NotFoundError text this endpoint used before
    (the year_end.py `_assert_engagement_scope` shape)."""
    try:
        entry = accounting_service.get_journal_entry(entry_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Journal entry not found.")
    if not can_access_client(current_user, entry.get("client_id")):
        raise HTTPException(status_code=404, detail="Journal entry not found.")
    return entry


@router.patch("/journal/{entry_id}/post")
def post_journal_entry(entry_id: str, current_user: dict = Depends(rbac("accounting", "approve"))):
    """Post (approve) a journal entry — Partner only."""
    _assert_journal_scope(current_user, entry_id)
    try:
        entry = accounting_service.post_journal_entry(entry_id)
        log_event(current_user["firm_id"], "journal_entry", entry_id, "approve",
                  actor_id=current_user.get("auth_user_id"), actor_email=current_user.get("email"),
                  new_data={"status": "posted"})
        timeline_service.log_timeline_event(
            client_id=entry.get("client_id", ""),
            firm_id=current_user.get("firm_id", ""),
            financial_year=_current_fy_long(),
            category="accounting",
            event_type="journal_posted",
            title=f"Journal {entry.get('reference_no', '')} posted",
            description="Manual journal entry posted to ledger.",
            severity="info",
            entity_type="journal_entry",
            entity_id=entry_id,
            actor_id=current_user.get("auth_user_id"),
            actor_name=current_user.get("email"),
        )
        return api_response(True, entry)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/journal/{entry_id}/reverse")
def reverse_journal_entry(
    entry_id: str,
    data: JournalReversalIn,
    current_user: dict = Depends(rbac("accounting", "approve")),
):
    """
    Reverse a posted journal entry — Partner only.
    Creates a new equal-and-opposite journal entry linked to the original.
    The original entry is NOT modified (immutability preserved).
    Audit trail: reversal_of field links back to original entry id.
    """
    try:
        narration = data.narration or f"Reversal of journal {entry_id}"

        if not os.environ.get("SUPABASE_URL"):
            return api_response(True, {"id": "mock-reversal", "reversal_of": entry_id})
        from core.supabase_client import get_supabase
        from services.phase2_journal_service import phase2_journal_service
        db = get_supabase()
        firm_id = current_user["firm_id"]

        # FY-lock: a reversal is a new posting — block it if its date is in a locked year.
        period_validation_service.validate_posting_date(firm_id, data.reversal_date)

        # Original (firm-scoped) — only for the timeline reference; reverse_entry
        # re-validates existence/posted/not-already-reversed itself.
        orig = (db.table("journal_entries").select("client_id, reference_no, entry_type")
                .eq("id", entry_id).eq("firm_id", firm_id).limit(1).execute().data or [None])[0]

        # `approve` is Partner-only by RBAC (firm-wide), so M2 cannot be
        # bypassed by construction — this closes the firm-BOUNDARY half, the
        # billing.py/record_fee_receipt convention. Same fixed text
        # phase2_journal_service.reverse_entry already raises for a genuinely
        # missing/wrong-firm entry_id, so hidden vs. missing read identically.
        if orig and not can_access_client(current_user, orig.get("client_id")):
            raise HTTPException(status_code=404, detail="Journal entry not found")

        # task #102: a Receipt/Payment journal must be reversed through its own
        # cascade (POST /api/receipts/{id}/reverse or
        # POST /api/purchase-payments/{id}/reverse) — reversing the JOURNAL
        # alone here would leave the receipt/payment row un-flagged and its
        # invoice/bill allocations un-rolled-back, exactly the gap those
        # endpoints exist to close.
        if orig and orig.get("entry_type") in ("Receipt", "Payment"):
            kind = "receipt" if orig["entry_type"] == "Receipt" else "purchase payment"
            endpoint = "/api/receipts/{id}/reverse" if orig["entry_type"] == "Receipt" else "/api/purchase-payments/{id}/reverse"
            raise HTTPException(
                status_code=422,
                detail=f"This journal belongs to a {kind} — reverse the {kind} itself via {endpoint}, not the journal directly.",
            )

        # Single reversal path through the kernel (append-only; original untouched).
        rev_id = phase2_journal_service.reverse_entry(
            db, firm_id, entry_id, data.reversal_date,
            narration=narration, created_by=current_user.get("id"),
        )

        log_event(
            firm_id, "journal_entry", rev_id,
            "reverse", actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"),
            new_data={"reversal_of": entry_id},
        )
        if orig:
            timeline_service.log(
                orig.get("client_id"), "accounting", "Journal Reversed",
                f"Reversal of {orig.get('reference_no') or entry_id[:8]} posted",
                "warning", firm_id=firm_id,
                entity_type="journal_entry", entity_id=rev_id,
                actor_id=current_user.get("auth_user_id"),
            )
        return api_response(True, {"id": rev_id, "reversal_of": entry_id})
    except HTTPException:
        raise
    except Exception:
        _logger.exception("reverse_journal_entry failed for entry %s", entry_id)
        raise HTTPException(status_code=500, detail="Unable to reverse journal entry. Please try again.")


@router.get("/ledger")
def get_ledger(
    account_id: str = Query(...),
    client_id: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Per-account general ledger from the single reporting engine — opening,
    running and closing balances are computed server-side (firm/client scoped,
    posted-only). The browser only renders the result.

    client_id is checked when named; when omitted, every reporting endpoint
    below aggregates across the WHOLE FIRM rather than narrowing to the
    caller's own assigned clients — "accounting" read is _AT_LEAST_EXECUTIVE,
    not Partner-only, so this is a live gap for a non-firm-wide caller who
    simply omits client_id. Recorded, not fixed: correctly narrowing an
    aggregate report means threading effective_client_ids through
    domain/reporting.py's ReportingService (ledger/trial_balance/profit_loss/
    balance_sheet/schedule_iii/cash_flow) and both its Supabase and mock
    sources — a bigger lift than a guard, the same line drawn for
    /api/copilot/intelligence/* and /api/copilot/executive-dashboard."""
    if client_id:
        assert_client_access(current_user, client_id)
    return api_response(True, _reporting_service().ledger(
        current_user["firm_id"], client_id, account_id, start_date, end_date
    ))


@router.get("/trial-balance")
def get_trial_balance(
    as_of_date: Optional[str] = Query(None),
    client_id: Optional[str] = Query(None),
    basis: str = Query("accrual", pattern="^(accrual|cash)$"),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """
    IT Act Section 145: method of accounting.
    Cash basis is derived from real allocation links (management reporting only);
    it never affects GST returns, which remain invoice-based per the CGST Act.
    """
    if client_id:
        assert_client_access(current_user, client_id)
    tb = _reporting_service().trial_balance(
        current_user["firm_id"], client_id, as_of_date, basis=basis
    )
    return api_response(True, tb)


@router.get("/ledger-span")
def get_ledger_span(
    client_id: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """First and last posted entry dates — what "All Time" actually means.

    Guarded with accounting:read, matching trial-balance / profit-loss /
    balance-sheet: the span leaks when a client's books begin and end, which is
    the same class of fact as the reports themselves and must not be reachable
    through a looser permission just because the payload is two dates.
    """
    if client_id:
        assert_client_access(current_user, client_id)
        scoped = [client_id]
    else:
        ids = effective_client_ids(current_user)
        scoped = None if ids is None else sorted(ids)

    from core.supabase_client import get_supabase
    from services.ledger_span_service import ledger_span
    return api_response(True, ledger_span(get_supabase(), current_user["firm_id"], scoped))


@router.get("/profit-loss")
def get_profit_loss(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    client_id: Optional[str] = Query(None),
    basis: str = Query("accrual", pattern="^(accrual|cash)$"),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """
    IT Act Section 44AA: professionals may use cash basis for record-keeping.
    basis=cash is management reporting only — never affects GST/ITR filings.
    """
    if client_id:
        assert_client_access(current_user, client_id)
    pl = _reporting_service().profit_loss(
        current_user["firm_id"], client_id, start_date, end_date, basis=basis
    )
    return api_response(True, pl)


@router.get("/balance-sheet")
def get_balance_sheet(
    as_of_date: Optional[str] = Query(None),
    client_id: Optional[str] = Query(None),
    basis: str = Query("accrual", pattern="^(accrual|cash)$"),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """
    Companies Act Section 128: balance sheet must use accrual for companies.
    basis=cash excludes unpaid A/R and A/P — for management view only.
    """
    if client_id:
        assert_client_access(current_user, client_id)
    bs = _reporting_service().balance_sheet(
        current_user["firm_id"], client_id, as_of_date, basis=basis
    )
    return api_response(True, bs)


@router.get("/schedule-iii")
def get_schedule_iii(
    fy_start: Optional[str] = Query(None),
    fy_end: Optional[str] = Query(None),
    client_id: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """
    Companies Act 2013 Section 129 read with Schedule III (Division I): financial
    statements presented in the prescribed form. Amounts are the authoritative
    accrual P&L / Balance Sheet from the reporting engine; the statutory
    line-caption grouping is done server-side (never in the UI). client_id=None
    returns the firm-wide consolidation.
    """
    if client_id:
        assert_client_access(current_user, client_id)
    data = _reporting_service().schedule_iii(
        current_user["firm_id"], client_id, fy_start, fy_end
    )
    return api_response(True, data)


@router.get("/cash-flow")
def get_cash_flow(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    client_id: Optional[str] = Query(None),
    basis: str = Query("accrual", pattern="^(accrual|cash)$"),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """
    Cash Flow Statement — AS-3 (indirect method), Companies Act 2013 Schedule III.
    Operating + Investing + Financing = net cash movement = closing − opening cash
    (guaranteed by double-entry; all integer paise). basis=cash is management
    reporting only (IT Act §145) and never affects GST/ITR filings.
    """
    if client_id:
        assert_client_access(current_user, client_id)
    cf = _reporting_service().cash_flow_statement(
        current_user["firm_id"], client_id, start_date, end_date, basis=basis
    )
    return api_response(True, cf)


@router.get("/statement-analysis")
async def get_statement_analysis(
    financial_year: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    client_id: Optional[str] = Query(None),
    basis: str = Query("accrual", pattern="^(accrual|cash)$"),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """
    Short AI-generated narrative plus liquidity/profitability ratios for the
    P&L and Balance Sheet, computed from the SAME reporting engine as every
    other statement (domain/financial_analysis_service.compute_ratios never
    re-derives a money figure — it only aggregates the backend's own paise
    totals). Advisory only, for the CA's own review — never auto-filed or
    submitted anywhere.
    """
    if client_id:
        assert_client_access(current_user, client_id)
    from domain.financial_analysis_service import generate_statement_analysis

    def _fy_range(fy: str) -> tuple[str, str]:
        y = int(fy.split("-")[0])
        return f"{y}-04-01", f"{y + 1}-03-31"

    def _shift_fy(fy: str, delta: int) -> str:
        y = int(fy.split("-")[0]) + delta
        return f"{y}-{str(y + 1)[-2:]}"

    start, end = _fy_range(financial_year)
    prev_fy = _shift_fy(financial_year, -1)
    prev_start, prev_end = _fy_range(prev_fy)

    svc = _reporting_service()
    firm_id = current_user["firm_id"]
    pl = svc.profit_loss(firm_id, client_id, start, end, basis=basis)
    bs = svc.balance_sheet(firm_id, client_id, end, basis=basis)
    prev_pl = svc.profit_loss(firm_id, client_id, prev_start, prev_end, basis=basis)

    result = await generate_statement_analysis(pl, bs, prev_pl, financial_year, prev_fy)
    return api_response(True, result)
