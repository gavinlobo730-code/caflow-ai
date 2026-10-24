"""A draft is asked whether it adds up to its own lines before it is issued (ledger POST-A-335).

The issue routes post the journal and the tax columns from the STORED header row, and a draft is a row a signed-in member's own token can
still change over PostgREST (only the settlement, the status and the journal link are the API's alone since migration 544). So a member who
holds the accounting tier could flag a draft as carried over (`is_opening`) and issue it, which posts a taxed sale and declares it nowhere,
or set a header total or tax to something its lines do not say and have that posted.

Four layers, each with its own reason to exist:

  * the pure rule, `domain/accounting/draft_integrity.problems`, for each of the six kinds of document;
  * the service that reads the lines (paged, because a read cut short at a thousand rows would refuse a draft that adds up);
  * the six issue routes, driven end to end on documents the API itself created (the positive control that matters most: no
    legitimate draft is refused) and then tampered with;
  * a rule over the routers: every route that posts a draft's journal asks, after the period locks and before anything is written.
"""
from __future__ import annotations

import ast
import pathlib

import pytest
from fastapi import HTTPException

import routers.credit_notes as cn
import routers.debit_notes as dn
import routers.purchase_bills as pb
import routers.purchase_credit_notes as pcn
import routers.sales_debit_notes as sdn
import routers.sales_invoices as si
import routers.vendors as ve
from domain.accounting import draft_integrity as rule
from models.invoices import InvoiceLineIn, PurchaseBillIn, PurchaseBillLineIn, PurchaseBillUpdateIn, SalesInvoiceIn
from services import draft_integrity_service as service
from tests.e2e_harness import FakeDB, seed_standard_coa, wire_e2e

API = pathlib.Path(__file__).resolve().parents[1]
FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "id": "u", "auth_user_id": "auth", "email": "ca@f.test", "role": "Partner"}


# ── the pure rule ────────────────────────────────────────────────────────────────────────────────────────────────────────

def _header(kind: str, **over) -> dict:
    """A header that adds up: ₹1,000 taxable, 18% GST split CGST/SGST."""
    h = {"taxable_amount_paise": 100_000, "cgst_paise": 9_000, "sgst_paise": 9_000, "igst_paise": 0,
         "total_gst_paise": 18_000, "total_paise": 118_000}
    if kind in (rule.SALES_INVOICE, rule.PURCHASE_BILL):
        h.update(cess_paise=0, txn_currency="INR")
    if kind == rule.SALES_INVOICE:
        h.update(round_off_paise=0, discount_paise=0)
    if kind == rule.PURCHASE_BILL:
        h.update(tds_paise=0, net_payable_paise=118_000, is_reverse_charge=False,
                 ineligible_itc_cgst_paise=0, ineligible_itc_sgst_paise=0,
                 ineligible_itc_igst_paise=0, ineligible_itc_cess_paise=0)
    h.update(over)
    return h


def _lines(kind: str, **over) -> list[dict]:
    line = {"taxable_amount_paise": 100_000, "cgst_paise": 9_000, "sgst_paise": 9_000, "igst_paise": 0,
            "cess_paise": 0, "discount_paise": 0, "itc_eligible": True}
    line.update(over)
    return [line]


def _codes(found) -> set[str]:
    return {p.code for p in found}


@pytest.mark.parametrize("kind", rule.KINDS)
def test_a_draft_that_adds_up_is_not_refused(kind):
    assert rule.problems(kind, _header(kind), _lines(kind)) == []


@pytest.mark.parametrize("kind", rule.KINDS)
def test_a_flagged_as_carried_over_draft_is_refused_whatever_its_figures(kind):
    found = rule.problems(kind, _header(kind, is_opening=True), _lines(kind))
    assert _codes(found) == {rule.OPENING}
    assert "carried-over" in found[0].text and "never issued from a draft" in found[0].text


@pytest.mark.parametrize("kind", rule.KINDS)
def test_one_paise_off_the_total_is_refused(kind):
    h = _header(kind)
    h["total_paise"] += 1
    if kind == rule.PURCHASE_BILL:
        h["net_payable_paise"] += 1          # keep the bill's other identity true so ONLY the total is wrong
    found = rule.problems(kind, h, _lines(kind))
    assert _codes(found) == {rule.ARITHMETIC}
    assert "its total is" in found[0].text and "₹1,180.01" in found[0].text and "₹1,180.00" in found[0].text


@pytest.mark.parametrize("kind", rule.KINDS)
def test_a_recorded_gst_that_is_not_the_three_heads_is_refused(kind):
    found = rule.problems(kind, _header(kind, total_gst_paise=17_999), _lines(kind))
    assert _codes(found) == {rule.ARITHMETIC}
    assert "recorded GST" in found[0].text


@pytest.mark.parametrize("kind,column", [
    (k, c) for k in rule.KINDS for c in ("taxable_amount_paise", "cgst_paise", "sgst_paise", "igst_paise")])
def test_a_header_figure_that_is_not_its_lines_is_refused_in_each_column(kind, column):
    """The line is moved and the header kept: one column of the header disagrees with the lines, and only that one is named."""
    over = {column: _lines(kind)[0][column] + 1}
    found = rule.problems(kind, _header(kind), _lines(kind, **over))
    assert _codes(found) == {rule.LINES}
    assert len(found) == 1


