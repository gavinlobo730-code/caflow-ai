"""A payroll handler that takes a client from the request acts only on an employee OF THAT CLIENT (found on 24-10-2026).

WHAT WAS WRONG
    Eleven handlers in routers/payroll.py take the client from the request (a body field or a query parameter) and the employee
    from the path or the body, assert the caller's access to the CLIENT THEY NAMED, and then read or write the employee's rows
    with the privileged client, filtered by the firm and the employee id alone. Access to client A says nothing about an employee
    of client B, so a member assigned to client A alone could name A beside B's employee id and:
      * read B's employee's leaver settlement (preview), salary revisions and loans;
      * record B's employee's settlement (a journal posted into A's books out of B's salary data, B's employee marked resigned),
        perquisites, salary revision, loan, bonus disqualification and income-tax declaration, verify B's declaration, delete B's
        bonus disqualification.
    `_employee_of_client` is the one read that ties the two, 404 "Employee not found" for a missing employee and for one of another
    client alike; `verify_declaration` ties the declaration to the client in its own read.

THE RULE, AND WHY IT IS THIS SHAPE
    Every handler in routers/payroll.py that names an employee must call one of the helpers that establishes whose employee it is
    (or be listed below with the reason it needs none). The list is derived from the router's own source, so a new handler is held
    to it without being added here.
"""
from __future__ import annotations

import ast
import pathlib

import pytest
from fastapi import HTTPException

import routers.payroll as pr
from models.payroll import DeclarationIn, DeclarationVerifyIn
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "11111111-1111-1111-1111-111111111111"
CLIENT_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
CLIENT_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
EMP_A = "a0000000-0000-0000-0000-00000000000a"
EMP_B = "b0000000-0000-0000-0000-00000000000b"
DECL_B = "d0000000-0000-0000-0000-00000000000b"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "au1", "role": "Partner", "email": "p@example.test"}

ROUTER = pathlib.Path(pr.__file__)


@pytest.fixture
def world(monkeypatch):
    db = FakeDB()
    db.seed("payroll_employees", {"id": EMP_A, "firm_id": FIRM, "client_id": CLIENT_A, "name": "Asha"})
    db.seed("payroll_employees", {"id": EMP_B, "firm_id": FIRM, "client_id": CLIENT_B, "name": "Bala"})
    db.seed("payroll_it_declarations", {"id": DECL_B, "firm_id": FIRM, "client_id": CLIENT_B, "employee_id": EMP_B,
                                        "fy": "2026-27", "status": "submitted", "rent_paid_declared_paise": 100,
                                        "rent_paid_verified_paise": 0, "lta_declared_paise": 0, "lta_verified_paise": 0,
                                        "home_loan_interest_declared_paise": 0, "home_loan_interest_verified_paise": 0})
    db.seed("payroll_salary_revisions", {"id": "r-b", "firm_id": FIRM, "client_id": CLIENT_B, "employee_id": EMP_B,
                                         "effective_from": "2026-04-01", "basic_paise": 5000000})
    db.seed("payroll_loans", {"id": "l-b", "firm_id": FIRM, "client_id": CLIENT_B, "employee_id": EMP_B,
                              "principal_paise": 100000, "outstanding_paise": 100000})
    db.seed("payroll_perquisites", {"id": "p-b", "firm_id": FIRM, "client_id": CLIENT_B, "employee_id": EMP_B, "fy": "2026-27",
                                    "label": "car", "value_paise": 100})
    db.seed("bonus_disqualifications", {"id": "bd-b", "firm_id": FIRM, "client_id": CLIENT_B, "employee_id": EMP_B,
                                        "accounting_year": "2025-26", "ground": "fraud", "dismissed_on": "2026-01-01"})
    wire_e2e(monkeypatch, db, [pr])
    monkeypatch.setattr(pr, "_db", lambda: db)
    monkeypatch.setattr(pr, "assert_payroll_enabled", lambda *a, **k: None)
    monkeypatch.setattr(pr, "assert_not_internal_for_payroll", lambda *a, **k: None)
    import services.audit_service as audit
    monkeypatch.setattr(audit, "log_event", lambda *a, **k: None)
    return db


