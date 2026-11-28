"""A document billed in a foreign currency is not settled, credited or debited in rupees alone (ledger POST-A-579).

WHAT WAS WRONG
    A foreign receipt or payment moves a document's rupee amount and its foreign amount together, and the receipt and payment
    functions refuse a rupee one in words (POST-A-576). Six other doors moved the rupees alone: a bank line matched one-to-one to
    an invoice or a bill, a party's credit applied to one, and a credit or debit note issued against one, on both sides. The document
    then read settled in rupees with its foreign amount outstanding, and the next foreign receipt refused it in words that blamed a
    rupee shortfall nobody could see.

WHAT THIS HOLDS (mock mode; the doors that write run on the e2e harness)
    * each of the four notes, issued against a document billed in a foreign currency, is refused in a sentence that names the document
      and its currency, and leaves the document, the ledger and the note as they were; against a rupee document it is issued as before;
    * a party's credit applied to a foreign invoice or bill is refused and the party keeps its credit (the balance taken first is put
      back); applied to a rupee document it still works;
    * the bank door refuses a line matched one-to-one to a foreign invoice or bill, on the post and on the preview, before the line
      is claimed; a rupee document, a line matched to nothing and a category that settles no document are not touched;
    * `billed_in` reads the column the way the receipt and payment doors read it: blank is rupees, case does not matter.
"""
from __future__ import annotations

import inspect

import pytest
from fastapi import HTTPException

import routers.credit_notes as cn
import routers.debit_notes as dn
import routers.purchase_bills as pb
import routers.purchase_credit_notes as pcn
import routers.sales_debit_notes as sdn
import routers.sales_invoices as si
import routers.vendors as ve
from domain.accounting import foreign_documents as fd
from models.invoices import InvoiceLineIn, PurchaseBillIn, PurchaseBillLineIn, SalesInvoiceIn, SalesInvoiceLineIn
from services import party_credit_service as pcs_module
from services.bank_posting_service import BankPostingService
from tests.e2e_harness import FakeDB, seed_standard_coa, trial_balance, wire_e2e

FIRM = "FIRM-579"
CALLER = {"firm_id": FIRM, "id": "u", "auth_user_id": "auth", "email": "ca@f.test", "role": "Partner"}


def _world(monkeypatch) -> FakeDB:
    db = FakeDB()
    wire_e2e(monkeypatch, db, [si, cn, dn, pb, pcn, sdn, ve, pcs_module])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27AAAAA0000A1Z2", "financial_year_start": "2025-04-01"})
    db.seed("customers", {"id": "CUST-CLI", "firm_id": FIRM, "client_id": "CLI", "name": "Acme", "is_active": True,
                          "opening_balance_paise": 0})
    db.seed("vendors", {"id": "VEND-CLI", "firm_id": FIRM, "client_id": "CLI", "name": "Supplier", "state_code": "27",
                        "gstin": "27CCCCC2222C1Z5", "tds_applicable": False, "opening_balance_paise": 0})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-CLI", "firm_id": FIRM, "client_id": "CLI", "name": "Services", "kind": "service"})
    return db


def _row(db, table, row_id):
    return next(r for r in db.rows(table) if r["id"] == row_id)


def _invoice(db, *, currency=None, no="INV-1") -> str:
    res = si.create_invoice(SalesInvoiceIn(
        client_id="CLI", customer_id="CUST-CLI", invoice_no=no, invoice_date="2025-06-01", supply_state_code="27",
        lines=[SalesInvoiceLineIn(description="svc", quantity=1, rate_paise=100_000, gst_rate_percent=18.0,
                                  service_catalogue_id="SVC-CLI")]), CALLER)
    assert res["success"] is True, res
    assert si.issue_invoice(res["data"]["id"], CALLER)["success"] is True
    if currency:
        _row(db, "client_sales_invoices", res["data"]["id"])["txn_currency"] = currency
    return res["data"]["id"]


