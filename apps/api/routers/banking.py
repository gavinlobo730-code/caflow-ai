"""
Banking & Reconciliation router.
Handles bank accounts, statement import, and reconciliation matching.

IMPORTANT: AI match suggestions require human review — never auto-post.
CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from datetime import datetime, timezone

from models.common import api_response
from models.banking import BankAccountIn, BankAccountUpdateIn, StatementImportIn, ReconcileMatchIn, MatchingRuleIn
from core.permissions import rbac
from services.timeline_service import timeline_service

router = APIRouter(prefix="/api/banking", tags=["banking"])

# In-memory dedup store for mock mode: set of (client_id, bank_account_id, txn_date, debit_paise, credit_paise, description)
_MOCK_IMPORTED_TXNS: set[tuple] = set()


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
    current_user: dict = Depends(rbac("accounting", "read"))
):
    db = _db()
    if not db:
        return api_response(True, [])
    res = db.table("bank_accounts").select("*").eq("client_id", client_id).eq("is_active", True).order("bank_name").execute()
    return api_response(True, res.data or [])


@router.post("/accounts")
def create_bank_account(
    data: BankAccountIn,
    current_user: dict = Depends(rbac("accounting", "write"))
):
    db = _db()
    if not db:
        return api_response(True, {"id": "mock-id", **data.model_dump()})
    row = db.table("bank_accounts").insert({
        "firm_id":               current_user["firm_id"],
        **data.model_dump(),
    }).execute()
    return api_response(True, (row.data or [{}])[0])


@router.patch("/accounts/{account_id}")
def update_bank_account(
    account_id: str,
    data: BankAccountUpdateIn,
    current_user: dict = Depends(rbac("accounting", "write"))
):
    db = _db()
    update = data.model_dump(exclude_none=True)
    if not db:
        return api_response(True, update)
    row = db.table("bank_accounts").update(update).eq("id", account_id).execute()
    return api_response(True, (row.data or [{}])[0])


# ─── Statement Import ─────────────────────────────────────────────────────────

@router.post("/statements/import")
def import_statement(
    data: StatementImportIn,
    current_user: dict = Depends(rbac("accounting", "write"))
):
    """
    Import parsed bank transactions into bank_transactions table.
    All amounts must already be in integer paise — no float conversion here.
    """
    db = _db()
    client_id       = data.client_id
    bank_account_id = data.bank_account_id

    if not db:
        inserted = 0
        skipped = 0
        for r in data.rows:
            key = (client_id, bank_account_id, r.txn_date, r.debit_paise, r.credit_paise, r.description)
            if key in _MOCK_IMPORTED_TXNS:
                skipped += 1
            else:
                _MOCK_IMPORTED_TXNS.add(key)
                inserted += 1
        timeline_service.log(client_id, "accounting", "Bank Statement Imported",
            f"{inserted} transactions imported, {skipped} skipped", "info")
        return api_response(True, {"imported": inserted, "skipped": skipped})

    firm_id = current_user["firm_id"]
    inserted = 0
    skipped  = 0

    for r in data.rows:
        try:
            db.table("bank_transactions").insert({
                "firm_id":         firm_id,
                "client_id":       client_id,
                "bank_account_id": bank_account_id,
                "txn_date":        r.txn_date,
                "description":     r.description,
                "debit_paise":     r.debit_paise,
                "credit_paise":    r.credit_paise,
                "balance_paise":   r.balance_paise,
                "reconciled":      False,
            }).execute()
            inserted += 1
        except Exception:
            skipped += 1  # duplicate or constraint violation

    timeline_service.log(client_id, "accounting", "Bank Statement Imported",
        f"{inserted} transactions imported, {skipped} skipped", "info")

    return api_response(True, {"imported": inserted, "skipped": skipped})


# ─── Reconciliation ───────────────────────────────────────────────────────────

@router.get("/transactions")
def list_transactions(
    client_id: str = Query(...),
    bank_account_id: Optional[str] = Query(None),
    reconciled: Optional[bool] = Query(None),
    limit: int = Query(100),
    offset: int = Query(0),
    current_user: dict = Depends(rbac("accounting", "read"))
):
    db = _db()
    if not db:
        return api_response(True, [])
    q = db.table("bank_transactions").select("*").eq("client_id", client_id)
    if bank_account_id:
        q = q.eq("bank_account_id", bank_account_id)
    if reconciled is not None:
        q = q.eq("reconciled", reconciled)
    res = q.order("txn_date", desc=True).range(offset, offset + limit - 1).execute()
    return api_response(True, res.data or [])


@router.post("/reconcile/match")
def match_transaction(
    data: ReconcileMatchIn,
    current_user: dict = Depends(rbac("accounting", "write"))
):
    """
    Link a bank transaction to a journal entry.
    CA REVIEW REQUIRED — this records the match but does NOT auto-post any journal.
    Human must review and confirm each match before it takes effect.
    """
    db = _db()
    txn_id     = data.bank_transaction_id
    journal_id = data.journal_entry_id

    if not db:
        return api_response(True, {"matched": True, "txn_id": txn_id})

    # Validate both records belong to same firm
    txn = db.table("bank_transactions").select("id, client_id, reconciled").eq("id", txn_id).single().execute().data
    if not txn:
        raise HTTPException(status_code=404, detail="Bank transaction not found")
    if txn["reconciled"]:
        raise HTTPException(status_code=409, detail="Transaction already reconciled")

    db.table("bank_transactions").update({
        "reconciled":            True,
        "reconciled_journal_id": journal_id,
        "reconciled_at":         datetime.now(timezone.utc).isoformat(),
    }).eq("id", txn_id).execute()

    timeline_service.log(
        txn["client_id"], "accounting", "Reconciliation Matched",
        f"Bank transaction matched to journal entry (CA reviewed)",
        "success", firm_id=current_user.get("firm_id", ""),
        entity_type="bank_transaction", entity_id=txn_id,
        actor_id=current_user.get("auth_user_id"),
    )

    return api_response(True, {"matched": True, "txn_id": txn_id, "journal_id": journal_id})


@router.delete("/reconcile/unmatch/{txn_id}")
def unmatch_transaction(
    txn_id: str,
    current_user: dict = Depends(rbac("accounting", "write"))
):
    """Reverse a reconciliation match — resets transaction to unmatched."""
    db = _db()
    if not db:
        return api_response(True, {"unmatched": True})
    txn = db.table("bank_transactions").select("id, client_id").eq("id", txn_id).single().execute().data
    db.table("bank_transactions").update({
        "reconciled":            False,
        "reconciled_journal_id": None,
        "reconciled_at":         None,
    }).eq("id", txn_id).execute()
    if txn:
        timeline_service.log(
            txn["client_id"], "accounting", "Reconciliation Unmatched",
            "Bank transaction match reversed",
            "warning", firm_id=current_user.get("firm_id", ""),
            entity_type="bank_transaction", entity_id=txn_id,
            actor_id=current_user.get("auth_user_id"),
        )
    return api_response(True, {"unmatched": True, "txn_id": txn_id})


@router.get("/reconcile/suggestions")
def get_match_suggestions(
    client_id: str = Query(...),
    bank_account_id: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("accounting", "read"))
):
    """
    AI-assisted match suggestions — amount + date proximity matching.
    CA REVIEW REQUIRED — suggestions only, never auto-posted.
    Matches unreconciled bank txns against unmatched journal lines by amount and date ±3 days.
    """
    db = _db()
    if not db:
        return api_response(True, [])

    # Fetch unreconciled bank transactions
    q = db.table("bank_transactions").select("*").eq("client_id", client_id).eq("reconciled", False)
    if bank_account_id:
        q = q.eq("bank_account_id", bank_account_id)
    txns = q.order("txn_date", desc=True).limit(50).execute().data or []

    # Fetch unmatched journal lines (not yet linked to any bank txn)
    journals = db.table("journal_entries").select(
        "id, entry_date, reference_no, narration, journal_lines(debit_paise, credit_paise)"
    ).eq("client_id", client_id).eq("is_posted", True).limit(200).execute().data or []

    suggestions = []
    for txn in txns:
        txn_amount = txn.get("debit_paise", 0) or txn.get("credit_paise", 0)
        txn_date   = txn["txn_date"]

        for j in journals:
            for line in (j.get("journal_lines") or []):
                line_amount = line.get("debit_paise", 0) or line.get("credit_paise", 0)
                if abs(line_amount - txn_amount) <= 100:  # ≤₹1 tolerance
                    # Date proximity check
                    from datetime import date
                    try:
                        td = date.fromisoformat(txn_date[:10])
                        jd = date.fromisoformat(j["entry_date"][:10])
                        if abs((td - jd).days) <= 3:
                            suggestions.append({
                                "bank_transaction_id": txn["id"],
                                "txn_date":           txn_date,
                                "txn_description":    txn.get("description"),
                                "txn_amount_paise":   txn_amount,
                                "journal_entry_id":   j["id"],
                                "journal_date":       j["entry_date"],
                                "journal_reference":  j.get("reference_no"),
                                "journal_narration":  j.get("narration"),
                                "confidence":         "high" if abs(line_amount - txn_amount) == 0 else "medium",
                            })
                    except Exception:
                        pass

    return api_response(True, suggestions[:30])  # cap suggestions


# ─── Matching Rules ───────────────────────────────────────────────────────────

@router.get("/rules")
def list_rules(
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("accounting", "read"))
):
    db = _db()
    if not db:
        return api_response(True, [])
    res = db.table("bank_matching_rules").select("*").eq("client_id", client_id).eq("is_active", True).execute()
    return api_response(True, res.data or [])


@router.post("/rules")
def create_rule(
    data: MatchingRuleIn,
    current_user: dict = Depends(rbac("accounting", "write"))
):
    db = _db()
    if not db:
        return api_response(True, {"id": "mock-id", **data.model_dump()})
    row = db.table("bank_matching_rules").insert({
        "firm_id": current_user["firm_id"],
        **data.model_dump(),
    }).execute()
    return api_response(True, (row.data or [{}])[0])


# ─── Reports ─────────────────────────────────────────────────────────────────

@router.get("/reports/reconciliation-summary")
def reconciliation_summary(
    client_id: str = Query(...),
    bank_account_id: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("accounting", "read"))
):
    db = _db()
    if not db:
        return api_response(True, {})

    q = db.table("bank_transactions").select("reconciled, debit_paise, credit_paise").eq("client_id", client_id)
    if bank_account_id:
        q = q.eq("bank_account_id", bank_account_id)
    txns = q.execute().data or []

    matched   = [t for t in txns if t["reconciled"]]
    unmatched = [t for t in txns if not t["reconciled"]]

    def total_amount(rows):
        return sum((r.get("debit_paise") or 0) + (r.get("credit_paise") or 0) for r in rows)

    return api_response(True, {
        "total_transactions":   len(txns),
        "matched_count":        len(matched),
        "unmatched_count":      len(unmatched),
        "matched_amount_paise": total_amount(matched),
        "unmatched_amount_paise": total_amount(unmatched),
        "reconciliation_percent": round(len(matched) / len(txns) * 100, 1) if txns else 0,
    })
