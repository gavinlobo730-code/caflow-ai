"""What the portal says a client OWES is total + debit notes - paid - credit notes (POST-A-244).

THE DEFECT
    `collections_service.assess_invoice` computes the amount owed from four columns: `total_paise`, `debit_note_paise`,
    `paid_paise` and `credited_paise` (CGST Act s.34: a credit note reduces the amount recoverable, a debit note raises it).
    `portal_data_service.list_invoices` selected only two of them, so the figure fell back to total - paid. The states the
    product can actually reach showed it two ways: a PART-credited invoice (status partially_paid) was owed and overdue at its
    pre-credit amount on the client portal and in the staff preview; and a FULLY credited one (the credit-note route marks it
    paid once paid + credited covers the total) was listed with its full amount in the Outstanding column against a Paid
    status. A cancelled invoice also printed total - paid as outstanding, because the figure reads no status.

WHAT IS HELD
    * the query names both note columns, so a double that projects the way PostgREST does cannot hide them;
    * a credit note lowers what the client owes, a debit note raises it, and the totals the dues screen shows agree;
    * a fully credited invoice (status paid) owes nothing in the list, and the arithmetic holds for a status the product
      does not produce too;
    * a cancelled invoice owes nothing.
"""
from __future__ import annotations

import pytest

import services.portal_data_service as pds
from tests.test_portal_data_surfaces import (
    FIRM, INTERNAL_CLIENT, LINKED_CUSTOMER, PORTAL_CLIENT, TODAY, FakeDB, _Query, _inv,
)


class _Projecting(_Query):
    """The part of PostgREST the shared double leaves out: only the columns named in select() come back."""

    def select(self, cols="*", *_a, **_k):
        self._cols = None if str(cols).strip() == "*" else [c.strip() for c in str(cols).split(",")]
        self._db.selects.setdefault(self._table, []).append(self._cols)
        return self

    def execute(self):
        res = super().execute()
        cols = getattr(self, "_cols", None)
        if cols is not None:
            res.data = [{c: r[c] for c in cols if c in r} for r in res.data]
        return res


class _ProjectingDB(FakeDB):
    def __init__(self):
        super().__init__()
        self.selects: dict[str, list] = {}

    def table(self, name):
        return _Projecting(self, name)


@pytest.fixture
def db(monkeypatch):
    d = _ProjectingDB()
    d.seed("client_firm_customer_links",
           {"firm_id": FIRM, "client_id": PORTAL_CLIENT, "internal_customer_id": LINKED_CUSTOMER})
    import services.internal_client_service as ics
    monkeypatch.setattr(ics, "get_internal_client_id", lambda firm_id: INTERNAL_CLIENT if firm_id == FIRM else None)
    return d


def _with_notes(iid, *, credited=0, debited=0, **kw):
    return {**_inv(iid, **kw), "credited_paise": credited, "debit_note_paise": debited}


def test_the_query_names_both_note_columns(db):
    db.seed("client_sales_invoices", _with_notes("A"))
    pds.list_invoices(FIRM, PORTAL_CLIENT, db=db, today=TODAY)
    asked = db.selects["client_sales_invoices"][-1]
    assert "credited_paise" in asked and "debit_note_paise" in asked, asked


def test_a_credit_note_lowers_what_the_client_owes(db):
    db.seed("client_sales_invoices", _with_notes("A", total=100000, paid=0, credited=40000, due="2024-12-31"))
    [row] = pds.list_invoices(FIRM, PORTAL_CLIENT, db=db, today=TODAY)
    assert row["outstanding_paise"] == 60000, "total 1,000 less a 400 credit note, nothing paid: 600 is owed"
    assert row["total_paise"] == 100000, "the face value is still the invoice's own"


def test_a_debit_note_raises_what_the_client_owes(db):
    db.seed("client_sales_invoices", _with_notes("A", total=100000, paid=30000, debited=20000, due="2024-12-31"))
    [row] = pds.list_invoices(FIRM, PORTAL_CLIENT, db=db, today=TODAY)
    assert row["outstanding_paise"] == 90000


def test_the_dues_totals_are_net_of_the_notes(db):
    db.seed("client_sales_invoices", _with_notes("A", total=100000, credited=40000, due="2024-12-31"))
    db.seed("client_sales_invoices", _with_notes("B", total=50000, paid=10000, debited=5000, due="2024-01-01"))
    out = pds.dues(FIRM, PORTAL_CLIENT, db=db, today=TODAY)
    assert out["total_outstanding_paise"] == 60000 + 45000
    assert out["overdue_paise"] == 45000 and out["overdue_count"] == 1, "only B is past its due date"


def test_an_invoice_credited_down_to_nothing_is_not_a_due(db):
    """The arithmetic guard, on a status the credit-note route does not leave behind (it marks such an invoice paid)."""
    db.seed("client_sales_invoices", _with_notes("GONE", total=100000, credited=100000, due="2024-01-01"))
    db.seed("client_sales_invoices", _with_notes("OPEN", total=50000, due="2024-12-31"))
    out = pds.dues(FIRM, PORTAL_CLIENT, db=db, today=TODAY)
    assert [d["id"] for d in out["dues"]] == ["OPEN"]
    assert out["overdue_count"] == 0, "a fully credited invoice must not count as overdue"


def test_a_fully_credited_invoice_the_credit_note_route_marked_paid_owes_nothing_in_the_list(db):
    """The reachable state: paid + credited covers the total, so the route sets status paid. The list used to print the
    full 1,000.00 in the Outstanding column against a Paid badge."""
    db.seed("client_sales_invoices", _with_notes("PAID-BY-CREDIT", status="paid", total=100000, paid=0,
                                                 credited=100000, due="2024-01-01"))
    [row] = pds.list_invoices(FIRM, PORTAL_CLIENT, db=db, today=TODAY)
    assert row["status"] == "paid" and row["outstanding_paise"] == 0


def test_a_part_credited_invoice_is_owed_and_overdue_at_the_net_amount(db):
    """The other reachable state: status partially_paid after a part credit, owed at the pre-credit amount before."""
    db.seed("client_sales_invoices", _with_notes("PART", status="partially_paid", total=100000, paid=0,
                                                 credited=30000, due="2024-01-01"))
    out = pds.dues(FIRM, PORTAL_CLIENT, db=db, today=TODAY)
    assert out["total_outstanding_paise"] == 70000 and out["overdue_paise"] == 70000 and out["overdue_count"] == 1


def test_a_cancelled_invoice_owes_nothing(db):
    db.seed("client_sales_invoices", _with_notes("WITHDRAWN", status="cancelled", total=100000, paid=0,
                                                 due="2024-01-01"))
    [row] = pds.list_invoices(FIRM, PORTAL_CLIENT, db=db, today=TODAY)
    assert row["status"] == "cancelled" and row["outstanding_paise"] == 0
    assert pds.dues(FIRM, PORTAL_CLIENT, db=db, today=TODAY)["dues"] == [], "and it is not a due"