@pytest.mark.parametrize("kind", [rule.SALES_INVOICE, rule.PURCHASE_BILL])
def test_a_cess_that_is_not_the_lines_is_refused_on_the_two_kinds_that_carry_cess(kind):
    h = _header(kind, cess_paise=500, total_paise=118_500)
    if kind == rule.PURCHASE_BILL:
        h["net_payable_paise"] = 118_500
    assert rule.problems(kind, h, _lines(kind, cess_paise=500)) == []
    found = rule.problems(kind, h, _lines(kind, cess_paise=499))
    assert _codes(found) == {rule.LINES} and "cess" in found[0].text


@pytest.mark.parametrize("kind", [rule.CREDIT_NOTE, rule.DEBIT_NOTE, rule.PURCHASE_CREDIT_NOTE, rule.SALES_DEBIT_NOTE])
def test_a_note_carries_no_cess_or_round_off_so_neither_enters_its_total(kind):
    """The four notes' create paths add taxable and the three heads and nothing else, so a stray cess or round-off key on a note's
    header is not added into what the total must be."""
    assert rule.problems(kind, _header(kind, cess_paise=999, round_off_paise=7), _lines(kind, cess_paise=0)) == []


def test_a_bill_has_no_round_off_and_no_discount_so_neither_enters_its_figures():
    """Round-off is an invoice's opt-in and a discount is an invoice line's (CGST s.15(3)(a)); a bill's total is not adjusted by a
    stray key of either name, and its lines' discount column (a sales-side column) is not compared."""
    h = _header(rule.PURCHASE_BILL, round_off_paise=7)
    assert rule.problems(rule.PURCHASE_BILL, h, _lines(rule.PURCHASE_BILL, discount_paise=5)) == []


def test_an_invoice_marked_reverse_charge_still_totals_its_tax():
    """Only a BILL is owed the taxable value alone on a reverse-charge supply. The create path adds an invoice's tax whatever the
    flag says, and the stored total is that sum, so it is the right total."""
    h = _header(rule.SALES_INVOICE, is_reverse_charge=True)
    assert rule.problems(rule.SALES_INVOICE, h, _lines(rule.SALES_INVOICE)) == []


def test_the_currency_is_read_without_regard_to_case_or_padding():
    base_wrong = _header(rule.SALES_INVOICE, txn_currency=" inr ", taxable_amount_paise=100_001, total_paise=118_001,
                         txn_taxable=100_000, txn_total_gst=18_000)       # the currency columns agree, so only the rupee compare can object
    assert _codes(rule.problems(rule.SALES_INVOICE, base_wrong, _lines(rule.SALES_INVOICE))) == {rule.LINES}   # rupees: compared
    foreign = _header(rule.SALES_INVOICE, txn_currency=" usd ", taxable_amount_paise=100_001, total_paise=118_001,
                      txn_taxable=100_000, txn_total_gst=18_000)
    assert rule.problems(rule.SALES_INVOICE, foreign, _lines(rule.SALES_INVOICE)) == []                    # foreign: not compared


def test_each_blocked_credit_head_is_compared_with_its_own_line_head():
    """Four different amounts, so a head compared against another head's column is not an accident of equal figures."""
    heads = {"cgst_paise": 9_000, "sgst_paise": 7_000, "igst_paise": 3_000, "cess_paise": 500}
    blocked = {"taxable_amount_paise": 100_000, "itc_eligible": False, **heads}
    header = _header(rule.PURCHASE_BILL, cgst_paise=9_000, sgst_paise=7_000, igst_paise=3_000, cess_paise=500,
                     total_gst_paise=19_000, total_paise=119_500, net_payable_paise=119_500,
                     ineligible_itc_cgst_paise=9_000, ineligible_itc_sgst_paise=7_000,
                     ineligible_itc_igst_paise=3_000, ineligible_itc_cess_paise=500)
    assert rule.problems(rule.PURCHASE_BILL, header, [blocked]) == []
    for column, label in (("ineligible_itc_cgst_paise", "CGST"), ("ineligible_itc_sgst_paise", "SGST"),
                          ("ineligible_itc_igst_paise", "IGST"), ("ineligible_itc_cess_paise", "cess")):
        found = rule.problems(rule.PURCHASE_BILL, dict(header, **{column: header[column] - 1}), [blocked])
        assert [p.text for p in found if f"blocked-credit {label} " in p.text], (column, found)
        assert len(found) == 1, (column, found)


def test_an_invoice_total_includes_cess_and_round_off():
    h = _header(rule.SALES_INVOICE, cess_paise=500, round_off_paise=-20, total_paise=118_480)
    assert rule.problems(rule.SALES_INVOICE, h, _lines(rule.SALES_INVOICE, cess_paise=500)) == []
    h["total_paise"] = 118_500          # the round-off left out
    assert _codes(rule.problems(rule.SALES_INVOICE, h, _lines(rule.SALES_INVOICE, cess_paise=500))) == {rule.ARITHMETIC}


