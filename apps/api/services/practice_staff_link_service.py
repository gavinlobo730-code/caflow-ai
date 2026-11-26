"""A MEMBER OF THE FIRM'S STAFF IS TWO RECORDS, AND ONE COLUMN SAYS THEY ARE ONE PERSON (POST-A-540).

A sign-in on the Team screen is a row of `users`. An employee the firm pays in its own payroll (the practice client,
POST-A-532) is a row of `payroll_employees`. `payroll_employees.staff_user_id` (migration 776) is the link between them.

A LINK, NEVER A MERGE. Nothing here writes one record from the other: a name may be spelt differently on each and both are
shown; removing a member does not remove an employee, and the reverse. The link is on the payroll side on purpose: the firm's
own payroll is a Partner's alone (guardrail G4), so only somebody who may read that payroll can read who is on it. The Team
list is a Manager's too, and it never carries the link.

Three rules, each asked here in a sentence before anything is written, and each also held by the database:

  1. the member is one of this firm's (`member_is_the_firms`; the database's `guard_member_firm`);
  2. the employee is in the firm's OWN payroll: a client's employee is not a member of the firm's staff (the trigger);
  3. one member is at most one employee (the partial unique index).

Every statement runs on the server's own client (`privileged_for`, as every query on a payroll table must: the signed-in
role holds nothing on them since migration 549) and names the firm, because row security does not run for that client.
"""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException

from core.db_paging import fetch_all
from core.db_provider import privileged_for
from core.observability import capture_soft_failure
from services.internal_client_service import get_internal_client_id
from services.named_row_ownership import member_is_the_firms

#: The columns of an employee the Team screen is shown. Nothing of pay, no identifier, no bank detail.
ROSTER_COLUMNS = "id, name, employee_code, designation, status, staff_user_id"

A_CLIENTS_EMPLOYEE = (
    "A team member is linked only to an employee in the firm's own payroll (My practice, Payroll). "
    "This employee is on a client's payroll, so there is nobody on the Team screen for them to be."
)


def already_linked(name: Optional[str]) -> str:
    who = f"{name.strip()} in" if (name or "").strip() else "another employee in"
    return f"That team member is already linked to {who} the firm's own payroll. Remove that link first: one person is one employee."


def the_member_may_be_linked(db, firm_id: str, client_id: Optional[str], staff_user_id: Optional[str],
                             *, employee_id: Optional[str] = None) -> None:
    """Ask the three rules of a link BEFORE it is written. Nothing named, nothing asked.

    `employee_id` is the employee the link is being written ON (None while that employee is being created), so that writing
    the link an employee already carries is not refused as a duplicate of itself."""
    if db is None or not staff_user_id:
        return
    practice = get_internal_client_id(firm_id)
    if not practice or str(practice) != str(client_id or ""):
        raise HTTPException(status_code=422, detail=A_CLIENTS_EMPLOYEE)
    member_is_the_firms(db, firm_id, staff_user_id)
    holders = (privileged_for(db).table("payroll_employees").select("id, name")
               .eq("firm_id", firm_id).eq("staff_user_id", staff_user_id).limit(2).execute().data) or []
    others = [h for h in holders if str(h.get("id")) != str(employee_id or "")]
    if others:
        raise HTTPException(status_code=409, detail=already_linked(others[0].get("name")))


def set_link(db, firm_id: str, employee_id: str, client_id: Optional[str], staff_user_id: Optional[str]) -> dict:
    """Write, or clear, the link on one employee of the firm's own payroll, and answer the row as the roster shows it."""
    if staff_user_id:
        the_member_may_be_linked(db, firm_id, client_id, staff_user_id, employee_id=employee_id)
    rows = (privileged_for(db).table("payroll_employees").update({"staff_user_id": staff_user_id or None})
            .eq("id", employee_id).eq("firm_id", firm_id).eq("client_id", client_id).execute().data) or []
    if not rows:
        raise HTTPException(status_code=404, detail="Employee not found")
    return {k.strip(): rows[0].get(k.strip()) for k in ROSTER_COLUMNS.split(",")}


def roster(db, firm_id: str) -> dict:
    """The firm's own payroll as the Team screen needs it: is there one, is it switched on, and who is on it.

    `payroll_enabled` is None when the switch could not be read (never False: "not switched on" sends a Partner to switch it on).
    A firm with no practice client answers `practice_client_id: None` and an empty list, which is a fact and not a failure."""
    practice = get_internal_client_id(firm_id)
    if db is None or not practice:
        return {"practice_client_id": None, "payroll_enabled": False, "employees": []}
    try:
        resp = (privileged_for(db).table("client_payroll_settings").select("payroll_enabled")
                .eq("firm_id", firm_id).eq("client_id", practice).limit(1).execute())
        enabled: Optional[bool] = bool(((resp.data if resp else None) or [{}])[0].get("payroll_enabled"))
    except Exception as exc:
        capture_soft_failure(exc, operation="payroll.practice_staff.switch", firm_id=firm_id)
        enabled = None
    employees = fetch_all(
        lambda: (privileged_for(db).table("payroll_employees").select("id, name, employee_code, designation, status, staff_user_id")
                 .eq("firm_id", firm_id).eq("client_id", practice)),
        "id", label="payroll_employees")
    employees.sort(key=lambda r: (str(r.get("name") or "").casefold(), str(r.get("id") or "")))
    return {"practice_client_id": str(practice), "payroll_enabled": enabled, "employees": employees}
