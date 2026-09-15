"""
THE YEAR-END FX REVALUATION HAD NO DOOR.

AS 11 paragraph 11 (Ind AS 21 paragraph 23) retranslates a MONETARY item held
in a foreign currency at the CLOSING rate on each balance sheet date, and
paragraph 13 takes the difference to the profit and loss account. A client with
an open USD receivable at 31 March is carrying it at the rate it was invoiced
at, and the accounts are wrong by the movement until somebody restates it.

`domain/currency/fx_revaluation_service.py` has done that correctly since
Multi-Currency Phase 4 — idempotent, self-healing, period-lock aware, posting
through the one kernel and auto-reversing on day 1 of the next period — and it
had **zero production importers**. `revalue()` is the only writer of
`fx_revaluations` and `fx_adjustments`' unrealized half, so
`GET /api/fx-reports/unrealized` reported a structural nil for every client
however many foreign documents they held; `services/fx_reporting_service.py`'s
own header says those tables are "written by the Phase-4 settlement +
revaluation paths", which was true of settlement and not of revaluation. The
same shape as the year-end `capital_wip` line that nothing could reach.

Migration 122's gates were made WRITABLE by ACC-19 on 13-09-2026, which is what
turned this from a dormant phase into a live gap: a firm can now switch
multi-currency on, and the year-end step it needs is unreachable.

WHY ITS OWN ROUTER. `routers/fx_reports.py` says "read-only FX reporting" in
its first line and means it. A POST that writes journals to the general ledger
does not belong under a prefix whose contract is that nothing there can post —
the same reasoning that kept CWIP off `/api/fixed-assets`.

WHAT THIS ROUTER DECIDES: nothing. The exposure, the targets, the deltas and
the refusals are the domain service's; the gates are `resolve_currency_policy`'s;
the period lock is `period_validation_service`'s.
"""
import logging
import os

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from core.authz import assert_client_access
from core.permissions import rbac
from domain.currency import resolve_currency_policy
from domain.currency.fx_revaluation_service import fx_revaluation_service

from models.common import api_response

_logger = logging.getLogger("caflow.fx_revaluation")
_USE_MOCK = not os.environ.get("SUPABASE_URL")

router = APIRouter(prefix="/api/fx-revaluation", tags=["fx-revaluation"])


def _db_and_policy(current_user: dict, client_id: str):
    """The caller's db handle and the resolved multi-currency policy.

    ONE resolution for both endpoints. A preview that answered without the
    gates would show a CA an adjustment they cannot post, and a run that
    answered without them would post journals for a feature nobody switched
    on — which is the whole reason the three gates exist.
    """
    from core.supabase_client import get_supabase

    db = get_supabase()
    firm_id = current_user.get("firm_id")
    firm_res = (db.table("firms").select("id, multi_currency_entitled")
                .eq("id", firm_id).limit(1).execute())
    firm = (getattr(firm_res, "data", None) or [None])[0]
    # Tenant isolation: the client must belong to the caller's firm.
    client_res = (db.table("clients")
                  .select("id, functional_currency, multi_currency_enabled")
                  .eq("id", client_id).eq("firm_id", firm_id).limit(1).execute())
    client = (getattr(client_res, "data", None) or [None])[0]
    return db, firm_id, resolve_currency_policy(firm, client)


_NOT_ACTIVE = (
    "Multi-currency is not active for this client, so there is nothing to "
    "revalue. Settings → Multi-Currency says which of the three gates is "
    "still down.")


