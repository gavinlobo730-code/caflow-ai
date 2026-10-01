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

THE PAYSLIP PDF IS THE SECOND DOOR, AND IT NAMES A DOCUMENT, NEVER A PERSON
    `GET /payslips/{slip_id}/pdf` (payroll-01). The portal's Download button used
    to call the STAFF route, which needs a `users` row an employee does not have
    and answered 403 to every employee for every slip. The caller has to say
    WHICH of their payslips, so `slip_id` is a parameter — but it is resolved
    only WITHIN the principal's own released slips
    (`services/employee_payslip_service`), so a colleague's slip, a draft's and a
    made-up id are one and the same 404. Nothing that identifies a person —
    employee, client, firm — is a parameter, which is what the signature guard
    asserts.

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


@router.get("/payslips/{slip_id}/pdf")
def employee_payslip_pdf(
    slip_id: str,
    employee: dict = Depends(get_current_portal_employee),
):
    """The caller's OWN payslip as a PDF (payroll-01).

    THE PORTAL'S DOWNLOAD BUTTON USED TO CALL THE STAFF ROUTE, which is
    `rbac("payroll", "read")` and needs a `users` row an employee does not have,
    so it answered 403 to every employee for every slip. This is the employee's
    door onto the same renderer.

    WHICH slip is the one thing the caller chooses, and it is resolved only
    WITHIN their own rows: `services.employee_payslip_service.own_released_slip`
    asks for the slip by id AND by the principal's employee id, inside the run's
    firm and client, and only once the run is released. A colleague's slip, a
    slip that does not exist and a slip in a draft run all come back as the same
    404 — a different answer for "exists but is not yours" would tell an
    employee whether somebody else's payslip id is real. There is no
    employee_id, client_id or firm_id on this route; they come from the
    principal.

    Read-only, and it renders nothing itself: `get_payslip_pdf` is the one
    payslip renderer, called by the staff route too.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    """
    from fastapi.responses import Response

    from routers.payroll import _db
    from services.employee_payslip_service import PayslipNotFound, own_released_slip
    from services.payslip_pdf_service import get_payslip_pdf

    not_found = HTTPException(status_code=404, detail="Payslip not found.")
    db = _db()
    if not db:
        raise HTTPException(status_code=503,
                            detail="Payslip PDF unavailable in mock mode")
    try:
        own_released_slip(db, employee, slip_id)
    except PayslipNotFound:
        raise not_found

    try:
        pdf_bytes, filename = get_payslip_pdf(slip_id, employee["firm_id"])
    except PermissionError:
        # Ownership was proven above, so the renderer's own firm check failing
        # means the two disagree about whose slip this is. Nothing is handed
        # over, and it says the same thing every other refusal says.
        raise not_found
    except ValueError:
        # The renderer refuses a run that carries no client (PAY-03 — the slip
        # would be headed with the CA firm's name). That is the EMPLOYER's to
        # fix and is worded for the CA on the staff route; an employee is told
        # it cannot be produced and who can put it right.
        raise HTTPException(status_code=409, detail=(
            "This payslip cannot be produced right now. Please ask your "
            "employer to check it."))

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            # A payslip carries a PAN and bank details: nothing between the
            # server and the employee's disk should keep a copy.
            "Cache-Control": "private, no-store",
        },
    )
