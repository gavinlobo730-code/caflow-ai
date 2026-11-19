"""Gratuity is named under the Code, says what it carries over, and the five years are waived on the expiry of a fixed term (POST-A-526).

WHAT WAS WRONG
    1. The product computed and labelled gratuity under the Payment of Gratuity Act, 1972, which the Code on Social Security, 2020
       repealed from 21-11-2025 (section 164(1)). Section 53 of the Code and rules 31 to 34 of the Social Security (Central) Rules,
       2026 (G.S.R. 344(E)) govern now. The formula is the same (fifteen days' wages, divisor twenty-six, a part over six months counted
       as a year, five years' service); two figures are not settled by the text read: the ceiling, which section 53(3) leaves to
       "such amount as may be notified", and the base, since the Code defines wages once in section 2(88) (owner list S50).
    2. Where a fixed term EXPIRES the five years are not needed (the second proviso to section 53(1)) and, by rule 33(1)(a), one year
       under the contract is enough, pro rata (the third proviso to section 53(2)). The module refused everybody under five years
       except on death or disablement, and the product held no fixed-term setting.

WHAT THE FIX DOES
    (a) The settlement line, the module and the screens name section 53; the settlement says in words that the ceiling and the base are
        carried over from the repealed Act until S50 is answered. NO FIGURE MOVES.
    (b) `payroll_employees.fixed_term_employment` and `fixed_term_end_date` (migration 770, additive, NULL for everyone who exists);
        `gratuity.compute(fixed_term=True, fixed_term_expired=True)` needs one year, not five, and counts a part of a year over six
        months as a year by the rounding it already used. An employee with no record computes exactly as before, and so does a
        fixed-term employee whose term has NOT expired: whether a fixed-term employee who resigns or is dismissed early is eligible on
        one year is not settled by the text read, so it is not built (owner list S50) and the reason says so.

NEGATIVE CONTROLS (each mutant was run and these fail)
    * ignore `fixed_term` in `compute`                      — the limb tests fail
    * waive the five years for a fixed-term employee whose term has not expired — the open-reading tests fail
    * keep the five-year refusal after the term expires    — the one-year tests fail
    * drop the carried-over note from the settlement        — the settlement test fails
    * stop popping the new keys on create                   — the create test fails
"""
from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from domain.payroll import gratuity as G
from domain.payroll import settlement as S
from models.payroll import EmployeeIn, EmployeeUpdateIn

WAGE = 52_000 * 100          # basic + DA: 52,000 a month, so one year is 52,000 x 15 / 26 = 30,000 exactly
JOIN = date(2024, 1, 1)


def _c(leaving: date, **kw):
    kw.setdefault("basic_plus_da_paise", WAGE)
    kw.setdefault("joining", JOIN)
    return G.compute(leaving=leaving, **kw)


# ═══ (a) THE LABELS, AND WHAT IS CARRIED OVER ═══════════════════════════════════════════════════════════════════════════════════

def test_the_module_names_the_code_and_not_the_repealed_act_as_the_authority():
    src = G.__doc__
    assert src.splitlines()[1].startswith("Gratuity — section 53 of the Code on Social Security, 2020")
    assert "repealed the Payment of Gratuity Act, 1972 from 21-11-2025" in src
    assert "section 164(1)" in src


def test_no_reason_the_module_serves_cites_the_repealed_acts_section():
    reasons = _c(date(2025, 6, 1)).reasons + _c(date(2025, 6, 1), fixed_term=True).reasons
    reasons += G.compute(basic_plus_da_paise=0, joining=JOIN, leaving=date(2031, 1, 1)).reasons
    text = " ".join(reasons)
    assert "§4(1)" not in text and "§2(s)" not in text
    assert "53(1) of the Code on Social Security, 2020" in text


def test_the_figures_did_not_move():
    """Rs 52,000 for five years is 52,000 x 15 x 5 / 26 = 1,50,000 whichever Act the label names."""
    r = _c(date(2029, 1, 1))
    assert r.eligible and r.payable_paise == 150_000 * 100
    assert G.GRATUITY_CEILING_PAISE == 20_00_000 * 100


