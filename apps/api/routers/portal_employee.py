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

THE PORTAL'S OWN RECORD IS A ROUTE NOW (POST-A-010)
    This module used to say there was deliberately no `/me`: the portal read its own `payroll_employees` row, its payslip
    list, its leave balance and its tax declaration straight over PostgREST under migration 262's and 297's policies, and a
    second way to ask who the caller is would be one more thing to keep in step. The reasoning held while the browser was
    allowed to reach payroll tables at all. POST-A-010 closes that, for the staff screens and for this one, so the same
    four things are asked of the server, as the SAME principal, with nothing about a person in the request: `/access` (is
    this identity an activated employee, which two pages ask to decide where to send somebody), `/me`, `/payslips`,
    `/leave-balances` and `/tax-declaration`. They are read and written with the SERVER's client, as the two routes above
    already are, so the only thing that scopes a query is the principal's own ids: every query below carries the employee
    (and, where the table has them, the firm and the client) from the principal, and a test seeds a colleague's and another
    firm's rows beside the caller's to prove none is served.

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

from core.auth import get_jwt_user
from core.db_paging import fetch_all
from core.ist_clock import ist_today
from core.portal_auth import get_current_portal_employee
from domain.payroll import declarations as decl_domain
from domain.payroll.run_status import PAYROLL_RELEASED
from models.common import api_response
from models.fy import FYLabel
from models.payroll import EmployeeDeclarationIn
from services import it_declaration_service
from services.audit_service import log_event
from core.db_provider import privileged_for

router = APIRouter(prefix="/api/portal/employee", tags=["portal_employee"])


