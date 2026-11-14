"""Every route that names a day in its query string refuses, when CALLED, a day that is not one, and names the parameter (POST-A-380, the query-string half).

WHY THIS AND NOT ONLY THE GUARD
    `test_a_date_in_a_query_string_is_a_real_day_or_is_on_the_frozen_list.py` reads the SOURCE: a parameter handed to `query_day` counts as judged wherever the call is.
    That cannot see a call placed after the value was already used, or one whose result is thrown away. This calls each handler the guard counts as judged, as a Partner in
    mock mode, once per judged parameter, with a day that is not one, and asks for the 422 that names the parameter.

    Before this batch 87 of these parameters were on `tests/fixtures/bare_date_query_params.txt`: the reports' windows and as-at days, the statements, the list filters, the
    stock and fixed-asset positions, the invoice number's day. A malformed one reached a date parser (a 500 with no sentence), a text comparison (`b["bill_date"] >= "soon"`, an
    empty or a wrong list with a 200) or a DATE column read month first (`'01/02/2026'::date` is 2 January on the production database). The list is empty now.

WHAT IS NOT CALLED, AND WHY
    `MOCK_RETURNS_FIRST` names the handlers whose mock-mode early return comes before the day is judged, because the access check they make first needs the database: in production
    the day is judged after it. The set is asserted EXACTLY, so a handler that starts returning early cannot drop out of the test unseen. Two doors answer a refusal in their own
    `{success: false}` envelope by design (`ENVELOPE`), and are asked for that instead.
"""
from __future__ import annotations

import importlib
import inspect

import pytest
from fastapi import HTTPException
from fastapi.params import Depends as _DependsParam
from pydantic_core import PydanticUndefined

from tests.test_a_date_in_a_query_string_is_a_real_day_or_is_on_the_frozen_list import scan

PARTNER = {"id": "u1", "firm_id": "F1", "role": "Partner", "email": "p@f1.test", "auth_user_id": "auth-partner"}
PORTAL = {"firm_id": "F1", "client_id": "C1", "contact_id": "k1"}
#: A slash date (stored month first by the database) and a real day with text after it (which the ten-character readers took as the day).
BAD_DAYS = ("01/02/2026", "2026-07-01junk")

#: The modules this batch judged; the three earlier slices' doors have their own tests.
MODULES = ("accounting", "audit", "banking", "billing", "bills_of_entry", "customer_statements", "customers", "cwip", "eway_bill", "fixed_assets", "fx_reports",
           "gst_workspace", "income_tax", "inventory", "invoices", "itr_workspace", "mca_workspace", "payroll", "portal_data", "purchase_bills", "purchase_payments",
           "rcm_documents", "receipts", "reports", "sales_invoices", "tds_workspace", "time_tracking", "vendors")
#: Handlers whose mock-mode return comes before the day is judged (their access check needs the database). Asserted exactly.
MOCK_RETURNS_FIRST = {
    "routers/banking.py::bank_register", "routers/banking.py::transaction_candidate_search",
    "routers/fixed_assets.py::preview_disposal",
}
#: Doors that answer a refusal in the `{success: false}` envelope, as their own tests pin.
ENVELOPE = {"routers/income_tax.py::regime_election", "routers/mca_workspace.py::mca_calendar"}
#: Doors judged by the earlier slices, outside this batch.
EARLIER = {"recurring_invoices", "recurring_purchase_bills", "recurring_journals", "late_interest"}


def _judged() -> list[tuple[str, str, str]]:
    _, judged, _ = scan()
    out = []
    for entry in sorted(judged):
        rel, rest = entry.split("::")
        fn, param = rest.split(".")
        mod = rel.split("/")[-1][:-3]
        if mod in MODULES and fn != "billing_preview_run" and mod not in EARLIER:
            out.append((rel, fn, param))
    return out