def _snapshot(db):
    return {t: [dict(r) for r in db.rows(t)] for t in
            ("payroll_employees", "payroll_it_declarations", "payroll_salary_revisions", "payroll_loans",
             "payroll_perquisites", "bonus_disqualifications", "payroll_settlements")}


def _settlement_in(cls, **over):
    return cls(client_id=CLIENT_A, leaving_date="2026-09-30", **over)


def _calls():
    """(label, callable) — each names client A and employee B's id (or declaration B's), as an assigned-to-A member could."""
    from domain.payroll import bonus_register as br
    ground = sorted(br.SECTION_9_GROUNDS)[0]
    return [
        ("preview_settlement",
         lambda: pr.preview_settlement(EMP_B, _settlement_in(pr.SettlementIn), current_user=USER)),
        ("record_settlement",
         lambda: pr.record_settlement(EMP_B, _settlement_in(pr.SettlementRecordIn), current_user=USER)),
        ("upsert_declaration",
         lambda: pr.upsert_declaration(DeclarationIn(client_id=CLIENT_A, employee_id=EMP_B, fy="2026-27"), current_user=USER)),
        ("verify_declaration",
         lambda: pr.verify_declaration(DECL_B, DeclarationVerifyIn(client_id=CLIENT_A), current_user=USER)),
        ("record_perquisites",
         lambda: pr.record_perquisites(EMP_B, pr.PerquisiteRecordIn(client_id=CLIENT_A, fy="2026-27",
                                                                    items=[{"label": "x", "value_paise": 1}]),
                                       current_user=USER)),
        ("add_salary_revision",
         lambda: pr.add_salary_revision(EMP_B, pr.SalaryRevisionIn(client_id=CLIENT_A, effective_from="2026-04-01",
                                                                   basic_paise=1), current_user=USER)),
        ("list_salary_revisions",
         lambda: pr.list_salary_revisions(EMP_B, client_id=CLIENT_A, current_user=USER)),
        ("add_employee_loan",
         lambda: pr.add_employee_loan(EMP_B, pr.EmployeeLoanIn(client_id=CLIENT_A, principal_paise=1000,
                                                               monthly_instalment_paise=100), current_user=USER)),
        ("list_employee_loans",
         lambda: pr.list_employee_loans(EMP_B, client_id=CLIENT_A, current_user=USER)),
        ("put_bonus_disqualification",
         lambda: pr.put_bonus_disqualification(pr.BonusDisqualificationIn(client_id=CLIENT_A, employee_id=EMP_B,
                                                                          accounting_year="2025-26", ground=ground,
                                                                          dismissed_on="2026-02-02"), current_user=USER)),
        ("delete_bonus_disqualification",
         lambda: pr.delete_bonus_disqualification(client_id=CLIENT_A, employee_id=EMP_B, accounting_year="2025-26",
                                                  current_user=USER)),
    ]


@pytest.mark.parametrize("label,call", _calls(), ids=[c[0] for c in _calls()])
def test_naming_ones_own_client_beside_another_clients_employee_is_a_404_and_writes_nothing(world, label, call):
    before = _snapshot(world)
    with pytest.raises(HTTPException) as e:
        call()
    assert e.value.status_code == 404, label
    # the SAME words for an employee that is not there and for one in another client; the declaration route words its own row
    assert e.value.detail in ("Employee not found", "Declaration not found"), (label, e.value.detail)
    assert _snapshot(world) == before, f"{label} changed a row of the other client"