def test_the_settlement_says_the_ceiling_and_the_base_are_carried_over():
    s = S.build(salary_to_last_day_paise=0, gratuity=_c(date(2029, 1, 1)))
    note = [g for g in s.gaps if g == G.CARRIED_OVER_FROM_THE_REPEALED_ACT]
    assert len(note) == 1
    for needle in ("section 53 of the Code on Social Security, 2020", "Rs 20,00,000", "section 53(3)", "section 2(88)",
                   "confirm both"):
        assert needle in note[0], needle
    line = next(c for c in s.components if c.label == "Gratuity")
    assert line.statute == "Code on Social Security, 2020 section 53; IT Act §10(10)"


def test_a_settlement_without_gratuity_carries_no_such_note():
    s = S.build(salary_to_last_day_paise=10_000_00)
    assert G.CARRIED_OVER_FROM_THE_REPEALED_ACT not in s.gaps


# ═══ (b) FIXED-TERM EMPLOYMENT ══════════════════════════════════════════════════════════════════════════════════════════════════

def _fx(leaving: date, **kw):
    """A fixed-term employee whose term has EXPIRED, the case the Code waives the five years for."""
    kw.setdefault("fixed_term", True)
    kw.setdefault("fixed_term_expired", True)
    return _c(leaving, **kw)


def test_an_ordinary_employee_with_two_years_is_still_refused():
    """The negative control against replacing the five-year rule for everybody."""
    r = _c(date(2026, 1, 1))
    assert not r.eligible and r.payable_paise == 0
    assert "requires five" in r.reasons[0]


def test_a_fixed_term_employee_with_less_than_a_year_is_refused_in_the_rules_own_words():
    r = _fx(date(2024, 12, 1))
    assert not r.eligible
    assert "at least one year" in r.reasons[0] and "rule 33(1)(a)" in r.reasons[0]
    assert "second proviso to section 53(1)" in r.reasons[0] and "has expired" in r.reasons[0]


def test_exactly_one_year_under_the_contract_qualifies_and_is_one_year_of_gratuity():
    r = _fx(date(2025, 1, 1))
    assert r.eligible and r.fixed_term and r.fixed_term_expired
    assert (r.completed_years, r.service_years_counted) == (1, 1)
    assert r.payable_paise == 30_000 * 100


def test_a_part_of_a_year_over_six_months_counts_as_a_year_for_a_fixed_term_employee_too():
    """Rule 33(1)(a): the subsequent period in excess of six months but less than one year is rounded off to one additional year."""
    assert _fx(date(2025, 7, 2)).service_years_counted == 2       # six months and a day
    assert _fx(date(2025, 7, 1)).service_years_counted == 1       # exactly six months is not in excess of it


def test_it_is_pro_rata_to_the_service_rendered():
    one, two, three = (_fx(date(2025 + i, 1, 1)).payable_paise for i in range(3))
    assert (one, two, three) == (30_000 * 100, 60_000 * 100, 90_000 * 100)


def test_the_basis_is_said_when_the_gratuity_is_payable_only_because_the_term_expired():
    r = _fx(date(2026, 1, 1))
    assert G.FIXED_TERM_BASIS in r.gaps
    assert "one year of service under the contract, not five" in G.FIXED_TERM_BASIS
    assert "expired" in G.FIXED_TERM_BASIS


def test_it_is_not_said_when_the_employee_would_have_qualified_anyway():
    assert G.FIXED_TERM_BASIS not in _fx(date(2029, 1, 1)).gaps


def test_death_or_disablement_is_unchanged_for_a_fixed_term_employee():
    r = _fx(date(2024, 6, 1), on_death_or_disablement=True)
    assert r.eligible
    assert G.FIXED_TERM_BASIS not in r.gaps


def test_the_ceiling_still_applies_to_a_fixed_term_employee():
    r = G.compute(basic_plus_da_paise=10_00_000 * 100, joining=JOIN, leaving=date(2031, 1, 1),
                  fixed_term=True, fixed_term_expired=True)
    assert r.payable_paise == G.GRATUITY_CEILING_PAISE


