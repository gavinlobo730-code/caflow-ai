"""GET /api/cash-flow-forecast — what a client's bank balance is expected to do.

ITS OWN ROUTER, NOT `/api/accounting/reports/*`, AND DELIBERATELY SO. That
prefix already serves the AS-3 CASH FLOW STATEMENT — `public.cash_flow_report`,
migration 277 — which is a statement of what HAS happened, classified into
operating, investing and financing. This is a projection of what is expected to
happen, built from open documents and their due dates. Two things called cash
flow, one historical and one forward-looking, sitting under one prefix is how a
reader comes to quote one at a meeting about the other; the same reasoning that
kept capital work-in-progress off `/api/fixed-assets`.

It decides nothing. `domain/cash_flow/forecast.py` is the rule and
`services/cash_flow_service.py` fetches.
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Depends, Query

from core.authz import assert_client_access, effective_client_ids
from core.permissions import rbac
from models.common import api_response
from services import cash_flow_service

router = APIRouter(prefix="/api/cash-flow-forecast", tags=["cash-flow-forecast"])

#: The window a CA actually asks about. Six months is the default the screen
#: this replaces used; one to twenty-four is bounded because the answer is one
#: row per month and a caller asking for a thousand is asking for a mistake.
_MIN_MONTHS, _MAX_MONTHS, _DEFAULT_MONTHS = 1, 24, 6


def _service(current_user: dict):
    """A reporting engine scoped to THIS caller's own book (ACC-17), and the
    raw client for the document reads."""
    from domain.reporting.service import ReportingService
    from domain.reporting.sources import SupabaseLedgerSource, mock_ledger_source

    allowed = effective_client_ids(current_user)
    if os.environ.get("SUPABASE_URL"):
        from core.supabase_client import get_supabase
        db = get_supabase()
        return ReportingService(SupabaseLedgerSource(db, allowed)), db
    return ReportingService(mock_ledger_source(allowed)), None


def _serialise(f) -> dict:
    return {
        "as_at": f.as_at.isoformat(),
        "opening_paise": f.opening_paise,
        "months": [
            {
                "period": m.period,
                "label": m.label,
                "opening_paise": m.opening_paise,
                "inflows_paise": m.inflows_paise,
                "outflows_paise": m.outflows_paise,
                "closing_paise": m.closing_paise,
                "by_kind": m.by_kind,
                "is_shortfall": m.is_shortfall,
            }
            for m in f.months
        ],
        # Always present, null where there is none — an absent key and a null
        # key read the same to a screen and are different bugs.
        "first_shortfall": f.first_shortfall,
        "overdue_in_paise": f.overdue_in_paise,
        "overdue_out_paise": f.overdue_out_paise,
        "undated": [
            {"amount_paise": u.amount_paise, "kind": u.kind,
             "reference": u.reference}
            for u in f.undated
        ],
        "unpriced": f.unpriced,
        "gaps": f.gaps,
    }


@router.get("")
def cash_flow_forecast(
    client_id: str = Query(..., description="The client whose bank this is about"),
    months: int = Query(_DEFAULT_MONTHS, ge=_MIN_MONTHS, le=_MAX_MONTHS),
    current_user: dict = Depends(rbac("report", "read")),
):
    """Six months of expected inflows and outflows, and what is unpriced.

    `client_id` is REQUIRED. A firm-wide cash forecast would add up the bank
    balances of clients who are separate legal persons, which is not a figure
    about anything — unlike the practice's own revenue, which IS a firm
    question and lives under /practice.
    """
    assert_client_access(current_user, client_id)
    svc, db = _service(current_user)
    answer = cash_flow_service.forecast_for_client(
        svc, db, current_user["firm_id"], client_id, months=months)
    return api_response(True, _serialise(answer))
