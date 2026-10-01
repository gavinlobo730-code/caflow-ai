"""The post-dated cheque register (accounting-21).

THE VERIFY LINE, AS A TEST: record a PDC dated next month and the books are
UNCHANGED; on the cheque date it shows as due; converting it creates ONE receipt
with the customer invoice settled exactly as a normal receipt settles it.

WHAT ELSE IS HELD HERE

  * A PDC is a MEMORANDUM. The register has no journal column and recording,
    editing and cancelling a cheque write nothing to the ledger, to a receipt, to
    a payment or to an invoice.
  * "Due" and "stale" are DERIVED from the cheque's date and today, never stored:
    due on the cheque's own date (not the day after), stale after three calendar
    months. Stale warns and never refuses.
  * Converting goes through the ONE receipt engine (a cheque received) and the ONE
    vendor-payment engine (a cheque issued) — the same two calls the bank match
    queue makes — and the books it produces are compared line for line with the
    books a receipt typed on the Receipts screen produces.
  * Conversion is claimed before it is performed: a second click makes no second
    receipt, and a refused engine call puts the cheque back to held.
  * Another client's party, bank account or document is reported as not found.
"""
from __future__ import annotations

import ast
import re
from datetime import date
from pathlib import Path

import pytest
from fastapi import HTTPException

from domain.banking import pdc as P

API = Path(__file__).resolve().parents[1]
WEB = API.parent / "web"
TODAY = date(2026, 11, 15)


# ═════════════════════════════════════════════════════════════════════════════
# THE RULE (pure)
# ═════════════════════════════════════════════════════════════════════════════

def test_a_cheque_is_due_on_its_own_date_not_the_day_after():
    assert not P.is_due("2026-11-16", TODAY)
    assert P.is_due("2026-11-15", TODAY)
    assert P.is_due("2026-11-14", TODAY)
    assert not P.is_due("not a date", TODAY)


def test_the_state_is_derived_and_only_a_held_cheque_can_be_due():
    assert P.state_of(P.HELD, "2026-12-01", TODAY) == P.NOT_DUE
    assert P.state_of(P.HELD, "2026-11-15", TODAY) == P.DUE
    assert P.state_of(P.CONVERTED, "2026-01-01", TODAY) == P.CONVERTED, \
        "a finished cheque is not 'due' because its date has passed"
    assert P.state_of(P.CANCELLED, "2026-01-01", TODAY) == P.CANCELLED


@pytest.mark.parametrize("cheque_date,last_good", [
    ("2026-11-15", "2027-02-15"),
    ("2026-08-31", "2026-11-30"),      # a month end clamps, it does not roll into December
    ("2026-11-30", "2027-02-28"),
    ("2023-11-30", "2024-02-29"),      # and a leap February keeps its 29th
])
def test_a_cheque_is_good_for_three_calendar_months(cheque_date, last_good):
    assert P.stale_after(cheque_date).isoformat() == last_good
    last = date.fromisoformat(last_good)
    assert not P.is_stale(cheque_date, last), "good on its last day"
    assert P.is_stale(cheque_date, date.fromordinal(last.toordinal() + 1)), "stale the day after"


def test_stale_is_a_warning_and_never_a_refusal():
    old = "2026-01-10"                                     # more than three months before TODAY
    assert P.is_stale(old, TODAY)
    assert P.conversion_problem(status=P.HELD, cheque_date=old, presented_on=TODAY,
                                today=TODAY) is None
    row = P.register_row({"status": P.HELD, "cheque_date": old, "direction": P.RECEIVED,
                          "amount_paise": 1, "cheque_no": "1"}, TODAY)
    assert row["is_stale"] and "three months" in row["stale_note"] and "[S]" in row["stale_note"]


def test_a_finished_cheque_is_never_called_stale():
    for status in (P.CONVERTED, P.CANCELLED):
        row = P.register_row({"status": status, "cheque_date": "2020-01-01",
                              "direction": P.RECEIVED, "amount_paise": 1, "cheque_no": "1"}, TODAY)
        assert row["is_stale"] is False and row["stale_note"] is None


def test_each_refusal_to_convert_says_its_own_thing():
    ok = dict(cheque_date="2026-11-15", presented_on=TODAY, today=TODAY)
    assert P.conversion_problem(status=P.HELD, **ok) is None
    sentences = {
        "early": P.conversion_problem(status=P.HELD, cheque_date="2026-12-01",
                                      presented_on=TODAY, today=TODAY),
        "before_own_date": P.conversion_problem(status=P.HELD, cheque_date="2026-11-10",
                                                presented_on=date(2026, 11, 9), today=TODAY),
        "future": P.conversion_problem(status=P.HELD, cheque_date="2026-11-10",
                                       presented_on=date(2026, 11, 20), today=TODAY),
        "converted": P.conversion_problem(status=P.CONVERTED, **ok),
        "cancelled": P.conversion_problem(status=P.CANCELLED, **ok),
    }
    assert all(sentences.values()), sentences
    assert len(set(sentences.values())) == 5, "five different problems, five different sentences"
    assert "not due until" in sentences["early"] and "2026-12-01" in sentences["early"]


def test_what_has_happened_outranks_what_is_merely_early():
    """A converted cheque dated in the future (a data slip) is reported as
    converted, which is the thing the CA can act on."""
    s = P.conversion_problem(status=P.CONVERTED, cheque_date="2027-06-01",
                             presented_on=TODAY, today=TODAY)
    assert "already been converted" in s


@pytest.mark.parametrize("direction,customer,vendor,ok", [
    (P.RECEIVED, "c", None, True), (P.ISSUED, None, "v", True),
    (P.RECEIVED, None, "v", False), (P.ISSUED, "c", None, False),
    (P.RECEIVED, "c", "v", False), (P.RECEIVED, None, None, False),
    ("exchanged", "c", None, False),
])
def test_a_received_cheque_names_a_customer_and_an_issued_one_a_supplier(direction, customer, vendor, ok):
    assert (P.party_problem(direction, customer, vendor) is None) is ok


def test_allocations_are_checked_for_shape_and_never_for_the_invoices_balance():
    inv = lambda i, p: {"sales_invoice_id": i, "allocated_paise": p}      # noqa: E731
    assert P.allocations_problem(P.RECEIVED, [inv("a", 600), inv("b", 400)], 1000) is None
    assert P.allocations_problem(P.RECEIVED, [], 1000) is None, "empty is money landing unallocated"
    assert "more than the cheque" in P.allocations_problem(P.RECEIVED, [inv("a", 1001)], 1000)
    assert "twice" in P.allocations_problem(P.RECEIVED, [inv("a", 1), inv("a", 2)], 1000)
    assert P.allocations_problem(P.RECEIVED, [inv("a", 0)], 1000)
    assert P.allocations_problem(P.RECEIVED, [inv("a", True)], 1000), "a bool is not an amount"
    assert P.allocations_problem(P.RECEIVED, [inv("a", 1.5)], 1000)
    # The right key for the direction: a bill is not an invoice.
    assert P.allocations_problem(P.ISSUED, [inv("a", 1)], 1000)
    assert P.allocations_problem(P.ISSUED, [{"purchase_bill_id": "b", "allocated_paise": 1}], 1000) is None


