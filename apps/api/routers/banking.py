"""
Banking & Reconciliation router.

Phase B.0: a THIN HTTP layer over the banking domain service. All mutations
(import, account mapping, posting, ignore) are delegated to
services.banking_service — the single source of banking business logic. The
frontend calls these endpoints instead of writing to Supabase directly.

Columns use the canonical model (transaction_date, match_status).

IMPORTANT: posting is explicit and human-initiated — never auto-post.
CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import Response
from typing import Optional

from models.common import api_response
from core.authz import assert_client_access, filter_by_client

_logger = logging.getLogger("caflow.banking")


def _sync_opening_balances(db, firm_id: str, client_id: str, actor_id) -> bool:
    """Idempotently regenerate the client's opening-balance journal after a bank
    opening balance changes. Returns True on success, False on failure (caller
    rolls back). The reporting engine is unchanged — only the trigger moved here.

    actor_id MUST be the internal public.users.id (journal_entries.created_by FKs
    to users.id), never the Supabase auth id."""
    try:
        from services.opening_balance_service import post_opening_balances
        post_opening_balances(firm_id, client_id, created_by=actor_id)
        return True
    except Exception as e:
        _logger.error("bank opening-balance sync failed: %s", e)
        return False
from models.banking import (
    BankAccountIn, BankAccountUpdateIn, StatementImportIn,
    TransactionAccountIn, PostBankTxnIn, MatchingRuleIn, MatchingRuleUpdateIn,
    CategorizeIn, MatchIn, BankMatchMultiIn,
    ReconciliationCreateIn, ReconciliationUpdateIn, ReconcileItemsIn,
)
from core.permissions import rbac
from services.banking_service import banking_service
from services.bank_matching_service import bank_matching_service
from services.bank_posting_service import bank_posting_service
from services.bank_reconciliation_service import bank_reconciliation_service
from domain.banking import parse_statement, file_hash, StatementParseError

# Defensive upload cap (bank statements are small; protects the parser/DB).
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024

router = APIRouter(prefix="/api/banking", tags=["banking"])


def _db():
    import os
    if not os.environ.get("SUPABASE_URL"):
        return None
    from core.supabase_client import get_supabase
    return get_supabase()


def _scope_rows(current_user: dict, client_id: Optional[str], rows: list) -> list:
    """M2 assignment scoping for the "all clients" list endpoints below: when a
    specific client is requested the caller must actually be allowed to see it
    (assert_client_access); when no client is specified (firm-wide view), narrow
    the result set to the caller's assigned clients instead of returning every
    client in the firm's banking data to an Executive/Reviewer who isn't
    assigned to all of them."""
    if client_id:
        assert_client_access(current_user, client_id)
        return rows
    return filter_by_client(current_user, rows)


def _guard_foreign_bank_currency(db, firm_id: str, client_id: Optional[str], currency: str) -> None:
    """Allow a non-INR bank account ONLY when multi-currency is active for this client
    (env + firm entitlement + client enablement) and the currency is in the ISO master.
    Fail-safe: any missing gate ⇒ rejected, so INR stays the only option by default."""
    from domain.currency import resolve_currency_policy, currency_service
    firm = (db.table("firms").select("id, multi_currency_entitled")
            .eq("id", firm_id).limit(1).execute().data or [None])[0]
    client = (db.table("clients").select("id, functional_currency, multi_currency_enabled")
              .eq("id", client_id).eq("firm_id", firm_id).limit(1).execute().data or [None])[0] if client_id else None
    if not resolve_currency_policy(firm, client).active:
        raise HTTPException(status_code=422,
                            detail="Multi-currency is not enabled for this client — foreign-currency bank accounts are unavailable.")
    if not currency_service.get_currency(db, currency):
        raise HTTPException(status_code=422, detail=f"Unsupported currency: {currency}.")


# ─── Bank Accounts ────────────────────────────────────────────────────────────

@router.get("/accounts")
def list_bank_accounts(
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    assert_client_access(current_user, client_id)
    db = _db()
    if not db:
        return api_response(True, [])
    res = (db.table("bank_accounts").select("*")
           .eq("firm_id", current_user["firm_id"]).eq("client_id", client_id)
           .eq("is_active", True).order("bank_name").execute())
    return api_response(True, res.data or [])


@router.post("/accounts")
def create_bank_account(
    data: BankAccountIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    assert_client_access(current_user, data.client_id)
    db = _db()
    if not db:
        return api_response(True, {"id": "mock-id", **data.model_dump()})
    firm_id = current_user["firm_id"]
    payload = {"firm_id": firm_id, **data.model_dump()}
    # Multi-Currency Phase 5 — resolve the account currency. None ⇒ let the column
    # default to INR (byte-for-byte today's). A non-INR currency is allowed ONLY when
    # multi-currency is active for this client and the code is in the ISO master.
    cur = payload.pop("currency", None)
    if cur and cur != "INR":
        _guard_foreign_bank_currency(db, firm_id, payload.get("client_id"), cur)
        payload["currency"] = cur
    elif cur == "INR":
        payload["currency"] = "INR"
    row = db.table("bank_accounts").insert(payload).execute()
    account = (row.data or [{}])[0]
    # Auto-sync opening balances to the GL (no manual post). Roll back on failure.
    if int(payload.get("opening_balance_paise") or 0) != 0 and payload.get("client_id"):
        if not _sync_opening_balances(db, current_user["firm_id"], payload["client_id"],
                                      current_user.get("id")):
            try:
                if account.get("id"):
                    db.table("bank_accounts").delete().eq("id", account["id"]).eq("firm_id", current_user["firm_id"]).execute()
            except Exception:
                pass
            return api_response(False, None, "Unable to save bank account. Please try again.")
    return api_response(True, account)


@router.patch("/accounts/{account_id}")
def update_bank_account(
    account_id: str,
    data: BankAccountUpdateIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    db = _db()
    update = data.model_dump(exclude_none=True)
    if not db:
        return api_response(True, update)
    firm_id = current_user["firm_id"]
    prior = (db.table("bank_accounts").select("*")
             .eq("id", account_id).eq("firm_id", firm_id).limit(1).execute().data or [{}])[0]
    assert_client_access(current_user, prior.get("client_id"))
    row = (db.table("bank_accounts").update(update)
           .eq("id", account_id).eq("firm_id", firm_id).execute())
    account = (row.data or [{}])[0]
    # Auto-sync opening balances only when the opening balance actually changed.
    if int(account.get("opening_balance_paise") or 0) != int(prior.get("opening_balance_paise") or 0):
        client_id = account.get("client_id") or prior.get("client_id")
        if client_id and not _sync_opening_balances(db, firm_id, client_id, current_user.get("id")):
            try:
                db.table("bank_accounts").update({k: prior.get(k) for k in update.keys()}).eq("id", account_id).eq("firm_id", firm_id).execute()
            except Exception:
                pass
            return api_response(False, None, "Unable to save bank account. Please try again.")
    return api_response(True, account)


@router.get("/accounts/{account_id}/balance")
def bank_account_balance(
    account_id: str,
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Current balance of one bank account (Multi-Currency Phase 5). Always returns the
    authoritative base (INR) balance; for a foreign-currency account it also returns the
    foreign balance, both DERIVED from posted journal lines (no stored balance)."""
    assert_client_access(current_user, client_id)
    db = _db()
    if not db:
        return api_response(True, {"account_id": account_id, "currency": "INR",
                                   "base_balance_paise": 0, "foreign_balance_minor": None})
    firm_id = current_user["firm_id"]
    acct = (db.table("bank_accounts").select("id, currency, coa_account_id, bank_name, account_no")
            .eq("id", account_id).eq("firm_id", firm_id).eq("client_id", client_id)
            .limit(1).execute().data or [None])[0]
    if not acct:
        raise HTTPException(status_code=404, detail="Bank account not found for this client.")
    cur = (acct.get("currency") or "INR").upper()
    base = foreign = 0
    if acct.get("coa_account_id"):
        from services.fx_reporting_service import _account_foreign_and_base
        foreign, base = _account_foreign_and_base(db, firm_id, client_id, acct["coa_account_id"], cur)
    return api_response(True, {
        "account_id": account_id, "bank_name": acct.get("bank_name"), "account_no": acct.get("account_no"),
        "currency": cur, "base_currency": "INR", "base_balance_paise": base,
        "foreign_balance_minor": (foreign if cur != "INR" else None),
    })