@router.post("/preview")
def preview_revaluation(
    client_id: str = Query(...),
    payload: dict = Body(default={}),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """What a revaluation at `period_end` would post. Writes NOTHING.

    A POST because the closing rates are a map and a query string is the wrong
    place for one; `POST /api/filing-demo/{flow}/preview` is the same shape for
    the same reason. It carries `rbac("accounting", "read")`, because what it
    does is read.

    The rates may be OMITTED. That is the useful first call: the answer names
    every currency the period is exposed in and says, per row, that no closing
    rate is recorded — so a CA opens the screen and is told what to go and find
    rather than having to know in advance.
    """
    assert_client_access(current_user, client_id)
    period_end = str(payload.get("period_end") or "").strip()
    if not period_end:
        raise HTTPException(status_code=422,
                            detail="period_end is required (YYYY-MM-DD).")
    rates = payload.get("closing_rates") or {}
    if not isinstance(rates, dict):
        raise HTTPException(status_code=422,
                            detail="closing_rates must be an object of {currency: rate}.")

    if _USE_MOCK:
        return api_response(True, {"active": False, "refusal": _NOT_ACTIVE,
                                   "period_end": period_end, "rows": [],
                                   "currencies": [], "rate_gaps": [], "would_post": 0})

    db, firm_id, policy = _db_and_policy(current_user, client_id)
    if not policy.active:
        return api_response(True, {"active": False, "refusal": _NOT_ACTIVE,
                                   "period_end": period_end, "rows": [],
                                   "currencies": [], "rate_gaps": [], "would_post": 0})

    plan = fx_revaluation_service.plan(db, firm_id, client_id, period_end,
                                       {str(k).upper(): v for k, v in rates.items()})
    # WHETHER IT COULD BE POSTED IS A DIFFERENT QUESTION FROM WHAT IT WOULD BE,
    # and both belong on a preview. `plan` deliberately does not ask the period
    # lock — a preview of a closed year still says what the adjustment was —
    # so the answer is asked here and REPORTED rather than raised.
    #
    # `closure_reason`, NOT the firm-FY validator and NOT `lock_reason`, and
    # the choice is the one CLAUDE.md makes for every path: report exactly what
    # will actually refuse the post, no more and no less.
    #
    #   * The firm-FY validator alone UNDER-reports. The posting kernel asks
    #     `period_closure_reason` for every entry it writes (migration 361), so
    #     a client whose year-end is finalised will be refused — and a preview
    #     asking only the firm's own switch would have said nothing about it
    #     and then failed at the button.
    #   * `lock_reason` would OVER-report. It adds the filed-return branch, and
    #     an FX revaluation posts no tax leg: CGST Rule 34 fixes the rate of
    #     exchange at the time of supply, so restating the rupee carrying
    #     amount afterwards cannot change a figure any filed GSTR-1 or GSTR-3B
    #     reported. Telling a CA their June return has closed this March
    #     adjustment would be false.
    from services import period_lock_service
    period_problem = period_lock_service.closure_reason(
        db, firm_id or "", client_id, period_end)
    return api_response(True, {**plan, "active": True, "refusal": None,
                               "period_problem": period_problem})


@router.post("/run")
def run_revaluation(
    client_id: str = Query(...),
    payload: dict = Body(...),
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Post the period-end revaluation. CA-initiated, one period at a time.

    Deliberately NOT on a schedule and not part of any sweep. The closing rate
    is a fact somebody has to record, and the entry it produces is a real
    posting to the profit and loss account — so it happens when a CA asks for
    it, on a period they named.

    Re-running is SAFE and is the intended correction path: the service posts
    only the delta needed to reach the new target, so a rate corrected before
    the accounts are signed produces a correcting entry rather than a
    duplicate.
    """
    assert_client_access(current_user, client_id)
    period_end = str(payload.get("period_end") or "").strip()
    if not period_end:
        raise HTTPException(status_code=422,
                            detail="period_end is required (YYYY-MM-DD).")
    rates = payload.get("closing_rates") or {}
    if not isinstance(rates, dict) or not rates:
        raise HTTPException(
            status_code=422,
            detail=("closing_rates is required — AS 11 retranslates at the "
                    "closing rate, and a rate nobody recorded cannot be "
                    "guessed. Run the preview to see which currencies need one."))

    if _USE_MOCK:
        return api_response(False, None, _NOT_ACTIVE)

    db, firm_id, policy = _db_and_policy(current_user, client_id)
    if not policy.active:
        return api_response(False, None, _NOT_ACTIVE)

    out = fx_revaluation_service.revalue(
        db, firm_id, client_id, period_end,
        {str(k).upper(): v for k, v in rates.items()}, actor=current_user)
    return api_response(True, out)
