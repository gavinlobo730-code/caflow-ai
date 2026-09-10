"""
PUR-10 — §194 charges at credit OR payment, whichever is EARLIER.

Every §194-series charging section, and §195, reads "at the time of credit of
such sum to the account of the [payee] or at the time of payment thereof ...
whichever is earlier". Until migration 358 the payment half of that did not
exist: routers/purchase_payments.py asserted "TDS already deducted at bill
stage; payment is net amount" and had no TDS logic at all, so a ₹5,00,000
mobilisation advance to a contractor withheld ₹0 where §194C charges ₹10,000.
§201(1A) interest runs from the payment date and §40(a)(ia) disallows 30% of
the whole expenditure.

What is asserted here is the arithmetic that stops the same expenditure being
charged twice, which is the hard half: the advance and the bill it is later
adjusted against are ONE sum credited-or-paid, and charging both would put a
debit balance on the vendor equal to the over-deduction.
"""
import pytest

from models.invoices import PurchaseBillIn, PurchaseBillLineIn, PurchasePaymentIn
from tests.e2e_harness import (
    FakeDB, wire_e2e, seed_standard_coa, trial_balance, account_balance, coa_id,
)

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "auth_user_id": "u1", "email": "ca@firma.test", "role": "Partner"}


def _setup(monkeypatch, section="194C", pan="PQRST9012K", **vendor_extra):
    import routers.purchase_bills as pb
    import routers.purchase_payments as pp
    db = FakeDB()
    wire_e2e(monkeypatch, db, [pb, pp])
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5"})
    db.seed("vendors", {"id": "VEND", "firm_id": FIRM, "client_id": "CLI",
                        "name": "Bharat Constructions Pvt Ltd", "state_code": "27",
                        "gstin": "27PQRST9012K1Z8", "pan": pan, "is_active": True,
                        "tds_applicable": True, "tds_section": section,
                        "residential_status": "resident", **vendor_extra})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI",
                                  "name": "Civil works", "kind": "service"})
    return pb, pp, db


def _pay(pp, amount_paise, *, on="2026-04-10", bill_id=None):
    resp = pp.create_purchase_payment(PurchasePaymentIn(
        client_id="CLI", vendor_id="VEND", payment_date=on,
        amount_paise=amount_paise, purchase_bill_id=bill_id,
    ), CALLER)
    assert resp["success"] is True, resp
    return resp["data"]


def _bill(pb, taxable_paise, *, bill_no, on="2026-05-05", gst=0.0):
    resp = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id="VEND", bill_date=on, bill_no=bill_no,
        lines=[PurchaseBillLineIn(service_catalogue_id="SVC-1", description="Civil works",
                                  hsn_sac="9954", quantity=1, rate_paise=taxable_paise,
                                  gst_rate_percent=gst)],
    ), CALLER)
    assert resp["success"] is True, resp
    return resp["data"]


def _receive(pb, bill_id):
    resp = pb.receive_purchase_bill(bill_id, CALLER)
    assert resp["success"] is True, resp
    return resp["data"]


# ── The charge itself ───────────────────────────────────────────────────────

def test_a_mobilisation_advance_withholds_where_the_bill_does_not_exist_yet(monkeypatch):
    """IT Act §194C: the advance is the earlier event, so the tax falls due on it.

    ₹5,00,000 to a company contractor: 2% is ₹10,000, the vendor is paid
    ₹4,90,000 and the Government is owed ₹10,000 by 7 May (Rule 30).
    """
    _pb, pp, db = _setup(monkeypatch)
    pay = _pay(pp, 5_00_000_00)

    assert pay["tds_paise"] == 10_000_00
    assert pay["tds_base_paise"] == 5_00_000_00
    assert pay["tds_section"] == "194C"
    assert pay["tds_rate_bps"] == 200
    # amount_paise is UNCHANGED — the sum credited or paid to the vendor. What
    # the withholding changes is the split of the credit side of the journal.
    assert pay["amount_paise"] == 5_00_000_00

    tb = trial_balance(db, FIRM, "CLI")
    assert tb["total_debit_paise"] == tb["total_credit_paise"] == 5_00_000_00
    assert account_balance(db, coa_id(db, FIRM, "bank")) == -4_90_000_00
    assert account_balance(db, coa_id(db, FIRM, "tds_payable")) == -10_000_00
    assert account_balance(db, coa_id(db, FIRM, "ap")) == 5_00_000_00


