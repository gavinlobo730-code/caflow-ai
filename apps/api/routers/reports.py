"""
Reporting feed for /reports and /client-portal.

Both screens read a `transactions` table until migration 139 dropped it. There
is no single live table to replace it — a sale lives in client_sales_invoices, a
purchase in purchase_bills — so the union, and the decision about what counts,
happens in services/report_transactions_service.py and is served from here.

GUARD — accounting:read, matching the endpoints that already list the SAME rows
(sales_invoices.list_invoices and purchase_bills.list_purchase_bills both use
it). `report:read` would have been the tempting choice given the router's name,
but that is _ALL_STAFF: it would have handed a Reviewer, through a reporting
URL, exactly the invoice and bill data the two existing list endpoints refuse
them. A new endpoint must never be the loosest way to reach existing data.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from core.authz import assert_client_access, effective_client_ids
from core.permissions import rbac
from core.supabase_client import get_supabase
from models.common import api_response
from services import report_transactions_service as svc

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _scoped_client_ids(current_user: dict, client_id: Optional[str]) -> Optional[list[str]]:
    """Which clients this call may read.

    One id  → checked with assert_client_access, which 404s rather than
              disclosing that a client outside the caller's book exists.
    No id   → every client the caller is assigned to; None for firm-wide roles,
              which the service reads as "no client filter".
    """
    if client_id:
        assert_client_access(current_user, client_id)
        return [client_id]
    eff = effective_client_ids(current_user)
    return None if eff is None else sorted(eff)


@router.get("/transactions")
def list_report_transactions(
    client_id: Optional[str] = Query(None, description="Omit for every assigned client"),
    date_from: Optional[str] = Query(None, description="transaction_date >= (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="transaction_date <= (YYYY-MM-DD)"),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Issued sales invoices and received purchase bills as one list."""
    rows = svc.list_transactions(
        get_supabase(), current_user["firm_id"],
        client_ids=_scoped_client_ids(current_user, client_id),
        date_from=date_from, date_to=date_to,
    )
    return api_response(True, {"transactions": rows})


@router.get("/gst-summary")
def gst_summary(
    client_id: str = Query(..., description="CA client ID — required"),
    month: str = Query(..., description="YYYY-MM"),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """GSTR-1 / GSTR-3B working figures for one client-month.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    Working figures for a screen, not a filed return. The filing path is
    /api/gst/{gstr1,gstr3b}/from-books, which also reconciles to the ledger.
    """
    if len(month) != 7 or month[4] != "-" or not (month[:4] + month[5:]).isdigit():
        raise HTTPException(422, "month must be YYYY-MM")
    if not 1 <= int(month[5:]) <= 12:
        raise HTTPException(422, "month must be YYYY-MM with a month of 01-12")

    assert_client_access(current_user, client_id)
    return api_response(True, svc.gst_summary(
        get_supabase(), current_user["firm_id"], client_id, month))