def test_an_invoices_discount_is_the_sum_of_its_lines_discounts():
    h = _header(rule.SALES_INVOICE, discount_paise=2_000)
    assert rule.problems(rule.SALES_INVOICE, h, _lines(rule.SALES_INVOICE, discount_paise=2_000)) == []
    found = rule.problems(rule.SALES_INVOICE, h, _lines(rule.SALES_INVOICE, discount_paise=1_000))
    assert _codes(found) == {rule.LINES} and "discount" in found[0].text


def test_a_reverse_charge_bill_owes_the_supplier_the_taxable_value_alone():
    """The supplier charged no tax (CGST Act s.9(3)/(4)): the bill's total is the taxable value even though the three heads are
    recorded for the self-assessed liability. The same total on an ordinary bill is wrong, and the other way round."""
    rcm = _header(rule.PURCHASE_BILL, is_reverse_charge=True, total_paise=100_000, net_payable_paise=100_000)
    assert rule.problems(rule.PURCHASE_BILL, rcm, _lines(rule.PURCHASE_BILL)) == []
    wrong = _header(rule.PURCHASE_BILL, is_reverse_charge=True)       # taxable + tax on a reverse-charge bill
    assert _codes(rule.problems(rule.PURCHASE_BILL, wrong, _lines(rule.PURCHASE_BILL))) == {rule.ARITHMETIC}
    ordinary = _header(rule.PURCHASE_BILL, total_paise=100_000, net_payable_paise=100_000)
    assert _codes(rule.problems(rule.PURCHASE_BILL, ordinary, _lines(rule.PURCHASE_BILL))) == {rule.ARITHMETIC}


def test_a_bills_net_payable_is_its_total_less_the_tax_withheld():
    ok = _header(rule.PURCHASE_BILL, tds_paise=2_000, net_payable_paise=116_000)
    assert rule.problems(rule.PURCHASE_BILL, ok, _lines(rule.PURCHASE_BILL)) == []
    found = rule.problems(rule.PURCHASE_BILL, _header(rule.PURCHASE_BILL, tds_paise=2_000), _lines(rule.PURCHASE_BILL))
    assert _codes(found) == {rule.ARITHMETIC} and "net payable" in found[0].text


def test_a_bills_blocked_credit_is_the_tax_on_the_lines_marked_not_eligible():
    """CGST Act s.17(5): the blocked columns are read by the GSTR-3B ITC claim, so a header that says less is blocked than the lines
    say claims credit the Act denies."""
    blocked_line = {"taxable_amount_paise": 100_000, "cgst_paise": 9_000, "sgst_paise": 9_000, "igst_paise": 0, "cess_paise": 0,
                    "itc_eligible": False}
    ok = _header(rule.PURCHASE_BILL, ineligible_itc_cgst_paise=9_000, ineligible_itc_sgst_paise=9_000)
    assert rule.problems(rule.PURCHASE_BILL, ok, [blocked_line]) == []
    claims_it = _header(rule.PURCHASE_BILL)           # the lines say blocked; the header says nothing is
    found = rule.problems(rule.PURCHASE_BILL, claims_it, [blocked_line])
    assert _codes(found) == {rule.LINES} and len(found) == 2
    assert all("blocked-credit" in p.text for p in found)


def test_a_line_whose_eligibility_is_unstated_is_eligible_not_blocked():
    """The column is a boolean the create path always writes; an absent value is not read as a block."""
    line = _lines(rule.PURCHASE_BILL)[0]
    line.pop("itc_eligible")
    assert rule.problems(rule.PURCHASE_BILL, _header(rule.PURCHASE_BILL), [line]) == []


@pytest.mark.parametrize("kind", [rule.SALES_INVOICE, rule.PURCHASE_BILL])
def test_in_a_foreign_currency_the_lines_are_compared_with_the_documents_own_currency_columns(kind):
    """The header is in rupees and the lines are not: ₹83.50 to the dollar turns a $100 line into a ₹8,350 header, and comparing the
    two would refuse every foreign-currency document. The header keeps the currency's own totals and those are what the lines must say."""
    h = _header(kind, txn_currency="USD", taxable_amount_paise=835_000, cgst_paise=75_150, sgst_paise=75_150,
                total_gst_paise=150_300, total_paise=985_300, txn_taxable=100_000, txn_total_gst=18_000)
    if kind == rule.PURCHASE_BILL:
        h["net_payable_paise"] = 985_300
    assert rule.problems(kind, h, _lines(kind)) == []
    found = rule.problems(kind, dict(h, txn_taxable=100_001), _lines(kind))
    assert _codes(found) == {rule.LINES} and "document's currency" in found[0].text
    found = rule.problems(kind, dict(h, txn_total_gst=18_001), _lines(kind))
    assert _codes(found) == {rule.LINES}


def test_a_foreign_currency_document_is_still_asked_whether_its_own_figures_add_up():
    h = _header(rule.SALES_INVOICE, txn_currency="USD", txn_taxable=100_000, txn_total_gst=18_000, total_paise=1)
    assert _codes(rule.problems(rule.SALES_INVOICE, h, _lines(rule.SALES_INVOICE))) == {rule.ARITHMETIC}