# ─── Statements ───────────────────────────────────────────────────────────────

@router.post("/statements/import")
def import_statement(
    data: StatementImportIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Store an already-parsed statement and its lines. (File parsing is Phase B.1.)"""
    assert_client_access(current_user, data.client_id)
    db = _db()
    if not db:
        return api_response(True, {"statement_id": "mock-id", "imported": len(data.rows)})
    result = banking_service.import_statement(
        db, current_user["firm_id"], data.client_id, data.bank_name,
        data.account_number, [r.model_dump() for r in data.rows],
        bank_account_id=data.bank_account_id,
        actor_id=current_user.get("auth_user_id"),
    )
    return api_response(True, result)


@router.post("/statements/upload")
async def upload_statement(
    file: UploadFile = File(...),
    client_id: str = Form(...),
    bank_name: str = Form("Bank"),
    account_number: Optional[str] = Form(None),
    bank_account_id: Optional[str] = Form(None),
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Upload a CSV/XLSX bank statement. Parsing + normalization + dedup happen
    SERVER-SIDE (Banking B.1) — the browser sends the raw file only. Returns the
    counts of imported and duplicate-skipped transactions."""
    assert_client_access(current_user, client_id)
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 10 MB).")
    try:
        txns = parse_statement(file.filename or "", content)
    except StatementParseError as e:
        raise HTTPException(status_code=422, detail=str(e))

    db = _db()
    fmt = "xlsx" if (file.filename or "").lower().endswith(".xlsx") else "csv"
    if not db:
        return api_response(True, {"statement_id": "mock-id", "imported": len(txns),
                                   "duplicates_skipped": 0, "total_rows": len(txns)})
    file_meta = {
        "file_name": file.filename, "file_size_bytes": len(content),
        "source_format": fmt, "file_hash": file_hash(content),
    }
    result = banking_service.import_normalized(
        db, current_user["firm_id"], client_id, bank_name, account_number, txns,
        bank_account_id=bank_account_id, actor_id=current_user.get("auth_user_id"),
        file_meta=file_meta,
    )
    return api_response(True, result)


