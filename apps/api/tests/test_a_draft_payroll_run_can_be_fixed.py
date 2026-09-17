"""A payroll run computed on the wrong inputs can be rebuilt or thrown away.

WHAT WAS WRONG (PAY-21)

A run is computed from the employee master, the attendance and the salary
revisions AS THEY STOOD when it was created. A CA who created June before
entering the attendance, or before recording a revision, or while somebody was
still missing from the roster, could not fix it:

  * creating the month again 409s on migration 237's unique index;
  * there was no delete;
  * reversing a FINALISED run reopens it at `review` with the SAME slips, so
    re-finalising posts the identical wrong figures.

The only escape was a direct edit against the database — and the product's own
attendance-gap sentence told the CA to "Regenerate the run to find out", naming
an action that did not exist.

WHAT IT DOES NOW

`POST /runs/{run_id}/recompute` deletes the slips and rebuilds them through
`_compute_and_store_slips`, which is the SAME function `create_run` calls: a
recomputed month cannot differ from a month created today on the same inputs.
`DELETE /runs/{run_id}` throws a draft away so the month becomes creatable
again.

WHY A DRAFT IS SAFE AND A RELEASED RUN IS NOT

A draft posts no journal, registers no §192 TDS and records no loan recovery —
all three happen at FINALISE. PAY-04 is the other half: the FY TDS aggregate and
the ESI period test read only RELEASED runs, so deleting and rebuilding a draft
cannot disturb what an earlier month withheld. A finalised run has done all
three, so both endpoints refuse it and name the reversal path instead.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import routers.payroll as payroll_mod
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "FIRM-PAY21"
CALLER = {"firm_id": FIRM, "id": "u-1", "auth_user_id": "auth-1",
          "email": "ca@f.test", "role": "Partner"}


@pytest.fixture()
def db(monkeypatch):
    d = FakeDB()
    wire_e2e(monkeypatch, d, [payroll_mod])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    d.seed("clients", {"id": "CLI", "firm_id": FIRM,
                       "financial_year_start": "2026-04-01"})
    d.seed("client_payroll_settings", {"id": "cps-1", "firm_id": FIRM,
                                       "client_id": "CLI", "payroll_enabled": True})
    for name in ("Salaries Expense", "Net Salary Payable", "PF Payable",
                 "ESI Payable", "PT Payable", "TDS Payable - Salary"):
        d.seed("chart_of_accounts", {"firm_id": FIRM, "client_id": "CLI",
                                     "account_name": name, "is_active": True})
    return d


def _employee(db, name="Asha", emp_id="e-1", **kw):
    row = {"id": emp_id, "firm_id": FIRM, "client_id": "CLI", "name": name,
           "basic_paise": 5_000_000, "hra_percent": 0.0, "da_percent": 0.0,
           "other_allowances_paise": 0, "lta_paise": 0, "medical_paise": 0,
           "special_allowance_paise": 0, "pf_applicable": False,
           "esi_applicable": False, "pt_applicable": False,
           "is_active": True, "status": "active"}
    row.update(kw)
    return db.seed("payroll_employees", row)


def _run(db, month="2026-06"):
    out = payroll_mod.create_run(
        payroll_mod.PayrollRunIn(client_id="CLI", month=month), CALLER)
    assert out["success"] is True
    return out["data"]["id"]


def _slips(db, run_id):
    return [s for s in db.rows("payroll_slips") if s.get("run_id") == run_id]


# ── recompute ────────────────────────────────────────────────────────────────

def test_an_employee_added_after_the_run_is_picked_up(db):
    """THE HEADLINE. The roster is read at creation, so a late joiner was simply
    not in the month, and there was no way to put them in it."""
    _employee(db)
    run_id = _run(db)
    assert len(_slips(db, run_id)) == 1

    _employee(db, name="Bhaskar", emp_id="e-2")
    out = payroll_mod.recompute_run(run_id, CALLER)

    assert out["success"] is True
    assert out["data"]["headcount"] == 2
    assert {s["employee_id"] for s in _slips(db, run_id)} == {"e-1", "e-2"}


def test_the_rebuild_replaces_the_slips_rather_than_adding_to_them(db):
    """A second set of slips for one run would double every total on the
    payslip screen, on the ECR and in the journal at finalise."""
    _employee(db)
    run_id = _run(db)
    payroll_mod.recompute_run(run_id, CALLER)
    assert len(_slips(db, run_id)) == 1


def test_the_run_keeps_its_id_and_its_month(db):
    """Recompute is not delete-and-create: anything already pointing at this
    run — a transition log row, an ECR filing record — still does."""
    _employee(db)
    run_id = _run(db)
    out = payroll_mod.recompute_run(run_id, CALLER)
    assert out["data"]["id"] == run_id
    assert out["data"]["month"] == "2026-06"


def test_the_totals_are_restamped_on_the_run(db):
    """The header carries the figures every list screen reads; leaving them at
    the first computation would show one month and pay another."""
    _employee(db)
    run_id = _run(db)
    _employee(db, name="Bhaskar", emp_id="e-2")
    payroll_mod.recompute_run(run_id, CALLER)

    row = [r for r in db.rows("payroll_runs") if r["id"] == run_id][0]
    assert row["headcount"] == 2
    assert row["total_gross_paise"] == sum(s["gross_paise"] for s in _slips(db, run_id))


def test_the_gaps_are_recomputed_and_returned(db):
    """A CA recomputes precisely BECAUSE something changed; answering with the
    first run's gaps would describe a month that no longer exists."""
    _employee(db)
    run_id = _run(db)
    out = payroll_mod.recompute_run(run_id, CALLER)
    assert any("no attendance entered" in g for g in out["data"]["attendance_gaps"])


