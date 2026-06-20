"""
Banking & Reconciliation router.

Phase B.0: a THIN HTTP layer over the banking domain service. All mutations
(import, account mapping, posting, ignore) are delegated to
services.banking_service — the single source of banking business logic. The
frontend calls these endpoints instead of writing to Supabase directly.

Columns use the canonical model (transaction_date, match_status). Matching-rule
and suggestion endpoints are foundation-only scaffolding for Phases B.2/B.4 and
are intentionally NOT wired to the UI yet.

IMPORTANT: posting is explicit and human-initiated — never auto-post.
CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional

from models.common import api_response
from models.banking import (
    BankAccountIn, BankAccountUpdateIn, StatementImportIn,
    TransactionAccountIn, PostTransactionIn, MatchingRuleIn,
)
from core.permissions import rbac
from services.banking_service import banking_service

router = APIRouter(prefix="/api/banking", tags=["banking"])


def _db():
    import os
    if not os.environ.get("SUPABASE_URL"):
        return None
    from core.supabase_client import get_supabase
    return get_supabase()


# ─── Bank Accounts ────────────────────────────────────────────────────────────

@router.get("/accounts")
def list_bank_accounts(
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("accounting", "read")),
):
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
    db = _db()
    if not db:
        return api_response(True, {"id": "mock-id", **data.model_dump()})
    row = db.table("bank_accounts").insert(
        {"firm_id": current_user["firm_id"], **data.model_dump()}
    ).execute()
    return api_response(True, (row.data or [{}])[0])


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
    row = (db.table("bank_accounts").update(update)
           .eq("id", account_id).eq("firm_id", current_user["firm_id"]).execute())
    return api_response(True, (row.data or [{}])[0])


# ─── Statements ───────────────────────────────────────────────────────────────

@router.post("/statements/import")
def import_statement(
    data: StatementImportIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Store an already-parsed statement and its lines. (File parsing is Phase B.1.)"""
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


@router.get("/statements")
def list_statements(
    client_id: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    db = _db()
    if not db:
        return api_response(True, [])
    return api_response(True, banking_service.list_statements(db, current_user["firm_id"], client_id))


# ─── Transactions ─────────────────────────────────────────────────────────────

@router.get("/transactions")
def list_transactions(
    statement_id: Optional[str] = Query(None),
    client_id: Optional[str] = Query(None),
    match_status: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    db = _db()
    if not db:
        return api_response(True, [])
    return api_response(True, banking_service.list_transactions(
        db, current_user["firm_id"], statement_id=statement_id,
        client_id=client_id, match_status=match_status,
    ))


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


@router.post("/transactions/{txn_id}/post")
def post_transaction(
    txn_id: str,
    data: PostTransactionIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """
    Post a bank transaction to the ledger (double-entry via the shared engine).
    Human-initiated only. Refuses to post into a locked financial year.
    CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    """
    db = _db()
    if not db:
        return api_response(True, {"id": txn_id, "match_status": "posted", "journal_entry_id": "mock-je"})
    return api_response(True, banking_service.post_transaction(
        db, current_user["firm_id"], txn_id, data.account_id, data.bank_account_id,
        actor_id=current_user.get("auth_user_id"),
    ))


# ─── Matching rules (foundation only — Phase B.2; not wired to UI) ────────────

@router.get("/rules")
def list_rules(
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    db = _db()
    if not db:
        return api_response(True, [])
    res = (db.table("bank_matching_rules").select("*")
           .eq("firm_id", current_user["firm_id"]).eq("client_id", client_id)
           .eq("is_active", True).execute())
    return api_response(True, res.data or [])


@router.post("/rules")
def create_rule(
    data: MatchingRuleIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    db = _db()
    if not db:
        return api_response(True, {"id": "mock-id", **data.model_dump()})
    row = db.table("bank_matching_rules").insert(
        {"firm_id": current_user["firm_id"], **data.model_dump()}
    ).execute()
    return api_response(True, (row.data or [{}])[0])


# ─── Reports ──────────────────────────────────────────────────────────────────

@router.get("/reports/reconciliation-summary")
def reconciliation_summary(
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Counts/sums by match_status (canonical). Reconciliation workflow is Phase B.4."""
    db = _db()
    if not db:
        return api_response(True, {})
    txns = (db.table("bank_transactions").select("match_status, debit_paise, credit_paise")
            .eq("firm_id", current_user["firm_id"]).eq("client_id", client_id).execute().data or [])

    def amount(rows):
        return sum((r.get("debit_paise") or 0) + (r.get("credit_paise") or 0) for r in rows)

    posted = [t for t in txns if t.get("match_status") == "posted"]
    unmatched = [t for t in txns if t.get("match_status", "unmatched") == "unmatched"]
    return api_response(True, {
        "total_transactions": len(txns),
        "posted_count": len(posted),
        "unmatched_count": len(unmatched),
        "posted_amount_paise": amount(posted),
        "unmatched_amount_paise": amount(unmatched),
        "posted_percent": round(len(posted) / len(txns) * 100, 1) if txns else 0,
    })