def test_the_engine_payload_is_what_the_bank_queue_hands_the_same_engines():
    row = {"direction": P.RECEIVED, "customer_id": "c1", "cheque_no": "  000  123 ",
           "cheque_date": "2026-11-10", "amount_paise": 5_000_000, "drawee_bank": " HDFC ",
           "bank_account_id": "ba1", "notes": "for Q2",
           "allocations": [{"sales_invoice_id": "i1", "allocated_paise": 5_000_000, "junk": 1}]}
    kind, data = P.engine_payload(row=row, presented_on=date(2026, 11, 15), client_id="cli")
    assert kind == P.RECEIVED
    assert data["receipt_date"] == "2026-11-15", "the day it was presented, not the date printed"
    assert data["payment_mode"] == "cheque" and data["reference_no"] == "000 123"
    assert data["tds_paise"] == 0 and data["bank_account_id"] == "ba1"
    assert data["allocations"] == [{"sales_invoice_id": "i1", "allocated_paise": 5_000_000}]
    assert "HDFC" in data["notes"] and "for Q2" in data["notes"] and "register" in data["notes"]
    pay_kind, pay = P.engine_payload(row={
        "direction": P.ISSUED, "vendor_id": "v1", "cheque_no": "9", "cheque_date": "2026-11-10",
        "amount_paise": 100, "allocations": [{"purchase_bill_id": "b1", "allocated_paise": 100}]},
        presented_on=date(2026, 11, 15), client_id="cli")
    assert pay_kind == P.ISSUED and pay["payment_date"] == "2026-11-15"
    assert pay["vendor_id"] == "v1" and "tds_paise" not in pay
    assert pay["allocations"] == [{"purchase_bill_id": "b1", "allocated_paise": 100}]


def test_the_register_lists_due_first_oldest_first_and_totals_in_paise():
    rows = [P.register_row(r, TODAY) for r in (
        {"status": P.HELD, "cheque_date": "2026-12-20", "cheque_no": "5", "direction": P.RECEIVED, "amount_paise": 500},
        {"status": P.HELD, "cheque_date": "2026-11-15", "cheque_no": "3", "direction": P.RECEIVED, "amount_paise": 300},
        {"status": P.HELD, "cheque_date": "2026-11-01", "cheque_no": "2", "direction": P.ISSUED, "amount_paise": 200},
        {"status": P.CONVERTED, "cheque_date": "2026-10-01", "cheque_no": "1", "direction": P.RECEIVED, "amount_paise": 100},
    )]
    rows.sort(key=P.sort_key)
    assert [r["cheque_no"] for r in rows] == ["2", "3", "5", "1"]
    s = P.summarise(rows)
    assert s[P.RECEIVED][P.DUE] == {"count": 1, "amount_paise": 300}
    assert s[P.RECEIVED][P.NOT_DUE] == {"count": 1, "amount_paise": 500}
    assert s[P.ISSUED][P.DUE] == {"count": 1, "amount_paise": 200}
    assert s[P.RECEIVED][P.CONVERTED] == {"count": 1, "amount_paise": 100}


# ═════════════════════════════════════════════════════════════════════════════
# THE SERVICE, against the e2e double and the REAL receipt and payment engines
# ═════════════════════════════════════════════════════════════════════════════

import routers.purchase_bills as pb                         # noqa: E402
import routers.purchase_payments as pp                      # noqa: E402
import routers.receipts as rc                               # noqa: E402
import routers.sales_invoices as si                         # noqa: E402
import services.purchase_payment_service as pps             # noqa: E402
import services.receipt_service as rs                       # noqa: E402
from models.invoices import (                               # noqa: E402
    InvoiceLineIn, PurchaseBillIn, PurchaseBillLineIn, PurchasePaymentAllocationIn,
    PurchasePaymentIn, ReceiptAllocationIn, ReceiptIn, SalesInvoiceIn)
from services import post_dated_cheque_service as svc       # noqa: E402
from tests.e2e_harness import (                             # noqa: E402
    FakeDB, account_balance, coa_id, seed_standard_coa, trial_balance, wire_e2e)

FIRM, CLI = "FIRM-A", "CLI"
CALLER = {"firm_id": FIRM, "id": "u-pdc-1", "auth_user_id": "auth-1",
          "email": "ca@f.test", "role": "Partner"}


def _book(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [si, rc, rs, pb, pp, pps])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("clients", {"id": CLI, "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5"})
    db.seed("customers", {"id": "CUST", "firm_id": FIRM, "client_id": CLI, "name": "Acme Buyer",
                          "state_code": "27", "gstin": "27XYZAB5678C1Z2", "is_active": True})
    db.seed("vendors", {"id": "VEND", "firm_id": FIRM, "client_id": CLI, "name": "Supplier Co",
                        "state_code": "27", "gstin": "27PQRST9012K1Z8", "pan": "PQRST9012K",
                        "is_active": True, "tds_applicable": False})
    seed_standard_coa(db, FIRM, CLI)
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": CLI,
                                  "name": "Consulting", "kind": "service"})
    return db


def _issued_invoice(n=1, rate=1_000_000):
    inv = si.create_invoice(SalesInvoiceIn(
        client_id=CLI, customer_id="CUST", invoice_date="2026-04-10", due_date="2026-05-10",
        invoice_no=f"PDC-INV-{n:03d}",
        lines=[InvoiceLineIn(service_catalogue_id="SVC-1", description="Consulting",
                             hsn_sac="9982", quantity=1, rate_paise=rate, gst_rate_percent=18.0)]),
        CALLER)["data"]
    assert si.issue_invoice(inv["id"], CALLER)["success"]
    return inv


def _received(db, invoice=None, *, no="000123", date_="2026-11-15", amount=1_180_000, **kw):
    allocations = ([{"sales_invoice_id": invoice["id"], "allocated_paise": amount}]
                   if invoice else [])
    return svc.create(db, FIRM, CLI, direction=P.RECEIVED, customer_id="CUST", vendor_id=None,
                      cheque_no=no, cheque_date=date_, amount_paise=amount,
                      drawee_bank=kw.get("drawee_bank", "HDFC Bank"),
                      bank_account_id=kw.get("bank_account_id"), allocations=allocations,
                      notes=kw.get("notes"), actor=CALLER, today=TODAY)


