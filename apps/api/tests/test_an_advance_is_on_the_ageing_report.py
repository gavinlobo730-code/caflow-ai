"""PUR-24 — an ageing report that ties to its control account.

`ap_aging` summed open BILLS and stopped. A payment made to a supplier before
the bill arrives is real money out of the bank, debited to Trade Payables by
`journal_for_purchase_payment`, and it appeared nowhere: the vendor STATEMENT
debited it (build_statement's payment loop) while the ageing did not, so the
two disagreed by exactly the advances outstanding and neither could be tied to
the control account. The AR side had the identical defect with customer
receipts.

The trap these tests exist to hold is the DERIVATION. `settlement − Σ
allocations` reads as the careful way to compute an unapplied balance and is
wrong for every single-bill payment: `routers/purchase_payments.py` writes no
allocation rows on that path, so the derivation returns the whole payment as an
advance on money that discharged a bill.
"""
from datetime import date

import pytest

import routers.purchase_bills as pb
import routers.purchase_payments as pp
import routers.vendors as ve
from models.invoices import PurchaseBillIn, PurchaseBillLineIn, PurchasePaymentIn
from domain.reporting.party_advances import AdvanceInput, unapplied_advances
from services.vendor_statement_service import vendor_statement_service
from services.customer_statement_service import customer_statement_service
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM = "FIRM-ADV"
CALLER = {"firm_id": FIRM, "id": "u", "auth_user_id": "auth", "email": "ca@f.test", "role": "Partner"}


def _setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [pb, pp, ve])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27AAAAA0000A1Z2"})
    db.seed("vendors", {"id": "VEND1", "firm_id": FIRM, "client_id": "CLI", "name": "Supplier",
                        "state_code": "27", "gstin": "27CCCCC2222C1Z5", "tds_applicable": False,
                        "opening_balance_paise": 0})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI",
                                  "name": "Materials", "kind": "good"})
    return db


def _received_bill(db, no="B1", rate=1_00_000):
    res = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id="VEND1", bill_date="2025-06-01", bill_no=no,
        lines=[PurchaseBillLineIn(description="m", rate_paise=rate, quantity=1,
                                  gst_rate_percent=18.0, service_catalogue_id="SVC-1")],
    ), CALLER)
    bid = res["data"]["id"]
    assert pb.receive_purchase_bill(bid, CALLER)["success"] is True
    return bid, res["data"]["net_payable_paise"]


# ── the pure function ─────────────────────────────────────────────────────────

def _adv(**kw):
    base = dict(document_id="P1", document_no="VPMT-0001", party_id="V1",
                party_name="Supplier", document_date="2025-06-01",
                settlement_paise=1_00_000, unallocated_paise=1_00_000)
    base.update(kw)
    return AdvanceInput(**base)


def test_an_unapplied_payment_is_an_advance():
    pos = unapplied_advances([_adv()], today=date(2025, 6, 15), document_label="payment")
    assert pos.total_paise == 1_00_000
    assert [a["document_no"] for a in pos.advances] == ["VPMT-0001"]
    assert pos.advances[0]["days_old"] == 14
    assert pos.advances[0]["aging_bucket"] == "0-30"
    assert pos.gaps == []


def test_a_fully_applied_payment_is_not_an_advance():
    pos = unapplied_advances([_adv(unallocated_paise=0)], today=date(2025, 6, 15))
    assert pos.advances == [] and pos.total_paise == 0


def test_the_single_bill_path_has_no_allocation_rows_and_is_not_derived():
    """THE TRAP. allocated_paise is None — no bridge rows — so the cross-check
    is not run at all. Deriving `settlement − 0` would call this a full
    advance; the stored column says nil and the stored column is right."""
    pos = unapplied_advances(
        [_adv(unallocated_paise=0, allocated_paise=None)], today=date(2025, 6, 15))
    assert pos.advances == []
    assert pos.gaps == []          # not a discrepancy — there is nothing to compare