def _bill(db, *, currency=None, no="BILL-1") -> str:
    res = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id="VEND-CLI", bill_date="2025-06-01", bill_no=no,
        lines=[PurchaseBillLineIn(description="svc", quantity=1, rate_paise=100_000, gst_rate_percent=18.0,
                                  service_catalogue_id="SVC-CLI")]), CALLER)
    assert res["success"] is True, res
    assert pb.receive_purchase_bill(res["data"]["id"], CALLER)["success"] is True
    if currency:
        _row(db, "purchase_bills", res["data"]["id"])["txn_currency"] = currency
    return res["data"]["id"]


def _line(**over):
    kw = dict(description="adjustment", quantity=1, rate_paise=10_000, gst_rate_percent=18.0, service_catalogue_id="SVC-CLI")
    kw.update(over)
    return InvoiceLineIn(**kw)


# kind -> (document kind, how the note is made against the document, how it is issued, the note's table, the document's table, the label)
def _credit(doc_id):
    return cn.create_credit_note(cn.CreditNoteIn(client_id="CLI", customer_id="CUST-CLI", credit_note_date="2025-06-05",
                                                 sales_invoice_id=doc_id, reason="returned", goods_returned=False,
                                                 lines=[_line()]), CALLER)


def _sales_debit(doc_id):
    return sdn.create_sales_debit_note(sdn.SalesDebitNoteIn(client_id="CLI", customer_id="CUST-CLI", debit_note_date="2025-06-05",
                                                            sales_invoice_id=doc_id, reason="undercharged", lines=[_line()]), CALLER)


def _purchase_debit(doc_id):
    return dn.create_debit_note(dn.DebitNoteIn(client_id="CLI", vendor_id="VEND-CLI", debit_note_date="2025-06-05",
                                               purchase_bill_id=doc_id, reason="returned", goods_returned=False,
                                               lines=[_line()]), CALLER)


def _purchase_credit(doc_id):
    return pcn.create_purchase_credit_note(pcn.PurchaseCreditNoteIn(client_id="CLI", vendor_id="VEND-CLI",
                                                                    credit_note_date="2025-06-05", purchase_bill_id=doc_id,
                                                                    reason="undercharged", lines=[_line()]), CALLER)


NOTES = {
    "credit note": (_invoice, _credit, lambda i: cn.issue_credit_note(i, CALLER), "credit_notes", "client_sales_invoices", "credited_paise", "Invoice"),
    "sales debit note": (_invoice, _sales_debit, lambda i: sdn.issue_sales_debit_note(i, CALLER), "sales_debit_notes", "client_sales_invoices",
                         "debit_note_paise", "Invoice"),
    "purchase debit note": (_bill, _purchase_debit, lambda i: dn.issue_debit_note(i, CALLER), "debit_notes", "purchase_bills", "debited_paise", "Bill"),
    "purchase credit note": (_bill, _purchase_credit, lambda i: pcn.issue_purchase_credit_note(i, CALLER), "purchase_credit_notes", "purchase_bills",
                             "credit_note_paise", "Bill"),
}


# ── the rule ──────────────────────────────────────────────────────────────

def test_billed_in_reads_blank_as_rupees_and_ignores_case_and_spaces():
    assert [fd.billed_in(d) for d in ({}, None, {"txn_currency": None}, {"txn_currency": ""}, {"txn_currency": "  "}, {"txn_currency": "inr"},
                                      {"txn_currency": "INR"})] == ["INR"] * 7
    assert fd.billed_in({"txn_currency": " usd "}) == "USD"
    assert [fd.is_foreign(d) for d in ({}, {"txn_currency": "INR"}, {"txn_currency": "usd"}, {"txn_currency": "EUR"})] == [False, False, True, True]


