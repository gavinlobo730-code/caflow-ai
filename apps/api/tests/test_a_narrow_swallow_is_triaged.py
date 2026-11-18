"""POST-A-021, fifth slice: a NARROW handler whose whole body was `pass` is triaged into a report or an explicit check.

WHAT WAS WRONG
    Fifteen handlers named the one error they expected and then said nothing. Most guarded a stored date or month that the database
    types as a date, so reaching them means damage, and each one silently moved a figure onto a fallback: an invoice's overdue status
    and dunning off its stored due date, the due date or credit days a draft edit recomputes, the late-filing history of a client's
    risk score, a payslip's month, a TDS return's descriptive slip date. Three guarded ordinary absences that are better asked than
    caught (an impossible date in a notice's text, a trigger's missing due date, a mock invoice number with no digits), one guarded
    an import that cannot fail, and the sales-invoice router held a second copy of the credit-terms rule.

WHAT IS HELD
    * in the files below no handler of any kind has a body that is only `pass` or `continue`;
    * each report names a literal operation of its own, unique across these files and the earlier slices';
    * driven: an unreadable stored date is reported and the fallback still answers; the checks keep their old answers; the sales
      router's names are the credit-terms module's rule.
"""
from __future__ import annotations

import ast
import logging
from datetime import date
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]

CLEARED_FILES = (
    "routers/credit_notes.py", "routers/sales_invoices.py", "services/collections_service.py", "services/credit_terms.py",
    "services/intelligence_service.py", "services/invoice_lifecycle_service.py", "services/payslip_pdf_service.py",
    "services/tds_return_service.py", "domain/ai/statutory_brief.py", "domain/workflow_engine_v2.py",
    "repositories/invoice_repository.py",
)


def _silent_any(source: str) -> list[int]:
    return [n.lineno for n in ast.walk(ast.parse(source))
            if isinstance(n, ast.ExceptHandler) and all(isinstance(b, (ast.Pass, ast.Continue)) for b in n.body)]


@pytest.mark.parametrize("relative", CLEARED_FILES)
def test_no_handler_in_a_triaged_file_is_silent(relative):
    silent = _silent_any((API_ROOT / relative).read_text(encoding="utf-8"))
    assert not silent, f"{relative} swallows an exception without a word at lines {silent}: report it or ask the question instead."


def test_every_report_in_these_files_has_its_own_literal_operation():
    from tests.test_a_swallowed_failure_beyond_the_money_paths_is_reported import CLEARED_FILES as EARLIER
    from tests.test_a_swallowed_failure_on_a_money_path_is_reported_not_silent import MONEY_PATH_FILES, reporter_calls
    seen: dict[str, str] = {}
    for relative in dict.fromkeys(MONEY_PATH_FILES + EARLIER + CLEARED_FILES):
        for call in reporter_calls((API_ROOT / relative).read_text(encoding="utf-8")):
            ops = [k.value for k in call.keywords if k.arg == "operation" and isinstance(k.value, ast.Constant)]
            assert ops, f"{relative}:{call.lineno} has no literal operation"
            assert ops[0].value not in seen, f"{ops[0].value!r} at {seen[ops[0].value]} and {relative}:{call.lineno}"
            seen[ops[0].value] = f"{relative}:{call.lineno}"


@pytest.fixture
def reports(caplog):
    caplog.set_level(logging.ERROR, logger="caflow.observability")
    return lambda: " ".join(r.getMessage() for r in caplog.records)


def test_an_unreadable_base_date_is_reported_and_the_due_date_is_left_as_it_was(reports):
    from services.credit_terms import apply_credit_days_due_date, apply_due_date_credit_days
    d = {"credit_days": 15}
    apply_credit_days_due_date(d, "not-a-date")
    assert "due_date" not in d and "credit_terms.due_date_from_credit_days" in reports()
    d = {"due_date": "2026-05-01"}
    apply_due_date_credit_days(d, "garbage")
    assert "credit_days" not in d and "credit_terms.credit_days_from_due_date" in reports()


def test_the_sales_router_uses_the_credit_terms_rule():
    import routers.sales_invoices as si
    d = {"credit_days": 15}
    si._apply_credit_days_due_date(d, "2026-04-10")
    assert d["due_date"] == "2026-04-25"
    d = {"due_date": "2026-05-10"}
    si._apply_due_date_credit_days(d, "2026-04-10")
    assert d["credit_days"] == 30
    src = (API_ROOT / "routers" / "sales_invoices.py").read_text(encoding="utf-8")
    assert "from services.credit_terms import apply_credit_days_due_date" in src


def test_an_unreadable_due_date_falls_back_and_is_reported(reports):
    from services.collections_service import reference_due_date
    from services.invoice_lifecycle_service import _effective_due_date
    inv = {"id": "i1", "due_date": "31-31-2026", "invoice_date": "2026-04-01", "credit_days": 10}
    assert reference_due_date(inv) == date(2026, 4, 11)
    assert "collections.due_date_unreadable" in reports()
    assert _effective_due_date(inv) is not None
    assert "invoice_lifecycle.due_date_unreadable" in reports()


def test_a_notice_names_only_dates_the_calendar_has():
    from domain.ai.statutory_brief import _dates_in
    assert _dates_in("due 31/02/2026, or 28/02/2026, or 2026-13-01, or 2026-03-31") == [date(2026, 2, 28), date(2026, 3, 31)]


def test_a_trigger_due_date_is_read_or_left_absent():
    from domain.workflow_engine_v2 import _iso_day
    assert _iso_day("2026-04-10") == date(2026, 4, 10)
    for bad in ("2026-02-30", "10/04/2026", None, 20260410, "2026-4-1"):
        assert _iso_day(bad) is None, bad


def test_a_payslip_month_that_does_not_read_falls_back_to_the_slip_and_is_reported(reports):
    from services.payslip_pdf_service import _pay_period
    assert _pay_period({"month": 4, "year": 2026}, {"id": "r1", "month": "2026-xx"})[1:] == (4, 2026)
    assert "payslip_pdf.run_month_unreadable" in reports()