def test_allocation_rows_that_disagree_with_the_column_are_named_not_absorbed():
    pos = unapplied_advances(
        [_adv(settlement_paise=1_00_000, allocated_paise=40_000, unallocated_paise=1_00_000)],
        today=date(2025, 6, 15), document_label="payment")
    # The STORED figure is reported…
    assert pos.total_paise == 1_00_000
    # …and the difference is stated rather than silently resolved.
    assert len(pos.gaps) == 1
    assert "60000" in pos.gaps[0] and "100000" in pos.gaps[0]
    assert "VPMT-0001" in pos.gaps[0]


def test_allocation_rows_that_agree_produce_no_gap():
    pos = unapplied_advances(
        [_adv(settlement_paise=1_00_000, allocated_paise=40_000, unallocated_paise=60_000)],
        today=date(2025, 6, 15))
    assert pos.total_paise == 60_000 and pos.gaps == []


def test_an_over_allocated_document_is_reported_and_treated_as_nil():
    pos = unapplied_advances([_adv(unallocated_paise=-5_000)], today=date(2025, 6, 15))
    assert pos.total_paise == 0
    assert any("allocations exceed" in g for g in pos.gaps)


def test_age_buckets_run_from_the_document_date():
    rows = [
        _adv(document_id="A", document_no="A", document_date="2025-06-10"),   # 5 days
        _adv(document_id="B", document_no="B", document_date="2025-05-01"),   # 45
        _adv(document_id="C", document_no="C", document_date="2025-01-01"),   # 165
    ]
    pos = unapplied_advances(rows, today=date(2025, 6, 15))
    assert pos.buckets["0-30"] == 1_00_000
    assert pos.buckets["31-60"] == 1_00_000
    assert pos.buckets["90+"] == 1_00_000
    assert sum(pos.buckets.values()) == pos.total_paise


def test_a_foreign_advance_carries_its_label_and_its_base_amount():
    pos = unapplied_advances([_adv(currency="usd")], today=date(2025, 6, 15))
    assert pos.advances[0]["txn_currency"] == "USD"
    # No invented foreign minor — there is no stored counterpart to divide back.
    assert "unapplied_foreign_minor" not in pos.advances[0]


def test_an_inr_advance_carries_no_currency_label():
    pos = unapplied_advances([_adv()], today=date(2025, 6, 15))
    assert "txn_currency" not in pos.advances[0]


# ── AP ageing, end to end ─────────────────────────────────────────────────────

def test_ap_ageing_reports_an_advance_and_the_net_payable(monkeypatch):
    db = _setup(monkeypatch)
    _bid, net = _received_bill(db, rate=1_00_000)             # payable 1,18,000
    # An advance: a payment naming no bill. The router writes
    # unallocated_paise = amount_paise on this path.
    pp.create_purchase_payment(PurchasePaymentIn(
        client_id="CLI", vendor_id="VEND1", payment_date="2025-06-05",
        amount_paise=30_000, purchase_bill_id=None,
    ), CALLER)

    ag = vendor_statement_service.ap_aging(db, FIRM, "CLI", as_of="2025-06-15")
    assert ag["total_outstanding_paise"] == net              # bills unchanged
    assert ag["total_advances_paise"] == 30_000
    assert ag["net_payable_paise"] == net - 30_000
    assert [a["document_no"] for a in ag["advances"]]
    assert ag["advances"][0]["party_name"] == "Supplier"
    assert ag["advance_gaps"] == []


def test_an_advance_is_never_folded_into_the_payables_buckets(monkeypatch):
    """A supplier advance is an ASSET. Adding it to the payables ageing would
    misstate the Schedule III payables note this report feeds."""
    db = _setup(monkeypatch)
    _bid, net = _received_bill(db, rate=1_00_000)
    pp.create_purchase_payment(PurchasePaymentIn(
        client_id="CLI", vendor_id="VEND1", payment_date="2025-06-05",
        amount_paise=30_000, purchase_bill_id=None,
    ), CALLER)
    ag = vendor_statement_service.ap_aging(db, FIRM, "CLI", as_of="2025-06-15")
    assert sum(ag["buckets"].values()) == net
    assert sum(ag["advance_buckets"].values()) == 30_000