def _ledger(db):
    return (len(db.rows("journal_entries")), len(db.rows("journal_lines")),
            len(db.rows("receipts")), len(db.rows("purchase_payments")))


def test_recording_a_cheque_leaves_the_books_unchanged(monkeypatch):
    """THE VERIFY LINE'S FIRST HALF."""
    db = _book(monkeypatch)
    inv = _issued_invoice()
    before = _ledger(db)
    tb = trial_balance(db, FIRM, CLI)
    invoice_before = dict(next(r for r in db.rows("client_sales_invoices") if r["id"] == inv["id"]))

    cheque = _received(db, inv, date_="2026-12-15")          # dated next month

    assert _ledger(db) == before
    assert trial_balance(db, FIRM, CLI) == tb
    invoice_after = next(r for r in db.rows("client_sales_invoices") if r["id"] == inv["id"])
    assert (invoice_after["paid_paise"], invoice_after["status"]) == (
        invoice_before["paid_paise"], invoice_before["status"]), "no invoice is touched"
    assert cheque["state"] == P.NOT_DUE and cheque["status"] == P.HELD
    assert len(db.rows("post_dated_cheques")) == 1


def test_editing_and_cancelling_a_cheque_post_nothing_either(monkeypatch):
    db = _book(monkeypatch)
    inv = _issued_invoice()
    before = _ledger(db)
    c = _received(db, inv, date_="2026-12-15")
    svc.update(db, FIRM, CLI, c["id"], {"cheque_date": "2026-12-20", "notes": "moved"},
               actor=CALLER, today=TODAY)
    svc.cancel(db, FIRM, CLI, c["id"], "customer took it back", actor=CALLER, today=TODAY)
    assert _ledger(db) == before


def test_it_shows_as_due_on_its_date_and_not_the_day_before(monkeypatch):
    db = _book(monkeypatch)
    _received(db, None, no="1", date_="2026-11-15", amount=100)
    _received(db, None, no="2", date_="2026-11-16", amount=200)
    on_the_day = svc.list_register(db, FIRM, CLI, today=date(2026, 11, 15))
    assert {c["cheque_no"]: c["state"] for c in on_the_day["cheques"]} == {
        "1": P.DUE, "2": P.NOT_DUE}
    assert [c["cheque_no"] for c in on_the_day["cheques"]] == ["1", "2"], "due first"
    day_before = svc.list_register(db, FIRM, CLI, today=date(2026, 11, 14))
    assert {c["state"] for c in day_before["cheques"]} == {P.NOT_DUE}
    assert on_the_day["summary"][P.RECEIVED][P.DUE] == {"count": 1, "amount_paise": 100}


def test_the_register_names_the_party_and_reads_only_this_clients_cheques(monkeypatch):
    db = _book(monkeypatch)
    _received(db, None, no="1", amount=100)
    db.seed("post_dated_cheques", {
        "id": "OTHER", "firm_id": FIRM, "client_id": "CLI-2", "direction": P.RECEIVED,
        "customer_id": "X", "cheque_no": "99", "cheque_date": "2026-11-01", "amount_paise": 9,
        "allocations": [], "status": P.HELD})
    out = svc.list_register(db, FIRM, CLI, today=TODAY)
    assert [c["cheque_no"] for c in out["cheques"]] == ["1"]
    assert out["cheques"][0]["party_name"] == "Acme Buyer"


def test_only_held_cheques_are_read_unless_the_finished_ones_are_asked_for(monkeypatch):
    db = _book(monkeypatch)
    keep = _received(db, None, no="1", amount=100)
    gone = _received(db, None, no="2", amount=200)
    svc.cancel(db, FIRM, CLI, gone["id"], None, actor=CALLER, today=TODAY)
    assert [c["cheque_no"] for c in svc.list_register(db, FIRM, CLI, today=TODAY)["cheques"]] == ["1"]
    everything = svc.list_register(db, FIRM, CLI, today=TODAY, include_finished=True)
    assert {c["cheque_no"]: c["state"] for c in everything["cheques"]} == {
        "1": P.DUE, "2": P.CANCELLED}
    assert keep["id"]


def _journal_shape(db, journal_id):
    """The ledger effect of one entry, independent of ids, dates and numbers."""
    lines = [ln for ln in db.rows("journal_lines") if ln["journal_entry_id"] == journal_id]
    accounts = {a["id"]: a.get("account_name") or a.get("name") for a in db.rows("chart_of_accounts")}
    return sorted((accounts.get(ln["account_id"]), int(ln.get("debit_paise") or 0),
                   int(ln.get("credit_paise") or 0)) for ln in lines)


def test_converting_a_due_cheque_makes_one_receipt_settled_exactly_as_a_normal_receipt_is(monkeypatch):
    """THE VERIFY LINE'S SECOND HALF. Two identical invoices; one is settled by a
    receipt typed the ordinary way, the other by converting a cheque. The books
    each leaves must be the same, line for line."""
    db = _book(monkeypatch)
    normal_inv = _issued_invoice(1)
    cheque_inv = _issued_invoice(2)
    cheque = _received(db, cheque_inv, no="000123", date_="2026-11-15", notes="Q2 fee")
    receipts_before = len(db.rows("receipts"))

    normal = rc.create_receipt(ReceiptIn(
        client_id=CLI, customer_id="CUST", receipt_date="2026-11-15", amount_paise=1_180_000,
        payment_mode="cheque", reference_no="000123",
        allocations=[ReceiptAllocationIn(sales_invoice_id=normal_inv["id"],
                                         allocated_paise=1_180_000)]), CALLER)["data"]
    converted = svc.convert(db, FIRM, CLI, cheque["id"], actor=CALLER, today=TODAY)

    assert len(db.rows("receipts")) == receipts_before + 2, "one receipt each, not two for the cheque"
    doc = converted["document"]
    assert doc["kind"] == "receipt" and doc["number"] and doc["journal_entry_id"]

    # The invoice is settled exactly as a normal receipt settles it.
    inv = {r["id"]: r for r in db.rows("client_sales_invoices")}
    for a, b in ((normal_inv["id"], cheque_inv["id"]),):
        assert (inv[a]["paid_paise"], inv[a]["status"]) == (inv[b]["paid_paise"], inv[b]["status"]) \
            == (1_180_000, "paid")
    # ... and so is the ledger: same accounts, same debits, same credits.
    assert _journal_shape(db, doc["journal_entry_id"]) == _journal_shape(db, normal["journal_entry_id"])
    shape = _journal_shape(db, doc["journal_entry_id"])
    assert sum(d for _, d, _ in shape) == sum(c for _, _, c in shape) == 1_180_000
    # The receipt says where it came from and carries the cheque's own number.
    receipt = next(r for r in db.rows("receipts") if r["id"] == doc["id"])
    assert receipt["payment_mode"] == "cheque" and receipt["reference_no"] == "000123"
    assert receipt["amount_paise"] == 1_180_000 and receipt["receipt_date"] == "2026-11-15"
    assert "post-dated cheque register" in receipt["notes"] and "Q2 fee" in receipt["notes"]
    # And the cheque records which receipt it became.
    row = next(r for r in db.rows("post_dated_cheques") if r["id"] == cheque["id"])
    assert row["status"] == P.CONVERTED and row["converted_receipt_id"] == doc["id"]
    assert row["converted_payment_id"] is None and row["converted_by"] == "u-pdc-1"
    assert converted["cheque"]["state"] == P.CONVERTED


