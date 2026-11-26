"""POST-A-440, the API half: when the database refuses an issue because the issued invoices would bill more of an order line than was
ordered (migration 650), the issue route says so in words and the invoice stays a draft.

The database half, the race itself and the parity with `order_cycle.over_billing`, is `test_650_order_line_billing_parity_pg.py`.
Here, with no database: the ledger door's error is classified as the over-billing refusal and not as any other (a 23514 that is not
this one stays a posting failure), and `_post_and_mark_issued` turns it into a refusal that posts nothing.
"""
from __future__ import annotations

import pytest

from domain.accounting import journal_figures
from services import phase2_journal_service as pjs


class _PgError(Exception):
    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


def _door_raising(error):
    def door(*_a, **_k):
        raise error
    return door


def _call_door(monkeypatch, error):
    monkeypatch.setattr(pjs, "ledger_rpc", _door_raising(error))
    return pjs.phase2_journal_service._post_through_the_ledger_door(
        object(), firm_id="f", client_id="c", entry_payload={}, line_payloads=[],
        issues_invoice={"invoice_id": "i", "issued_at": "2026-11-16T00:00:00+00:00"}, reference_no="INV-1")


def test_the_databases_over_billing_refusal_is_its_own_exception(monkeypatch):
    error = _PgError('The issued invoices would bill 12.000 of the order line "Widget", which was ordered as 10.000: more than its '
                     'sales order line has unbilled.', "23514")
    with pytest.raises(journal_figures.InvoiceBillsMoreThanItsOrder):
        _call_door(monkeypatch, error)


def test_another_check_violation_is_not_read_as_over_billing(monkeypatch):
    error = _PgError("new row violates check constraint something_else", "23514")
    with pytest.raises(_PgError):
        _call_door(monkeypatch, error)


def test_the_issue_route_words_the_refusal_and_posts_nothing(monkeypatch):
    from routers import sales_invoices as si

    def refused(*_a, **_k):
        raise journal_figures.InvoiceBillsMoreThanItsOrder("order_line_over_billed")

    monkeypatch.setattr(pjs.phase2_journal_service, "journal_for_sales_invoice", refused)
    row, entry, refusal = si._post_and_mark_issued(object(), {"firm_id": "f", "id": "u"}, {"client_id": "c"}, "i")
    assert row is None and entry is None
    assert refusal["success"] is False
    assert "another invoice billing the same sales order line was issued a moment ago" in refusal["error"]
    assert "remains a draft" in refusal["error"]
