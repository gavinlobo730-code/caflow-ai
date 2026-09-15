"""The employee-facing API (PAY-26).

WHAT WAS MISSING
    An employee already holds a real Supabase identity — `accept_employee_invite`
    binds `payroll_employees.auth_user_id` and flips `portal_enabled`, and
    migration 262's RLS reads exactly that pair — but the API had no way to
    resolve one. So the employee portal could only read the three tables RLS
    lets it read straight over PostgREST, and anything COMPUTED was unreachable
    to an employee however well it worked for the CA.

    The §192 projection is the case that forced it. `GET /api/payroll/
    tds-projection` answers off `_compute_slip`, the same function the payroll
    run pays from, and it is precisely the working an employee asks their
    employer for in January: how much tax is coming out, and why. There was no
    door onto it.

THE PRINCIPAL IS DELIBERATELY NARROW (owner decision, 14-09-2026)
    Read-only, self-scoped, no client switcher — `core/portal_auth.
    get_current_portal_employee` states each and why. What that buys is on this
    side: no endpoint in this module takes an employee_id or a client_id. They
    come from the resolved principal, so there is no parameter to tamper with
    and an employee cannot ask for a colleague's salary by editing a query
    string. A guard asserts that property rather than trusting it.

THERE IS DELIBERATELY NO /me
    The portal already reads its own `payroll_employees` row over PostgREST
    under migration 262's policy. A second way to ask who the caller is would
    be one more thing to keep in step, and the reachability ratchet
    (`tests/test_every_mounted_endpoint_has_a_way_in.py`) named it on the first
    run: an endpoint no screen calls cannot be used by anybody.

NOTHING HERE COMPUTES
    `compute_tds_projection` is the payroll module's own function and this
    router calls it. A second implementation of a withholding figure is exactly
    what PAY-10 existed to undo — the browser's copy had last year's slab
    ladder, no old regime, no declaration and no §192(3) — and rebuilding it
    for the employee's side of the same screen would have re-created it.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from core.portal_auth import get_current_portal_employee
from models.common import api_response
from models.fy import FYLabel

router = APIRouter(prefix="/api/portal/employee", tags=["portal_employee"])


@router.get("/tds-projection")
def employee_tds_projection(
    financial_year: Annotated[FYLabel, Query(description='e.g. "2026-27"')] = ...,
    employee: dict = Depends(get_current_portal_employee),
):
    """The caller's OWN §192 withholding for a year, month by month.

    THE PARAMETERS ARE THE POINT. There is no employee_id and no client_id —
    both come from the principal — so this endpoint cannot be asked about
    anybody else. The financial year is the only thing the caller chooses, and
    a year is not a person.

    The figures, the caveats and the gaps are the payroll module's; this
    forwards them unchanged. In particular the sentence saying a projected
    month assumes a full month's attendance travels through, because an
    employee reading a number without it would take an estimate for a
    deduction that has been decided.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    """
    # Imported here rather than at module import: `routers/payroll` is a large
    # module and this router is mounted on every boot, while the projection is
    # asked for rarely.
    from routers.payroll import EmployeeNotFound, _db, compute_tds_projection
    try:
        data = compute_tds_projection(
            _db(), firm_id=employee["firm_id"], client_id=employee["client_id"],
            employee_id=employee["employee_id"], fy=financial_year)
    except EmployeeNotFound:
        # The ids came from the principal, so a miss means the principal no
        # longer matches a live employee row — deleted, or moved between
        # clients. That is a 403 about the caller, not a 404 about a request.
        raise HTTPException(status_code=403, detail="Not an employee portal user.")
    return api_response(True, data)