def test_the_receipt_is_dated_the_day_it_was_presented_not_the_day_it_was_written(monkeypatch):
    db = _book(monkeypatch)
    c = _received(db, None, no="7", date_="2026-11-10", amount=500_000)
    out = svc.convert(db, FIRM, CLI, c["id"], presented_on="2026-11-13", actor=CALLER, today=TODAY)
    receipt = next(r for r in db.rows("receipts") if r["id"] == out["document"]["id"])
    assert receipt["receipt_date"] == "2026-11-13" == out["document"]["date"]


def test_a_cheque_with_no_allocations_lands_as_an_unallocated_receipt(monkeypatch):
    db = _book(monkeypatch)
    c = _received(db, None, no="8", amount=500_000)
    out = svc.convert(db, FIRM, CLI, c["id"], actor=CALLER, today=TODAY)
    assert out["document"]["unallocated_paise"] == 500_000
    assert account_balance(db, coa_id(db, FIRM, "bank")) == 500_000


def test_converting_twice_makes_one_receipt(monkeypatch):
    db = _book(monkeypatch)
    inv = _issued_invoice()
    c = _received(db, inv)
    svc.convert(db, FIRM, CLI, c["id"], actor=CALLER, today=TODAY)
    entries, receipts = len(db.rows("journal_entries")), len(db.rows("receipts"))
    with pytest.raises(HTTPException) as e:
        svc.convert(db, FIRM, CLI, c["id"], actor=CALLER, today=TODAY)
    assert e.value.status_code == 409 and "already been converted" in e.value.detail
    assert (len(db.rows("journal_entries")), len(db.rows("receipts"))) == (entries, receipts)


class _Spy:
    """A client that delegates to the double and remembers which tables it was
    asked about, so a test can say which CLIENT a piece of work went through."""

    def __init__(self, inner):
        self._inner, self.tables = inner, []

    def table(self, name):
        self.tables.append(name)
        return self._inner.table(name)

    def __getattr__(self, name):                      # rpc, and anything else the engine probes
        return getattr(self._inner, name)


def test_the_engine_runs_on_the_engine_client_and_only_the_register_on_the_privileged_one(monkeypatch):
    """Conversion uses TWO clients on purpose: the privileged one for the register's
    own table (its writes are service-role-only by grant) and the request-scoped one
    for the receipt engine, so row-level security applies to a converted cheque
    exactly as it does to a receipt typed on the Receipts screen."""
    db = _book(monkeypatch)
    inv = _issued_invoice()
    c = _received(db, inv)
    privileged, engine = _Spy(db), _Spy(db)

    svc.convert(privileged, FIRM, CLI, c["id"], actor=CALLER, today=TODAY, engine_db=engine)

    assert "post_dated_cheques" in privileged.tables
    assert "post_dated_cheques" not in engine.tables, "the engine's client never touches the register"
    assert {"customers", "client_sales_invoices"} <= set(engine.tables), (
        "the receipt engine did its work through the engine client")
    assert not ({"customers", "client_sales_invoices", "receipts"} & set(privileged.tables)), (
        "and the privileged client was not used for the books")
    assert len(db.rows("receipts")) == 1


def test_the_door_hands_the_engine_the_request_scoped_client(monkeypatch):
    db = _book(monkeypatch)
    inv = _issued_invoice()
    c = _received(db, inv)
    http = _http(monkeypatch, db=db)
    request_scoped = _Spy(db)
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: request_scoped)
    seen = {}
    real = svc.convert

    def spy(*a, **k):
        seen.update(k)
        return real(*a, **k)
    monkeypatch.setattr(svc, "convert", spy)

    r = http.post(f"/api/post-dated-cheques/{c['id']}/convert", json={"client_id": CLI})

    assert r.status_code == 200, r.text
    assert seen["engine_db"] is request_scoped
    assert "customers" in request_scoped.tables


def test_the_claim_and_not_the_precheck_is_what_stops_a_second_receipt(monkeypatch):
    """Two clicks in one instant both READ the cheque as held, so the pre-check
    cannot be what saves the second one. Simulate exactly that — the pre-check
    sees a held cheque both times — and the compare-and-set on status must still
    let only one of them reach the engine."""
    db = _book(monkeypatch)
    inv = _issued_invoice()
    c = _received(db, inv)
    real_get = svc._get
    stale_read = dict(real_get(db, FIRM, CLI, c["id"]))        # what both clicks read: held
    monkeypatch.setattr(svc, "_get", lambda *_a, **_k: dict(stale_read))

    svc.convert(db, FIRM, CLI, c["id"], actor=CALLER, today=TODAY)          # the winner
    receipts = len(db.rows("receipts"))
    with pytest.raises(HTTPException) as e:
        svc.convert(db, FIRM, CLI, c["id"], actor=CALLER, today=TODAY)      # the loser
    assert e.value.status_code == 409 and "just been converted" in e.value.detail
    assert len(db.rows("receipts")) == receipts == 1


def test_a_cheque_not_yet_due_is_refused_and_posts_nothing(monkeypatch):
    db = _book(monkeypatch)
    inv = _issued_invoice()
    c = _received(db, inv, date_="2026-12-15")
    before = _ledger(db)
    with pytest.raises(HTTPException) as e:
        svc.convert(db, FIRM, CLI, c["id"], actor=CALLER, today=TODAY)
    assert e.value.status_code == 409 and "not due until" in e.value.detail
    assert _ledger(db) == before
    assert next(r for r in db.rows("post_dated_cheques"))["status"] == P.HELD