def test_an_unset_fixed_term_computes_exactly_as_before():
    for leaving in (date(2025, 1, 1), date(2027, 6, 1), date(2029, 1, 1), date(2031, 9, 9)):
        assert _c(leaving) == _c(leaving, fixed_term=False)
        # the expiry means nothing for an employee who is not recorded as on a fixed term
        assert _c(leaving) == _c(leaving, fixed_term_expired=True)


def test_a_fixed_term_employee_whose_term_has_not_expired_is_refused_as_before_and_the_reason_names_the_open_reading():
    """The Code waives the five years on the EXPIRY of the term; a resignation is clause (b), which needs five, and rule 33(1)(a) names
    one year without naming expiry. The text read does not say how the two fit, so this is not built and it says so (owner list S50)."""
    r = _c(date(2026, 1, 1), fixed_term=True)                         # two years' service, the term not said to have expired
    assert not r.eligible and r.payable_paise == 0 and r.fixed_term and not r.fixed_term_expired
    text = r.reasons[0]
    for needle in ("recorded as on fixed-term employment", "only where the employment ends by the expiry of the fixed term",
                   "second proviso", "rule 33(1)(a)", "owner list S50", "say so when the settlement is recorded"):
        assert needle in text, needle


def test_a_fixed_term_employee_who_stays_five_years_is_eligible_the_ordinary_way():
    r = _c(date(2029, 1, 1), fixed_term=True)
    assert r.eligible and G.FIXED_TERM_BASIS not in r.gaps and r.payable_paise == 150_000 * 100


def test_a_recorded_end_date_has_expired_only_once_it_is_reached():
    end = date(2026, 12, 31)
    assert not G.fixed_term_has_expired(None, date(2030, 1, 1))              # no recorded end date is "not known to have expired"
    assert not G.fixed_term_has_expired(end, date(2026, 12, 30))
    assert G.fixed_term_has_expired(end, date(2026, 12, 31))
    assert G.fixed_term_has_expired(end, date(2027, 1, 5))
    assert not G.fixed_term_has_expired(end, None)


# ═══ THE EMPLOYEE RECORD ════════════════════════════════════════════════════════════════════════════════════════════════════════

def test_a_contract_end_date_belongs_to_a_fixed_term_employee():
    with pytest.raises(ValidationError) as exc:
        EmployeeIn(client_id="CLI", name="Asha", basic_paise=10_000_00, fixed_term_end_date="2026-12-31")
    assert "A contract end date belongs to a fixed-term employee" in str(exc.value)
    with pytest.raises(ValidationError):
        EmployeeIn(client_id="CLI", name="Asha", basic_paise=10_000_00, fixed_term_employment=False,
                   fixed_term_end_date="2026-12-31")


def test_a_fixed_term_employee_may_carry_an_end_date_or_none():
    a = EmployeeIn(client_id="CLI", name="Asha", basic_paise=10_000_00, fixed_term_employment=True,
                   fixed_term_end_date="2026-12-31")
    b = EmployeeIn(client_id="CLI", name="Asha", basic_paise=10_000_00, fixed_term_employment=True)
    assert a.fixed_term_end_date == "2026-12-31" and b.fixed_term_end_date is None


def test_a_date_that_is_not_a_date_is_a_sentence():
    with pytest.raises(ValidationError):
        EmployeeIn(client_id="CLI", name="Asha", basic_paise=10_000_00, fixed_term_employment=True,
                   fixed_term_end_date="31/12/2026")


def test_the_update_model_carries_both_fields():
    u = EmployeeUpdateIn(fixed_term_employment=True, fixed_term_end_date="2026-12-31")
    assert u.fixed_term_employment is True and u.fixed_term_end_date == "2026-12-31"


# ═══ THE ROUTES: create, update and the settlement ══════════════════════════════════════════════════════════════════════════════

import routers.payroll as pr                                      # noqa: E402
from fastapi import HTTPException                                 # noqa: E402
from tests.e2e_harness import FakeDB, wire_e2e                    # noqa: E402

FIRM = "FIRM-526"
CALLER = {"firm_id": FIRM, "id": "u-1", "auth_user_id": "auth-1", "email": "ca@f.test", "role": "Partner"}


