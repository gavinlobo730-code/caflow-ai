"""
A salary REVISION reaches the Statutory Deductions projection, not only the run.

WHAT WAS WRONG — a defect with no finding, from the 12 September probe pass.

    `payroll_salary_revisions` (migration 300) records what an employee's pay
    was and from when, and `_salary_in_force` resolves the set that governs a
    month. `create_run` has merged it since the table existed.
    `statutory_position` did not: it read `payroll_employees` and took
    `basic_paise`, `da_percent`, `hra_percent` and the four allowance columns
    straight off the master.

    So a revision recorded through the employee drawer moved the payslip, the
    PF wage base, the ECR and the ledger, and left the Statutory Deductions
    screen projecting the pay the employee was on BEFORE it. Two PF figures for
    one employee in one month, with nothing to say which the challan would
    carry — which is precisely the defect PAY-20 closed, reopened through a
    different input.

WHY THE FIX IS A SHARED MERGE AND NOT A SECOND ONE

    The merge is `_pay_in_force`, and both readers call it. Copying
    `create_run`'s six-line dict comprehension into `statutory_position` would
    have fixed today's divergence and left the next component a revision learns
    to carry to be added in two places — which is how these two came to
    disagree in the first place.

    `test_payroll_reports_what_it_deducted.py` is the parity test that pins the
    projection to the run on the WAGE BASE. This file pins the other input to
    the same computation: which employee's pay is being projected at all.
"""
from __future__ import annotations

import pytest

import routers.payroll as pr
from tests.test_payroll_reports_what_it_deducted import (   # noqa: F401
    CLIENT, FIRM, LOW_BASIC, USER, _DB, _allow_every_client,
)

MONTH = "2026-12"

#: A raise effective 1 December, recorded before the December run.
REVISION = {"employee_id": "e1", "firm_id": FIRM, "client_id": CLIENT,
            "effective_from": "2026-12-01", "basic_paise": 20_000_00,
            "hra_percent": 180, "da_percent": 0, "lta_paise": 0,
            "medical_paise": 0, "special_allowance_paise": 0,
            "other_allowances_paise": 0, "reason": "Annual increment",
            "source_structure_id": None}


def _position(revisions, monkeypatch, month=MONTH, emp=None):
    db = _DB({"payroll_employees": [emp or LOW_BASIC], "payroll_runs": [],
              "payroll_slips": [], "payroll_salary_revisions": revisions})
    monkeypatch.setattr(pr, "_db", lambda: db)
    resp = pr.statutory_position(client_id=CLIENT, month=month, current_user=USER)
    assert resp["success"] is True
    return resp["data"]["rows"][0]


# ── the defect ────────────────────────────────────────────────────────────────

def test_the_projection_uses_the_pay_in_force_that_month(monkeypatch):
    on_master = _position([], monkeypatch)
    revised = _position([REVISION], monkeypatch)
    assert revised["gross_paise"] > on_master["gross_paise"], (
        "the revision doubled basic and the projection did not move")
    assert revised["pf_employee_paise"] != on_master["pf_employee_paise"]


def test_the_projection_and_the_run_agree_on_the_revised_pay(monkeypatch):
    """The parity that matters: the figure the screen shows and the figure the
    run will deduct are the same figure, computed on the same employee."""
    revised = _position([REVISION], monkeypatch)
    merged = pr._pay_in_force(dict(LOW_BASIC), {"e1": REVISION})
    slip = pr._compute_slip(merged, fy="2026-27", pt_month=12)
    assert revised["pf_employee_paise"] == slip["pf_employee_paise"]
    assert revised["gross_paise"] == slip["gross_paise"]


def test_a_revision_effective_later_does_not_reach_this_month(monkeypatch):
    """`_salary_in_force` takes the latest revision effective ON OR BEFORE the
    month's first day, so one entered in advance must not be projected early."""
    future = {**REVISION, "effective_from": "2027-04-01"}
    assert _position([future], monkeypatch) == _position([], monkeypatch)


# ── the merge itself ──────────────────────────────────────────────────────────

def test_the_merge_replaces_only_what_a_revision_carries():
    """A revision records PAY. PF applicability, EPS eligibility, the PT state
    and the joining date are facts about the employment and stay on the
    master — substituting the revision for the row would drop them."""
    merged = pr._pay_in_force(dict(LOW_BASIC), {"e1": REVISION})
    assert merged["basic_paise"] == 20_000_00
    assert merged["pf_applicable"] is True
    assert merged["eps_eligible"] is True
    assert merged["joining_date"] == LOW_BASIC["joining_date"]
    assert merged["name"] == LOW_BASIC["name"]


def test_a_component_the_revision_omits_keeps_the_masters_value():
    partial = {"employee_id": "e1", "effective_from": "2026-12-01",
               "basic_paise": 20_000_00}
    merged = pr._pay_in_force(dict(LOW_BASIC), {"e1": partial})
    assert merged["basic_paise"] == 20_000_00
    assert merged["hra_percent"] == LOW_BASIC["hra_percent"]


def test_an_employee_with_no_revision_is_untouched():
    row = dict(LOW_BASIC)
    assert pr._pay_in_force(row, {}) == row


def test_the_revisable_set_is_pay_and_nothing_else():
    """Pinned, because the harm runs the other way too: adding a column here
    that a revision does not actually record would let one blank field on the
    revisions form wipe a fact off the master for that month."""
    assert pr._REVISABLE_COMPONENTS == (
        "basic_paise", "hra_percent", "da_percent", "lta_paise",
        "medical_paise", "special_allowance_paise", "other_allowances_paise",
    )


def test_both_readers_go_through_the_one_merge():
    """Stated as the rule rather than as a call count: neither reader may build
    the merge itself. A second inline comprehension over the same component
    list is exactly how these two came to disagree, and it would pass every
    behavioural test above on the day it was written."""
    import inspect
    for fn in (pr.create_run, pr.statutory_position):
        src = inspect.getsource(fn)
        assert "_pay_in_force(" in src, (
            f"{fn.__name__} must merge the month's revision through the shared "
            f"helper — the run and the projection have to describe one employee")
        assert "revisions.get(" not in src, (
            f"{fn.__name__} reaches into the revision map itself. Which "
            f"components a revision replaces is _pay_in_force's answer — a "
            f"reader that opens the map is one component away from being a "
            f"second copy of _REVISABLE_COMPONENTS")