def test_a_presentation_date_before_the_cheque_or_in_the_future_is_refused(monkeypatch):
    db = _book(monkeypatch)
    c = _received(db, None, date_="2026-11-10", amount=100)
    for bad in ("2026-11-09", "2026-11-20"):
        with pytest.raises(HTTPException) as e:
            svc.convert(db, FIRM, CLI, c["id"], presented_on=bad, actor=CALLER, today=TODAY)
        assert e.value.status_code == 409
    assert db.rows("receipts") == []


def test_an_engine_that_refuses_puts_the_cheque_back_to_held(monkeypatch):
    """The invoice was settled some other way between recording and conversion, so
    the engine's own live-outstanding check refuses; nothing is posted and the CA
    can fix the cause and try again."""
    db = _book(monkeypatch)
    inv = _issued_invoice()
    c = _received(db, inv)
    # A normal receipt settles the invoice first.
    assert rc.create_receipt(ReceiptIn(
        client_id=CLI, customer_id="CUST", receipt_date="2026-11-01", amount_paise=1_180_000,
        allocations=[ReceiptAllocationIn(sales_invoice_id=inv["id"], allocated_paise=1_180_000)]),
        CALLER)["success"]
    before = _ledger(db)
    with pytest.raises(HTTPException) as e:
        svc.convert(db, FIRM, CLI, c["id"], actor=CALLER, today=TODAY)
    assert e.value.status_code == 422
    assert _ledger(db) == before, "the refused conversion posted nothing"
    row = next(r for r in db.rows("post_dated_cheques") if r["id"] == c["id"])
    assert row["status"] == P.HELD and row["converted_at"] is None and row["converted_by"] is None
    assert row.get("converted_receipt_id") is None


def test_a_stale_cheque_converts_and_carries_its_warning(monkeypatch):
    db = _book(monkeypatch)
    c = _received(db, None, no="old", date_="2026-01-10", amount=100_000)
    out = svc.convert(db, FIRM, CLI, c["id"], actor=CALLER, today=TODAY)
    assert out["document"]["id"] and "three months" in out["stale_note"]


def test_a_period_the_engine_has_closed_refuses_a_conversion_exactly_as_it_refuses_a_receipt(monkeypatch):
    """The lock is the engine's to ask, at the presented date — so it is the same
    refusal and the cheque goes back to held."""
    db = _book(monkeypatch)
    c = _received(db, None, no="9", amount=100_000)

    def closed(*_a, **_k):
        raise HTTPException(status_code=422, detail="The financial year is locked.")
    monkeypatch.setattr(rs.period_validation_service, "validate_posting_date", closed)
    with pytest.raises(HTTPException) as e:
        svc.convert(db, FIRM, CLI, c["id"], actor=CALLER, today=TODAY)
    assert "locked" in e.value.detail
    assert db.rows("receipts") == []
    assert next(r for r in db.rows("post_dated_cheques"))["status"] == P.HELD


# ── a cheque ISSUED ──────────────────────────────────────────────────────────

def _received_bill(n=1, rate=10_000_000):
    bill = pb.create_purchase_bill(PurchaseBillIn(
        client_id=CLI, vendor_id="VEND", bill_date="2026-04-05", bill_no=f"V-{n:03d}",
        lines=[PurchaseBillLineIn(service_catalogue_id="SVC-1", description="Audit services",
                                  hsn_sac="9982", quantity=1, rate_paise=rate,
                                  gst_rate_percent=18.0)]), CALLER)["data"]
    assert pb.receive_purchase_bill(bill["id"], CALLER)["success"]
    return bill


def test_an_issued_cheque_converts_into_one_vendor_payment_settled_like_a_normal_one(monkeypatch):
    db = _book(monkeypatch)
    normal_bill, cheque_bill = _received_bill(1), _received_bill(2)
    amount = cheque_bill["net_payable_paise"]
    cheque = svc.create(
        db, FIRM, CLI, direction=P.ISSUED, customer_id=None, vendor_id="VEND", cheque_no="55001",
        cheque_date="2026-11-15", amount_paise=amount, drawee_bank=None, bank_account_id=None,
        allocations=[{"purchase_bill_id": cheque_bill["id"], "allocated_paise": amount}],
        notes=None, actor=CALLER, today=TODAY)
    before = _ledger(db)
    assert before[3] == 0, "recording the cheque made no payment"

    normal = pp.create_purchase_payment(PurchasePaymentIn(
        client_id=CLI, vendor_id="VEND", payment_date="2026-11-15", amount_paise=amount,
        payment_mode="cheque", reference_no="55001",
        allocations=[PurchasePaymentAllocationIn(purchase_bill_id=normal_bill["id"],
                                                 allocated_paise=amount)]), CALLER)["data"]
    out = svc.convert(db, FIRM, CLI, cheque["id"], actor=CALLER, today=TODAY)

    assert len(db.rows("purchase_payments")) == 2
    doc = out["document"]
    assert doc["kind"] == "payment" and doc["journal_entry_id"]
    assert _journal_shape(db, doc["journal_entry_id"]) == _journal_shape(db, normal["journal_entry_id"])
    bills = {r["id"]: r for r in db.rows("purchase_bills")}
    assert (bills[cheque_bill["id"]]["paid_paise"], bills[cheque_bill["id"]]["status"]) == (
        bills[normal_bill["id"]]["paid_paise"], bills[normal_bill["id"]]["status"])
    payment = next(r for r in db.rows("purchase_payments") if r["id"] == doc["id"])
    assert payment["payment_mode"] == "cheque" and payment["reference_no"] == "55001"
    row = next(r for r in db.rows("post_dated_cheques") if r["id"] == cheque["id"])
    assert row["converted_payment_id"] == doc["id"] and row["converted_receipt_id"] is None


# ── what may be recorded ─────────────────────────────────────────────────────

def test_the_same_cheque_number_twice_for_one_party_is_refused_and_a_cancelled_one_frees_it(monkeypatch):
    db = _book(monkeypatch)
    first = _received(db, None, no="000123", amount=100)
    with pytest.raises(HTTPException) as e:
        _received(db, None, no=" 000123 ", amount=100)
    assert e.value.status_code == 409 and "already on the register" in e.value.detail
    svc.cancel(db, FIRM, CLI, first["id"], None, actor=CALLER, today=TODAY)
    assert _received(db, None, no="000123", amount=100)["status"] == P.HELD


