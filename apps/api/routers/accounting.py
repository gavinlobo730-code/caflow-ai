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
from models.accounting import AccountIn, AccountUpdateIn, JournalEntryIn, JournalReversalIn
from domain.accounting_service import accounting_service
from domain.reporting import ReportingService, SupabaseLedgerSource, mock_ledger_source
from services.journal_posting_service import journal_posting_service
from core.exceptions import NotFoundError, ValidationError
from core.permissions import rbac
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


@router.patch("/accounts/{account_id}")
def update_account(account_id: str, data: AccountUpdateIn, current_user: dict = Depends(rbac("accounting", "write"))):
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
    entries = accounting_service.list_journal_entries(
        client_id=client_id,
        start_date=start_date,
        end_date=end_date,
        firm_id=current_user["firm_id"],
    )
    return api_response(True, entries)


@router.post("/journal")
def create_journal_entry(data: JournalEntryIn, current_user: dict = Depends(rbac("accounting", "write"))):
    """Create a manual journal entry (draft or posted).

    Production posts through the SINGLE posting kernel (manual_journal_service →
    phase2_journal_service._create_journal) — the same engine every other workflow
    uses (no alternative posting path). Dev/demo (no SUPABASE_URL) keeps the
    in-memory engine so existing tests are unaffected.
    """
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
        log_event(current_user["firm_id"], "journal_entry", entry.get("id", ""), "create",
                  actor_id=current_user.get("auth_user_id"), actor_email=current_user.get("email"),
                  new_data=entry)
        return api_response(True, entry)
    except HTTPException:
        raise
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))


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


class YearLockIn(BaseModel):
    financial_year: str           # e.g. "2025-26"
    lock: bool                    # True = lock, False = unlock
    pin: Optional[str] = None     # firm lock PIN (verified server-side)


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
    db = _prod_db()
    if not db:
        return api_response(True, [])
    return api_response(True, journal_posting_service.list_journals(
        db, current_user["firm_id"], client_id, status))


@router.post("/journals/{journal_id}/post")
def post_draft_journal(journal_id: str, current_user: dict = Depends(rbac("accounting", "approve"))):
    """Approve & post a DRAFT journal to the ledger (Phase 3.5) — approve permission
    (Partner) only, FY-lock enforced, audited. Fires deferred downstream actions
    (e.g. bank settlement) only after the journal is on the books.
    CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT"""
    db = _prod_db()
    if not db:
        return api_response(True, {"id": journal_id, "is_posted": True})
    return api_response(True, journal_posting_service.post_draft(
        db, current_user["firm_id"], journal_id, actor_id=current_user.get("auth_user_id")))


@router.patch("/journal/{entry_id}/post")
def post_journal_entry(entry_id: str, current_user: dict = Depends(rbac("accounting", "approve"))):
    """Post (approve) a journal entry — Partner only."""
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

        # Fetch the original — firm-scoped (tenant isolation under service-role).
        orig_res = (db.table("journal_entries").select("*")
                    .eq("id", entry_id).eq("firm_id", firm_id).limit(1).execute())
        orig = (orig_res.data or [None])[0]
        if not orig:
            raise HTTPException(status_code=404, detail="Journal entry not found")
        if not orig.get("is_posted"):
            raise HTTPException(status_code=422, detail="Only posted journal entries can be reversed")
        if orig.get("reversal_of"):
            raise HTTPException(status_code=409, detail="This entry is itself a reversal — cannot reverse a reversal")

        existing_rev = (db.table("journal_entries").select("id")
                        .eq("firm_id", firm_id).eq("reversal_of", entry_id).limit(1).execute().data)
        if existing_rev:
            raise HTTPException(status_code=409, detail=f"Journal {entry_id} has already been reversed")

        # FY-lock: a reversal is a new posting — block it if its date is in a locked year.
        period_validation_service.validate_posting_date(firm_id, data.reversal_date)

        # Fetch the original lines explicitly (robust across PostgREST and the test
        # double) and build the equal-and-opposite legs (swap debit ↔ credit).
        orig_lines = (db.table("journal_lines").select("*")
                      .eq("journal_entry_id", entry_id).execute().data) or []
        if not orig_lines:
            raise HTTPException(status_code=422, detail="Cannot reverse a journal entry with no lines")
        rev_lines = [{
            "account_id":   l["account_id"],
            "debit_paise":  int(l.get("credit_paise") or 0),
            "credit_paise": int(l.get("debit_paise") or 0),
            "narration":    narration,
        } for l in orig_lines]

        # Single posting kernel — validates double-entry balance and writes the entry.
        ref = f"REV-{orig.get('reference_no') or entry_id[:8]}"
        rev_id = phase2_journal_service._create_journal(
            db=db,
            firm_id=firm_id,
            client_id=orig["client_id"],
            entry_date=data.reversal_date,
            reference_no=ref,
            narration=narration,
            entry_type=orig.get("entry_type") or "Journal",
            lines=rev_lines,
            is_posted=True,
            created_by=current_user.get("id"),   # internal users.id (FK), not the auth id
            reversal_of=entry_id,
        )

        log_event(
            firm_id, "journal_entry", rev_id,
            "reverse", actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"),
            new_data={"reversal_of": entry_id},
        )
        timeline_service.log(
            orig["client_id"], "accounting", "Journal Reversed",
            f"Reversal of {orig.get('reference_no') or entry_id[:8]} posted",
            "warning", firm_id=firm_id,
            entity_type="journal_entry", entity_id=rev_id,
            actor_id=current_user.get("auth_user_id"),
        )
        return api_response(True, {
            "id": rev_id, "reversal_of": entry_id, "reference_no": ref,
            "client_id": orig["client_id"], "entry_date": data.reversal_date,
            "is_posted": True, "lines": rev_lines,
        })
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
    posted-only). The browser only renders the result."""
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
    tb = _reporting_service().trial_balance(
        current_user["firm_id"], client_id, as_of_date, basis=basis
    )
    return api_response(True, tb)


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
    bs = _reporting_service().balance_sheet(
        current_user["firm_id"], client_id, as_of_date, basis=basis
    )
    return api_response(True, bs)


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
    cf = _reporting_service().cash_flow_statement(
        current_user["firm_id"], client_id, start_date, end_date, basis=basis
    )
    return api_response(True, cf)
