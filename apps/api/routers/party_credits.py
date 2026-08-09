"""Party credit balances (task #102) — view and apply a customer/vendor's
non-GST cash credit (e.g. from a bank overpayment; see migration 214 and
services/party_credit_service.py). Never auto-applied to anything — every
application is an explicit CA action.
"""
import os
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from models.common import api_response
from core.permissions import rbac
from core.authz import assert_client_access
from services.party_credit_service import party_credit_service

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.party_credits")

router = APIRouter(prefix="/api/party-credits", tags=["party_credits"])


def _get_db():
    from core.supabase_client import get_supabase
    return get_supabase()


class ApplyPartyCreditIn(BaseModel):
    client_id: str
    party_type: str          # 'customer' | 'vendor'
    party_id: str
    amount_paise: int
    applied_to_type: str     # 'sales_invoice' | 'purchase_bill'
    applied_to_id: str


@router.get("")
def list_party_credits(
    client_id: str = Query(...),
    party_type: str | None = Query(None),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    if _USE_MOCK:
        return api_response(True, [])
    try:
        assert_client_access(current_user, client_id)
        db = _get_db()
        rows = party_credit_service.list_balances(db, current_user["firm_id"], client_id, party_type)
        return api_response(True, rows)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("list_party_credits error: %s", e)
        return api_response(False, None, "Unable to load party credits. Please try again.")


@router.get("/{party_type}/{party_id}")
def get_party_credit(
    party_type: str,
    party_id: str,
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    if _USE_MOCK:
        return api_response(True, {"balance_paise": 0, "ledger": []})
    try:
        assert_client_access(current_user, client_id)
        db = _get_db()
        firm_id = current_user["firm_id"]
        balance = party_credit_service.get_balance(db, firm_id, client_id, party_type, party_id)
        ledger = party_credit_service.ledger(db, firm_id, client_id, party_type, party_id)
        return api_response(True, {"balance_paise": balance, "ledger": ledger})
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("get_party_credit error: %s", e)
        return api_response(False, None, "Unable to load party credit. Please try again.")


@router.post("/apply")
def apply_party_credit(
    data: ApplyPartyCreditIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    if _USE_MOCK:
        raise HTTPException(status_code=422, detail="Party credits require a configured database.")
    if data.amount_paise <= 0:
        raise HTTPException(status_code=422, detail="amount_paise must be positive")
    assert_client_access(current_user, data.client_id)
    # client_id rides in the JSON body here; explicit so the check is visible
    # before the credit is applied. Outside the try — see below.
    try:
        db = _get_db()
        row = party_credit_service.apply_credit(
            db, current_user["firm_id"], data.client_id, data.party_type, data.party_id,
            data.amount_paise, data.applied_to_type, data.applied_to_id,
            created_by=current_user.get("id"),
        )
        return api_response(True, row)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("apply_party_credit error: %s", e)
        return api_response(False, None, "Unable to apply party credit. Please try again.")