def test_the_party_a_bank_account_and_a_document_of_another_client_are_not_found(monkeypatch):
    db = _book(monkeypatch)
    db.seed("customers", {"id": "CUST-X", "firm_id": FIRM, "client_id": "CLI-2", "name": "Elsewhere"})
    db.seed("bank_accounts", {"id": "BA-X", "firm_id": FIRM, "client_id": "CLI-2", "bank_name": "X"})
    foreign_inv = db.seed("client_sales_invoices", {
        "firm_id": FIRM, "client_id": "CLI-2", "customer_id": "CUST-X", "invoice_no": "X/1",
        "status": "issued", "total_paise": 100})
    kw = dict(direction=P.RECEIVED, vendor_id=None, cheque_no="1", cheque_date="2026-11-15",
              amount_paise=100, drawee_bank=None, bank_account_id=None, allocations=[],
              notes=None, actor=CALLER, today=TODAY)
    with pytest.raises(HTTPException) as e:
        svc.create(db, FIRM, CLI, customer_id="CUST-X", **kw)
    assert e.value.status_code == 404 and e.value.detail == "Customer not found."
    with pytest.raises(HTTPException) as e:
        svc.create(db, FIRM, CLI, customer_id="CUST", **{**kw, "bank_account_id": "BA-X"})
    assert e.value.status_code == 404 and e.value.detail == "Bank account not found."
    with pytest.raises(HTTPException) as e:
        svc.create(db, FIRM, CLI, customer_id="CUST", **{
            **kw, "allocations": [{"sales_invoice_id": foreign_inv["id"], "allocated_paise": 100}]})
    assert e.value.status_code == 422 and "not part of this client's books" in e.value.detail
    assert db.rows("post_dated_cheques") == []


def test_a_cheques_documents_must_belong_to_its_own_party(monkeypatch):
    db = _book(monkeypatch)
    inv = _issued_invoice()
    db.seed("customers", {"id": "CUST-2", "firm_id": FIRM, "client_id": CLI, "name": "Other Buyer"})
    with pytest.raises(HTTPException) as e:
        svc.create(db, FIRM, CLI, direction=P.RECEIVED, customer_id="CUST-2", vendor_id=None,
                   cheque_no="1", cheque_date="2026-11-15", amount_paise=1_180_000,
                   drawee_bank=None, bank_account_id=None,
                   allocations=[{"sales_invoice_id": inv["id"], "allocated_paise": 1_180_000}],
                   notes=None, actor=CALLER, today=TODAY)
    assert e.value.status_code == 422 and "somebody else" in e.value.detail


def test_a_cheque_for_the_wrong_kind_of_party_is_refused_in_words(monkeypatch):
    db = _book(monkeypatch)
    with pytest.raises(HTTPException) as e:
        svc.create(db, FIRM, CLI, direction=P.RECEIVED, customer_id=None, vendor_id="VEND",
                   cheque_no="1", cheque_date="2026-11-15", amount_paise=100, drawee_bank=None,
                   bank_account_id=None, allocations=[], notes=None, actor=CALLER, today=TODAY)
    assert e.value.status_code == 422 and "customer" in e.value.detail


@pytest.mark.parametrize("field,value,fragment", [
    ("cheque_no", "   ", "needs its number"),
    ("cheque_date", "next month", "date written on it"),
    ("amount_paise", 0, "positive"),
    ("amount_paise", -5, "positive"),
    ("amount_paise", True, "positive"),
])
def test_a_cheque_with_no_number_date_or_amount_is_refused(monkeypatch, field, value, fragment):
    db = _book(monkeypatch)
    kw = dict(direction=P.RECEIVED, customer_id="CUST", vendor_id=None, cheque_no="1",
              cheque_date="2026-11-15", amount_paise=100, drawee_bank=None,
              bank_account_id=None, allocations=[], notes=None, actor=CALLER, today=TODAY)
    kw[field] = value
    with pytest.raises(HTTPException) as e:
        svc.create(db, FIRM, CLI, **kw)
    assert e.value.status_code == 422 and fragment in e.value.detail
    assert db.rows("post_dated_cheques") == []


def test_a_converted_cheque_can_be_neither_edited_nor_cancelled(monkeypatch):
    db = _book(monkeypatch)
    c = _received(db, None, no="1", amount=100_000)
    svc.convert(db, FIRM, CLI, c["id"], actor=CALLER, today=TODAY)
    with pytest.raises(HTTPException) as e:
        svc.update(db, FIRM, CLI, c["id"], {"notes": "x"}, actor=CALLER, today=TODAY)
    assert e.value.status_code == 409
    with pytest.raises(HTTPException) as e:
        svc.cancel(db, FIRM, CLI, c["id"], None, actor=CALLER, today=TODAY)
    assert e.value.status_code == 409 and "reverse that document" in e.value.detail


def test_editing_changes_only_what_was_sent_and_never_the_party_or_direction(monkeypatch):
    db = _book(monkeypatch)
    c = _received(db, None, no="1", date_="2026-12-15", amount=100_000, drawee_bank="HDFC Bank")
    out = svc.update(db, FIRM, CLI, c["id"], {"cheque_date": "2026-12-20"}, actor=CALLER, today=TODAY)
    row = next(r for r in db.rows("post_dated_cheques") if r["id"] == c["id"])
    assert (row["cheque_date"], row["amount_paise"], row["drawee_bank"], row["cheque_no"]) == (
        "2026-12-20", 100_000, "HDFC Bank", "1")
    assert (row["direction"], row["customer_id"], row["vendor_id"]) == (P.RECEIVED, "CUST", None)
    assert out["cheque_date"] == "2026-12-20"


def test_a_cheque_from_another_client_is_not_found_for_every_act(monkeypatch):
    db = _book(monkeypatch)
    c = _received(db, None, no="1", amount=100_000)
    for act in (
        lambda: svc.update(db, FIRM, "CLI-2", c["id"], {"notes": "x"}, actor=CALLER),
        lambda: svc.cancel(db, FIRM, "CLI-2", c["id"], None, actor=CALLER),
        lambda: svc.convert(db, FIRM, "CLI-2", c["id"], actor=CALLER, today=TODAY),
        lambda: svc.update(db, "FIRM-B", CLI, c["id"], {"notes": "x"}, actor=CALLER),
    ):
        with pytest.raises(HTTPException) as e:
            act()
        assert e.value.status_code == 404 and e.value.detail == "Cheque not found."
    assert db.rows("receipts") == []


def test_a_held_row_says_up_front_when_no_bank_account_is_named(monkeypatch):
    db = _book(monkeypatch)
    db.seed("bank_accounts", {"id": "BA-1", "firm_id": FIRM, "client_id": CLI, "bank_name": "HDFC"})
    _received(db, None, no="1", amount=100)
    _received(db, None, no="2", amount=100, bank_account_id="BA-1")
    rows = {c["cheque_no"]: c for c in svc.list_register(db, FIRM, CLI, today=TODAY)["cheques"]}
    assert rows["1"]["posting_account_notice"] and "general Bank ledger" in rows["1"]["posting_account_notice"]
    assert rows["2"]["posting_account_notice"] is None, "present and null where it is attributable"