def test_a_bill_linked_payment_is_not_reported_as_an_advance(monkeypatch):
    """The real single-bill path, through the router that writes no allocation
    rows — the exact case a derivation gets wrong."""
    db = _setup(monkeypatch)
    bid, net = _received_bill(db, rate=1_00_000)
    pp.create_purchase_payment(PurchasePaymentIn(
        client_id="CLI", vendor_id="VEND1", payment_date="2025-06-05",
        amount_paise=18_000, purchase_bill_id=bid,
    ), CALLER)
    ag = vendor_statement_service.ap_aging(db, FIRM, "CLI", as_of="2025-06-15")
    assert ag["total_advances_paise"] == 0
    assert ag["advances"] == []
    assert ag["net_payable_paise"] == ag["total_outstanding_paise"] == net - 18_000


def test_a_reversed_payment_is_not_an_advance(monkeypatch):
    db = _setup(monkeypatch)
    _received_bill(db, rate=1_00_000)
    res = pp.create_purchase_payment(PurchasePaymentIn(
        client_id="CLI", vendor_id="VEND1", payment_date="2025-06-05",
        amount_paise=30_000, purchase_bill_id=None,
    ), CALLER)
    pid = res["data"]["id"]
    next(p for p in db.rows("purchase_payments") if p["id"] == pid)["is_reversed"] = True
    ag = vendor_statement_service.ap_aging(db, FIRM, "CLI", as_of="2025-06-15")
    assert ag["total_advances_paise"] == 0


def test_a_client_with_no_advances_reports_zero_not_nothing(monkeypatch):
    """A screen must be able to say 'none' rather than fall back to guessing."""
    db = _setup(monkeypatch)
    _bid, net = _received_bill(db, rate=1_00_000)
    ag = vendor_statement_service.ap_aging(db, FIRM, "CLI", as_of="2025-06-15")
    assert ag["advances"] == []
    assert ag["total_advances_paise"] == 0
    assert ag["net_payable_paise"] == net
    assert set(ag["advance_buckets"]) == {"not_due", "0-30", "31-60", "61-90", "90+"}


def test_a_voided_allocation_does_not_count_as_applied(monkeypatch):
    db = _setup(monkeypatch)
    res = pp.create_purchase_payment(PurchasePaymentIn(
        client_id="CLI", vendor_id="VEND1", payment_date="2025-06-05",
        amount_paise=50_000, purchase_bill_id=None,
    ), CALLER)
    pid = res["data"]["id"]
    db.seed("purchase_payment_allocations", {
        "purchase_payment_id": pid, "purchase_bill_id": "BILL-X",
        "allocated_paise": 50_000, "is_voided": True})
    ag = vendor_statement_service.ap_aging(db, FIRM, "CLI", as_of="2025-06-15")
    # The column still says 50,000 unapplied and the voided row must not
    # contradict it — a reversed payment's allocations are voided, not deleted.
    assert ag["total_advances_paise"] == 50_000
    assert ag["advance_gaps"] == []


def test_the_create_path_persists_what_the_payment_has_not_discharged(monkeypatch):
    """The defect found while building the section above, and not in any
    finding: `routers/purchase_payments.py` computed `unallocated_paise` for
    the §194 advance test and never wrote it, so every advance recorded from
    the Purchases screen kept the column's DEFAULT 0 (migration 226).

    That is not only a reporting gap. `update_allocations_core` is how a
    stranded advance is applied to a bill once the bill exists, and its
    docstring names `unallocated_paise > 0` as how such a payment is found —
    so an advance recorded on that screen could never be applied later.
    """
    db = _setup(monkeypatch)
    res = pp.create_purchase_payment(PurchasePaymentIn(
        client_id="CLI", vendor_id="VEND1", payment_date="2025-06-05",
        amount_paise=30_000, purchase_bill_id=None,
    ), CALLER)
    row = next(p for p in db.rows("purchase_payments") if p["id"] == res["data"]["id"])
    assert row["unallocated_paise"] == 30_000