@pytest.fixture()
def db(monkeypatch):
    d = FakeDB()
    wire_e2e(monkeypatch, d, [pr])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    d.seed("clients", {"id": "CLI", "firm_id": FIRM, "financial_year_start": "2026-04-01"})
    d.seed("client_payroll_settings", {"id": "cps-1", "firm_id": FIRM, "client_id": "CLI", "payroll_enabled": True})
    return d


def _create(**kw):
    out = pr.create_employee(EmployeeIn(client_id="CLI", name="Asha Kumar", basic_paise=52_000_00, **kw), CALLER)
    assert out["success"] is True
    return out["data"]["id"]


def test_an_employee_created_without_a_fixed_term_never_names_the_new_columns(db):
    """A deploy that reaches production a few minutes before migration 770 must not break an ordinary create."""
    _create()
    row = db.rows("payroll_employees")[0]
    assert "fixed_term_employment" not in row and "fixed_term_end_date" not in row


def test_a_fixed_term_employee_is_stored_with_both(db):
    _create(fixed_term_employment=True, fixed_term_end_date="2026-12-31")
    row = db.rows("payroll_employees")[0]
    assert row["fixed_term_employment"] is True and row["fixed_term_end_date"] == "2026-12-31"


def test_withdrawing_a_fixed_term_clears_the_end_date_with_it(db):
    emp_id = _create(fixed_term_employment=True, fixed_term_end_date="2026-12-31")
    pr.update_employee(emp_id, EmployeeUpdateIn(fixed_term_employment=False), CALLER)
    row = db.rows("payroll_employees")[0]
    assert row["fixed_term_employment"] is False and row["fixed_term_end_date"] is None


def test_an_end_date_sent_alone_lands_only_on_an_employee_who_is_on_a_fixed_term(db):
    ordinary = _create()
    with pytest.raises(HTTPException) as exc:
        pr.update_employee(ordinary, EmployeeUpdateIn(fixed_term_end_date="2026-12-31"), CALLER)
    assert exc.value.status_code == 422 and "A contract end date belongs to a fixed-term employee" in exc.value.detail
    fixed = _create(fixed_term_employment=True)
    pr.update_employee(fixed, EmployeeUpdateIn(fixed_term_end_date="2027-03-31"), CALLER)
    assert [r for r in db.rows("payroll_employees") if r["id"] == fixed][0]["fixed_term_end_date"] == "2027-03-31"


def _settle(emp: dict, leaving: str, **body_kw):
    body = pr.SettlementIn(client_id="CLI", leaving_date=leaving, **body_kw)
    settlement, grat, _leaving = pr._compose_settlement(emp, body)
    return settlement, grat


EMP = {"basic_paise": 52_000_00, "da_percent": 0, "joining_date": "2024-01-01", "gratuity_act_covered": True}


def test_the_settlement_route_passes_the_record_and_the_stated_expiry_to_the_computation():
    _s, ordinary = _settle(EMP, "2025-02-01")
    _s, recorded = _settle({**EMP, "fixed_term_employment": True}, "2025-02-01")
    _s, expired = _settle({**EMP, "fixed_term_employment": True}, "2025-02-01", fixed_term_contract_expired=True)
    assert not ordinary.eligible
    assert not recorded.eligible and "expiry of the fixed term" in recorded.reasons[0]     # recorded is not expired
    assert expired.eligible and expired.payable_paise == 30_000 * 100


def test_a_stated_expiry_means_nothing_for_an_employee_not_recorded_as_on_a_fixed_term():
    for value in (None, False):
        _s, grat = _settle({**EMP, "fixed_term_employment": value}, "2025-02-01", fixed_term_contract_expired=True)
        assert not grat.eligible and "requires five" in grat.reasons[0]


def test_a_recorded_end_date_that_has_been_reached_is_the_expiry_without_anybody_saying_so():
    emp = {**EMP, "fixed_term_employment": True, "fixed_term_end_date": "2025-02-01"}
    _s, on_the_day = _settle(emp, "2025-02-01")
    _s, after = _settle(emp, "2025-03-15")
    _s, before = _settle(emp, "2025-01-15")                 # one year and two weeks of service, but the term had not ended
    assert on_the_day.eligible and after.eligible
    assert not before.eligible


