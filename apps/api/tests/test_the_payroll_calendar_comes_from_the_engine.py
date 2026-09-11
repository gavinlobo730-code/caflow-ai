"""A payroll deadline comes from compliance_engine, not from the browser (PAY-19).

WHAT WAS WRONG

CLAUDE.md names `services/compliance_engine.py` "the single source for every
due date", and the two payroll calendars in apps/web called it or anything else
exactly never. They built their own lists in TypeScript, and what they built
disagreed with the engine, with each other, and with the statute:

  * BOTH INVENTED A MONTHLY PROFESSIONAL TAX ROW — dated the last day of the
    month, described as "Maharashtra: ₹200 if salary > ₹10,000", for EVERY
    CLIENT whatever state its employees are in. The engine deliberately has no
    PT date: it is fixed by each state, there is no single rule, and this
    codebase models the slabs for four states of twenty-two. Its own docstring
    says why — "inventing one would put a wrong date in a CA's calendar, which
    is worse than the date being missing".

  * BOTH OMITTED THE TWO THAT ATTRACT INTEREST. The ESI deposit is the 15th
    (reg. 31, ESI (General) Regulations 1950) and the salary TDS deposit is the
    7th (Rule 30(2)) — 30 April for March, the exception most often missed.
    §201(1A)(ii) runs 1.5% a month from the date of DEDUCTION, so three weeks
    late on March costs two months of interest, not one.

  * ONE SHOWED THE WRONG QUARTER IN JANUARY. Its branch gave Q4 for January,
    whose return is due 31 May — while the Q3 return is due on 31 JANUARY
    itself. A CA opening the calendar that week saw a deadline five months out
    and not the one falling in eleven days.

The engine had all of this right the whole time. What was missing was a way for
a screen to ask.
"""
from __future__ import annotations

from datetime import date

import pytest

from services import compliance_engine as ce


def _call(year: int, month: int):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from core.auth import get_current_user
    import routers.compliance as mod

    app = FastAPI()
    # The router already carries prefix="/api/compliance" itself.
    app.include_router(mod.router)
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "u1", "firm_id": "F1", "role": "Partner",
        "email": "p@f1.test", "auth_user_id": "auth-partner"}
    return TestClient(app, raise_server_exceptions=False).get(
        f"/api/compliance/payroll-deposit-due-dates?year={year}&month={month}")


# ── the three deposits ───────────────────────────────────────────────────────

def test_all_three_deposits_are_served():
    """EPF, ESI and salary TDS. The calendars carried only the first."""
    data = _call(2026, 6).json()["data"]
    assert [d["label"] for d in data["deposits"]] == [
        "TDS on salary", "EPF contribution", "ESI contribution"], data["deposits"]


def test_the_deposits_are_the_engine_s_own_figures():
    """Served, not restated. A second computation here would be the defect in
    the other direction — two implementations, free to drift."""
    for year, month in ((2026, 6), (2026, 3), (2027, 1), (2026, 12)):
        served = _call(year, month).json()["data"]["deposits"]
        engine = ce.payroll_deposit_due_dates(year, month)
        assert [d["due_date"] for d in served] == \
            [d["due_date"].isoformat() for d in engine], (year, month)


def test_the_esi_deposit_is_the_fifteenth():
    """Regulation 31 — fifteen days, not the pre-2017 twenty-one."""
    data = _call(2026, 6).json()["data"]
    esi = next(d for d in data["deposits"] if d["label"] == "ESI contribution")
    assert esi["due_date"] == "2026-07-15"
    assert "reg. 31" in esi["statute"]


def test_the_salary_tds_deposit_is_the_seventh_except_for_march():
    """Rule 30(2). March is 30 April, not 7 April — the exception §201(1A)(ii)
    makes expensive."""
    june = _call(2026, 6).json()["data"]["deposits"]
    assert next(d for d in june if d["label"] == "TDS on salary")["due_date"] \
        == "2026-07-07"
    march = _call(2026, 3).json()["data"]["deposits"]
    assert next(d for d in march if d["label"] == "TDS on salary")["due_date"] \
        == "2026-04-30"


# ── professional tax: absent, and said so ────────────────────────────────────

def test_professional_tax_is_not_given_a_date():
    """The invented row. Its date is per state and this app models four of
    twenty-two, so any single date shown is wrong for most clients."""
    data = _call(2026, 6).json()["data"]
    labels = " ".join(d["label"] for d in data["deposits"]).lower()
    assert "professional" not in labels and "pt " not in labels


def test_professional_tax_is_reported_as_a_named_gap():
    """Absent is not the same as nil. A calendar with no PT row cannot be told
    from one whose client has no PT liability, and only the CA can settle it."""
    data = _call(2026, 6).json()["data"]
    assert data["gaps"], "professional tax was dropped silently"
    assert "rofessional tax" in data["gaps"][0]
    assert "state" in data["gaps"][0].lower()


