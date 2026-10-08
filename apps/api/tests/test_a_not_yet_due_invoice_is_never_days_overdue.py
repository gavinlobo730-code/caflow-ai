"""PRE-A-010 — a fee invoice that is not yet due is never "N days overdue".

`collections_service.assess_invoice` computed `days_overdue = (today - due).days`
and returned it as it stood while the invoice was open, so an issued invoice due
in twelve days came back -12. `sweep_overdue` wrote that into
`client_sales_invoices.days_overdue` (migration 077: NOT NULL DEFAULT 0, no
CHECK, so the database accepted it), the sales screen printed
"(-12d overdue)" wherever the value was truthy, and the client portal's
`safe_invoice` passed it on to the client. The statement services already
clamped (`max(days, 0)`); this one function did not.

The rule is stated, not a spelling of today's call sites: whatever the dates,
`days_overdue` is never negative, `is_overdue` stays the ONLY overdue flag, and
what the sweep writes and the portal shows are the same clamped figure.
"""
from datetime import date, timedelta

import pytest

import services.collections_service as coll
import services.portal_data_service as pds

TODAY = date(2026, 6, 30)


def _inv(due, *, status="issued", total=118000, paid=0, invoice_date="2026-03-01", **extra):
    row = {"id": "I1", "firm_id": "F1", "client_id": "INT", "invoice_no": "SINV-1",
           "invoice_date": invoice_date, "due_date": due, "total_paise": total,
           "paid_paise": paid, "status": status}
    row.update(extra)
    return row


def test_an_open_invoice_not_yet_due_reports_nil_days_overdue():
    m = coll.assess_invoice(_inv((TODAY + timedelta(days=12)).isoformat()), TODAY)
    assert m["days_overdue"] == 0
    assert m["is_overdue"] is False
    assert m["aging_bucket"] == "not_due"


@pytest.mark.parametrize("days_until_due", [-400, -91, -31, -30, -1, 0, 1, 12, 365])
def test_days_overdue_is_never_negative_and_is_overdue_is_the_only_flag(days_until_due):
    # Negative: the due date has passed. Zero: due today. Positive: not yet due.
    due = (TODAY + timedelta(days=days_until_due)).isoformat()
    m = coll.assess_invoice(_inv(due), TODAY)
    assert m["days_overdue"] >= 0
    # The figure and the flag agree, and the flag is what says "overdue".
    assert m["is_overdue"] is (m["days_overdue"] > 0)
    assert m["days_overdue"] == max(-days_until_due, 0)
    # Due today is not overdue: the day AFTER the due date is the first late one.
    if days_until_due >= 0:
        assert m["is_overdue"] is False


def test_a_genuinely_overdue_invoice_keeps_its_positive_count():
    m = coll.assess_invoice(_inv("2026-06-20"), TODAY)
    assert m["days_overdue"] == 10 and m["is_overdue"] is True
    assert m["aging_bucket"] == "0-30"


def test_a_not_yet_due_date_derived_from_credit_days_is_clamped_too():
    # No due_date: the reference date is invoice_date + credit_days, which is
    # the other way a reference date can land after today.
    m = coll.assess_invoice(_inv(None, invoice_date="2026-06-25", credit_days=45), TODAY)
    assert m["days_overdue"] == 0 and m["is_overdue"] is False


def test_a_closed_invoice_still_reports_nil():
    m = coll.assess_invoice(_inv("2026-01-01", status="paid", paid=118000), TODAY)
    assert m["days_overdue"] == 0 and m["is_overdue"] is False and m["aging_bucket"] is None


def test_the_sweep_never_persists_a_negative_figure(monkeypatch):
    """The writer: what reaches `client_sales_invoices.days_overdue`."""
    rows = [
        _inv("2026-07-12", **{"id": "NOT_DUE"}),
        _inv("2026-06-20", **{"id": "LATE"}),
        _inv("2026-06-30", **{"id": "DUE_TODAY"}),
    ]
    written = {}

    class _Update:
        def __init__(self, payload):
            self.payload = payload

        def eq(self, _col, value):
            written[value] = self.payload
            return self

        def execute(self):
            return None

    class _Table:
        def update(self, payload):
            return _Update(payload)

    class _Db:
        def table(self, _name):
            return _Table()

    monkeypatch.setattr(coll, "_USE_MOCK", False)
    monkeypatch.setattr(coll, "get_internal_client_id", lambda firm_id: "INT")
    monkeypatch.setattr(coll, "_open_invoices", lambda firm_id, internal_id: rows)
    monkeypatch.setattr(coll, "_db", lambda: _Db())

    assert coll.sweep_overdue("F1", today=TODAY) == {"swept": 3}
    assert written["NOT_DUE"]["days_overdue"] == 0
    assert written["NOT_DUE"]["is_overdue"] is False
    assert written["NOT_DUE"]["aging_bucket"] == "not_due"
    assert written["DUE_TODAY"]["days_overdue"] == 0
    assert written["LATE"]["days_overdue"] == 10 and written["LATE"]["is_overdue"] is True
    assert all(p["days_overdue"] >= 0 for p in written.values())


def test_the_client_portal_is_never_told_a_negative_figure():
    out = pds.safe_invoice(_inv("2026-07-12"), TODAY)
    assert out["days_overdue"] == 0 and out["is_overdue"] is False