@pytest.mark.parametrize("kind", rule.KINDS)
@pytest.mark.parametrize("lines", [None, []])
def test_a_draft_with_no_lines_has_nothing_behind_its_figures(kind, lines):
    found = rule.problems(kind, _header(kind), lines)
    assert _codes(found) == {rule.LINES} and "no lines" in found[0].text and "₹1,180.00" in found[0].text


def test_an_unknown_kind_is_a_programming_error_not_a_pass():
    with pytest.raises(ValueError):
        rule.problems("receipt", {}, [])


def test_the_refusal_says_what_to_do_about_what_was_wrong():
    both = rule.problems(rule.SALES_INVOICE, _header(rule.SALES_INVOICE, is_opening=True, total_paise=1),
                         _lines(rule.SALES_INVOICE))
    text = rule.refusal(rule.SALES_INVOICE, both)
    assert text.startswith("Cannot issue this invoice: ") and text.endswith("Nothing was posted.")
    assert "Delete this draft" in text and "save it again" in text
    only_flag = rule.refusal(rule.PURCHASE_BILL, rule.problems(rule.PURCHASE_BILL, _header(rule.PURCHASE_BILL, is_opening=True),
                                                               _lines(rule.PURCHASE_BILL)))
    assert "Delete this draft" in only_flag and "save it again" not in only_flag
    only_sum = rule.refusal(rule.CREDIT_NOTE, rule.problems(rule.CREDIT_NOTE, _header(rule.CREDIT_NOTE, total_paise=5),
                                                           _lines(rule.CREDIT_NOTE)))
    assert "save it again" in only_sum and "Delete this draft" not in only_sum
    assert "credit note" in only_sum


def test_the_refusal_names_three_problems_and_counts_the_rest():
    many = [rule.Problem(rule.LINES, f"problem {i}") for i in range(1, 6)]
    text = rule.refusal(rule.DEBIT_NOTE, many)
    assert "problem 1; problem 2; problem 3 (and 2 more)." in text and "problem 4" not in text


# ── the service: the lines are read in pages ─────────────────────────────────────────────────────────────────────────────

class _PagedQuery:
    """Enough of a PostgREST builder for core.db_paging.fetch_all, with the server's cap of 1,000 rows to a response."""

    def __init__(self, rows, cap=1000):
        self.rows, self.cap = rows, cap
        self._filters, self._after, self._limit = [], None, None

    def select(self, *_a, **_k): return self
    def eq(self, column, value): self._filters.append((column, value)); return self
    def gt(self, column, value): self._after = (column, value); return self
    def order(self, *_a, **_k): return self
    def limit(self, n): self._limit = n; return self

    def execute(self):
        rows = [r for r in self.rows if all(r.get(c) == v for c, v in self._filters)]
        rows.sort(key=lambda r: r["id"])
        if self._after:
            rows = [r for r in rows if r[self._after[0]] > self._after[1]]
        take = min(self._limit or self.cap, self.cap)
        return type("R", (), {"data": rows[:take]})()


class _PagedDB:
    def __init__(self, table, rows): self.table_name, self.rows = table, rows
    def table(self, name):
        assert name == self.table_name, name
        return _PagedQuery(self.rows)


def test_more_than_a_thousand_lines_are_all_read():
    """A draft of 1,200 lines whose header is their sum is NOT refused. Read once, the server cuts the response at a thousand rows and
    says nothing, the sums fall short and the draft is refused for a mismatch that is the read's, not the document's."""
    n = 1_200
    lines = [{"id": f"L{i:05d}", "sales_invoice_id": "INV", "taxable_amount_paise": 100, "cgst_paise": 9, "sgst_paise": 9,
              "igst_paise": 0, "cess_paise": 0, "discount_paise": 0} for i in range(n)]
    header = {"id": "INV", "taxable_amount_paise": 100 * n, "cgst_paise": 9 * n, "sgst_paise": 9 * n, "igst_paise": 0,
              "total_gst_paise": 18 * n, "total_paise": 118 * n, "cess_paise": 0, "round_off_paise": 0, "discount_paise": 0}
    service.assert_draft_adds_up(_PagedDB("client_sales_invoice_lines", lines), rule.SALES_INVOICE, header)
    with pytest.raises(HTTPException) as e:
        service.assert_draft_adds_up(_PagedDB("client_sales_invoice_lines", lines[:-1]), rule.SALES_INVOICE, header)
    assert e.value.status_code == 422


@pytest.mark.parametrize("kind,table,fk", [
    (rule.SALES_INVOICE, "client_sales_invoice_lines", "sales_invoice_id"),
    (rule.PURCHASE_BILL, "purchase_bill_lines", "bill_id"),
    (rule.CREDIT_NOTE, "credit_note_lines", "credit_note_id"),
    (rule.DEBIT_NOTE, "debit_note_lines", "debit_note_id"),
    (rule.PURCHASE_CREDIT_NOTE, "purchase_credit_note_lines", "credit_note_id"),
    (rule.SALES_DEBIT_NOTE, "sales_debit_note_lines", "debit_note_id"),
])
def test_each_kind_reads_its_own_line_table_by_the_headers_id(kind, table, fk):
    """A line of ANOTHER document in the same table is not this draft's line: the filter is the document."""
    mine = {"id": "L1", fk: "DOC", "taxable_amount_paise": 100_000, "cgst_paise": 9_000, "sgst_paise": 9_000,
            "igst_paise": 0, "cess_paise": 0, "discount_paise": 0, "itc_eligible": True}
    others = {"id": "L2", fk: "OTHER", "taxable_amount_paise": 7, "cgst_paise": 7, "sgst_paise": 7, "igst_paise": 0}
    header = dict(_header(kind), id="DOC")
    service.assert_draft_adds_up(_PagedDB(table, [mine, others]), kind, header)