@router.get("/tds-projection")
def employee_tds_projection(
    financial_year: Annotated[FYLabel, Query(description='e.g. "2026-27"')],
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
        # The employer block is read with the privileged client: ownership was proved above, and an employee's own
        # sign-in cannot read the `clients` row the letterhead comes from (POST-A-220).
        pdf_bytes, filename = get_payslip_pdf(slip_id, employee["firm_id"], employer_db=db)
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


# ── the employee's own record, payslips, leave and declaration (POST-A-010) ─────────────────────────────────────────────

_DENIED = "Not an employee portal user."


def _employee_db():
    """The server's client, as the two routes above use it (`routers.payroll._db` is the privileged one): an employee's own
    sign-in is not what reads here, so every query below is scoped by the principal's ids and by nothing else. Refused in
    words where there is no database, because inventing an employee would make every guard vacuous."""
    from routers.payroll import _db
    db = _db()
    if not db:
        raise HTTPException(status_code=503, detail="The employee portal is unavailable in mock mode")
    return db


@router.get("/access")
def employee_portal_access(jwt_user: dict = Depends(get_jwt_user)):
    """Whether the signed-in identity is an activated employee: `{enabled: true|false}`, and never an error for someone who is
    not one.

    Two pages ask this to decide where to send somebody (the activation page: has this single-use link been used already;
    the client portal's dashboard: is this person in the wrong portal). A client contact who signs in at the client portal
    is not an employee, and answering that with a 403 would put a refusal in the log for every client login."""
    try:
        get_current_portal_employee(jwt_user)
    except HTTPException as exc:
        if exc.status_code == 403:
            return api_response(True, {"enabled": False})
        raise
    return api_response(True, {"enabled": True})


@router.get("/me")
def employee_me(employee: dict = Depends(get_current_portal_employee)):
    """The caller's OWN employee record: what the Profile tab and the page header show. No parameters; who is asking comes
    from the principal."""
    db = _employee_db()
    rows = (privileged_for(db).table("payroll_employees")
            .select("id, name, designation, department, pan, bank_account_no, bank_name, bank_ifsc")
            .eq("id", employee["employee_id"]).eq("firm_id", employee["firm_id"]).limit(1).execute().data) or []
    if not rows:
        # The ids came from the principal, so a miss means it no longer matches a live employee row.
        raise HTTPException(status_code=403, detail=_DENIED)
    return api_response(True, {"employee": rows[0]})


@router.get("/payslips")
def employee_payslips(employee: dict = Depends(get_current_portal_employee)):
    """The caller's OWN payslips in released runs, newest first.

    The same rule `own_released_slip` holds for one slip, for the list: the slip is the principal's, its run is in the
    principal's firm and client, and the run is released (`finalized` or `paid`). A draft has paid nobody, and migration 323
    already withholds it from the employee's own PostgREST read, so this list must not be the way round that policy. The
    period is the run's `month` as stored; a slip's amounts are the payroll module's, forwarded and never recomputed."""
    db = _employee_db()
    slips = fetch_all(
        lambda: privileged_for(db).table("payroll_slips").select("id, run_id, gross_paise, net_paise, created_at")
        .eq("employee_id", employee["employee_id"]),
        "id", label="payroll_slips")
    run_ids = sorted({str(s["run_id"]) for s in slips if s.get("run_id")})
    months: dict[str, str] = {}
    for start in range(0, len(run_ids), 50):
        for run in (privileged_for(db).table("payroll_runs").select("id, month, status")
                    .eq("firm_id", employee["firm_id"]).eq("client_id", employee["client_id"])
                    .in_("id", run_ids[start:start + 50]).execute().data or []):
            if run.get("status") in PAYROLL_RELEASED:
                months[str(run["id"])] = run.get("month") or ""
    rows = [{"id": s["id"], "month": months[str(s["run_id"])], "gross_paise": s.get("gross_paise"),
             "net_paise": s.get("net_paise"), "created_at": s.get("created_at")}
            for s in slips if str(s.get("run_id")) in months]
    rows.sort(key=lambda r: str(r["id"]))
    rows.sort(key=lambda r: str(r["created_at"] or ""), reverse=True)
    return api_response(True, {"payslips": rows})


@router.get("/leave-balances")
def employee_leave_balances(employee: dict = Depends(get_current_portal_employee)):
    """The caller's OWN leave entitlement recorded for the current calendar year, in IST.

    The year is the one the staff side keeps leave under (`PUT /api/payroll/leave-balances` records an allotment "for a
    calendar year"), asked as the Indian day: the portal used to ask for the April-to-March year's first calendar year,
    which from January to March is the PREVIOUS year's row and so showed an employee last year's entitlement while the CA
    had recorded this year's. An entitlement nobody recorded is an empty list, never a default."""
    db = _employee_db()
    year = ist_today().year
    rows = (privileged_for(db).table("leave_balances")
            .select("id, year, casual_leave_balance, sick_leave_balance, earned_leave_balance")
            .eq("employee_id", employee["employee_id"]).eq("firm_id", employee["firm_id"])
            .eq("year", year).execute().data) or []
    return api_response(True, {"year": year, "balances": rows})


def _declaration_view(db, employee: dict, fy: str) -> dict:
    """The caller's declaration for a year and its Chapter VI-A lines, in the columns the form shows (no firm, client or
    employee id: the form never needed them and the server owns them)."""
    heads = (privileged_for(db).table("payroll_it_declarations")
             .select("id, fy, regime, status, rent_paid_declared_paise, landlord_name, landlord_address, landlord_pan, "
                     "rent_is_metro, lta_declared_paise, home_loan_interest_declared_paise, lender_name, lender_pan, "
                     "other_income_declared_paise, house_property_loss_declared_paise, proofs_verified")
             .eq("employee_id", employee["employee_id"]).eq("firm_id", employee["firm_id"])
             .eq("fy", fy).limit(1).execute().data) or []
    if not heads:
        return {"fy": fy, "declaration": None, "items": []}
    items = (privileged_for(db).table("payroll_it_declaration_items")
             .select("id, section, label, amount_declared_paise, amount_verified_paise, status")
             .eq("declaration_id", heads[0]["id"]).eq("firm_id", employee["firm_id"]).execute().data) or []
    items.sort(key=lambda i: str(i.get("section") or ""))
    return {"fy": fy, "declaration": heads[0], "items": items}


@router.get("/tax-declaration")
def employee_tax_declaration(
    financial_year: Annotated[FYLabel, Query(description='e.g. "2026-27"')],
    employee: dict = Depends(get_current_portal_employee),
):
    """The caller's OWN §192 declaration (Form 12BB) for a year, or `declaration: null` when none is filed."""
    return api_response(True, _declaration_view(_employee_db(), employee, financial_year))


_LOCKED = ("Your proofs have been verified, so this declaration is read-only. Ask your payroll contact if something "
           "needs to change.")
_CHANGED = "Your declaration was changed while you were saving it. Reload it to see what is there now, then try again."


def _validated_candidate(body: EmployeeDeclarationIn, employee_id: str) -> "decl_domain.Declaration":
    """The declaration the body states, as the domain module's own type, or a 422 in words. The staff door's validation
    (`decl_domain.validate`) is the authority on what payroll can give effect to; a head declared twice is refused here."""
    candidate = decl_domain.Declaration(
        employee_id=employee_id, fy=body.fy, regime=body.regime, status=decl_domain.STATUS_SUBMITTED,
        rent_paid_declared_paise=body.rent_paid_declared_paise,
        landlord_name=body.landlord_name or "", landlord_address=body.landlord_address or "",
        landlord_pan=body.landlord_pan or "", rent_is_metro=body.rent_is_metro,
        lta_declared_paise=body.lta_declared_paise,
        home_loan_interest_declared_paise=body.home_loan_interest_declared_paise,
        lender_name=body.lender_name or "", lender_pan=body.lender_pan or "",
        other_income_declared_paise=body.other_income_declared_paise,
        house_property_loss_declared_paise=body.house_property_loss_declared_paise,
    )
    seen: set[str] = set()
    for it in body.items:
        if it.section in seen:
            raise HTTPException(status_code=422, detail=f"{it.section} is declared twice; declare each head once.")
        seen.add(it.section)
        candidate.items.append(decl_domain.DeclarationItem(section=it.section, amount_declared_paise=it.amount_declared_paise))
    problems = decl_domain.validate(candidate)
    if problems:
        raise HTTPException(status_code=422, detail=" ".join(problems))
    return candidate


@router.put("/tax-declaration")
def file_employee_tax_declaration(
    body: EmployeeDeclarationIn,
    employee: dict = Depends(get_current_portal_employee),
):
    """File the caller's OWN §192 declaration for a year, replacing the one they filed before.

    Rule 26C makes Form 12BB the EMPLOYEE's statement and the proofs the employer's to check, so this is the employee's
    door and the verification is not here: the body has no verified amount, no status and no proof, and the figures the CA
    had checked are reset (re-declaring means the figures being claimed are not the ones that were checked, and carrying
    the old verdict forward would let a raised claim inherit the proof for a smaller one: the staff door does the same).

    WHO AND WHAT come from the principal: the employee, their client and their firm are never in the request. A
    declaration the CA has finished verifying is read-only to the employee (409), and that is decided IN THE WRITE: the
    database function locks the declaration's row and refuses a verified one in the same transaction that would have
    changed it, so a CA who finishes verifying between this request's start and its write is not overwritten. The same
    validation the staff door applies refuses what payroll cannot give effect to (a landlord's name against rent, a
    landlord's PAN above the Rule 26C threshold, a lender's PAN against §24(b) interest, a section it does not compute),
    in the employee's own terms, naming the box.

    ONE TRANSACTION (migration 548, POST-A-340): the header, the new lines and the removal of the old lines are made by
    `file_it_declaration` in one database transaction under a row lock, so a failure at any step leaves the declaration as
    it was and two filings by one employee at the same instant run one after the other. The read-back and the put-back
    this route used to carry are gone with the thing they stood in for.

    Written with the SERVER's client: ownership is proved above, the verified columns belong to whoever checks them
    (migration 297 raises on an employee changing one, and this write must be able to reset them), and the browser is no
    longer a writer of these tables.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    """
    from core.supabase_client import get_service_supabase

    firm_id, client_id, employee_id = employee["firm_id"], employee["client_id"], employee["employee_id"]
    candidate = _validated_candidate(body, employee_id)

    if not client_id:
        raise HTTPException(status_code=403, detail=_DENIED)
    svc = get_service_supabase()
    # A head declared at nothing is not a line.
    lines = [{"section": i.section, "label": "", "amount_declared_paise": i.amount_declared_paise,
              "proof_reference": "", "proof_attachments": []}
             for i in candidate.items if i.amount_declared_paise > 0]
    try:
        decl_id = it_declaration_service.file_declaration(
            svc, firm_id=firm_id, client_id=client_id, employee_id=employee_id, fy=body.fy, regime=body.regime,
            rent_paid_declared_paise=body.rent_paid_declared_paise,
            landlord_name=body.landlord_name or "", landlord_address=body.landlord_address or "",
            landlord_pan=body.landlord_pan or "", rent_is_metro=body.rent_is_metro,
            lta_declared_paise=body.lta_declared_paise,
            home_loan_interest_declared_paise=body.home_loan_interest_declared_paise,
            lender_name=body.lender_name or "", lender_pan=body.lender_pan or "",
            other_income_declared_paise=body.other_income_declared_paise,
            house_property_loss_declared_paise=body.house_property_loss_declared_paise,
            items=lines, refuse_verified=True)
    except it_declaration_service.DeclarationVerified as exc:
        raise HTTPException(status_code=409, detail=_LOCKED) from exc
    except it_declaration_service.DeclarationBusy as exc:
        raise HTTPException(status_code=409, detail=_CHANGED) from exc
    except it_declaration_service.DeclarationOutOfScope as exc:
        raise HTTPException(status_code=403, detail=_DENIED) from exc

    log_event(firm_id, "payroll_it_declaration", decl_id, "employee_declare", actor_id=employee.get("auth_user_id"),
              actor_email=employee.get("email"),
              new_data={"fy": body.fy, "regime": body.regime, "lines": len(lines)},
              metadata={"employee_id": employee_id, "principal": "PortalEmployee"})
    return api_response(True, _declaration_view(svc, employee, body.fy))
