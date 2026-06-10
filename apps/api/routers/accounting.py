"""
Accounting router — Chart of Accounts, Journal Entries, Ledger, Trial Balance, P&L, Balance Sheet.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from datetime import datetime, timezone
from models.common import api_response
from domain.accounting_service import accounting_service
from core.exceptions import NotFoundError, ValidationError
from core.permissions import rbac
from services.audit_service import log_event
from services.timeline_service import timeline_service


def _current_fy_long() -> str:
    """Return full financial year string like '2025-26'. Indian FY: April 1 – March 31."""
    now = datetime.now(timezone.utc)
    start = now.year if now.month >= 4 else now.year - 1
    return f"{start}-{str(start + 1)[2:]}"

router = APIRouter(prefix="/api/accounting", tags=["accounting"])


@router.get("/accounts")
def list_accounts(current_user: dict = Depends(rbac("accounting", "read"))):
    return api_response(True, accounting_service.list_accounts())


@router.post("/accounts")
def create_account(data: dict, current_user: dict = Depends(rbac("accounting", "write"))):
    try:
        account = accounting_service.create_account(data)
        return api_response(True, account)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.patch("/accounts/{account_id}")
def update_account(account_id: str, data: dict, current_user: dict = Depends(rbac("accounting", "write"))):
    try:
        account = accounting_service.update_account(account_id, data)
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
def create_journal_entry(data: dict, current_user: dict = Depends(rbac("accounting", "write"))):
    try:
        data["firm_id"] = current_user["firm_id"]
        entry = accounting_service.create_journal_entry(data)
        log_event(current_user["firm_id"], "journal_entry", entry.get("id",""), "create",
                  actor_id=current_user.get("auth_user_id"), actor_email=current_user.get("email"),
                  new_data=entry)
        return api_response(True, entry)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))


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


@router.get("/ledger")
def get_ledger(
    account_id: str = Query(...),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    try:
        lines = accounting_service.get_ledger(account_id, start_date, end_date)
        return api_response(True, lines)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/trial-balance")
def get_trial_balance(
    as_of_date: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    tb = accounting_service.get_trial_balance(as_of_date)
    return api_response(True, tb)


@router.get("/profit-loss")
def get_profit_loss(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    client_id: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    pl = accounting_service.get_profit_loss(
        start_date, end_date, client_id, firm_id=current_user["firm_id"]
    )
    return api_response(True, pl)


@router.get("/balance-sheet")
def get_balance_sheet(
    as_of_date: Optional[str] = Query(None),
    client_id: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    bs = accounting_service.get_balance_sheet(
        as_of_date, client_id, firm_id=current_user["firm_id"]
    )
    return api_response(True, bs)