def test_a_header_without_an_id_cannot_be_checked():
    with pytest.raises(ValueError):
        service.assert_draft_adds_up(_PagedDB("client_sales_invoice_lines", []), rule.SALES_INVOICE, {})


def test_the_status_test_keeps_each_routes_own_sentence():
    service.assert_a_draft({"status": "draft"}, not_a_draft="x")
    for status in ("issued", "received", "cancelled", "paid", None):
        with pytest.raises(HTTPException) as e:
            service.assert_a_draft({"status": status}, not_a_draft="Only draft invoices can be issued")
        assert e.value.status_code == 422 and e.value.detail == "Only draft invoices can be issued"


# ── the six routes, on documents the API created ─────────────────────────────────────────────────────────────────────────

def _setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [si, cn, dn, pb, pcn, sdn, ve])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27AAAAA0000A1Z2", "financial_year_start": "2025-04-01"})
    db.seed("customers", {"id": "CUST-CLI", "firm_id": FIRM, "client_id": "CLI", "name": "Acme", "is_active": True,
                          "opening_balance_paise": 0})
    db.seed("vendors", {"id": "VEND-CLI", "firm_id": FIRM, "client_id": "CLI", "name": "Supplier", "state_code": "27",
                        "gstin": "27CCCCC2222C1Z5", "tds_applicable": False, "opening_balance_paise": 0})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-CLI", "firm_id": FIRM, "client_id": "CLI", "name": "Goods", "kind": "good"})
    return db


def _line(rate=100_000, **kw):
    return InvoiceLineIn(description="item", quantity=1, rate_paise=rate, gst_rate_percent=18.0,
                         service_catalogue_id="SVC-CLI", **kw)


def _new_invoice(no="INV-1", **kw):
    res = si.create_invoice(SalesInvoiceIn(client_id="CLI", customer_id="CUST-CLI", invoice_no=no, invoice_date="2025-06-01",
                                           supply_state_code="27", lines=kw.pop("lines", [_line()]), **kw), CALLER)
    assert res["success"] is True, res
    return res["data"]["id"]


def _new_bill(no="BILL-1", **kw):
    lines = kw.pop("lines", [PurchaseBillLineIn(description="mat", rate_paise=100_000, quantity=1, gst_rate_percent=18.0,
                                                service_catalogue_id="SVC-CLI")])
    res = pb.create_purchase_bill(PurchaseBillIn(client_id="CLI", vendor_id="VEND-CLI", bill_date="2025-06-01", bill_no=no,
                                                 lines=lines, **kw), CALLER)
    assert res["success"] is True, res
    return res["data"]["id"]


def _issued_invoice(db):
    inv = _new_invoice("INV-BASE")
    assert si.issue_invoice(inv, CALLER)["success"] is True
    return inv


def _received_bill(db):
    bill = _new_bill("BILL-BASE")
    assert pb.receive_purchase_bill(bill, CALLER)["success"] is True
    return bill


def _new_credit_note(db):
    res = cn.create_credit_note(cn.CreditNoteIn(client_id="CLI", customer_id="CUST-CLI", credit_note_date="2025-06-05",
                                                sales_invoice_id=_issued_invoice(db), reason="returned", lines=[_line(10_000)]), CALLER)
    assert res["success"] is True, res
    return res["data"]["id"]


def _new_debit_note(db):
    res = dn.create_debit_note(dn.DebitNoteIn(client_id="CLI", vendor_id="VEND-CLI", debit_note_date="2025-06-05",
                                              purchase_bill_id=_received_bill(db), reason="short", lines=[_line(10_000)]), CALLER)
    assert res["success"] is True, res
    return res["data"]["id"]


def _new_sales_debit_note(db):
    res = sdn.create_sales_debit_note(sdn.SalesDebitNoteIn(
        client_id="CLI", customer_id="CUST-CLI", debit_note_date="2025-06-05", sales_invoice_id=_issued_invoice(db),
        reason="undercharged", lines=[_line(10_000)]), CALLER)
    assert res["success"] is True, res
    return res["data"]["id"]


def _new_purchase_credit_note(db):
    res = pcn.create_purchase_credit_note(pcn.PurchaseCreditNoteIn(
        client_id="CLI", vendor_id="VEND-CLI", credit_note_date="2025-06-05", purchase_bill_id=_received_bill(db),
        reason="undercharged", lines=[_line(10_000)]), CALLER)
    assert res["success"] is True, res
    return res["data"]["id"]


