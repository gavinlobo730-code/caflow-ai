"""
FX reports (Multi-Currency Phase 5, Task 3) — READ-ONLY foreign-exchange reporting.

Every endpoint is firm-scoped, client-scoped, requires accounting-read, and returns
data DERIVED FROM POSTED ACCOUNTING (fx_adjustments / fx_revaluations + open foreign
documents). No endpoint posts, mutates, or recomputes a historical rate — the base
(INR) ledger stays authoritative. With multi-currency dormant these simply return
empty foreign data, so INR-only firms are unaffected.
"""
import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, Query

from models.common import api_response
from core.permissions import rbac
from core.authz import assert_client_access
from services.fx_reporting_service import fx_reporting_service

_logger = logging.getLogger("caflow.fx_reports")
_USE_MOCK = not os.environ.get("SUPABASE_URL")

router = APIRouter(prefix="/api/fx-reports", tags=["fx-reports"])


def _db_or_none():
    if _USE_MOCK:
        return None
    from core.supabase_client import get_supabase
    return get_supabase()


def _run(fn, empty):
    """Execute a report, returning a safe empty payload in mock/no-DB mode and a
    generic error envelope on failure (never leaking internals)."""
    db = _db_or_none()
    if db is None:
        return api_response(True, empty)
    try:
        return api_response(True, fn(db))
    except Exception as e:  # noqa: BLE001
        _logger.error("fx-report failed: %s", e)
        return api_response(False, None, "Unable to generate FX report. Please try again.")


@router.get("/realized")
def realized_fx(
    client_id: str = Query(..., description="CA client ID — required"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Realized FX gain/loss recognised on settlements in the window (per document)."""
    # Mount-guard-covered (required client_id query param); explicit so the
    # scope check is visible at the read.
    assert_client_access(current_user, client_id)
    firm_id = current_user.get("firm_id")
    return _run(lambda db: fx_reporting_service.realized_fx(db, firm_id, client_id, start_date, end_date),
                {"period": {"start": start_date, "end": end_date}, "lines": [],
                 "gain_paise": 0, "loss_paise": 0, "net_paise": 0, "by_currency": []})


@router.get("/unrealized")
def unrealized_fx(
    client_id: str = Query(..., description="CA client ID — required"),
    period_end: Optional[str] = Query(None, description="Restrict to one period-end (YYYY-MM-DD)"),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Period-end unrealized FX revaluation runs (idempotent deltas + auto-reversal)."""
    # Mount-guard-covered (required client_id query param); explicit so the
    # scope check is visible at the read.
    assert_client_access(current_user, client_id)
    firm_id = current_user.get("firm_id")
    return _run(lambda db: fx_reporting_service.unrealized_fx(db, firm_id, client_id, period_end),
                {"period_end": period_end, "lines": [], "by_currency": [], "net_paise": 0})


@router.get("/exposure")
def currency_exposure(
    client_id: str = Query(..., description="CA client ID — required"),
    as_of: Optional[str] = Query(None, description="Exposure as-of date (YYYY-MM-DD)"),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Open foreign monetary exposure by currency (AR + bank − AP), foreign + base."""
    # Mount-guard-covered (required client_id query param); explicit so the
    # scope check is visible at the read.
    assert_client_access(current_user, client_id)
    firm_id = current_user.get("firm_id")
    return _run(lambda db: fx_reporting_service.currency_exposure(db, firm_id, client_id, as_of),
                {"as_of": as_of, "by_currency": []})


@router.get("/rate-audit")
def exchange_rate_audit(
    client_id: str = Query(..., description="CA client ID — required"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Every exchange rate used (document bookings + FX adjustments) with provenance."""
    # Mount-guard-covered (required client_id query param); explicit so the
    # scope check is visible at the read.
    assert_client_access(current_user, client_id)
    firm_id = current_user.get("firm_id")
    return _run(lambda db: fx_reporting_service.exchange_rate_audit(db, firm_id, client_id, start_date, end_date),
                {"period": {"start": start_date, "end": end_date},
                 "documents": [], "adjustments": [], "overridden_count": 0})


@router.get("/open-balances")
def open_foreign_balances(
    client_id: str = Query(..., description="CA client ID — required"),
    as_of: Optional[str] = Query(None, description="As-of date (YYYY-MM-DD)"),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Each open foreign document's foreign + base outstanding at the booked rate."""
    # Mount-guard-covered (required client_id query param); explicit so the
    # scope check is visible at the read.
    assert_client_access(current_user, client_id)
    firm_id = current_user.get("firm_id")
    return _run(lambda db: fx_reporting_service.open_foreign_balances(db, firm_id, client_id, as_of),
                {"as_of": as_of, "receivables": [], "payables": [], "bank_accounts": []})