def test_a_missing_employee_and_one_of_another_client_say_the_same_words(world):
    with pytest.raises(HTTPException) as other:
        pr.list_employee_loans(EMP_B, client_id=CLIENT_A, current_user=USER)
    with pytest.raises(HTTPException) as missing:
        pr.list_employee_loans("00000000-0000-0000-0000-000000000000", client_id=CLIENT_A, current_user=USER)
    assert (other.value.status_code, other.value.detail) == (missing.value.status_code, missing.value.detail) == (404, "Employee not found")


def test_the_clients_own_employee_is_still_served_and_written(world):
    """The positive control: the tie must not break the ordinary path."""
    got = pr.list_salary_revisions(EMP_A, client_id=CLIENT_A, current_user=USER)
    assert got["success"] is True and got["data"]["revisions"] == []
    got = pr.list_employee_loans(EMP_A, client_id=CLIENT_A, current_user=USER)
    assert got["success"] is True and got["data"]["loans"] == []
    pr.add_salary_revision(EMP_A, pr.SalaryRevisionIn(client_id=CLIENT_A, effective_from="2026-04-01", basic_paise=1),
                           current_user=USER)
    assert [r["employee_id"] for r in world.rows("payroll_salary_revisions") if r["client_id"] == CLIENT_A] == [EMP_A]
    pr.add_employee_loan(EMP_A, pr.EmployeeLoanIn(client_id=CLIENT_A, principal_paise=1000, monthly_instalment_paise=100),
                         current_user=USER)
    assert [r["employee_id"] for r in world.rows("payroll_loans") if r["client_id"] == CLIENT_A] == [EMP_A]
    pr.record_perquisites(EMP_A, pr.PerquisiteRecordIn(client_id=CLIENT_A, fy="2026-27", items=[{"label": "x", "value_paise": 1}]),
                          current_user=USER)
    assert [r["employee_id"] for r in world.rows("payroll_perquisites") if r["client_id"] == CLIENT_A] == [EMP_A]


def test_the_declaration_bonus_and_settlement_routes_still_work_for_the_clients_own_employee(world):
    """Positive controls for the six handlers the loop above only refuses: a swapped argument would pass every negative above."""
    from domain.payroll import bonus_register as br
    ground = sorted(br.SECTION_9_GROUNDS)[0]
    # the employee's own declaration, filed under the employee's own client, is verified
    world.seed("payroll_it_declarations", {"id": "d0000000-0000-0000-0000-00000000000a", "firm_id": FIRM, "client_id": CLIENT_A,
                                           "employee_id": EMP_A, "fy": "2026-27", "status": "submitted",
                                           "rent_paid_declared_paise": 0, "rent_paid_verified_paise": 0, "lta_declared_paise": 0,
                                           "lta_verified_paise": 0, "home_loan_interest_declared_paise": 0,
                                           "home_loan_interest_verified_paise": 0})
    out = pr.verify_declaration("d0000000-0000-0000-0000-00000000000a", DeclarationVerifyIn(client_id=CLIENT_A), current_user=USER)
    assert out["success"] is True
    out = pr.upsert_declaration(DeclarationIn(client_id=CLIENT_A, employee_id=EMP_A, fy="2026-27"), current_user=USER)
    assert out["success"] is True
    # bonus disqualification: written, then retracted, for the employee's own client
    out = pr.put_bonus_disqualification(pr.BonusDisqualificationIn(client_id=CLIENT_A, employee_id=EMP_A, accounting_year="2025-26",
                                                                   ground=ground, dismissed_on="2026-02-02"), current_user=USER)
    assert out["success"] is True
    assert [r["employee_id"] for r in world.rows("bonus_disqualifications") if r["client_id"] == CLIENT_A] == [EMP_A]
    pr.delete_bonus_disqualification(client_id=CLIENT_A, employee_id=EMP_A, accounting_year="2025-26", current_user=USER)
    assert [r for r in world.rows("bonus_disqualifications") if r["client_id"] == CLIENT_A] == []
    # the leaver settlement is composed for the employee's own client (the figures are not the point: the 404 is not raised)
    world.rows("payroll_employees")[0].update({"joining_date": "2015-04-01", "basic_paise": 50_000_00, "status": "active"})
    out = pr.preview_settlement(EMP_A, pr.SettlementIn(client_id=CLIENT_A, leaving_date="2026-09-30"), current_user=USER)
    assert out["success"] is True and out["data"]["employee_id"] == EMP_A