# ── the quarter the browser got wrong ────────────────────────────────────────

def test_january_is_q4_and_the_q3_return_is_still_listed():
    """THE DEFECT. January IS Q4, whose return is due 31 May — and the Q3
    return is due 31 January, that same month. Returning all four quarters is
    what stops a caller having to choose, which is the choice the browser was
    getting wrong."""
    data = _call(2027, 1).json()["data"]
    assert data["period"]["quarter"] == "Q4"
    due = {r["quarter"]: r["due_date"] for r in data["returns"]}
    assert due["Q3"] == "2027-01-31"
    assert due["Q4"] == "2027-05-31"


def test_all_four_quarters_come_back_for_any_month():
    for month in range(1, 13):
        year = 2027 if month <= 3 else 2026
        returns = _call(year, month).json()["data"]["returns"]
        assert [r["quarter"] for r in returns] == ["Q1", "Q2", "Q3", "Q4"], month


def test_q4_is_the_last_day_of_may_not_the_month_after_quarter_end():
    """Rule 31A(2)'s exception. 30 April would be the pattern; 31 May is the
    rule."""
    due = {r["quarter"]: r["due_date"]
           for r in _call(2026, 6).json()["data"]["returns"]}
    assert due["Q4"] == "2027-05-31"
    assert due["Q1"] == "2026-07-31"


def test_a_wage_month_in_january_reads_its_own_financial_year():
    """January 2027 is in FY 2026-27, so its Q3 return (Oct–Dec 2026) is the one
    due that month. Reading the calendar year instead would offer FY 2027-28's
    quarters, none of which has fallen due."""
    data = _call(2027, 1).json()["data"]
    assert data["period"]["financial_year_end"] == 2027


# ── the engine's own helpers ─────────────────────────────────────────────────

def test_the_quarter_helper_maps_the_financial_year_not_the_calendar_one():
    assert [ce.tds_quarter_of_month(m) for m in range(1, 13)] == [
        "Q4", "Q4", "Q4", "Q1", "Q1", "Q1",
        "Q2", "Q2", "Q2", "Q3", "Q3", "Q3"]


def test_a_month_outside_one_to_twelve_is_refused():
    """A calendar that answers for month 13 answers for a month that does not
    exist, and the dates it returns look reasonable."""
    assert _call(2026, 0).status_code == 422
    assert _call(2026, 13).status_code == 422


# ── the whole-year mode the firm report needs ────────────────────────────────

def _call_fy(fy: str):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from core.auth import get_current_user
    import routers.compliance as mod

    app = FastAPI()
    app.include_router(mod.router)
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "u1", "firm_id": "F1", "role": "Partner",
        "email": "p@f1.test", "auth_user_id": "auth-partner"}
    return TestClient(app, raise_server_exceptions=False).get(
        f"/api/compliance/payroll-deposit-due-dates/fy?financial_year={fy}")


def test_a_financial_year_is_twelve_wage_months_starting_in_april():
    data = _call_fy("2026-27").json()["data"]
    assert [(m["year"], m["month"]) for m in data["months"]] == \
        [(2026, m) for m in range(4, 13)] + [(2027, m) for m in range(1, 4)]


def test_every_month_of_the_year_carries_all_three_deposits():
    for m in _call_fy("2026-27").json()["data"]["months"]:
        assert {d["label"] for d in m["deposits"]} == {
            "EPF contribution", "ESI contribution", "TDS on salary"}, m


def test_the_whole_year_agrees_with_the_per_month_endpoint():
    """Two routes, one engine. If they could disagree, this would be the second
    implementation the per-month one exists to prevent."""
    year = _call_fy("2026-27").json()["data"]["months"]
    for m in year:
        one = _call(m["year"], m["month"]).json()["data"]["deposits"]
        assert m["deposits"] == one, (m["year"], m["month"])


def test_march_is_the_exception_in_the_year_view_too():
    """March's salary TDS is due 30 April. A year view that recomputed the rule
    instead of asking the engine is exactly where that would be lost."""
    march = next(m for m in _call_fy("2026-27").json()["data"]["months"]
                 if m["month"] == 3)
    assert next(d for d in march["deposits"]
                if d["label"] == "TDS on salary")["due_date"] == "2027-04-30"


def test_professional_tax_is_named_as_a_gap_in_the_year_view_as_well():
    assert "rofessional tax" in _call_fy("2026-27").json()["data"]["gaps"][0]


def test_a_financial_year_whose_halves_do_not_follow_is_refused():
    """`2026-28` passes a shape regex and then MEANS 2026-27, because the older
    parsers read the first four characters and ignore the rest. FYLabel refuses
    it — and only because the parameter is written Annotated[FYLabel, Query()]
    rather than `FYLabel = Query(...)`, which validates nothing."""
    assert _call_fy("2026-28").status_code == 422
    assert _call_fy("not-a-year").status_code == 422
