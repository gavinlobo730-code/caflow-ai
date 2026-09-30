"""An employee's own payslip — the lookup that makes the PDF safe to hand over
(payroll-01).

WHAT WAS MISSING
    The employee portal's Download button called the STAFF route,
    `GET /api/payroll/salary-slips/{id}/pdf`, which is `rbac("payroll", "read")`
    and therefore needs a `users` row — `core.auth` answers 403 "User not found
    in firm" without one. An employee principal has none (CLAUDE.md, "THERE ARE
    THREE PRINCIPALS"), so the most basic thing an employee does with the portal
    was built, linked, and could not succeed. The reachability guard did not
    notice because it matched URL strings and asked nobody WHO the caller was.

THE RULE, STATED ONCE
    A slip is the caller's to download when THREE facts hold, and they are asked
    in the QUERY, not checked afterwards:

      * the slip is theirs            — `payroll_slips.employee_id` is the
                                        principal's, never a parameter;
      * its run belongs to their firm AND their client — `payroll_slips` has no
                                        tenant column, so the run is the only
                                        place either can be proven;
      * the run is RELEASED           — `finalized` or `paid`
                                        (`domain.payroll.run_status`). A draft has
                                        paid nobody, and migration 323 already
                                        withholds it from the employee's own
                                        PostgREST read, so this door must not be
                                        the way round the policy.

    Every way of failing is ONE answer, `PayslipNotFound`. A colleague's slip, a
    slip that does not exist and a slip in an unreleased run are
    indistinguishable to the caller, which is the point: a distinct refusal for
    "exists but is not yours" is an oracle for whether somebody else's payslip
    id is real.

    The ids come from the resolved principal (`core.portal_auth.
    get_current_portal_employee`), so nothing here takes an employee or a client
    from the request. The slip id IS chosen by the caller — they have to say
    WHICH of their payslips — but it is resolved only WITHIN their own rows.

NOTHING HERE RENDERS
    `services.payslip_pdf_service.get_payslip_pdf` is the one payslip renderer;
    the staff route and this one both call it. A second renderer for the
    employee's side would be two payslips that agree until one is changed.
"""
from __future__ import annotations

from typing import Optional

from domain.payroll.run_status import PAYROLL_RELEASED


class PayslipNotFound(LookupError):
    """The slip is not one this employee may download — for any reason."""


def own_released_slip(db, employee: dict, slip_id: str) -> dict:
    """The run row of `slip_id`, if the slip is the principal's own and released.

    `employee` is the dict `get_current_portal_employee` resolves; only its
    `employee_id`, `firm_id` and `client_id` are read, and all three are
    REQUIRED — a principal missing one matches nothing rather than everything.
    """
    employee_id = employee.get("employee_id")
    firm_id = employee.get("firm_id")
    client_id = employee.get("client_id")
    if not (employee_id and firm_id and client_id and slip_id):
        raise PayslipNotFound(slip_id)

    slips = (db.table("payroll_slips").select("id, run_id, employee_id")
             .eq("id", slip_id).eq("employee_id", employee_id)
             .limit(1).execute().data) or []
    if not slips:
        raise PayslipNotFound(slip_id)

    run: Optional[dict] = next(iter(
        (db.table("payroll_runs").select("id, firm_id, client_id, status")
         .eq("id", slips[0]["run_id"]).eq("firm_id", firm_id)
         .eq("client_id", client_id).limit(1).execute().data) or []), None)
    if run is None or run.get("status") not in PAYROLL_RELEASED:
        raise PayslipNotFound(slip_id)
    return run