# kind -> (the header table, the line table and its key, how to make a draft, how to issue it)
ROUTES = {
    rule.SALES_INVOICE: ("client_sales_invoices", "client_sales_invoice_lines", "sales_invoice_id",
                         lambda db: _new_invoice("INV-2"), lambda i: si.issue_invoice(i, CALLER)),
    rule.PURCHASE_BILL: ("purchase_bills", "purchase_bill_lines", "bill_id",
                         lambda db: _new_bill("BILL-2"), lambda i: pb.receive_purchase_bill(i, CALLER)),
    rule.CREDIT_NOTE: ("credit_notes", "credit_note_lines", "credit_note_id",
                       _new_credit_note, lambda i: cn.issue_credit_note(i, CALLER)),
    rule.DEBIT_NOTE: ("debit_notes", "debit_note_lines", "debit_note_id",
                      _new_debit_note, lambda i: dn.issue_debit_note(i, CALLER)),
    rule.SALES_DEBIT_NOTE: ("sales_debit_notes", "sales_debit_note_lines", "debit_note_id",
                            _new_sales_debit_note, lambda i: sdn.issue_sales_debit_note(i, CALLER)),
    rule.PURCHASE_CREDIT_NOTE: ("purchase_credit_notes", "purchase_credit_note_lines", "credit_note_id",
                                _new_purchase_credit_note, lambda i: pcn.issue_purchase_credit_note(i, CALLER)),
}


def _row(db, table, doc_id):
    return next(r for r in db.rows(table) if r["id"] == doc_id)


@pytest.mark.parametrize("kind", list(ROUTES))
def test_a_draft_the_api_created_is_issued(monkeypatch, kind):
    """THE POSITIVE CONTROL. Every legitimate draft the API can create adds up under the rule, so none is refused."""
    db = _setup(monkeypatch)
    header_table, _, _, make, issue = ROUTES[kind]
    doc = make(db)
    assert issue(doc)["success"] is True, kind
    assert _row(db, header_table, doc)["status"] in ("issued", "received")


@pytest.mark.parametrize("make_kwargs", [
    {"discount_paise": 5_000},
    {"discount_percent_bps": 1_000},
    {"round_off_enabled": True},
    {"lines": [_line(33_333), _line(12_345, discount_paise=100)]},
    {"lines": [_line(99_999)], "discount_paise": 1},
])
def test_an_invoice_with_a_discount_or_a_round_off_the_api_created_is_issued(monkeypatch, make_kwargs):
    """Discount on the lines, a document discount shared across them, an opt-in rupee round-off and an awkward mix: the header
    is whatever the create path worked out and the rule must agree with it on every shape."""
    _setup(monkeypatch)
    inv = _new_invoice("INV-X", **make_kwargs)
    assert si.issue_invoice(inv, CALLER)["success"] is True


def test_a_reverse_charge_bill_and_a_bill_with_a_blocked_line_the_api_created_are_received(monkeypatch):
    db = _setup(monkeypatch)
    rcm = _new_bill("BILL-RCM", is_reverse_charge=True)
    assert pb.receive_purchase_bill(rcm, CALLER)["success"] is True
    blocked = _new_bill("BILL-BLK", lines=[
        PurchaseBillLineIn(description="blocked", rate_paise=50_000, quantity=1, gst_rate_percent=18.0,
                           service_catalogue_id="SVC-CLI", itc_eligible=False,
                           blocked_credit_reason="Motor vehicle for personal use, CGST Act s.17(5)(a)"),
        PurchaseBillLineIn(description="ordinary", rate_paise=70_000, quantity=1, gst_rate_percent=18.0,
                           service_catalogue_id="SVC-CLI")])
    assert _row(db, "purchase_bills", blocked)["ineligible_itc_cgst_paise"] > 0      # the create path did record a block
    assert pb.receive_purchase_bill(blocked, CALLER)["success"] is True


@pytest.mark.parametrize("kind", list(ROUTES))
@pytest.mark.parametrize("tamper", ["total", "line", "no_lines", "gst_column"])
def test_a_tampered_draft_is_refused_and_nothing_is_posted(monkeypatch, kind, tamper):
    db = _setup(monkeypatch)
    header_table, line_table, fk, make, issue = ROUTES[kind]
    doc = make(db)
    row = _row(db, header_table, doc)
    entries_before = len(db.rows("journal_entries"))
    if tamper == "total":
        row["total_paise"] += 1
        if kind == rule.PURCHASE_BILL:
            row["net_payable_paise"] += 1
    elif tamper == "gst_column":
        row["total_gst_paise"] += 1
    elif tamper == "line":
        next(r for r in db.rows(line_table) if r[fk] == doc)["taxable_amount_paise"] += 1
    else:
        db._tables[line_table] = [r for r in db.rows(line_table) if r[fk] != doc]

    with pytest.raises(HTTPException) as e:
        issue(doc)
    assert e.value.status_code == 422 and e.value.detail.startswith("Cannot issue this ")
    assert e.value.detail.endswith("Nothing was posted.")
    assert row["status"] == "draft"
    assert len(db.rows("journal_entries")) == entries_before