def test_each_sentence_names_the_document_its_currency_and_that_nothing_was_written():
    for sentence, nothing in ((fd.refusal_for_a_bank_line("INV-7", "USD", is_bill=False), "Nothing was posted."),
                              (fd.refusal_for_a_party_credit("INV-7", "USD", is_bill=False), "Nothing was applied."),
                              (fd.refusal_for_a_note("INV-7", "USD", is_bill=False, note="credit note"), "Nothing was issued.")):
        assert "Invoice INV-7" in sentence and "USD" in sentence and sentence.endswith(nothing), sentence
    assert "Bill B-9" in fd.refusal_for_a_bank_line("B-9", "EUR", is_bill=True) and "payment" in fd.refusal_for_a_bank_line("B-9", "EUR", is_bill=True)
    assert "receipt" in fd.refusal_for_a_bank_line("INV-7", "USD", is_bill=False)


# ── the four notes ────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind", list(NOTES))
def test_a_note_against_a_foreign_document_is_refused_in_words_and_nothing_changes(monkeypatch, kind):
    db = _world(monkeypatch)
    doc_of, make, issue, note_table, doc_table, column, noun = NOTES[kind]
    doc_id = doc_of(db, currency="USD")
    made = make(doc_id)
    assert made["success"] is True, made
    before_doc = dict(_row(db, doc_table, doc_id))
    entries = len(db.rows("journal_entries"))
    with pytest.raises(HTTPException) as refused:
        issue(made["data"]["id"])
    assert refused.value.status_code == 422
    sentence = str(refused.value.detail)
    assert noun in sentence and "is billed in USD" in sentence and " ".join(kind.split()[-2:]) in sentence and sentence.endswith("Nothing was issued."), sentence
    after = _row(db, doc_table, doc_id)
    assert (after.get(column), after.get("status"), after.get("paid_paise")) == (before_doc.get(column), before_doc.get("status"),
                                                                                 before_doc.get("paid_paise"))
    assert len(db.rows("journal_entries")) == entries, "the refused note posted an entry"
    assert _row(db, note_table, made["data"]["id"])["status"] == "draft", "the refused note left draft"


@pytest.mark.parametrize("kind", list(NOTES))
def test_the_same_note_against_a_rupee_document_is_issued_as_before(monkeypatch, kind):
    db = _world(monkeypatch)
    doc_of, make, issue, note_table, doc_table, column, _noun = NOTES[kind]
    doc_id = doc_of(db)
    made = make(doc_id)
    assert made["success"] is True, made
    done = issue(made["data"]["id"])
    assert done["success"] is True, done
    assert int(_row(db, doc_table, doc_id).get(column) or 0) > 0
    tb = trial_balance(db, FIRM, "CLI")
    assert tb["total_debit_paise"] == tb["total_credit_paise"]


# ── a party's credit ──────────────────────────────────────────────────────

def _grant(db, party_type, party_id, amount):
    pcs_module.party_credit_service.grant_credit(db, FIRM, "CLI", party_type, party_id, amount, source_type="test", source_id="seed", created_by="u")


@pytest.mark.parametrize("party_type,party_id,doc_of,doc_type,doc_table", [
    ("customer", "CUST-CLI", _invoice, "sales_invoice", "client_sales_invoices"),
    ("vendor", "VEND-CLI", _bill, "purchase_bill", "purchase_bills"),
])
def test_a_party_credit_applied_to_a_foreign_document_is_refused_and_the_party_keeps_it(monkeypatch, party_type, party_id, doc_of, doc_type, doc_table):
    db = _world(monkeypatch)
    doc_id = doc_of(db, currency="USD")
    _grant(db, party_type, party_id, 50_000)
    before = pcs_module.party_credit_service.get_balance(db, FIRM, "CLI", party_type, party_id)
    with pytest.raises(HTTPException) as refused:
        pcs_module.party_credit_service.apply_credit(db, FIRM, "CLI", party_type, party_id, 20_000, doc_type, doc_id, created_by="u")
    assert refused.value.status_code == 422 and "is billed in USD" in str(refused.value.detail) and "Nothing was applied." in str(refused.value.detail)
    assert pcs_module.party_credit_service.get_balance(db, FIRM, "CLI", party_type, party_id) == before == 50_000
    assert int(_row(db, doc_table, doc_id).get("paid_paise") or 0) == 0


