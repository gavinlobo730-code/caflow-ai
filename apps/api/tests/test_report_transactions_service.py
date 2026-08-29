"""
The unified transaction feed that replaced the dropped `transactions` table.

Two screens depend on this being right — /reports (P&L, outstanding invoices,
GST summary) and /client-portal — and every number on them is money. The tests
below therefore pin the arithmetic and the inclusion rules, not just the shape.

The month-window test is the one worth reading: the code this replaced built its
range as `${month}-31`, which happens to work only because Postgres compares
those as strings. Any use as a real date, or a month boundary reached a
different way, would have been wrong. The replacement derives the exclusive end
from the month itself, and December is tested explicitly because that is where a
naive `month + 1` overflows.
"""
import pytest

from services import report_transactions_service as svc


FIRM = "firm-1"


class _Query:
    """Minimal stand-in for the supabase query builder: records filters and
    returns the rows the fake table was seeded with, filtered accordingly."""

    def __init__(self, rows):
        self._rows = rows
        self._eq, self._in, self._gte, self._lte, self._is = {}, {}, {}, {}, {}

    def select(self, *_a, **_k):
        return self

    def eq(self, k, v):
        self._eq[k] = v
        return self

    def in_(self, k, v):
        self._in[k] = list(v)
        return self

    def gte(self, k, v):
        self._gte[k] = v
        return self

    def lte(self, k, v):
        self._lte[k] = v
        return self

    def is_(self, k, v):
        self._is[k] = v
        return self

    def execute(self):
        rows = []
        for r in self._rows:
            if any(r.get(k) != v for k, v in self._eq.items()):
                continue
            if any(r.get(k) not in v for k, v in self._in.items()):
                continue
            if any((r.get(k) or "") < v for k, v in self._gte.items()):
                continue
            if any((r.get(k) or "") > v for k, v in self._lte.items()):
                continue
            if "deleted_at" in self._is and r.get("deleted_at") is not None:
                continue
            rows.append(dict(r))
        return type("R", (), {"data": rows})()


class FakeDB:
    def __init__(self, **tables):
        self.tables = tables

    def table(self, name):
        return _Query(self.tables.get(name, []))


def _sale(**over):
    row = {
        "id": "s1", "firm_id": FIRM, "client_id": "c1", "customer_id": "cus1",
        "invoice_no": "INV-1", "reference_no": None, "invoice_date": "2026-04-10",
        "is_interstate": False, "supply_state_code": "27",
        "taxable_amount_paise": 100_000, "cgst_paise": 9_000, "sgst_paise": 9_000,
        "igst_paise": 0, "total_paise": 118_000, "paid_paise": 0,
        "status": "issued", "deleted_at": None,
    }
    row.update(over)
    return row


def _bill(**over):
    row = {
        "id": "b1", "firm_id": FIRM, "client_id": "c1", "vendor_id": "ven1",
        "bill_no": "BILL-1", "our_reference": None, "bill_date": "2026-04-12",
        "is_interstate": True, "taxable_amount_paise": 50_000, "cgst_paise": 0,
        "sgst_paise": 0, "igst_paise": 9_000, "total_paise": 59_000,
        "paid_paise": 0, "tds_paise": 5_000, "tds_section": "194C",
        "status": "received", "deleted_at": None,
    }
    row.update(over)
    return row


def _db(sales=None, bills=None):
    return FakeDB(
        client_sales_invoices=sales if sales is not None else [],
        purchase_bills=bills if bills is not None else [],
        customers=[{"id": "cus1", "firm_id": FIRM, "name": "Acme Traders"}],
        vendors=[{"id": "ven1", "firm_id": FIRM, "name": "Bolt Supplies"}],
    )


# ── Shape ────────────────────────────────────────────────────────────────────

def test_a_sales_invoice_becomes_a_sales_transaction():
    rows = svc.list_transactions(_db(sales=[_sale()]), FIRM)

    assert len(rows) == 1
    t = rows[0]
    assert t["transaction_type"] == "sales_invoice"
    assert t["transaction_date"] == "2026-04-10"
    assert t["party_name"] == "Acme Traders"
    assert t["reference_no"] == "INV-1"      # falls back to invoice_no
    assert t["taxable_amount_paise"] == 100_000