@pytest.mark.parametrize("kind", [rule.SALES_INVOICE, rule.PURCHASE_BILL])
def test_a_draft_flagged_as_carried_over_is_refused_and_leaves_no_trace(monkeypatch, kind):
    """The sharp case: flagged as carried over, a taxed sale would post to Sales and GST Output and be left out of GSTR-1 and GSTR-3B."""
    db = _setup(monkeypatch)
    header_table, _, _, make, issue = ROUTES[kind]
    doc = make(db)
    row = _row(db, header_table, doc)
    entries_before = len(db.rows("journal_entries"))
    row["is_opening"] = True
    with pytest.raises(HTTPException) as e:
        issue(doc)
    assert e.value.status_code == 422 and "carried-over" in e.value.detail
    assert row["status"] == "draft" and len(db.rows("journal_entries")) == entries_before


@pytest.mark.parametrize("kind", list(ROUTES))
def test_the_status_sentence_is_asked_before_the_figures(monkeypatch, kind):
    """An already-issued document answers 'Only draft ... can be issued' and not a complaint about its figures."""
    db = _setup(monkeypatch)
    header_table, _, _, make, issue = ROUTES[kind]
    doc = make(db)
    assert issue(doc)["success"] is True
    _row(db, header_table, doc)["total_paise"] += 1            # damaged afterwards: it is no longer a draft, so nobody asks
    with pytest.raises(HTTPException) as e:
        issue(doc)
    assert e.value.status_code == 422 and e.value.detail.startswith("Only draft ")


# ── a draft bill edited to (or from) reverse charge stays a draft that adds up ───────────────────────────────────────────

def _bill_line():
    return PurchaseBillLineIn(description="mat", rate_paise=100_000, quantity=1, gst_rate_percent=18.0,
                              service_catalogue_id="SVC-CLI")


def test_a_draft_bill_edited_to_reverse_charge_is_totalled_under_the_new_flag(monkeypatch):
    """FOUND BY THE ISSUE-TIME CHECK. The edit recomputed the totals with the flag the bill HAD, so a draft saved with reverse charge
    ticked kept the total of an ordinary bill (the tax added) while the flag said the supplier charged none, and receiving it would
    have posted a payable of ₹1,180 to a supplier owed ₹1,000 (CGST Act s.9(3)/(4))."""
    db = _setup(monkeypatch)
    bill = _new_bill("BILL-E")
    res = pb.update_purchase_bill(bill, PurchaseBillUpdateIn(is_reverse_charge=True, lines=[_bill_line()]), CALLER)
    assert res["success"] is True, res
    row = _row(db, "purchase_bills", bill)
    assert row["is_reverse_charge"] is True and row["total_paise"] == 100_000 and row["net_payable_paise"] == 100_000
    assert row["total_gst_paise"] == 18_000                              # the self-assessed tax is still recorded, for 3B and the credit
    assert rule.problems(rule.PURCHASE_BILL, row, [r for r in db.rows("purchase_bill_lines") if r["bill_id"] == bill]) == []
    assert pb.receive_purchase_bill(bill, CALLER)["success"] is True


def test_a_draft_bill_edited_back_from_reverse_charge_is_totalled_with_its_tax_again(monkeypatch):
    db = _setup(monkeypatch)
    bill = _new_bill("BILL-F", is_reverse_charge=True)
    assert _row(db, "purchase_bills", bill)["total_paise"] == 100_000
    assert pb.update_purchase_bill(bill, PurchaseBillUpdateIn(is_reverse_charge=False, lines=[_bill_line()]), CALLER)["success"]
    row = _row(db, "purchase_bills", bill)
    assert row["is_reverse_charge"] is False and row["total_paise"] == 118_000 and row["net_payable_paise"] == 118_000


def test_the_in_memory_twin_of_the_bill_edit_totals_under_the_new_flag_too(monkeypatch):
    """Mock mode and local development answer from lists in memory; the same rule, so a screen driven against them shows what the
    database path will."""
    monkeypatch.setattr(pb, "_USE_MOCK", True)
    monkeypatch.setattr(pb, "MOCK_PURCHASE_BILLS", [{
        "id": "MB", "firm_id": FIRM, "client_id": "CLI", "vendor_id": "V", "status": "draft", "bill_date": "2025-06-01",
        "is_interstate": False, "is_reverse_charge": False, "total_paise": 118_000}])
    monkeypatch.setattr(pb, "MOCK_PURCHASE_BILL_LINES", [])
    res = pb.update_purchase_bill("MB", PurchaseBillUpdateIn(is_reverse_charge=True, lines=[_bill_line()]), CALLER)
    assert res["success"] is True, res
    assert res["data"]["is_reverse_charge"] is True and res["data"]["total_paise"] == 100_000


def test_changing_reverse_charge_without_the_lines_is_refused_in_words_and_changes_nothing(monkeypatch):
    db = _setup(monkeypatch)
    bill = _new_bill("BILL-G")
    before = dict(_row(db, "purchase_bills", bill))
    with pytest.raises(HTTPException) as e:
        pb.update_purchase_bill(bill, PurchaseBillUpdateIn(is_reverse_charge=True), CALLER)
    assert e.value.status_code == 422 and "send the bill's lines with it" in e.value.detail
    assert _row(db, "purchase_bills", bill) == before