def test_the_form_offers_active_parties_masked_bank_accounts_and_only_open_documents(monkeypatch):
    db = _book(monkeypatch)
    open_inv = _issued_invoice(1)
    settled = _issued_invoice(2)
    part = _issued_invoice(3)
    assert rc.create_receipt(ReceiptIn(
        client_id=CLI, customer_id="CUST", receipt_date="2026-05-01", amount_paise=1_180_000,
        allocations=[ReceiptAllocationIn(sales_invoice_id=settled["id"],
                                         allocated_paise=1_180_000)]), CALLER)["success"]
    assert rc.create_receipt(ReceiptIn(
        client_id=CLI, customer_id="CUST", receipt_date="2026-05-01", amount_paise=400_000,
        allocations=[ReceiptAllocationIn(sales_invoice_id=part["id"],
                                         allocated_paise=400_000)]), CALLER)["success"]
    si.create_invoice(SalesInvoiceIn(                      # a DRAFT: never issued
        client_id=CLI, customer_id="CUST", invoice_date="2026-04-10", invoice_no="PDC-DRAFT",
        lines=[InvoiceLineIn(service_catalogue_id="SVC-1", description="x", hsn_sac="9982",
                             quantity=1, rate_paise=100, gst_rate_percent=18.0)]), CALLER)
    db.seed("customers", {"id": "CUST-OFF", "firm_id": FIRM, "client_id": CLI, "name": "Dormant",
                          "is_active": False})
    db.seed("customers", {"id": "CUST-X", "firm_id": FIRM, "client_id": "CLI-2", "name": "Elsewhere",
                          "is_active": True})
    db.seed("bank_accounts", {"id": "BA-1", "firm_id": FIRM, "client_id": CLI, "bank_name": "HDFC",
                              "account_no": "50100123456789", "is_active": True})
    db.seed("bank_accounts", {"id": "BA-X", "firm_id": FIRM, "client_id": "CLI-2", "bank_name": "SBI",
                              "account_no": "1", "is_active": True})

    out = svc.options(db, FIRM, CLI, P.RECEIVED, "CUST")

    assert [p["name"] for p in out["parties"]] == ["Acme Buyer"], \
        "active parties of THIS client only"
    assert out["bank_accounts"] == [{"id": "BA-1", "name": "HDFC ····6789"}], \
        "another client's account is not offered and the number is masked"
    owed = {d["id"]: d["outstanding_paise"] for d in out["documents"]}
    assert owed == {open_inv["id"]: 1_180_000, part["id"]: 780_000}, (
        "the settled invoice and the draft are not offered; the part-paid one shows what is LEFT")
    assert svc.options(db, FIRM, CLI, P.RECEIVED)["documents"] == [], "no party, no documents"


def test_the_form_offers_a_suppliers_open_bills_for_an_issued_cheque(monkeypatch):
    db = _book(monkeypatch)
    bill = _received_bill(1)
    out = svc.options(db, FIRM, CLI, P.ISSUED, "VEND")
    assert [p["name"] for p in out["parties"]] == ["Supplier Co"]
    assert [(d["id"], d["outstanding_paise"]) for d in out["documents"]] == [
        (bill["id"], bill["net_payable_paise"])]
    with pytest.raises(HTTPException):
        svc.options(db, FIRM, CLI, "exchanged")


# ═════════════════════════════════════════════════════════════════════════════
# THE DOOR
# ═════════════════════════════════════════════════════════════════════════════

from fastapi import FastAPI                                  # noqa: E402
from fastapi.testclient import TestClient                    # noqa: E402

import routers.post_dated_cheques as door                    # noqa: E402
from core.auth import get_current_user                       # noqa: E402

REVIEWER = {**CALLER, "role": "Reviewer"}


def _http(monkeypatch, user=CALLER, *, db="x"):
    app = FastAPI()
    app.include_router(door.router)
    app.dependency_overrides[get_current_user] = lambda: user
    if db is None:
        monkeypatch.delenv("SUPABASE_URL", raising=False)
    else:
        monkeypatch.setenv("SUPABASE_URL", "test://db")
        monkeypatch.setattr("core.supabase_client.get_service_supabase", lambda: db)
    monkeypatch.setattr(svc, "ist_today", lambda: TODAY)
    return TestClient(app, raise_server_exceptions=False)


def test_no_database_is_a_503_not_a_silent_empty_register(monkeypatch):
    r = _http(monkeypatch, db=None).get("/api/post-dated-cheques", params={"client_id": CLI})
    assert r.status_code == 503


def test_a_malformed_date_is_a_422_at_the_door(monkeypatch):
    db = _book(monkeypatch)
    http = _http(monkeypatch, db=db)
    assert http.post("/api/post-dated-cheques/x/convert",
                     json={"client_id": CLI, "presented_on": "yesterday"}).status_code == 422
    assert http.post("/api/post-dated-cheques", json={
        "client_id": CLI, "direction": "received", "customer_id": "CUST", "cheque_no": "1",
        "cheque_date": "15/11/2026", "amount_paise": 100}).status_code == 422
    assert http.post("/api/post-dated-cheques", json={
        "client_id": CLI, "direction": "received", "customer_id": "CUST", "cheque_no": "1",
        "cheque_date": "2026-11-15", "amount_paise": 0}).status_code == 422


def test_the_door_records_lists_converts_and_cancels(monkeypatch):
    db = _book(monkeypatch)
    inv = _issued_invoice()
    http = _http(monkeypatch, db=db)
    made = http.post("/api/post-dated-cheques", json={
        "client_id": CLI, "direction": "received", "customer_id": "CUST", "cheque_no": "42",
        "cheque_date": "2026-11-01", "amount_paise": 1_180_000, "drawee_bank": "ICICI",
        "allocations": [{"sales_invoice_id": inv["id"], "allocated_paise": 1_180_000}]})
    assert made.status_code == 200, made.text
    cheque = made.json()["data"]
    listed = http.get("/api/post-dated-cheques", params={"client_id": CLI}).json()["data"]
    assert [c["id"] for c in listed["cheques"]] == [cheque["id"]]
    assert listed["cheques"][0]["state"] == "due"
    done = http.post(f"/api/post-dated-cheques/{cheque['id']}/convert", json={"client_id": CLI})
    assert done.status_code == 200, done.text
    assert done.json()["data"]["document"]["kind"] == "receipt"
    again = http.post(f"/api/post-dated-cheques/{cheque['id']}/convert", json={"client_id": CLI})
    assert again.status_code == 409
    gone = http.post(f"/api/post-dated-cheques/{cheque['id']}/cancel", json={"client_id": CLI})
    assert gone.status_code == 409
    patched = http.patch(f"/api/post-dated-cheques/{cheque['id']}",
                         json={"client_id": CLI, "notes": "late"})
    assert patched.status_code == 409


