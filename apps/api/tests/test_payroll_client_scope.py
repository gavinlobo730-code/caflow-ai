"""
Client-assignment scope on the payroll router.

The most sensitive surface the sweep has reached. `payroll` imported no authz at
all, so any authenticated member of a firm could reach any client's:

  * individual salaries, PAN, PF/ESI numbers and employee bank details
  * a named person's payslip PDF (`/salary-slips/{slip_id}/pdf`)
  * the salary register and statutory summary
  * and the endpoints that FINALIZE, **DISBURSE** and REVERSE a payroll run

`core.authz` makes only the Partner firm-wide; a Manager, Executive or Reviewer
sees only the clients in `user_client_assignments`.

THE AWKWARD TABLE
    `payroll_slips` has a `run_id` and an `employee_id` and nothing else — no
    client_id, and **no firm_id either**. One person's payslip is stored in a
    table with no tenant column at all, so it is scoped through its run. That
    makes the run lookup load-bearing for both boundaries, which is why the slip
    guard must not stop once it has found the slip row.
"""
import pytest
from fastapi import HTTPException

import routers.payroll as pr

FIRM, OTHER_FIRM = "firm-1", "firm-2"
MINE, THEIRS = "client-mine", "client-theirs"
USER = {"id": "u1", "firm_id": FIRM, "role": "manager"}

RUNS = [
    {"id": "RUN-MINE", "firm_id": FIRM, "client_id": MINE},
    {"id": "RUN-THEIRS", "firm_id": FIRM, "client_id": THEIRS},
]
EMPLOYEES = [
    {"id": "E-MINE", "firm_id": FIRM, "client_id": MINE, "name": "A", "status": "active"},
    {"id": "E-THEIRS", "firm_id": FIRM, "client_id": THEIRS, "name": "B", "status": "active"},
]
SLIPS = [
    {"id": "S-MINE", "run_id": "RUN-MINE", "employee_id": "E-MINE"},
    {"id": "S-THEIRS", "run_id": "RUN-THEIRS", "employee_id": "E-THEIRS"},
]
TABLES = {"payroll_runs": RUNS, "payroll_employees": EMPLOYEES, "payroll_slips": SLIPS}


class _Q:
    def __init__(self, rows, log, table):
        self.rows, self.log, self.table = rows, log, table
        self.eqs = []

    def select(self, *_a): return self
    def eq(self, k, v): self.eqs.append((k, v)); self.rows = [r for r in self.rows if r.get(k) == v]; return self
    def limit(self, n): self.rows = self.rows[:n]; return self
    def order(self, *_a, **_k): return self
    def execute(self):
        self.log.append((self.table, dict(self.eqs)))
        return type("R", (), {"data": list(self.rows)})()


class _DB:
    def __init__(self): self.log = []
    def table(self, name):
        return _Q([dict(r) for r in TABLES.get(name, [])], self.log, name)


@pytest.fixture
def db():
    return _DB()


@pytest.fixture
def deny(monkeypatch):
    """Refuse one client, allow the rest — a real assignment boundary, and it
    catches a guard that resolves the wrong id."""
    seen = []

    def _check(user, client_id):
        seen.append(client_id)
        if client_id == THEIRS:
            raise HTTPException(status_code=404, detail="Not found")

    monkeypatch.setattr(pr, "assert_client_access", _check)
    return seen


# ══════════════════════════════════════════════════════════════════════════════
# Runs — finalize, disburse, reverse
# ══════════════════════════════════════════════════════════════════════════════

def test_another_clients_payroll_run_is_refused(db, deny):
    with pytest.raises(HTTPException) as e:
        pr._assert_run_scope(db, USER, "RUN-THEIRS")
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_your_own_run_resolves_to_its_client(db, deny):
    assert pr._assert_run_scope(db, USER, "RUN-MINE") == MINE
    assert deny == [MINE]


def test_the_run_lookup_is_still_firm_scoped(db, deny):
    """Assignment scope is an ADDITION to tenant scope, not a replacement."""
    other = {"id": "u2", "firm_id": OTHER_FIRM, "role": "partner"}
    with pytest.raises(HTTPException) as e:
        pr._assert_run_scope(db, other, "RUN-MINE")
    assert e.value.status_code == 404
    assert db.log == [("payroll_runs", {"id": "RUN-MINE", "firm_id": OTHER_FIRM})]
    assert deny == []


def test_an_unknown_run_is_the_same_404_as_a_forbidden_one(db, deny):
    with pytest.raises(HTTPException) as missing:
        pr._assert_run_scope(_DB(), USER, "no-such-run")
    with pytest.raises(HTTPException) as hidden:
        pr._assert_run_scope(_DB(), USER, "RUN-THEIRS")
    assert missing.value.status_code == hidden.value.status_code == 404


@pytest.mark.parametrize("fn", ["update_run_status", "finalize_run",
                                "disburse_run", "reverse_run", "get_run_slips"])
