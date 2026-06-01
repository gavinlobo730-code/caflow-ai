"""
Accounting router — Chart of Accounts, Journal Entries, Ledger, Trial Balance, P&L, Balance Sheet.
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from models.common import api_response
from domain.accounting_service import accounting_service
from core.exceptions import NotFoundError, ValidationError

router = APIRouter(prefix="/api/accounting", tags=["accounting"])


@router.get("/accounts")
def list_accounts():
    return api_response(True, accounting_service.list_accounts())


@router.post("/accounts")
def create_account(data: dict):
    try:
        account = accounting_service.create_account(data)
        return api_response(True, account)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.patch("/accounts/{account_id}")
def update_account(account_id: str, data: dict):
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
):
    entries = accounting_service.list_journal_entries(
        client_id=client_id,
        start_date=start_date,
        end_date=end_date,
    )
    return api_response(True, entries)


@router.post("/journal")
def create_journal_entry(data: dict):
    try:
        entry = accounting_service.create_journal_entry(data)
        return api_response(True, entry)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.patch("/journal/{entry_id}/post")
def post_journal_entry(entry_id: str):
    try:
        entry = accounting_service.post_journal_entry(entry_id)
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
):
    try:
        lines = accounting_service.get_ledger(account_id, start_date, end_date)
        return api_response(True, lines)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/trial-balance")
def get_trial_balance(as_of_date: Optional[str] = Query(None)):
    tb = accounting_service.get_trial_balance(as_of_date)
    return api_response(True, tb)


@router.get("/profit-loss")
def get_profit_loss(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    client_id: Optional[str] = Query(None),
):
    pl = accounting_service.get_profit_loss(start_date, end_date, client_id)
    return api_response(True, pl)


@router.get("/balance-sheet")
def get_balance_sheet(
    as_of_date: Optional[str] = Query(None),
    client_id: Optional[str] = Query(None),
):
    bs = accounting_service.get_balance_sheet(as_of_date, client_id)
    return api_response(True, bs)
