"""The roster's monthly figure is the server's, to the paisa, and it is not called CTC (POST-A-134, first slice).

WHAT WAS WRONG
    The People screen added each employee's basic, HRA, DA and four fixed amounts in the browser
    (`employeeGrossPaise`: `Math.round(basic * hra_percent / 100)` and the same for DA), and headed the column "Monthly
    CTC". Two faults, one cause (a copy of a calculation the server owns):

      * the browser rounds a floating product and the slip rounds an exact decimal half-up (`_percent_of`, whose own docstring
        records that `float(hra_percent)` "produced verified off-by-one-paise mismatches"). They agree on almost every
        pair and not on all: with a basic of Rs 4,46,138.75 and DA at 9.2% the slip says 4104477 paise and the browser's
        formula, run in Node, says 4104476. A roster that disagrees with the payslip by a paisa is a roster nobody can
        tie out;
      * CTC is not what was added. Cost to company carries the employer's PF, ESI, EDLI and admin charge, which the CTC
        report reads off the slips; a roster column of the same name that stopped at gross told a client it was paying
        less than it was.

WHAT IS HELD
    * `_full_month_gross_paise` equals the gross `_compute_slip` produces at full attendance, over a table that includes
      the browser's disagreements and every optional component;
    * `GET /api/payroll/employees` carries it on every row, and an unreadable component gives that row None while the rest
      of the roster still lists;
    * the web side (`apps/web/scripts/the-people-screen-reads-the-servers-monthly-gross.test.ts`) no longer computes it.
"""
from __future__ import annotations

import pytest

import routers.payroll as pr
from tests.e2e_harness import FakeDB

FULL = {"working_days": 26, "days_present": 26, "lop_days": 0}

#: (basic_paise, hra_percent, da_percent) where the browser's `Math.round(basic * pct / 100)`, run in Node, is ONE PAISA
#: BELOW the slip's exact half-up: 44613875 x 9.2 -> 4104476 in the browser, 4104477 on the slip, and so on.
BROWSER_DISAGREES = [(44613875, 0, 9.2), (203959500, 5.1, 0), (721841750, 4.6, 0), (42588500, 0, 81.1), (907831000, 8.95, 33.23)]
ORDINARY = [(5000000, 40, 10), (3333333, 12.5, 0), (1, 50, 50), (99999, 7.5, 7.5), (4500000, 0, 0), (0, 40, 10),
            (7654321, 33.33, 0.1), (123456789, 18.75, 4.5)]


def _emp(basic, hra, da, **kw):
    base = {"id": "e1", "name": "Asha", "client_id": "c1", "firm_id": "f1", "status": "active",
            "basic_paise": basic, "hra_percent": hra, "da_percent": da,
            "pf_applicable": False, "esi_applicable": False, "pt_applicable": False}
    base.update(kw)
    return base


# ── the number is the slip's ────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("basic,hra,da", BROWSER_DISAGREES + ORDINARY)
def test_the_full_month_gross_is_the_slips_gross_at_full_attendance(basic, hra, da):
    emp = _emp(basic, hra, da)
    assert pr._full_month_gross_paise(emp) == pr._compute_slip(emp, FULL)["gross_paise"]


def test_every_optional_component_is_in_it_and_in_the_slip():
    emp = _emp(5000000, 40, 10, lta_paise=250000, medical_paise=125000, special_allowance_paise=300000,
               other_allowances_paise=75000)
    assert pr._full_month_gross_paise(emp) == 5000000 + 2000000 + 500000 + 250000 + 125000 + 300000 + 75000
    assert pr._full_month_gross_paise(emp) == pr._compute_slip(emp, FULL)["gross_paise"]


def test_an_absent_or_null_component_is_zero_as_it_is_on_the_slip():
    emp = _emp(5000000, None, None, lta_paise=None, other_allowances_paise=None)
    assert pr._full_month_gross_paise(emp) == 5000000 == pr._compute_slip(emp, FULL)["gross_paise"]


#: The browser's formula, run in Node, for the percentage part alone: `Math.round((basic * pct) / 100)`.
@pytest.mark.parametrize("basic,hra,da,browser_percent_part", [
    (44613875, 0, 9.2, 4104476), (203959500, 5.1, 0, 10401934), (721841750, 4.6, 0, 33204720), (42588500, 0, 81.1, 34539273)])
def test_the_browsers_disagreements_are_real_and_the_server_takes_the_half_up_side(basic, hra, da, browser_percent_part):
    percent_part = pr._full_month_gross_paise(_emp(basic, hra, da)) - basic
    assert percent_part == browser_percent_part + 1


# ── the route serves it ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def served(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(pr, "_db", lambda: db)
    monkeypatch.setattr(pr, "filter_by_client", lambda _user, rows: rows)
    user = {"id": "u1", "firm_id": "f1", "role": "partner"}
    return db, user


def _list(user, **kw):
    return pr.list_employees(client_id=None, include_inactive=False, current_user=user, **kw)["data"]


def test_each_row_carries_the_figure_and_nothing_else_changes(served):
    db, user = served
    row = db.seed("payroll_employees", _emp(44613875, 0, 9.2, lta_paise=100))
    [out] = _list(user)
    assert out["full_month_gross_paise"] == 44613875 + 4104477 + 100
    assert {k: v for k, v in out.items() if k != "full_month_gross_paise"} == row


def test_an_unreadable_component_gives_that_row_none_and_the_roster_still_lists(served):
    db, user = served
    db.seed("payroll_employees", _emp(5000000, "not a number", 0, id="bad", name="Bad"))
    db.seed("payroll_employees", _emp(5000000, 40, 0, id="good", name="Good"))
    out = {r["id"]: r["full_month_gross_paise"] for r in _list(user)}
    assert out == {"bad": None, "good": 7000000}


def test_the_stored_row_is_not_mutated(served):
    db, user = served
    db.seed("payroll_employees", _emp(5000000, 40, 0))
    _list(user)
    assert "full_month_gross_paise" not in db.rows("payroll_employees")[0]