def test_a_reviewer_may_neither_read_record_nor_convert(monkeypatch):
    """accounting:read is Executive and above and everything that changes the
    register is accounting:write, so a Reviewer is refused at the dependency —
    before any handler, and before the database is touched."""
    http = _http(monkeypatch, REVIEWER, db=_book(monkeypatch))
    assert http.get("/api/post-dated-cheques", params={"client_id": CLI}).status_code == 403
    assert http.get("/api/post-dated-cheques/options",
                    params={"client_id": CLI, "direction": "received"}).status_code == 403
    body = {"client_id": CLI}
    assert http.post("/api/post-dated-cheques", json={
        **body, "direction": "received", "customer_id": "CUST", "cheque_no": "1",
        "cheque_date": "2026-11-15", "amount_paise": 100}).status_code == 403
    assert http.post("/api/post-dated-cheques/x/convert", json=body).status_code == 403
    assert http.post("/api/post-dated-cheques/x/cancel", json=body).status_code == 403
    assert http.patch("/api/post-dated-cheques/x", json=body).status_code == 403


# ═════════════════════════════════════════════════════════════════════════════
# THE RULES, READ OFF THE SOURCE
# ═════════════════════════════════════════════════════════════════════════════

def _calls_and_imports(path: Path):
    tree = ast.parse(path.read_text())
    imported = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module:
            imported.add(n.module)
            imported.update(f"{n.module}.{a.name}" for a in n.names)
        elif isinstance(n, ast.Import):
            imported.update(a.name for a in n.names)
    called = {n.func.attr for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    called |= {n.func.id for n in ast.walk(tree)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    return tree, imported, called


_FILES = [API / "services" / "post_dated_cheque_service.py",
          API / "routers" / "post_dated_cheques.py",
          API / "domain" / "banking" / "pdc.py"]


@pytest.mark.parametrize("path", _FILES, ids=lambda p: p.name)
def test_there_is_no_second_posting_path(path):
    """The register reaches the books ONLY through the two engines. It imports no
    journal writer and calls none, however the call is spelled."""
    _tree, imported, called = _calls_and_imports(path)
    assert not {m for m in imported if "phase2_journal" in m or "journal_posting" in m}, imported
    assert not (called & {"_create_journal", "post_journal_atomic", "journal_for_receipt",
                          "journal_for_payment", "settle_receipt_atomic", "rpc"}), called


def test_conversion_calls_exactly_the_two_engines_and_writes_only_its_own_table():
    tree, _imported, called = _calls_and_imports(_FILES[0])
    assert {"create_receipt_core", "create_payment_core"} <= called
    written = {ast.unparse(n.func.value.args[0]) for n in ast.walk(tree)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr in {"insert", "update", "delete", "upsert"}
               and isinstance(n.func.value, ast.Call) and n.func.value.args}
    assert written == {"'post_dated_cheques'"}, (
        "the register writes its own table and nothing else: a receipt, a payment, "
        f"an invoice or a journal is the engines' to write — {written}")


def test_the_conversion_is_claimed_before_the_engine_is_called():
    """The order is the rule: the compare-and-set on status comes first, so two
    clicks cannot each reach the engine."""
    fn = next(n for n in ast.parse(_FILES[0].read_text()).body
              if isinstance(n, ast.FunctionDef) and n.name == "convert")
    src = ast.unparse(fn)
    assert src.index("P.CONVERTED") < src.index("create_receipt_core"), "claim first"
    assert '.eq("status", P.HELD)' in src.replace("'", '"')


def test_the_table_has_no_journal_column_in_its_migration():
    sql = (API / "migrations" / "460_a_post_dated_cheque_is_a_memo_until_it_is_presented.sql").read_text()
    body = re.sub(r"--[^\n]*", "", sql)
    create = body[body.index("CREATE TABLE IF NOT EXISTS public.post_dated_cheques"):]
    create = create[:create.index(");")]
    assert "journal" not in create.lower()


def test_the_router_is_mounted_behind_the_client_guard():
    src = (API / "main.py").read_text()
    assert re.search(r"include_router\(post_dated_cheques_router,\s*dependencies=_CLIENT_GUARD\)", src)


def test_the_reconciling_of_receipts_is_unchanged_by_the_register():
    """The engines are not edited to know about a cheque: no module under services
    other than the register itself mentions the register's table."""
    offenders = [p.name for p in (API / "services").glob("*.py")
                 if "post_dated_cheques" in p.read_text() and p.name != "post_dated_cheque_service.py"]
    assert offenders == []


# ═════════════════════════════════════════════════════════════════════════════
# THE BROWSER DECIDES NOTHING — held from this side
# ═════════════════════════════════════════════════════════════════════════════

_PANEL = WEB / "components" / "banking" / "PostDatedChequesPanel.tsx"


def _code(path: Path) -> str:
    src = path.read_text()
    src = re.sub(r"/\*[\s\S]*?\*/", "", src)
    return re.sub(r"(^|[^:])//.*$", r"\1", src, flags=re.M)


def test_the_screen_asks_the_server_whether_a_cheque_is_due_or_stale():
    """Whether a cheque is due is the server's answer (`state`, `is_due`,
    `is_stale`): a browser that compared dates itself would use the browser's
    clock, which is not the firm's (IST) day."""
    src = _code(_PANEL)
    assert not re.search(r"new Date\(|Date\.now|todayLocalISO", src), \
        "the panel must not compare a cheque's date with a clock of its own"
    assert "is_due" in src or "state" in src


def test_the_panel_reaches_the_api_only_through_the_cheque_namespace():
    src = _code(_PANEL)
    calls = set(re.findall(r"\bapi\.(\w+)\.(\w+)\(", src))
    assert calls and all(ns == "postDatedCheques" for ns, _ in calls), calls
    assert not re.search(r"\bfetch\(|\.from\(|supabase", src)
    assert not re.search(r"createReceipt|receipts\.|purchasePayments", src), \
        "conversion is a server act: the panel never builds a receipt itself"


def test_the_screen_is_reachable_from_the_client_sales_and_purchases_pages():
    sales = (WEB / "app" / "clients" / "[id]" / "sales" / "page.tsx").read_text()
    purchases = (WEB / "app" / "clients" / "[id]" / "purchases" / "page.tsx").read_text()
    assert "PostDatedChequesPanel" in sales and "PostDatedChequesPanel" in purchases
    assert re.search(r'direction="received"', sales) and re.search(r'direction="issued"', purchases)