# handler label -> (the employee id the handler was given, the client it was told to act for): what `_employee_of_client` must be asked
WIRING = {
    "preview_settlement": (EMP_B, CLIENT_A), "record_settlement": (EMP_B, CLIENT_A), "upsert_declaration": (EMP_B, CLIENT_A),
    "record_perquisites": (EMP_B, CLIENT_A), "add_salary_revision": (EMP_B, CLIENT_A), "list_salary_revisions": (EMP_B, CLIENT_A),
    "add_employee_loan": (EMP_B, CLIENT_A), "list_employee_loans": (EMP_B, CLIENT_A),
    "put_bonus_disqualification": (EMP_B, CLIENT_A), "delete_bonus_disqualification": (EMP_B, CLIENT_A),
}


@pytest.mark.parametrize("label", sorted(WIRING))
def test_each_handler_asks_the_helper_about_the_employee_and_the_client_it_was_given(world, monkeypatch, label):
    """A swapped or wrong argument would 404 the client's OWN employee, which no negative case above can see (it expects a 404)."""
    seen = []

    def spy(db, current_user, employee_id, client_id, columns="id"):
        seen.append((employee_id, client_id))
        raise HTTPException(status_code=404, detail="Employee not found")

    monkeypatch.setattr(pr, "_employee_of_client", spy)
    call = dict((c[0], c[1]) for c in _calls())[label]
    with pytest.raises(HTTPException):
        call()
    assert seen == [WIRING[label]], (label, seen)


def test_the_helper_filters_by_firm_as_well_as_client(world):
    world.seed("payroll_employees", {"id": "f0000000-0000-0000-0000-00000000000f", "firm_id": "99999999-9999-9999-9999-999999999999",
                                     "client_id": CLIENT_A, "name": "Other firm"})
    with pytest.raises(HTTPException):
        pr._employee_of_client(world, USER, "f0000000-0000-0000-0000-00000000000f", CLIENT_A)
    assert pr._employee_of_client(world, USER, EMP_A, CLIENT_A)["id"] == EMP_A


# ── the rule over the router's own source ────────────────────────────────────────────────────────────────────────────
ESTABLISHES_WHOSE = {"_assert_employee_scope", "_employee_of_client", "_assert_run_scope", "_assert_slip_scope"}

# handler -> why it needs no employee-to-client tie. Every entry is a handler whose source mentions an employee id and which is NOT
# one of the eleven above; the reason is the thing a reviewer checked.
EXEMPT = {
    "import_employees": "the roster is read by firm and client and an update's id comes from that roster (`existing_by_code`)",
    "apply_salary_structure": "the roster is read by firm and client; an employee id outside it is refused (`strangers`, 422)",
    "get_slips": "the runs are resolved by firm and client, and an employee id only narrows the slips of those runs",
    "get_attendance": "the roster is read by firm and client",
    "put_attendance": "the roster is read by firm and client and an id outside it is refused",
    "get_one_time_earnings": "the rows are read by firm, client and month",
    "put_one_time_earnings": "the roster is read by firm and client; an id outside it is refused (`strangers`)",
    "payroll_employee_exceptions": "reads the firm's employees and narrows the result to the caller's clients at the end",
    "tds_projection": "`compute_tds_projection` reads the employee by firm, client AND id",
    "statutory_position": "employees are read by firm and client; the employee id is only a key into those rows",
    "arrears_relief": "computes from the figures in the body and reads no row",
    "value_perquisites": "computes from the figures in the body and reads no row",
}