@pytest.mark.parametrize("party_type,party_id,doc_of,doc_type,doc_table", [
    ("customer", "CUST-CLI", _invoice, "sales_invoice", "client_sales_invoices"),
    ("vendor", "VEND-CLI", _bill, "purchase_bill", "purchase_bills"),
])
def test_a_party_credit_applied_to_a_rupee_document_still_works(monkeypatch, party_type, party_id, doc_of, doc_type, doc_table):
    db = _world(monkeypatch)
    doc_id = doc_of(db)
    _grant(db, party_type, party_id, 50_000)
    pcs_module.party_credit_service.apply_credit(db, FIRM, "CLI", party_type, party_id, 20_000, doc_type, doc_id, created_by="u")
    assert pcs_module.party_credit_service.get_balance(db, FIRM, "CLI", party_type, party_id) == 30_000
    assert int(_row(db, doc_table, doc_id).get("paid_paise") or 0) == 20_000


# ── the bank door ─────────────────────────────────────────────────────────

def _txn(category, kind, doc_id):
    return {"id": "T-1", "client_id": "CLI", "category": category, "matched_entity_type": kind, "matched_entity_id": doc_id}


def test_the_bank_door_refuses_a_line_matched_to_a_foreign_invoice_or_bill(monkeypatch):
    db = _world(monkeypatch)
    svc = BankPostingService()
    inv, bill = _invoice(db, currency="USD", no="USD-INV"), _bill(db, currency="EUR", no="EUR-BILL")
    with pytest.raises(HTTPException) as r1:
        svc._assert_matched_document_is_in_rupees(db, FIRM, _txn("Customer Payment", "sales_invoice", inv))
    assert r1.value.status_code == 422 and "Invoice USD-INV is billed in USD" in r1.value.detail and r1.value.detail.endswith("Nothing was posted.")
    with pytest.raises(HTTPException) as r2:
        svc._assert_matched_document_is_in_rupees(db, FIRM, _txn("Vendor Payment", "purchase_bill", bill))
    assert "Bill EUR-BILL is billed in EUR" in r2.value.detail and "payment" in r2.value.detail


def test_the_bank_door_leaves_everything_else_alone(monkeypatch):
    db = _world(monkeypatch)
    svc = BankPostingService()
    rupee_inv, foreign_inv = _invoice(db, no="RUPEE"), _invoice(db, currency="USD", no="USD")
    ok = [
        _txn("Customer Payment", "sales_invoice", rupee_inv),                     # a rupee document
        _txn("Customer Payment", "sales_invoice", None),                          # matched to nothing
        _txn("Bank Charges", "sales_invoice", foreign_inv),                       # a category that settles no document
        _txn("Customer Payment", "purchase_bill", foreign_inv),                   # a kind the category does not settle
        _txn("Customer Payment", "sales_invoice", "NOT-IN-THESE-BOOKS"),          # a document that is not there: the settlement refuses it later
    ]
    for txn in ok:
        assert svc._assert_matched_document_is_in_rupees(db, FIRM, txn) is None, txn
    # and another client's foreign invoice is not read for this client's line
    other = _txn("Customer Payment", "sales_invoice", foreign_inv)
    other["client_id"] = "OTHER-CLIENT"
    assert svc._assert_matched_document_is_in_rupees(db, FIRM, other) is None


def test_the_post_and_the_preview_both_ask_before_anything_is_claimed_or_planned():
    post_src, preview_src = inspect.getsource(BankPostingService.post), inspect.getsource(BankPostingService.preview)
    assert post_src.index("_assert_matched_document_is_in_rupees") < post_src.index("self._plan(")
    assert post_src.index("_assert_matched_document_is_in_rupees") < post_src.index('.eq(\n                "match_status", prior_status)') \
        if '.eq(\n                "match_status", prior_status)' in post_src else True
    assert preview_src.index("_assert_matched_document_is_in_rupees") < preview_src.index("self._plan(")