def _value(p: inspect.Parameter, target: str, bad: str):
    if p.name == target:
        return bad
    if p.name == "current_user":
        return PARTNER
    if p.name == "portal":
        return PORTAL
    if p.name in ("assessment_year", "financial_year", "fy"):
        return "2026-27"
    default = p.default
    if isinstance(default, _DependsParam):
        return None
    if hasattr(default, "default"):                         # Query(...), Path(...), Body(...)
        d = default.default
        if d is PydanticUndefined or d is Ellipsis:
            return "x" if "int" not in str(p.annotation) else 1
        return d
    if default is inspect.Parameter.empty:
        return "x" if "int" not in str(p.annotation) else 1
    return default


def _handler(rel: str, fn: str):
    return getattr(importlib.import_module(rel[:-3].replace("/", ".")), fn)


def _call(rel: str, fn: str, target: str, bad: str):
    handler = _handler(rel, fn)
    sig = inspect.signature(handler)
    kwargs = {name: _value(p, target, bad) for name, p in sig.parameters.items()}
    # A judged day other than the target is given a real one, so the refusal can only be the target's.
    for name in kwargs:
        if name != target and any(name == j for _, f, j in CASES if f == fn) and kwargs[name] in (None, "x"):
            kwargs[name] = "2026-04-01"
    return handler(**kwargs)


CASES = _judged()


def test_the_cases_are_the_batch():
    handlers = {f"{rel}::{fn}" for rel, fn, _ in CASES}
    assert len(CASES) >= 85, f"only {len(CASES)} judged query days were found in this batch's routers"
    assert MOCK_RETURNS_FIRST <= handlers and ENVELOPE <= handlers


@pytest.mark.parametrize("rel,fn,param", CASES, ids=[f"{fn}.{p}" for _, fn, p in CASES])
def test_a_query_day_that_is_not_a_day_is_refused_and_named(rel, fn, param, monkeypatch):
    key = f"{rel}::{fn}"
    if fn == "eway_validity_for_record":
        # The record is looked up (and its client's access asked) before the day; a record that exists is what this asks about.
        import routers.eway_bill as ewb
        monkeypatch.setattr(ewb, "_assert_ewb_scope", lambda *a, **k: {})
    for bad in BAD_DAYS:
        try:
            out = _call(rel, fn, param, bad)
        except HTTPException as e:
            assert key not in MOCK_RETURNS_FIRST, f"{key} now judges the day in mock mode: take it off MOCK_RETURNS_FIRST"
            assert e.status_code == 422, f"{key}.{param}={bad!r}: {e.status_code} {e.detail}"
            # The sentence names the parameter and the format: `query_day`'s, or `real_day_problem`'s where a door was judged before this batch (the day book).
            assert param in str(e.detail) and "YYYY-MM-DD" in str(e.detail), f"{key}: the refusal of {bad!r} is not a sentence about {param}: {e.detail}"
            continue
        if key in ENVELOPE:
            assert out["success"] is False and "YYYY-MM-DD" in (out["error"] or ""), (bad, out)
            continue
        assert key in MOCK_RETURNS_FIRST, f"{key}.{param}={bad!r} was answered, not refused: {str(out)[:200]}"


REQUIRED = [(rel, fn, p) for rel, fn, p in CASES
            if str(inspect.signature(_handler(rel, fn)).parameters[p].annotation).replace(" ", "") in ("str", "<class'str'>")]


def test_the_required_days_are_the_ones_the_routes_cannot_answer_without():
    assert len(REQUIRED) >= 12, f"only {len(REQUIRED)} required query days were found"


@pytest.mark.parametrize("rel,fn,param", REQUIRED, ids=[f"{fn}.{p}" for _, fn, p in REQUIRED])
def test_a_blank_required_day_is_refused_in_the_same_sentence(rel, fn, param, monkeypatch):
    """FastAPI refuses a required query parameter that is ABSENT; `?as_of=` is present and blank, and used to reach a parser or a comparison."""
    key = f"{rel}::{fn}"
    try:
        out = _call(rel, fn, param, "")
    except HTTPException as e:
        assert e.status_code == 422 and f"{param} must be a date written YYYY-MM-DD" in str(e.detail), (key, e.detail)
        return
    assert key in ENVELOPE and out["success"] is False, f"{key}.{param}='' was answered: {str(out)[:200]}"