def test_the_advance_reaches_the_register_so_there_is_something_to_file(monkeypatch):
    """A deduction that exists only in the GL has no challan and no 26Q line."""
    _pb, pp, db = _setup(monkeypatch)
    pay = _pay(pp, 5_00_000_00, on="2026-04-10")

    rows = db.table("tds_deductions").select("*").execute().data
    assert len(rows) == 1
    row = rows[0]
    assert row["purchase_payment_id"] == pay["id"]
    # .get() rather than [], because the in-memory source stores exactly the
    # keys written and Postgres would default the unwritten one to NULL. Either
    # way the row records ONE event — migration 358's own CHECK.
    assert row.get("purchase_bill_id") is None
    assert row["tds_paise"] == 10_000_00
    # The ADVANCE, not the whole payment — but here they are the same sum.
    assert row["payment_amount_paise"] == 5_00_000_00
    assert row["section"] == "194C"
    assert row["return_type"] == "26Q"              # Rule 31A(4), resident payee
    assert row["financial_year"] == "2026-27"
    assert row["quarter"] == "Q1"
    assert row["transaction_date"] == "2026-04-10"


def test_a_payment_that_settles_an_existing_bill_withholds_nothing(monkeypatch):
    """The LATER of the two events is not charged again.

    The bill credited the vendor and withheld then. Paying it is the second
    event for the same sum, and §194C charges once — even where the CA never
    linked the payment to the bill, which is how the end-to-end purchase cycle
    records a settlement.
    """
    pb, pp, db = _setup(monkeypatch)
    bill = _bill(pb, 5_00_000_00, bill_no="B-1", on="2026-04-05")
    _receive(pb, bill["id"])
    assert bill["tds_paise"] == 10_000_00
    assert bill["net_payable_paise"] == 4_90_000_00

    pay = _pay(pp, 4_90_000_00, on="2026-04-20")
    assert pay["tds_paise"] == 0
    assert pay["tds_base_paise"] == 0
    assert account_balance(db, coa_id(db, FIRM, "bank")) == -4_90_000_00
    assert account_balance(db, coa_id(db, FIRM, "ap")) == 0
    # One deduction in the year, not two.
    assert account_balance(db, coa_id(db, FIRM, "tds_payable")) == -10_000_00


# ── The adjustment, which is the hard half ──────────────────────────────────

def test_the_bill_that_follows_an_advance_does_not_charge_the_same_sum_again(monkeypatch):
    """₹10,000 withheld on ₹5,00,000, not ₹20,000.

    Without the adjustment the advance and the bill both enter the year's
    aggregate: ₹10,00,000 charged on ₹5,00,000 credited, and Trade Payables is
    left with a ₹10,000 DEBIT balance — the vendor owing back the over-deduction.
    """
    pb, pp, db = _setup(monkeypatch)
    _pay(pp, 5_00_000_00, on="2026-04-10")
    bill = _bill(pb, 5_00_000_00, bill_no="B-1", on="2026-05-05")

    assert bill["tds_advance_adjusted_paise"] == 5_00_000_00
    assert bill["tds_paise"] == 0
    assert bill["net_payable_paise"] == 5_00_000_00
    _receive(pb, bill["id"])
    assert account_balance(db, coa_id(db, FIRM, "tds_payable")) == -10_000_00


def test_the_pool_is_consumed_once_so_the_next_bill_pays_the_full_rate(monkeypatch):
    """The second bill has no advance left to absorb.

    Aggregate ₹8,00,000 at 2% is ₹16,000, less the ₹10,000 already withheld
    (§200) — so bill 2 withholds ₹6,000, which is 2% of its own ₹3,00,000.
    """
    pb, pp, _db = _setup(monkeypatch)
    _pay(pp, 5_00_000_00, on="2026-04-10")
    b1 = _bill(pb, 5_00_000_00, bill_no="B-1", on="2026-05-05")
    _receive(pb, b1["id"])
    b2 = _bill(pb, 3_00_000_00, bill_no="B-2", on="2026-06-05")

    assert b2["tds_advance_adjusted_paise"] == 0
    assert b2["tds_paise"] == 6_000_00