# ── delete ───────────────────────────────────────────────────────────────────

def test_a_deleted_month_can_be_created_again(db):
    """What the delete is FOR. Migration 237's unique index makes the month
    permanently uncreatable otherwise."""
    _employee(db)
    run_id = _run(db)

    with pytest.raises(HTTPException) as dup:
        _run(db)
    assert dup.value.status_code == 409

    out = payroll_mod.delete_run(run_id, CALLER)
    assert out["success"] is True
    assert out["data"]["deleted"] is True
    assert _run(db) != run_id


def test_the_delete_records_what_it_removed(db):
    """An audit row carrying only an id leaves a trail nobody can read
    afterwards — the reasoning migration 275 applies to a journal deletion."""
    _employee(db)
    run_id = _run(db)
    out = payroll_mod.delete_run(run_id, CALLER)
    assert out["data"]["slip_count"] == 1
    assert out["data"]["month"] == "2026-06"


# ── what is refused ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("status", ["finalized", "paid"])
@pytest.mark.parametrize("action", ["recompute_run", "delete_run"])
def test_a_released_run_is_refused_and_told_what_to_do(db, status, action):
    """It has posted a journal and registered its §192 TDS. Rebuilding or
    deleting it would leave the ledger describing slips that no longer exist,
    so the refusal names the reversal path — which exists, posts the contra
    entry and puts any loan recovery back."""
    _employee(db)
    run_id = _run(db)
    for row in db.rows("payroll_runs"):
        if row["id"] == run_id:
            row["status"] = status

    with pytest.raises(HTTPException) as e:
        getattr(payroll_mod, action)(run_id, CALLER)
    assert e.value.status_code == 409
    assert status in e.value.detail
    assert "reverse" in e.value.detail.lower()


@pytest.mark.parametrize("action", ["recompute_run", "delete_run"])
def test_a_run_in_another_firm_is_not_found(db, action):
    """404 and not 403, and the same 404 as "no such run" — otherwise the
    status code becomes an oracle for which run ids are real."""
    _employee(db)
    run_id = _run(db)
    other = {**CALLER, "firm_id": "FIRM-OTHER"}
    with pytest.raises(HTTPException) as e:
        getattr(payroll_mod, action)(run_id, other)
    assert e.value.status_code == 404


def test_review_is_still_fixable(db):
    """`review` posts nothing and pays nobody — it is a draft somebody has
    looked at. Refusing there would put the dead end back one step later."""
    _employee(db)
    run_id = _run(db)
    for row in db.rows("payroll_runs"):
        if row["id"] == run_id:
            row["status"] = "review"
    assert payroll_mod.recompute_run(run_id, CALLER)["success"] is True


# ── the rule the refactor rests on ───────────────────────────────────────────

def test_one_computation_serves_both_doors():
    """Copying two hundred lines would be two payrolls that agree until the day
    one of them is changed."""
    import ast
    import inspect

    src = inspect.getsource(payroll_mod)
    tree = ast.parse(src)
    fns = {n.name: n for n in ast.walk(tree)
           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for door in ("create_run", "recompute_run"):
        called = {c.func.id for c in ast.walk(fns[door])
                  if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
        assert "_compute_and_store_slips" in called, (
            f"{door} does not go through the shared computation")


def test_nothing_tells_a_ca_to_regenerate_a_run_that_cannot_be_regenerated():
    """The attendance-gap sentence said "Regenerate the run to find out" while
    no such action existed. It may say it now — and if the endpoint is ever
    removed, this fails rather than the sentence quietly becoming a lie."""
    import inspect

    src = inspect.getsource(payroll_mod)
    if "egenerate" in src or "ecompute the run" in src:
        assert "/runs/{run_id}/recompute" in src, (
            "the product tells a CA to regenerate a run and offers no way to")
