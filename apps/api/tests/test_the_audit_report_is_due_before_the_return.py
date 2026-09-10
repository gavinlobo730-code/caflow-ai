"""
IT-12: the §44AB report's due date was wrong on the one screen that shows it.

WHAT WAS WRONG

Two places, and one of them was already fixed. `compliance_obligation_service.
_tax_audit_obligation` used to date the report at `itr_due_date(is_audit=True)`
— the RETURN's 31 October — and now derives 30 September from
`compliance_engine.tax_audit_report_due_date`.

The screen was not. `apps/web/app/income-tax/tax-audit/page.tsx` headed the Tax
Audit Tracker with

    IT Act Section 44AB — Form 3CA/3CB/3CD | Due: 30 November

as a hardcoded string, wrong against BOTH dates: 30 November is the §92E
transfer-pricing date for the RETURN, and it was shown as the report's. No
backend was involved, so no backend fix could reach it.

Explanation (ii) to §44AB, substituted by the Finance Act 2020 w.e.f.
AY 2020-21, defines the "specified date" as the date ONE MONTH PRIOR to the
§139(1) due date. So the report is due 30 September and the return 31 October,
and they are two dates a month apart. §271B — 0.5% of turnover, capped at
₹1,50,000 — is what makes the lateness expensive.

WHAT THIS FILE PINS

The endpoint the screen now asks: that it answers both dates, that they are
derived from one another rather than stated, and that it refuses a financial
year it cannot read. The screen's half is
apps/web/scripts/a-statutory-due-date-is-never-a-literal.test.ts.
"""
from datetime import date

import pytest
from fastapi import HTTPException

import routers.compliance as compliance
from services.compliance_engine import itr_due_date, tax_audit_report_due_date

CALLER = {"firm_id": "firm-1", "id": "u-1", "auth_user_id": "auth-1",
          "role": "Partner"}


def _get(fy: str) -> dict:
    return compliance.tax_audit_due_dates(financial_year=fy, current_user=CALLER)["data"]


def test_the_report_is_due_30_september_and_the_return_31_october():
    got = _get("2025-26")
    assert got["report_due_date"] == "2026-09-30"
    assert got["return_due_date"] == "2026-10-31"
    assert got["financial_year"] == "2025-26"


def test_they_are_two_dates_a_month_apart_in_every_year():
    for fy, end in (("2023-24", 2024), ("2024-25", 2025), ("2025-26", 2026),
                    ("2026-27", 2027)):
        got = _get(fy)
        assert got["report_due_date"] == date(end, 9, 30).isoformat(), fy
        assert got["return_due_date"] == date(end, 10, 31).isoformat(), fy


def test_the_report_date_is_DERIVED_from_the_return_date(monkeypatch):
    """Explanation (ii) defines it BY REFERENCE to §139(1), so a CBDT extension
    of the return has to move the report with it. A stated 30 September would
    read identically today and diverge the first time a date moved."""
    import services.compliance_engine as ce
    monkeypatch.setattr(ce, "itr_due_date",
                        lambda fye, **kw: date(fye, 12, 15))
    assert ce.tax_audit_report_due_date(2026) == date(2026, 11, 15)


def test_the_long_financial_year_form_is_accepted_and_canonicalised():
    assert _get("2025-2026")["report_due_date"] == "2026-09-30"


def test_a_financial_year_that_contradicts_itself_is_refused():
    """`2026-28` passes a shape regex and then means 2026-27 — a wrong answer,
    not a rejected request (CLAUDE.md, Identifiers).

    Two halves, and calling the handler as a function proves neither: FastAPI
    runs the validator, so a direct call skips it entirely. So this asserts the
    validator refuses, and that the parameter is annotated the way that lets
    FastAPI reach it — `Annotated[FYLabel, Query(...)]`, not
    `FYLabel = Query(...)`, which discards the metadata SILENTLY and leaves an
    endpoint that reads as guarded (CLAUDE.md, Identifiers).
    """
    import typing
    from core.ist_clock import normalise_fy_label
    from models.fy import FYLabel

    with pytest.raises(ValueError):
        normalise_fy_label("2026-28")
    assert normalise_fy_label("2025-2026") == "2025-26"

    hints = typing.get_type_hints(compliance.tax_audit_due_dates, include_extras=True)
    assert hints["financial_year"].__origin__ is FYLabel.__origin__, (
        "the parameter must be Annotated[FYLabel, Query(...)]")


def test_the_basis_names_the_section_and_the_premise():
    """A date on a compliance screen is only as good as what a CA can check it
    against — and the premise matters, because whether §44AB applies at all is
    a turnover question this app does not hold."""
    basis = _get("2025-26")["basis"]
    assert "44AB" in basis and "Explanation (ii)" in basis
    assert "one month prior" in basis
    assert "Assumes §44AB applies" in basis


def test_the_obligation_generator_agrees_with_the_endpoint():
    """Two callers, one engine. The calendar and the tracker must not be able to
    show a CA two different dates for the same obligation."""
    from services.compliance_obligation_service import _tax_audit_obligation
    specs = _tax_audit_obligation("2025-26")
    assert specs, "the audit obligation must exist"
    assert any(s.get("due_date") == "2026-09-30" for s in specs), specs
    assert tax_audit_report_due_date(2026).isoformat() == _get("2025-26")["report_due_date"]


def test_30_november_is_the_transfer_pricing_RETURN_date_and_nothing_else():
    """The string the screen used to show. It is a real date — the §92E case's
    §139(1) date — which is why it looked plausible enough to survive."""
    assert itr_due_date(2026, has_transfer_pricing_report=True) == date(2026, 11, 30)
    assert _get("2025-26")["report_due_date"] != "2026-11-30"
    assert _get("2025-26")["return_due_date"] != "2026-11-30"