def test_an_advance_larger_than_the_bill_leaves_the_remainder_in_the_pool(monkeypatch):
    """₹5,00,000 advanced, ₹2,00,000 billed: ₹3,00,000 of pool survives.

    Bill 2 of ₹4,00,000 absorbs the remaining ₹3,00,000, so its own charged base
    is ₹1,00,000. Aggregate ₹6,00,000 at 2% is ₹12,000 less ₹10,000 held.
    """
    pb, pp, _db = _setup(monkeypatch)
    _pay(pp, 5_00_000_00, on="2026-04-10")
    b1 = _bill(pb, 2_00_000_00, bill_no="B-1", on="2026-05-05")
    assert b1["tds_advance_adjusted_paise"] == 2_00_000_00
    assert b1["tds_paise"] == 0
    _receive(pb, b1["id"])

    b2 = _bill(pb, 4_00_000_00, bill_no="B-2", on="2026-06-05")
    assert b2["tds_advance_adjusted_paise"] == 3_00_000_00
    assert b2["tds_paise"] == 2_000_00


# ── The threshold is on sums PAID, not on sums taxed ────────────────────────

def test_a_below_threshold_advance_still_counts_toward_the_years_aggregate(monkeypatch):
    """§194C(5) aggregates "the amounts of such sums credited or paid".

    Four ₹25,000 advances bear no tax — each is inside the ₹30,000 single limb
    and the running total stays inside ₹1,00,000. The fifth crosses, and carries
    the whole year's tax on ₹1,25,000. A base recorded as zero on the first four
    would forgive them.
    """
    _pb, pp, _db = _setup(monkeypatch)
    for i in range(4):
        p = _pay(pp, 25_000_00, on=f"2026-04-1{i}")
        assert p["tds_paise"] == 0
        assert p["tds_base_paise"] == 25_000_00     # counted, not taxed
    fifth = _pay(pp, 25_000_00, on="2026-04-15")
    assert fifth["tds_paise"] == 2_500_00           # 2% of ₹1,25,000
    # And the one after settles back to 2% of itself (§200).
    sixth = _pay(pp, 25_000_00, on="2026-04-16")
    assert sixth["tds_paise"] == 500_00


def test_a_sub_threshold_advance_leaves_no_register_row(monkeypatch):
    """26Q reports deductions. A payment that was never taxed is not one."""
    _pb, pp, db = _setup(monkeypatch)
    _pay(pp, 25_000_00)
    assert db.table("tds_deductions").select("*").execute().data == []


# ── Undoing it ──────────────────────────────────────────────────────────────

def test_reversing_an_advance_takes_its_register_row_and_its_aggregate_with_it(monkeypatch):
    """The journal is reversed, so the deductee row must go too.

    A row left behind is filed on 26Q for tax no longer in the books — the
    mirror of the missing row PUR-10 was about.
    """
    _pb, pp, db = _setup(monkeypatch)
    pay = _pay(pp, 5_00_000_00, on="2026-04-10")
    assert len(db.table("tds_deductions").select("*").execute().data) == 1

    from services import reversal_service
    reversal_service.reverse_payment(db, FIRM, pay["id"], "2026-04-20")

    assert db.table("tds_deductions").select("*").execute().data == []
    # And the year starts again: a fresh ₹5,00,000 advance carries the full
    # ₹10,000 rather than crediting tax that was reversed out of the ledger.
    again = _pay(pp, 5_00_000_00, on="2026-04-25")
    assert again["tds_paise"] == 10_000_00


def test_an_adjustment_whose_advance_is_reversed_goes_back_into_the_aggregate(monkeypatch):
    """A posted bill's withholding cannot be rewritten, so the NEXT one re-charges.

    Bill 1 took ₹5,00,000 out of its own charged base because the advance had
    carried the tax. Reversing the advance means nothing carried it — so that
    ₹5,00,000 is restored to the year's aggregate rather than being charged
    nowhere at all.
    """
    pb, pp, db = _setup(monkeypatch)
    pay = _pay(pp, 5_00_000_00, on="2026-04-10")
    b1 = _bill(pb, 5_00_000_00, bill_no="B-1", on="2026-05-05")
    assert b1["tds_paise"] == 0
    _receive(pb, b1["id"])

    from services import reversal_service
    reversal_service.reverse_payment(db, FIRM, pay["id"], "2026-05-10")

    # Aggregate is ₹5,00,000 (restored) + ₹1,00,000 (this bill) = ₹6,00,000 at
    # 2% = ₹12,000, and nothing is now withheld anywhere to credit against it.
    b2 = _bill(pb, 1_00_000_00, bill_no="B-2", on="2026-06-05")
    assert b2["tds_paise"] == 12_000_00


# ── The other charging regime ───────────────────────────────────────────────