def test_every_run_endpoint_refuses_before_it_acts(fn, deny, monkeypatch):
    """`disburse_run` moves money and `reverse_run` writes a reversing journal.
    A refusal after the fact is not a refusal, so the guard has to be the first
    thing each of these does."""
    monkeypatch.setattr(pr, "_db", lambda: _DB())
    handler = getattr(pr, fn)
    kwargs = {"current_user": USER}
    # Supply whatever body each handler declares — the point is the guard, not
    # the payload, and a missing-argument TypeError would look like a pass.
    import inspect as _i
    for name in _i.signature(handler).parameters:
        if name in ("data", "payload", "body"):
            kwargs[name] = type("D", (), {"status": "review", "client_id": THEIRS,
                                          "bank_account_id": "b1", "reason": "x"})()
    with pytest.raises(HTTPException) as e:
        handler("RUN-THEIRS", **kwargs)
    assert e.value.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# Employees — salary, PAN, PF/ESI, bank details
# ══════════════════════════════════════════════════════════════════════════════

def test_another_clients_employee_is_refused(db, deny):
    with pytest.raises(HTTPException) as e:
        pr._assert_employee_scope(db, USER, "E-THEIRS")
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_the_employee_roster_is_narrowed_when_no_client_is_named(monkeypatch, deny):
    """The firm-wide branch is exactly why this needs narrowing and not just a
    check: without it an Executive assigned to two clients gets every employee
    in the firm — salary and PAN included — in one call."""
    monkeypatch.setattr(pr, "_db", lambda: _DB())
    monkeypatch.setattr(pr, "filter_by_client",
                        lambda _u, rows: [r for r in rows if r.get("client_id") == MINE])
    out = pr.list_employees(client_id=None, include_inactive=False, current_user=USER)
    assert [e["id"] for e in out["data"]] == ["E-MINE"]


def test_naming_a_client_checks_it_instead_of_narrowing(monkeypatch, deny):
    """A named request gets a refusal, not a silently empty roster — an empty
    roster reads as "this client has no employees"."""
    monkeypatch.setattr(pr, "_db", lambda: _DB())
    monkeypatch.setattr(pr, "filter_by_client",
                        lambda *_a: pytest.fail("should not narrow a named request"))
    with pytest.raises(HTTPException):
        pr.list_employees(client_id=THEIRS, include_inactive=False, current_user=USER)
    assert deny == [THEIRS]


def test_the_runs_list_is_narrowed_too(monkeypatch, deny):
    monkeypatch.setattr(pr, "_db", lambda: _DB())
    monkeypatch.setattr(pr, "filter_by_client",
                        lambda _u, rows: [r for r in rows if r.get("client_id") == MINE])
    out = pr.list_runs(client_id=None, current_user=USER)
    assert [r["id"] for r in out["data"]] == ["RUN-MINE"]


# ══════════════════════════════════════════════════════════════════════════════
# Payslips — a table with no tenant column at all
# ══════════════════════════════════════════════════════════════════════════════

def test_another_clients_payslip_is_refused(db, deny):
    """One named person's salary, in a PDF."""
    with pytest.raises(HTTPException) as e:
        pr._assert_slip_scope(db, USER, "S-THEIRS")
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_your_own_payslip_resolves(db, deny):
    assert pr._assert_slip_scope(db, USER, "S-MINE") == MINE


def test_the_slip_guard_goes_through_the_run_for_BOTH_boundaries(db, deny):
    """payroll_slips has no firm_id, so the slip lookup CANNOT be firm-scoped —
    the run hop is what establishes the firm as well as the client. A guard that
    stopped at the slip row would have neither."""
    pr._assert_slip_scope(db, USER, "S-MINE")
    tables = [t for t, _f in db.log]
    assert tables == ["payroll_slips", "payroll_runs"]
    slip_filters, run_filters = (f for _t, f in db.log)
    assert "firm_id" not in slip_filters      # the column does not exist
    assert run_filters["firm_id"] == FIRM     # …so the run carries it


def test_a_payslip_from_another_firm_is_refused_by_the_run_hop(db, deny):
    other = {"id": "u2", "firm_id": OTHER_FIRM, "role": "partner"}
    with pytest.raises(HTTPException) as e:
        pr._assert_slip_scope(db, other, "S-MINE")
    assert e.value.status_code == 404


def test_an_unknown_slip_is_a_404(db, deny):
    with pytest.raises(HTTPException) as e:
        pr._assert_slip_scope(db, USER, "no-such-slip")
    assert e.value.status_code == 404
    assert deny == []


# ══════════════════════════════════════════════════════════════════════════════
# Mock mode
# ══════════════════════════════════════════════════════════════════════════════

def test_the_guards_are_inert_without_a_database(deny):
    """Mock mode has no assignments table, so there is nothing to resolve. The
    guards return rather than 404 — refusing everything would break local dev,
    and there is no other tenant's data present to protect."""
    assert pr._assert_run_scope(None, USER, "RUN-THEIRS") is None
    assert pr._assert_employee_scope(None, USER, "E-THEIRS") is None
    assert pr._assert_slip_scope(None, USER, "S-THEIRS") is None
    assert deny == []