@router.get("/statements")
def list_statements(
    client_id: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    db = _db()
    if not db:
        return api_response(True, [])
    rows = banking_service.list_statements(db, current_user["firm_id"], client_id)
    return api_response(True, _scope_rows(current_user, client_id, rows))


# ─── Transactions ─────────────────────────────────────────────────────────────

@router.get("/transactions")
def list_transactions(
    statement_id: Optional[str] = Query(None),
    client_id: Optional[str] = Query(None),
    match_status: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    min_amount_paise: Optional[int] = Query(None),
    max_amount_paise: Optional[int] = Query(None),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """List bank transactions with date / amount / account filters (B.1, Part E)."""
    db = _db()
    if not db:
        return api_response(True, [])
    rows = banking_service.list_transactions(
        db, current_user["firm_id"], statement_id=statement_id,
        client_id=client_id, match_status=match_status,
        date_from=date_from, date_to=date_to,
        min_amount_paise=min_amount_paise, max_amount_paise=max_amount_paise,
    )
    return api_response(True, _scope_rows(current_user, client_id, rows))


# ─── Matching & Categorization (B.2) ──────────────────────────────────────────

@router.get("/queue")
def matching_queue(
    client_id: Optional[str] = Query(None),
    status: str = Query("unmatched", pattern="^(unmatched|categorized|matched|needs_review|ignored|all)$"),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Work queue (B.2.4) with rule-based suggested categories inline. status ∈
    unmatched | categorized | matched | needs_review | all."""
    db = _db()
    if not db:
        return api_response(True, [])
    rows = bank_matching_service.queue(db, current_user["firm_id"], client_id, status)
    return api_response(True, _scope_rows(current_user, client_id, rows))


@router.get("/transactions/{txn_id}/suggestions")
def transaction_suggestions(
    txn_id: str,
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Ranked match suggestions with confidence (B.2.1). Suggestions only — no posting."""
    db = _db()
    if not db:
        return api_response(True, {"transaction_id": txn_id, "suggestions": []})
    return api_response(True, bank_matching_service.suggestions(db, current_user["firm_id"], txn_id))


@router.post("/transactions/{txn_id}/categorize")
def categorize_transaction(
    txn_id: str,
    data: CategorizeIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Set a controlled category (B.2.2). No free-form categories."""
    db = _db()
    if not db:
        return api_response(True, {"id": txn_id, "category": data.category})
    return api_response(True, bank_matching_service.categorize(
        db, current_user["firm_id"], txn_id, data.category))


@router.post("/transactions/{txn_id}/match")
def match_transaction(
    txn_id: str,
    data: MatchIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Accept a suggestion / manually link a transaction to an entity (B.2.5).
    Linkage only — does NOT post a journal (that is Phase B.3)."""
    db = _db()
    if not db:
        return api_response(True, {"id": txn_id, "match_status": "matched"})
    return api_response(True, bank_matching_service.match(
        db, current_user["firm_id"], txn_id, data.matched_entity_type,
        data.matched_entity_id, category=data.category,
        actor_id=current_user.get("auth_user_id")))


@router.post("/transactions/{txn_id}/unmatch")
def unmatch_transaction(
    txn_id: str,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Reject a suggestion / clear a manual match (B.2.5)."""
    db = _db()
    if not db:
        return api_response(True, {"id": txn_id, "match_status": "unmatched"})
    return api_response(True, bank_matching_service.unmatch(db, current_user["firm_id"], txn_id))


@router.post("/transactions/{txn_id}/match-multi")
def match_transaction_multi(
    txn_id: str,
    data: BankMatchMultiIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Multi-invoice bank allocation: match ONE bank transaction to MULTIPLE
    sales invoices (a credit transaction) or purchase bills (a debit
    transaction) in a single settlement. Unlike /match (linkage only, posts
    nothing), this immediately creates the settling receipt/purchase_payment
    and posts its journal — the CA's submission of the allocation split IS the
    explicit confirmation, mirroring how recording a receipt/payment from the
    Sales/Purchases pages is itself a single-step action."""
    db = _db()
    if not db:
        return api_response(True, {"id": txn_id, "match_status": "posted"})
    result = bank_posting_service.match_and_settle_multi(
        db, current_user["firm_id"], txn_id, data.entity_type,
        [a.model_dump() for a in data.allocations],
        reference_no=data.reference_no, notes=data.notes, tds_paise=data.tds_paise,
        currency=data.currency, exchange_rate=data.exchange_rate,
        actor=current_user,
    )
    return api_response(True, result)


@router.patch("/transactions/{txn_id}")
def set_transaction_account(
    txn_id: str,
    data: TransactionAccountIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Map a transaction to a GL account (status → matched). Does not post."""
    db = _db()
    if not db:
        return api_response(True, {"id": txn_id, "match_status": "matched", "account_id": data.account_id})
    return api_response(True, banking_service.set_account(
        db, current_user["firm_id"], txn_id, data.account_id))


@router.post("/transactions/{txn_id}/ignore")
def ignore_transaction(
    txn_id: str,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    db = _db()
    if not db:
        return api_response(True, {"id": txn_id, "match_status": "ignored"})
    return api_response(True, banking_service.ignore(db, current_user["firm_id"], txn_id))


@router.post("/transactions/{txn_id}/unignore")
def unignore_transaction(
    txn_id: str,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Undo an ignore — the transaction returns to the work queue."""
    db = _db()
    if not db:
        return api_response(True, {"id": txn_id, "match_status": "unmatched"})
    return api_response(True, banking_service.unignore(db, current_user["firm_id"], txn_id))


# ─── Posting Engine (B.3) ─────────────────────────────────────────────────────

@router.get("/ready-to-post")
def ready_to_post_queue(
    client_id: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Categorized/matched transactions awaiting an explicit post (B.3.1)."""
    db = _db()
    if not db:
        return api_response(True, [])
    rows = bank_posting_service.ready_to_post(db, current_user["firm_id"], client_id)
    return api_response(True, _scope_rows(current_user, client_id, rows))


@router.get("/pending")
def pending_queue(
    client_id: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Phase 3.5: draft journal created from the transaction, awaiting approval in
    the journal review queue (not yet posted / settled / reconciled)."""
    db = _db()
    if not db:
        return api_response(True, [])
    rows = bank_posting_service.pending(db, current_user["firm_id"], client_id)
    return api_response(True, _scope_rows(current_user, client_id, rows))


@router.get("/posted")
def posted_queue(
    client_id: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Transactions already posted to the ledger (draft approved; journal id + who/when)."""
    db = _db()
    if not db:
        return api_response(True, [])
    rows = bank_posting_service.posted(db, current_user["firm_id"], client_id)
    return api_response(True, _scope_rows(current_user, client_id, rows))


@router.post("/transactions/{txn_id}/posting-preview")
def posting_preview(
    txn_id: str,
    data: PostBankTxnIn,
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Proposed balanced journal + settlement effect — NO writes (review drawer)."""
    db = _db()
    if not db:
        return api_response(True, {"transaction_id": txn_id, "lines": []})
    return api_response(True, bank_posting_service.preview(
        db, current_user["firm_id"], txn_id, bank_account_id=data.bank_account_id,
        account_id=data.account_id, to_bank_account_id=data.to_bank_account_id))


@router.post("/transactions/{txn_id}/post")
def post_transaction(
    txn_id: str,
    data: PostBankTxnIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """
    Explicitly post a bank transaction to the ledger (B.3.2): category → balanced
    journal (shared engine) → settlement. Idempotent (one journal per transaction).
    Human-initiated only; refuses a locked financial year.
    CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    """
    db = _db()
    if not db:
        return api_response(True, {"id": txn_id, "match_status": "posted", "posted_journal_id": "mock-je"})
    return api_response(True, bank_posting_service.post(
        db, current_user["firm_id"], txn_id,
        bank_account_id=data.bank_account_id, account_id=data.account_id,
        to_bank_account_id=data.to_bank_account_id,
        actor_id=current_user.get("auth_user_id"),
    ))


# ─── Reconciliation Engine (B.4) ──────────────────────────────────────────────

@router.post("/reconciliations")
def create_reconciliation(
    data: ReconciliationCreateIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Open a reconciliation session for a bank account + statement period (B.4.1)."""
    assert_client_access(current_user, data.client_id)
    db = _db()
    if not db:
        return api_response(True, {"id": "mock-recon", **data.model_dump()})
    return api_response(True, bank_reconciliation_service.create_session(
        db, current_user["firm_id"], data.client_id, data.bank_account_id,
        data.statement_start_date, data.statement_end_date,
        opening_balance_paise=data.opening_balance_paise,
        closing_balance_paise=data.closing_balance_paise,
        actor_id=current_user.get("auth_user_id")))


@router.get("/reconciliations")
def list_reconciliations(
    client_id: Optional[str] = Query(None),
    bank_account_id: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    db = _db()
    if not db:
        return api_response(True, [])
    rows = bank_reconciliation_service.list_sessions(db, current_user["firm_id"], client_id, bank_account_id)
    return api_response(True, _scope_rows(current_user, client_id, rows))


@router.get("/reconciliations/{recon_id}")
def get_reconciliation(
    recon_id: str,
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Session header + live tie-out summary + counts."""
    db = _db()
    if not db:
        return api_response(True, {"id": recon_id})
    return api_response(True, bank_reconciliation_service.get_session(
        db, current_user["firm_id"], recon_id))


@router.patch("/reconciliations/{recon_id}")
def update_reconciliation(
    recon_id: str,
    data: ReconciliationUpdateIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Adjust opening/closing balance or adjustments (rejected once completed)."""
    db = _db()
    if not db:
        return api_response(True, {"id": recon_id, **data.model_dump(exclude_none=True)})
    return api_response(True, bank_reconciliation_service.update_session(
        db, current_user["firm_id"], recon_id, data.model_dump(exclude_none=True),
        actor_id=current_user.get("auth_user_id")))


@router.get("/reconciliations/{recon_id}/items")
def reconciliation_items(
    recon_id: str,
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Reconciled / unreconciled / exception transactions + summary (B.4.2/B.4.4)."""
    db = _db()
    if not db:
        return api_response(True, {"reconciled": [], "unreconciled": [], "exceptions": []})
    return api_response(True, bank_reconciliation_service.report(
        db, current_user["firm_id"], recon_id))


@router.post("/reconciliations/{recon_id}/reconcile")
def reconcile_items(
    recon_id: str,
    data: ReconcileItemsIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Manually reconcile posted transactions — explicit human confirmation (B.4.2).
    No automatic reconciliation."""
    db = _db()
    if not db:
        return api_response(True, {"id": recon_id, "reconciled": data.transaction_ids})
    return api_response(True, bank_reconciliation_service.reconcile(
        db, current_user["firm_id"], recon_id, data.transaction_ids,
        actor_id=current_user.get("auth_user_id")))


@router.post("/reconciliations/{recon_id}/unreconcile")
def unreconcile_items(
    recon_id: str,
    data: ReconcileItemsIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Manually unreconcile transactions (B.4.2)."""
    db = _db()
    if not db:
        return api_response(True, {"id": recon_id, "unreconciled": data.transaction_ids})
    return api_response(True, bank_reconciliation_service.unreconcile(
        db, current_user["firm_id"], recon_id, data.transaction_ids,
        actor_id=current_user.get("auth_user_id")))


@router.post("/reconciliations/{recon_id}/complete")
def complete_reconciliation(
    recon_id: str,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Finalize the reconciliation. Allowed only when the balance ties out; the
    session becomes immutable afterwards (B.4.1/B.4.3)."""
    db = _db()
    if not db:
        return api_response(True, {"id": recon_id, "status": "completed"})
    return api_response(True, bank_reconciliation_service.complete(
        db, current_user["firm_id"], recon_id, actor_id=current_user.get("auth_user_id")))


@router.get("/reconciliations/{recon_id}/report")
def reconciliation_report(
    recon_id: str,
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Full backend-driven reconciliation report (B.4.4)."""
    db = _db()
    if not db:
        return api_response(True, {"reconciliation": {"id": recon_id}})
    return api_response(True, bank_reconciliation_service.report(
        db, current_user["firm_id"], recon_id))


@router.get("/reconciliations/{recon_id}/report.csv")
def reconciliation_report_csv(
    recon_id: str,
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """CSV export of the reconciliation report (B.4.4). Returns a file download."""
    db = _db()
    csv_text = "" if not db else bank_reconciliation_service.report_csv(
        db, current_user["firm_id"], recon_id)
    return Response(
        content=csv_text, media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="reconciliation-{recon_id}.csv"'})


# ─── Matching rules (Phase B.2.3) ─────────────────────────────────────────────
#
# A rule annotates the work queue with a suggested category / counter account /
# narration. It NEVER posts and never writes to a transaction on its own — the
# CA accepts the suggestion. Precedence is creation order (bank_matching_service
# orders by created_at), so the first rule that fires wins.


def _rule_or_404(db, firm_id: str, rule_id: str) -> dict:
    """Fetch a rule scoped to the caller's firm. 404 rather than 403 for a rule
    belonging to another firm — the caller learns nothing about its existence."""
    res = (db.table("bank_matching_rules").select("*")
           .eq("id", rule_id).eq("firm_id", firm_id).execute())
    rows = res.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Matching rule not found.")
    return rows[0]


@router.get("/rules")
def list_rules(
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Every rule for the client — INACTIVE ONES INCLUDED. The rules screen has
    to show a deactivated rule to let anyone reactivate it; the queue applies its
    own is_active filter (bank_matching_service.queue), so nothing is applied
    that shouldn't be. Ordered by created_at, which is also the precedence."""
    assert_client_access(current_user, client_id)
    db = _db()
    if not db:
        return api_response(True, [])
    res = (db.table("bank_matching_rules").select("*")
           .eq("firm_id", current_user["firm_id"]).eq("client_id", client_id)
           .order("created_at").execute())
    return api_response(True, res.data or [])


@router.post("/rules")
def create_rule(
    data: MatchingRuleIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    assert_client_access(current_user, data.client_id)
    db = _db()
    if not db:
        return api_response(True, {"id": "mock-id", **data.model_dump()})
    row = db.table("bank_matching_rules").insert(
        {"firm_id": current_user["firm_id"], **data.model_dump()}
    ).execute()
    return api_response(True, (row.data or [{}])[0])


@router.patch("/rules/{rule_id}")
def update_rule(
    rule_id: str,
    data: MatchingRuleUpdateIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Edit a rule, or toggle it with {"is_active": false}. Only the supplied
    fields change. client_id is NOT editable — moving a rule between clients
    would silently re-target every suggestion it has ever made."""
    db = _db()
    if not db:
        return api_response(True, {"id": rule_id, **data.model_dump(exclude_none=True)})
    rule = _rule_or_404(db, current_user["firm_id"], rule_id)
    assert_client_access(current_user, rule["client_id"])
    fields = data.model_dump(exclude_none=True)
    if not fields:
        return api_response(True, rule)
    row = (db.table("bank_matching_rules").update(fields)
           .eq("id", rule_id).eq("firm_id", current_user["firm_id"]).execute())
    return api_response(True, (row.data or [{}])[0])


@router.delete("/rules/{rule_id}")
def delete_rule(
    rule_id: str,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Remove a rule outright. A rule is configuration, not a financial record —
    it has never written anything to the ledger, so there is nothing to preserve.
    To keep one for later, deactivate it instead (PATCH is_active=false)."""
    db = _db()
    if not db:
        return api_response(True, {"id": rule_id, "deleted": True})
    rule = _rule_or_404(db, current_user["firm_id"], rule_id)
    assert_client_access(current_user, rule["client_id"])
    (db.table("bank_matching_rules").delete()
     .eq("id", rule_id).eq("firm_id", current_user["firm_id"]).execute())
    return api_response(True, {"id": rule_id, "deleted": True})