def test_an_unreadable_end_date_is_not_an_expiry():
    emp = {"fixed_term_employment": True, "fixed_term_end_date": "garbage"}
    assert pr._fixed_term_for_gratuity(emp, date(2030, 1, 1)) == {"fixed_term": True, "fixed_term_expired": False}


def test_a_withdrawn_or_never_recorded_fixed_term_is_the_ordinary_rule():
    for value in (None, False):
        _s, grat = _settle({**EMP, "fixed_term_employment": value, "fixed_term_end_date": "2025-01-01"}, "2025-02-01")
        assert not grat.eligible


def test_the_settlement_carries_both_notes_for_a_fixed_term_leaver_whose_term_expired():
    emp = {**EMP, "joining_date": "2023-01-01", "fixed_term_employment": True}
    settlement, grat = _settle(emp, "2026-02-01", fixed_term_contract_expired=True)
    assert grat.eligible
    assert G.CARRIED_OVER_FROM_THE_REPEALED_ACT in settlement.gaps and G.FIXED_TERM_BASIS in settlement.gaps


def _position_row(monkeypatch, **employee):
    """One row of the Statutory Deductions position for September 2026 (as at 30-09-2026), read through the real handler."""
    from tests.test_payroll_reports_what_it_deducted import _DB, USER, FIRM as POS_FIRM, CLIENT as POS_CLIENT
    base = dict(id="e1", client_id=POS_CLIENT, firm_id=POS_FIRM, name="Priya Rao", status="active", basic_paise=1_00_000_00,
                hra_percent=0, da_percent=0, lta_paise=0, medical_paise=0, special_allowance_paise=0, other_allowances_paise=0,
                pf_applicable=False, eps_eligible=True, esi_applicable=False, pt_applicable=False,
                joining_date="2025-06-01", gratuity_act_covered=True)
    db = _DB({"payroll_employees": [{**base, **employee}], "payroll_runs": [], "payroll_slips": []})
    monkeypatch.setattr(pr, "_db", lambda: db)
    resp = pr.statutory_position(client_id=POS_CLIENT, month="2026-09", current_user=USER)
    assert resp["success"] is True
    return resp["data"]["rows"][0]


def test_the_statutory_deductions_position_honours_the_record_and_the_recorded_end_date_too(monkeypatch):
    """The screen that shows what a CA owes a leaver asks the same module, so it must be told the same facts. An employee who joined on
    01-06-2025 has one year and three months at the end of September 2026: eligible for a fixed-term employee whose recorded term has
    ended by then and for nobody else."""
    ordinary = _position_row(monkeypatch)
    assert ordinary["gratuity_eligible"] is False and ordinary["gratuity_payable_paise"] == 0
    recorded_only = _position_row(monkeypatch, fixed_term_employment=True)
    assert recorded_only["gratuity_eligible"] is False                       # no recorded end date: not known to have expired
    ended = _position_row(monkeypatch, fixed_term_employment=True, fixed_term_end_date="2026-08-31")
    assert ended["gratuity_eligible"] is True
    assert ended["gratuity_payable_paise"] == 1_00_000_00 * 15 // 26          # one year: fifteen days of the 26-day month
    running = _position_row(monkeypatch, fixed_term_employment=True, fixed_term_end_date="2026-12-31")
    assert running["gratuity_eligible"] is False                             # the term runs past the position date
    withdrawn = _position_row(monkeypatch, fixed_term_employment=False, fixed_term_end_date="2026-08-31")
    assert withdrawn["gratuity_eligible"] is False


def test_both_places_the_gratuity_is_computed_pass_the_record():
    """The settlement and the Statutory Deductions position: a third caller of `gratuity.compute` that forgot it would answer the
    five-year rule for a fixed-term employee."""
    import inspect
    src = inspect.getsource(pr)
    assert src.count("gratuity_domain.compute(") == 2
    assert src.count("**_fixed_term_for_gratuity(emp,") == 2
