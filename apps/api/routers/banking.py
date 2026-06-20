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
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import Response
from typing import Optional

from models.common import api_response
from models.banking import (
    BankAccountIn, BankAccountUpdateIn, StatementImportIn,
    TransactionAccountIn, PostBankTxnIn, MatchingRuleIn,
    CategorizeIn, MatchIn,
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
    return api_response(True, banking_service.list_statements(db, current_user["firm_id"], client_id))


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
    return api_response(True, banking_service.list_transactions(
        db, current_user["firm_id"], statement_id=statement_id,
        client_id=client_id, match_status=match_status,
        date_from=date_from, date_to=date_to,
        min_amount_paise=min_amount_paise, max_amount_paise=max_amount_paise,
    ))


# ─── Matching & Categorization (B.2) ──────────────────────────────────────────

@router.get("/queue")
def matching_queue(
    client_id: Optional[str] = Query(None),
    status: str = Query("unmatched", pattern="^(unmatched|categorized|matched|needs_review|all)$"),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Work queue (B.2.4) with rule-based suggested categories inline. status ∈
    unmatched | categorized | matched | needs_review | all."""
    db = _db()
    if not db:
        return api_response(True, [])
    return api_response(True, bank_matching_service.queue(
        db, current_user["firm_id"], client_id, status))


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
    return api_response(True, bank_posting_service.ready_to_post(db, current_user["firm_id"], client_id))


@router.get("/posted")
def posted_queue(
    client_id: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Transactions already posted to the ledger (journal id + who/when)."""
    db = _db()
    if not db:
        return api_response(True, [])
    return api_response(True, bank_posting_service.posted(db, current_user["firm_id"], client_id))


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
    return api_response(True, bank_reconciliation_service.list_sessions(
        db, current_user["firm_id"], client_id, bank_account_id))


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