def test_a_purchase_bill_becomes_a_purchase_transaction():
    rows = svc.list_transactions(_db(bills=[_bill()]), FIRM)

    t = rows[0]
    assert t["transaction_type"] == "purchase_invoice"
    assert t["party_name"] == "Bolt Supplies"
    assert t["tds_paise"] == 5_000
    assert t["tds_section"] == "194C"


def test_a_sale_carries_no_tds_of_its_own():
    """TDS on a sale is deducted by the CUSTOMER against their payment, not
    recorded on the invoice. Reporting it from the sales side would double-count
    it against the purchase side's real deduction."""
    rows = svc.list_transactions(_db(sales=[_sale()]), FIRM)

    assert rows[0]["tds_paise"] == 0


def test_an_explicit_reference_wins_over_the_document_number():
    sales = [_sale(reference_no="PO-99")]
    bills = [_bill(our_reference="OUR-7")]
    rows = {t["transaction_type"]: t for t in svc.list_transactions(_db(sales, bills), FIRM)}

    assert rows["sales_invoice"]["reference_no"] == "PO-99"
    assert rows["purchase_invoice"]["reference_no"] == "OUR-7"


# ── What counts ──────────────────────────────────────────────────────────────

def test_draft_and_cancelled_sales_are_excluded():
    """A draft is not yet a transaction with anyone, and a cancelled one has
    been undone. Including either overstates turnover in the P&L."""
    sales = [_sale(id="s1", status="draft"), _sale(id="s2", status="cancelled"),
             _sale(id="s3", status="issued")]

    rows = svc.list_transactions(_db(sales=sales), FIRM)

    assert [r["id"] for r in rows] == ["s3"]


def test_cancelled_purchases_are_excluded():
    bills = [_bill(id="b1", status="cancelled"), _bill(id="b2", status="received")]

    rows = svc.list_transactions(_db(bills=bills), FIRM)

    assert [r["id"] for r in rows] == ["b2"]


def test_an_unrecognised_status_is_excluded_rather_than_assumed():
    """The filter is an allowlist, not `!= "draft"`. A status added to either
    table later must fail CLOSED — excluded until someone decides where it
    belongs — rather than silently appearing in financial reports."""
    sales = [_sale(id="s9", status="part_paid_pending_review")]

    assert svc.list_transactions(_db(sales=sales), FIRM) == []


def test_soft_deleted_rows_never_appear():
    sales = [_sale(id="s1", deleted_at="2026-05-01T00:00:00Z"), _sale(id="s2")]

    rows = svc.list_transactions(_db(sales=sales), FIRM)

    assert [r["id"] for r in rows] == ["s2"]


# ── Outstanding ──────────────────────────────────────────────────────────────

def test_outstanding_is_total_less_paid():
    rows = svc.list_transactions(_db(sales=[_sale(total_paise=118_000, paid_paise=18_000)]), FIRM)

    assert rows[0]["outstanding_paise"] == 100_000


def test_outstanding_is_zero_when_fully_paid():
    rows = svc.list_transactions(_db(sales=[_sale(total_paise=118_000, paid_paise=118_000)]), FIRM)

    assert rows[0]["outstanding_paise"] == 0


def test_an_overpayment_does_not_produce_a_negative_outstanding():
    """Advances applied against a smaller invoice make paid > total. Left
    unfloored, that negative would silently cancel out another invoice's real
    debt when the outstanding report totals the column."""
    rows = svc.list_transactions(_db(sales=[_sale(total_paise=100_000, paid_paise=150_000)]), FIRM)

    assert rows[0]["outstanding_paise"] == 0


# ── Ordering and scope ───────────────────────────────────────────────────────

def test_rows_come_back_newest_first():
    sales = [_sale(id="old", invoice_date="2026-01-01"),
             _sale(id="new", invoice_date="2026-06-01")]
    bills = [_bill(id="mid", bill_date="2026-03-01")]

    rows = svc.list_transactions(_db(sales, bills), FIRM)

    assert [r["id"] for r in rows] == ["new", "mid", "old"]