def test_an_advance_to_a_non_resident_is_refused_rather_than_guessed(monkeypatch):
    """§194C charges sums paid "to a resident" and does not reach a non-resident.

    §195 applies instead, by the NATURE of the income, and refuses where
    chargeability is unknown — the same refusal the bill path raises, at the
    moment the money actually leaves. Under-deducting under §195 disallows the
    WHOLE expenditure (§40(a)(i)), not 30% of it.
    """
    from fastapi import HTTPException
    _pb, pp, _db = _setup(monkeypatch, residential_status="non_resident")
    with pytest.raises(HTTPException) as e:
        pp.create_purchase_payment(PurchasePaymentIn(
            client_id="CLI", vendor_id="VEND", payment_date="2026-04-10",
            amount_paise=5_00_000_00,
        ), CALLER)
    assert e.value.status_code == 422


def test_a_vendor_with_no_tds_marking_withholds_nothing(monkeypatch):
    """Nothing about this change reaches a vendor the CA has not marked."""
    import routers.purchase_payments as pp_mod
    _pb, pp, db = _setup(monkeypatch)
    db.table("vendors").update({"tds_applicable": False}).eq("id", "VEND").execute()
    pay = _pay(pp, 5_00_000_00)
    assert pay["tds_paise"] == 0 and pay["tds_base_paise"] == 0
    assert account_balance(db, coa_id(db, FIRM, "bank")) == -5_00_000_00
    assert pp_mod is not None


# ── The two bounds that keep the row and the journal legal ──────────────────

def test_the_deduction_never_exceeds_the_payment_it_is_taken_out_of(monkeypatch):
    """The advance that crosses a threshold carries the whole year's tax.

    §194J on ₹49,000 is nil — inside the ₹50,000 single limb — and the ₹2,000
    that follows owes ₹5,100 on the ₹51,000 aggregate. Unbounded, the bank leg
    of the journal goes negative (a payment that took money OUT of the vendor)
    and migration 358's CHECK rejects the row AFTER the journal has posted.

    The shortfall is not lost: tds_base_paise records the whole ₹2,000 while
    tds_paise records the ₹2,000 actually withheld, so the next payment
    re-charges the difference through §200.
    """
    _pb, pp, db = _setup(monkeypatch, section="194J")
    first = _pay(pp, 49_000_00, on="2026-04-05")
    assert first["tds_paise"] == 0

    second = _pay(pp, 2_000_00, on="2026-04-06")
    assert second["tds_paise"] == 2_000_00        # bounded, not ₹5,100
    assert second["tds_base_paise"] == 2_000_00
    assert account_balance(db, coa_id(db, FIRM, "bank")) == -49_000_00

    # The ₹3,100 still owed is re-charged on the next payment, not forgotten:
    # aggregate ₹61,000 at 10% is ₹6,100, less the ₹2,000 held.
    third = _pay(pp, 10_000_00, on="2026-04-07")
    assert third["tds_paise"] == 4_100_00


def test_the_cash_leg_is_the_account_the_money_left(monkeypatch):
    """Not the firm's generic Bank ledger.

    domain/accounting/payment_account.resolve_payment_account decides this —
    an explicit bank_account_id wins, a cash payment_mode resolves to Cash in
    Hand, and only then does the generic ledger apply. Both vendor-payment
    callers handed journal_for_purchase_payment a three-key dict carrying
    payment_no, payment_date and amount_paise, so `bank_account_id` and
    `payment_mode` were always absent and the resolver ALWAYS took its
    fallback. The receipts path has passed the whole document since that
    resolver was written; the AP mirror was left behind.
    """
    _pb, pp, db = _setup(monkeypatch)
    # The client's own current account, with its own ledger — what a CA picks
    # in the Record Payment form.
    hdfc = db.seed("chart_of_accounts", {
        "firm_id": FIRM, "client_id": "CLI", "system_account_key": None,
        "account_name": "HDFC Current A/c", "is_active": True})
    db.seed("bank_accounts", {
        "id": "BA-1", "firm_id": FIRM, "client_id": "CLI",
        "bank_name": "HDFC Bank", "account_type": "current",
        "coa_account_id": hdfc["id"]})

    resp = pp.create_purchase_payment(PurchasePaymentIn(
        client_id="CLI", vendor_id="VEND", payment_date="2026-04-10",
        amount_paise=5_00_000_00, bank_account_id="BA-1",
    ), CALLER)
    assert resp["success"] is True, resp
    assert account_balance(db, hdfc["id"]) == -4_90_000_00
    assert account_balance(db, coa_id(db, FIRM, "bank")) == 0