def _handlers():
    src = ROUTER.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for fn in tree.body:
        if not isinstance(fn, ast.FunctionDef):
            continue
        routed = any(isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                     and d.func.attr in ("get", "post", "put", "patch", "delete") for d in fn.decorator_list)
        if routed and "employee_id" in (ast.get_source_segment(src, fn) or ""):
            yield fn.name, ast.get_source_segment(src, fn)


def _calls_a_helper(source: str) -> bool:
    """A real, reachable CALL of one of the helpers, made on the bare name and handed the client: a comment, a docstring, a call in a
    lambda or under `if False`, a method of another object with the same name, and a call that is not given a client do not count."""
    import textwrap
    tree = ast.parse(textwrap.dedent(source))
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}

    def unreachable(node) -> bool:
        while node in parents:
            node = parents[node]
            if isinstance(node, ast.Lambda):
                return True
            if isinstance(node, ast.If) and isinstance(node.test, ast.Constant) and not node.test.value:
                return True
        return False

    for n in ast.walk(tree):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ESTABLISHES_WHOSE) or unreachable(n):
            continue
        # `_employee_of_client` must be handed the client; the `_assert_*_scope` helpers read the row's own client and are not
        if n.func.id != "_employee_of_client" or "client_id" in ast.unparse(n):
            return True
    return False


def test_every_payroll_handler_that_names_an_employee_establishes_whose_employee_it_is():
    offenders = sorted(n for n, s in _handlers() if not _calls_a_helper(s) and n not in EXEMPT)
    assert not offenders, (
        "These payroll handlers name an employee and neither call a helper that ties the employee to the client nor appear in "
        f"EXEMPT with a reason: {offenders}. Call `_employee_of_client(db, current_user, employee_id, client_id)` after asserting "
        "the client (a read by firm and employee id alone reaches another client's employee).")


def test_the_exemptions_are_still_needed_and_the_rule_is_not_vacuous():
    names = dict(_handlers())
    stale = sorted(n for n in EXEMPT if n not in names or _calls_a_helper(names[n]))
    assert not stale, f"These EXEMPT entries no longer apply (the handler is gone or now calls a helper): {stale}"
    covered = sorted(n for n, s in _handlers() if _calls_a_helper(s))
    assert len(covered) >= 18, f"the rule found only {len(covered)} handlers that establish whose employee it is"
    for needed in ("preview_settlement", "record_settlement", "upsert_declaration", "record_perquisites", "add_salary_revision",
                   "list_salary_revisions", "add_employee_loan", "list_employee_loans", "put_bonus_disqualification",
                   "delete_bonus_disqualification"):
        assert needed in covered, needed


def test_negative_control_the_old_shape_is_what_the_rule_catches():
    """A handler written the way the eleven were (assert the named client, read the employee by firm and id) is an offender."""
    old = (
        "def f(employee_id, body, current_user):\n"
        "    assert_client_access(current_user, body.client_id)\n"
        "    emp = db.table('payroll_employees').select('*').eq('id', employee_id).eq('firm_id', 'x').execute().data\n"
    )
    assert not _calls_a_helper(old)
    assert not _calls_a_helper(old + "    # _employee_of_client(db, current_user, employee_id, body.client_id)\n")
    # each way a call can look like protection and not be
    assert not _calls_a_helper(old + "    if False:\n        _employee_of_client(db, current_user, employee_id, body.client_id)\n")
    assert not _calls_a_helper(old + "    f = lambda: _employee_of_client(db, current_user, employee_id, body.client_id)\n")
    assert not _calls_a_helper(old + "    other._employee_of_client(db, current_user, employee_id, body.client_id)\n")
    assert not _calls_a_helper(old + "    _employee_of_client(db, current_user, employee_id, employee_id)\n")
    assert _calls_a_helper(old + "    _employee_of_client(db, current_user, employee_id, body.client_id)\n")