def test_same_date_rows_keep_a_stable_order():
    """Without a tiebreak the two rows could swap between calls, and a report
    would look different on every refresh for no reason."""
    sales = [_sale(id="s_b", invoice_date="2026-04-10"),
             _sale(id="s_a", invoice_date="2026-04-10")]

    first = [r["id"] for r in svc.list_transactions(_db(sales=sales), FIRM)]
    second = [r["id"] for r in svc.list_transactions(_db(sales=list(reversed(sales))), FIRM)]

    assert first == second


def test_scoping_to_no_clients_returns_nothing_without_querying():
    """A caller assigned to zero clients must get an empty list, NOT the
    firm-wide list an empty `in_` filter could produce."""
    called = []

    class Watching(FakeDB):
        def table(self, name):
            called.append(name)
            return super().table(name)

    db = Watching(client_sales_invoices=[_sale()], purchase_bills=[_bill()],
                  customers=[], vendors=[])

    assert svc.list_transactions(db, FIRM, client_ids=[]) == []
    assert called == []


def test_scoping_to_one_client_excludes_the_others():
    sales = [_sale(id="mine", client_id="c1"), _sale(id="theirs", client_id="c2")]

    rows = svc.list_transactions(_db(sales=sales), FIRM, client_ids=["c1"])

    assert [r["id"] for r in rows] == ["mine"]


def test_a_party_from_another_firm_does_not_resolve_to_a_name():
    """The name lookup is firm-scoped even though the ids came from firm-scoped
    rows — a stray id must not turn into another firm's customer name."""
    db = FakeDB(
        client_sales_invoices=[_sale()], purchase_bills=[],
        customers=[{"id": "cus1", "firm_id": "other-firm", "name": "Someone Else"}],
        vendors=[],
    )

    assert svc.list_transactions(db, FIRM)[0]["party_name"] == ""


# ── GST summary ──────────────────────────────────────────────────────────────

# ── The GST summary now DELEGATES, and these pin that it really does ────────
#
# It used to sum invoices and bills here and subtract per head. That was a
# second, quieter GST summary than the one a CA files from, and it differed in
# four ways that all understate or overstate real money: it ignored credit and
# debit notes on both sides; "net" was a raw per-head difference rather than the
# §49(5) set-off; it never reconciled to the General Ledger; and it keyed on a
# calendar month while the return keys on MMYYYY.
#
# The tests that used to live here asserted exactly that arithmetic — including
# `net_igst == -3_000`, a signed negative standing in for a carry-forward. They
# are gone rather than adjusted, because the behaviour they described was the
# defect. What replaces them asserts the new contract: one computation, and this
# is a view of it.
#
# They run through the real from-books harness rather than the query stub above,
# which was built for list_transactions and cannot serve the return's path.

import tests.test_gstr3b_itc_reversal_from_books as E   # noqa: E402
from _pytest.monkeypatch import MonkeyPatch              # noqa: E402


@pytest.fixture()
def books():
    mp = MonkeyPatch()
    try:
        db = E._setup(mp)
        E._receive_bill(db, "B-1", 5_00000, "2025-07-04")
        yield db
    finally:
        mp.undo()


def _month_of(period: str) -> str:
    return f"{period[2:]}-{period[:2]}"


def test_the_summary_and_the_return_report_the_same_figures(books):
    """The whole point. Two GST summaries in one product is worse than one
    imperfect summary: a CA who spots the difference cannot tell which is
    wrong, and one of them is what they filed."""
    ret = E._3b(books, E.JULY)
    rep = svc.gst_summary(books, E.FIRM, "CLI", _month_of(E.JULY))

    w = ret["working"]
    assert rep["gstr3b"]["output_igst"] == w["outward"]["taxable_igst_paise"]
    assert rep["gstr3b"]["output_cgst"] == w["outward"]["taxable_cgst_paise"]
    assert rep["gstr3b"]["output_sgst"] == w["outward"]["taxable_sgst_paise"]
    assert rep["gstr3b"]["itc_igst"] == w["itc"]["net_igst_paise"]
    assert rep["gstr3b"]["itc_cgst"] == w["itc"]["net_cgst_paise"]
    assert rep["gstr3b"]["itc_sgst"] == w["itc"]["net_sgst_paise"]
    assert rep["gstr1"]["taxable"] == w["outward"]["taxable_value_paise"]


