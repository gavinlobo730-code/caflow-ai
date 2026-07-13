"""
Unit tests for services/credit_terms.py — the shared "Net 30"-style due-date
resolver used by both sales invoices (against a customer's credit_days) and
purchase bills (against a vendor's credit_days). Pure functions, no DB.
"""
from services.credit_terms import resolve_credit_terms, apply_credit_days_due_date, apply_due_date_credit_days


def test_resolve_uses_party_default():
    assert resolve_credit_terms("2026-04-10", None, None, 15) == ("2026-04-25", 15)


def test_resolve_credit_days_override_beats_party_default():
    assert resolve_credit_terms("2026-04-10", None, 45, 15) == ("2026-05-25", 45)


def test_resolve_explicit_due_date_wins_and_derives_credit_days():
    # Apr 10 -> Jun 01 is 52 days; due_date kept verbatim.
    assert resolve_credit_terms("2026-04-10", "2026-06-01", None, 15) == ("2026-06-01", 52)


def test_resolve_falls_back_to_30_when_nothing_specified():
    assert resolve_credit_terms("2026-04-10", None, None, None) == ("2026-05-10", 30)


def test_resolve_zero_credit_days_due_on_doc_date():
    assert resolve_credit_terms("2026-04-10", None, 0, 15) == ("2026-04-10", 0)


def test_resolve_negative_credit_days_floored_at_zero():
    assert resolve_credit_terms("2026-04-10", None, -5, None) == ("2026-04-10", 0)


def test_resolve_malformed_doc_date_returns_none_due_date():
    due, cd = resolve_credit_terms("not-a-date", None, None, 15)
    assert due is None
    assert cd == 15


def test_apply_recompute_on_edit():
    d = {"credit_days": 20}
    apply_credit_days_due_date(d, "2026-04-10")
    assert d["due_date"] == "2026-04-30"


def test_apply_noop_when_due_date_already_present():
    d = {"credit_days": 20, "due_date": "2026-09-09"}
    apply_credit_days_due_date(d, "2026-04-10")
    assert d["due_date"] == "2026-09-09"


def test_apply_noop_when_no_credit_days():
    d = {}
    apply_credit_days_due_date(d, "2026-04-10")
    assert "due_date" not in d


def test_apply_noop_when_no_base_date():
    d = {"credit_days": 20}
    apply_credit_days_due_date(d, None)
    assert "due_date" not in d


def test_apply_reverse_recompute_on_edit():
    d = {"due_date": "2026-04-30"}
    apply_due_date_credit_days(d, "2026-04-10")
    assert d["credit_days"] == 20


def test_apply_reverse_noop_when_credit_days_already_present():
    d = {"due_date": "2026-04-30", "credit_days": 99}
    apply_due_date_credit_days(d, "2026-04-10")
    assert d["credit_days"] == 99


def test_apply_reverse_noop_when_no_due_date():
    d = {}
    apply_due_date_credit_days(d, "2026-04-10")
    assert "credit_days" not in d