def test_a_bill_linked_payment_persists_nil_unapplied(monkeypatch):
    """0, not the amount: `_claim_bill_outstanding` has already reserved the
    whole payment against the bill — the same reading the §194 advance test
    one line above it takes."""
    db = _setup(monkeypatch)
    bid, _net = _received_bill(db, rate=1_00_000)
    res = pp.create_purchase_payment(PurchasePaymentIn(
        client_id="CLI", vendor_id="VEND1", payment_date="2025-06-05",
        amount_paise=18_000, purchase_bill_id=bid,
    ), CALLER)
    row = next(p for p in db.rows("purchase_payments") if p["id"] == res["data"]["id"])
    assert row["unallocated_paise"] == 0


# ── AR ageing, the mirror ─────────────────────────────────────────────────────

def _ar_db(monkeypatch):
    db = FakeDB()
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("clients", {"id": "CLI", "firm_id": FIRM})
    db.seed("customers", {"id": "CUST1", "firm_id": FIRM, "client_id": "CLI", "name": "Acme"})
    return db


def test_ar_ageing_reports_an_unapplied_receipt(monkeypatch):
    db = _ar_db(monkeypatch)
    db.seed("client_sales_invoices", {
        "id": "INV1", "firm_id": FIRM, "client_id": "CLI", "customer_id": "CUST1",
        "invoice_no": "S-1", "invoice_date": "2025-06-01", "due_date": "2025-06-01",
        "total_paise": 1_00_000, "paid_paise": 0, "credited_paise": 0,
        "debit_note_paise": 0, "outstanding_paise": 1_00_000, "status": "sent"})
    db.seed("receipts", {
        "id": "R1", "firm_id": FIRM, "client_id": "CLI", "customer_id": "CUST1",
        "receipt_no": "RCPT-1", "receipt_date": "2025-06-05",
        "amount_paise": 40_000, "tds_paise": 0, "unallocated_paise": 40_000,
        "is_reversed": False})
    ag = customer_statement_service.ar_aging(db, FIRM, "CLI", as_of="2025-06-15")
    assert ag["total_outstanding_paise"] == 1_00_000
    assert ag["total_advances_paise"] == 40_000
    assert ag["net_receivable_paise"] == 60_000
    assert ag["advances"][0]["party_name"] == "Acme"


def test_a_receipt_settlement_is_cash_plus_the_tax_withheld(monkeypatch):
    """IT Act §198/§199 — the settlement is amount + tds, which is what
    receipt_service writes unallocated_paise against. Passing amount alone
    would report a spurious discrepancy on every receipt bearing §194J."""
    db = _ar_db(monkeypatch)
    db.seed("receipts", {
        "id": "R1", "firm_id": FIRM, "client_id": "CLI", "customer_id": "CUST1",
        "receipt_no": "RCPT-1", "receipt_date": "2025-06-05",
        "amount_paise": 90_000, "tds_paise": 10_000, "unallocated_paise": 20_000,
        "is_reversed": False})
    db.seed("receipt_allocations", {
        "receipt_id": "R1", "allocated_paise": 80_000, "is_voided": False})
    ag = customer_statement_service.ar_aging(db, FIRM, "CLI", as_of="2025-06-15")
    assert ag["total_advances_paise"] == 20_000
    assert ag["advance_gaps"] == []      # 90,000 + 10,000 − 80,000 == 20,000


# ── one bucket function ───────────────────────────────────────────────────────

def test_the_three_ageing_readers_share_one_bucket_function():
    """CLAUDE.md: when a rule has to exist twice, MOVE it. This one existed
    three times — the customer statement, the vendor statement and the
    collections sweep each carried a byte-identical private copy."""
    from domain.reporting import party_advances
    import services.collections_service as collections
    import services.customer_statement_service as cust
    import services.vendor_statement_service as vend
    assert collections.aging_bucket is party_advances.aging_bucket
    assert cust._aging_bucket is party_advances.aging_bucket
    assert vend._aging_bucket is party_advances.aging_bucket