def test_an_edit_that_does_not_change_the_flag_needs_no_lines(monkeypatch):
    db = _setup(monkeypatch)
    bill = _new_bill("BILL-H")
    assert pb.update_purchase_bill(bill, PurchaseBillUpdateIn(is_reverse_charge=False, notes="same flag"), CALLER)["success"]
    assert pb.update_purchase_bill(bill, PurchaseBillUpdateIn(notes="no flag at all"), CALLER)["success"]
    assert _row(db, "purchase_bills", bill)["notes"] == "no flag at all"


def test_a_received_bill_still_answers_its_locked_fields_in_the_old_words(monkeypatch):
    _setup(monkeypatch)
    bill = _new_bill("BILL-I")
    assert pb.receive_purchase_bill(bill, CALLER)["success"] is True
    with pytest.raises(HTTPException) as e:
        pb.update_purchase_bill(bill, PurchaseBillUpdateIn(is_reverse_charge=True), CALLER)
    assert e.value.status_code == 422 and "Cannot change is_reverse_charge on a received bill" in e.value.detail


# ── the rule over the routers ────────────────────────────────────────────────────────────────────────────────────────────

ISSUE_ROUTERS = {
    "sales_invoices": ("issue_invoice", "SALES_INVOICE"),
    "purchase_bills": ("receive_purchase_bill", "PURCHASE_BILL"),
    "credit_notes": ("issue_credit_note", "CREDIT_NOTE"),
    "debit_notes": ("issue_debit_note", "DEBIT_NOTE"),
    "sales_debit_notes": ("issue_sales_debit_note", "SALES_DEBIT_NOTE"),
    "purchase_credit_notes": ("issue_purchase_credit_note", "PURCHASE_CREDIT_NOTE"),
}


def _function(module: str, name: str) -> ast.FunctionDef:
    tree = ast.parse((API / "routers" / f"{module}.py").read_text(encoding="utf-8"))
    return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)


def _calls(fn: ast.FunctionDef, dotted_tail: str) -> list[ast.Call]:
    found = []
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            f = n.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            owner = ast.unparse(f.value) if isinstance(f, ast.Attribute) else ""
            if f"{owner}.{name}".endswith(dotted_tail):
                found.append(n)
    return found


@pytest.mark.parametrize("module,spec", list(ISSUE_ROUTERS.items()))
def test_each_issue_route_asks_after_the_locks_and_before_it_writes(module, spec):
    fn_name, kind_const = spec
    fn = _function(module, fn_name)
    asks = _calls(fn, "draft_integrity_service.assert_draft_adds_up")
    assert len(asks) == 1, f"{module}.{fn_name} must ask the draft whether it adds up, exactly once"
    ask = asks[0]
    assert ast.unparse(ask.args[1]) == f"draft_integrity.{kind_const}", "it must be asked as its own kind of document"
    status = _calls(fn, "draft_integrity_service.assert_a_draft")
    assert len(status) == 1 and status[0].lineno < ask.lineno, "the status sentence comes first"
    lock = _calls(fn, "period_lock_service.assert_open")
    assert lock and max(c.lineno for c in lock) < ask.lineno, "the period locks are asked before the figures"
    writers = [c for c in ast.walk(fn) if isinstance(c, ast.Call)
               and (getattr(c.func, "attr", "") in {"update_header", "journal_for_sales_invoice", "journal_for_purchase_bill",
                                                    "journal_for_credit_note", "journal_for_debit_note",
                                                    "journal_for_sales_debit_note", "journal_for_purchase_credit_note"}
                    or getattr(c.func, "id", "") == "update_header")
               and c.lineno != ask.lineno]
    # the mock-mode branch posts the in-memory row before the real branch begins; only the real branch (after the database is opened) counts
    opened = [c for c in ast.walk(fn) if isinstance(c, ast.Call) and getattr(c.func, "id", "") == "get_supabase"]
    assert opened, "the real branch opens the database"
    real_writers = [w for w in writers if w.lineno > min(o.lineno for o in opened)]
    assert real_writers and min(w.lineno for w in real_writers) > ask.lineno, "nothing is written before the draft is asked"


def test_the_rule_found_the_six_routes_and_every_poster_of_a_drafts_journal_is_one_of_them():
    """Every function in routers/ that posts a document's journal from a stored header is either one of the six issue routes or on
    this short list with the reason it needs no such question."""
    posters = {
        # an ISSUED invoice that has no journal yet: its header is the issued-document particulars migration 535 protects from a
        # signed-in session, which is why this route does not ask the draft question (it is not a draft)
        ("sales_invoices", "repost_journal"),
        # the mock-mode branch lives inside the issue routes themselves
    }
    names = {"journal_for_sales_invoice", "journal_for_purchase_bill", "journal_for_credit_note", "journal_for_debit_note",
             "journal_for_sales_debit_note", "journal_for_purchase_credit_note"}
    seen = set()
    for path in sorted((API / "routers").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
            if any(isinstance(c, ast.Call) and getattr(c.func, "attr", "") in names for c in ast.walk(fn)):
                seen.add((path.stem, fn.name))
    expected = {(m, f) for m, (f, _) in ISSUE_ROUTERS.items()} | posters
    assert seen == expected, f"a route posts a document's journal and is not asked about: {sorted(seen ^ expected)}"
    assert len(ISSUE_ROUTERS) == 6