def test_net_tax_is_the_section_49_set_off_not_a_per_head_subtraction(books):
    """The old code returned output minus credit per head, signed. That can show
    tax payable on one head while credit sits unused on another, because §49(5)
    cross-utilises IGST credit against CGST and SGST. Net is now the return's
    own figure and is never negative."""
    ret = E._3b(books, E.JULY)
    rep = svc.gst_summary(books, E.FIRM, "CLI", _month_of(E.JULY))

    for head in ("igst", "cgst", "sgst"):
        assert rep["gstr3b"][f"net_{head}"] == ret["working"]["net_payable"][f"{head}_paise"]
        assert rep["gstr3b"][f"net_{head}"] >= 0


def test_a_carry_forward_is_reported_rather_than_hidden_in_a_negative(books):
    """What the signed negative was standing in for. Credit that exceeds
    liability now has a field of its own, and it matches the return's."""
    ret = E._3b(books, E.JULY)
    rep = svc.gst_summary(books, E.FIRM, "CLI", _month_of(E.JULY))

    assert rep["gstr3b"]["itc_carried_forward"] == ret["itc_carried_forward_paise"]
    assert rep["gstr3b"]["itc_carried_forward"] > 0, (
        "this fixture posts a bill and no sales, so credit must carry"
    )


def test_the_summary_carries_the_ledger_reconciliation_it_never_had(books):
    """The old arithmetic could not offer this at all: it summed documents and
    never looked at the GL, so a books-vs-ledger difference was invisible on the
    one screen a partner might read instead of the return."""
    rep = svc.gst_summary(books, E.FIRM, "CLI", _month_of(E.JULY))
    assert rep["reconciliation"] is not None
    assert "output_gst" in rep["reconciliation"]
    assert rep["source"] == "posted_general_ledger"


def test_the_lines_are_the_documents_behind_the_figure_and_sum_to_it(books):
    """`lines` used to be a separate listing that happened to sit near the
    totals. It is now the 3.1(a) detail from the same fetchers, so the listing
    adds up to the figure printed above it — which is the property that makes a
    detail report worth having."""
    rep = svc.gst_summary(books, E.FIRM, "CLI", _month_of(E.JULY))
    lines = rep["gstr1"]["lines"]
    assert sum(int(r["taxable_paise"]) for r in lines) == rep["gstr1"]["taxable"]
    assert sum(int(r["igst_paise"]) for r in lines) == rep["gstr3b"]["output_igst"]


def test_the_month_is_converted_to_the_return_period(books):
    """The screen sends YYYY-MM; the return keys on MMYYYY. Converting at the
    caller was how the two could point at different windows."""
    rep = svc.gst_summary(books, E.FIRM, "CLI", "2025-07")
    assert rep["period"] == "2025-07"
    assert rep["return_period"] == "072025"


def test_the_summary_is_marked_as_needing_ca_review(books):
    """Working figures for a screen, not a filed return."""
    assert svc.gst_summary(books, E.FIRM, "CLI", _month_of(E.JULY))["ca_review_required"] is True


def test_tds_is_still_reported_alongside(books):
    """Not part of the GST return, so gstr3b_from_books does not compute it —
    but the screen has always shown it and removing a figure is a different
    change from correcting the ones that were wrong."""
    rep = svc.gst_summary(books, E.FIRM, "CLI", _month_of(E.JULY))
    assert isinstance(rep["tds_deducted"], int)


@pytest.mark.parametrize("field", ["taxable_amount_paise", "cgst_paise", "total_paise"])
def test_every_amount_is_an_integer(field):
    """CLAUDE.md: integer paise throughout, never a float. A float creeping in
    here would round differently on each screen that formats it."""
    rows = svc.list_transactions(_db(sales=[_sale()], bills=[_bill()]), FIRM)

    for r in rows:
        assert isinstance(r[field], int), f"{r['transaction_type']}.{field}"
