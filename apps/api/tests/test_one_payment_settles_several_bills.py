"""
One NEFT settles several supplier bills, from the Purchases screen. PUR-22.

WHAT WAS WRONG
    `purchase_payment_service.create_payment_core` has done multi-bill vendor
    settlement since migration 226 — every allocation pre-validated against
    live outstanding BEFORE anything posts, each bill's paid_paise CAS-guarded,
    the whole settlement compensated if any part fails — and its ONLY caller
    was `bank_posting_service.match_and_settle_multi`. `POST
    /api/purchase-payments`, which is what both the Payments tab and the bill
    drawer post to, took a single optional `purchase_bill_id`.

    So a client making one NEFT of Rs 4,50,000 against six bills left the CA
    with two bad options: six payments with six fabricated references and six
    journal entries against one bank line, or one unallocated payment that sat
    as an advance while all six bills still showed as outstanding in the AP
    ageing.

WHAT THE TWO SHAPES ARE, AND WHY BOTH SURVIVE
    A payment records WHICH BILLS IT SETTLED in one of two ways:
      * `purchase_payments.purchase_bill_id` — the legacy single-bill FK, and
        no allocation row;
      * `purchase_payment_allocations` rows — and that column NULL.
    `reversal_service.reverse_payment` branches on exactly that column: with it
    set it rolls the bill back by the payment's whole AP relief; with it NULL
    it rolls each allocation back by its own amount. So the column says WHICH
    SHAPE this payment is, not merely which bill it happened to pay — writing
    it from the allocation path would send a PARTLY allocated payment down the
    legacy branch and roll back more than the payment ever settled. Hence the
    endpoint refuses a request carrying both, and the single-bill path is
    untouched.

WHAT THAT COST SOMEWHERE ELSE, WITH NO FINDING OF ITS OWN
    `msme_43bh_service._payments` read ONLY the bridge table. Every payment
    recorded from the Purchases screen or the bill drawer writes the FK shape
    and no allocation row, so §43B(h) saw those bills as NEVER PAID — and
    §43B(h) (Finance Act 2023, AY 2024-25) disallows the deduction for a sum
    payable to a micro or small enterprise that was not ACTUALLY PAID within
    the MSMED §15 limit. A bill paid on time was added back to taxable income,
    invisibly: "no payment found" and "paid late" produce the same
    disallowance. It reads both shapes now.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from models.parties import VendorIn
from models.invoices import PurchaseBillIn, PurchaseBillLineIn, PurchasePaymentIn
import routers.purchase_bills as pb
import routers.purchase_payments as pp
import routers.vendors as ve
from services import purchase_payment_service as pps
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM = "FIRM-PUR22"
CALLER = {"firm_id": FIRM, "id": "u1", "auth_user_id": "u1",
          "email": "ca@f.test", "role": "Partner"}


def _setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [pb, pp, ve, pps])
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5"})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI",
                                  "name": "Materials", "kind": "service"})
    vend = ve.create_vendor(VendorIn(client_id="CLI", name="Supplier", state_code="27"),
                            CALLER)["data"]
    return db, vend["id"]


def _bill(vend_id, amount_paise, bill_no, bill_date="2026-06-01"):
    b = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id=vend_id, bill_date=bill_date, bill_no=bill_no,
        lines=[PurchaseBillLineIn(service_catalogue_id="SVC-1", description="m",
                                  rate_paise=amount_paise, quantity=1,
                                  gst_rate_percent=0.0)]), CALLER)["data"]
    pb.receive_purchase_bill(b["id"], CALLER)
    return b


def _bill_row(db, bill_id):
    return next(r for r in db.rows("purchase_bills") if r["id"] == bill_id)


def _pay(**kw):
    body = {"client_id": "CLI", "payment_date": "2026-06-20", "payment_mode": "bank"}
    body.update(kw)
    return pp.create_purchase_payment(PurchasePaymentIn(**body), CALLER)


# ── The endpoint reaches the engine ──────────────────────────────────────────

def test_one_payment_settles_three_bills(monkeypatch):
    db, vend = _setup(monkeypatch)
    b1, b2, b3 = (_bill(vend, 100000, "B1"), _bill(vend, 150000, "B2"),
                  _bill(vend, 200000, "B3"))

    res = _pay(vendor_id=vend, amount_paise=450000, allocations=[
        {"purchase_bill_id": b1["id"], "allocated_paise": 100000},
        {"purchase_bill_id": b2["id"], "allocated_paise": 150000},
        {"purchase_bill_id": b3["id"], "allocated_paise": 200000},
    ])
    assert res["success"], res
    assert res["data"]["unallocated_paise"] == 0
    for b in (b1, b2, b3):
        row = _bill_row(db, b["id"])
        assert row["status"] == "paid", f"{row['bill_no']} still {row['status']}"

    # ONE payment, ONE journal — the whole point. Six payments against one bank
    # line is what this replaces.
    assert len([p for p in db.rows("purchase_payments")]) == 1
    entries = [e for e in db.rows("journal_entries")
               if (e.get("reference_no") or "").startswith("VPMT-")]
    assert len(entries) == 1


def test_what_is_not_allocated_is_an_advance(monkeypatch):
    """§194/§195 charge at credit or payment, whichever is earlier, so the
    remainder is the part that withholds — and `unallocated_paise` is what the
    AP ageing's advances section and `update_allocations_core` both read."""
    db, vend = _setup(monkeypatch)
    b1 = _bill(vend, 100000, "B1")

    res = _pay(vendor_id=vend, amount_paise=175000, allocations=[
        {"purchase_bill_id": b1["id"], "allocated_paise": 100000}])
    assert res["data"]["unallocated_paise"] == 75000


def test_a_request_carrying_both_shapes_is_refused(monkeypatch):
    db, vend = _setup(monkeypatch)
    b1 = _bill(vend, 100000, "B1")
    with pytest.raises(HTTPException) as e:
        _pay(vendor_id=vend, amount_paise=100000, purchase_bill_id=b1["id"],
             allocations=[{"purchase_bill_id": b1["id"], "allocated_paise": 100000}])
    assert e.value.status_code == 422
    assert "not both" in str(e.value.detail)


def test_over_allocating_posts_nothing(monkeypatch):
    """create_payment_core checks the sum before it posts and each bill against
    its live outstanding — a phantom journal with no settlement behind it is
    the failure this guards."""
    db, vend = _setup(monkeypatch)
    b1 = _bill(vend, 100000, "B1")
    with pytest.raises(HTTPException) as e:
        _pay(vendor_id=vend, amount_paise=100000, allocations=[
            {"purchase_bill_id": b1["id"], "allocated_paise": 120000}])
    assert e.value.status_code == 422
    assert db.rows("purchase_payments") == []
    assert [x for x in db.rows("journal_entries")
            if (x.get("reference_no") or "").startswith("VPMT-")] == []
    assert int(_bill_row(db, b1["id"]).get("paid_paise") or 0) == 0


def test_allocating_more_than_a_bill_still_owes_is_refused(monkeypatch):
    db, vend = _setup(monkeypatch)
    b1, b2 = _bill(vend, 100000, "B1"), _bill(vend, 100000, "B2")
    _pay(vendor_id=vend, amount_paise=100000, allocations=[
        {"purchase_bill_id": b1["id"], "allocated_paise": 100000}])
    with pytest.raises(HTTPException) as e:
        _pay(vendor_id=vend, amount_paise=200000, allocations=[
            {"purchase_bill_id": b1["id"], "allocated_paise": 100000},
            {"purchase_bill_id": b2["id"], "allocated_paise": 100000},
        ])
    assert e.value.status_code == 422
    assert "exceed" in str(e.value.detail).lower()


def test_the_single_bill_path_is_unchanged(monkeypatch):
    """The control. A single-bill request must still write the legacy FK — that
    column is what reverse_payment reads to decide which shape it is undoing."""
    db, vend = _setup(monkeypatch)
    b1 = _bill(vend, 100000, "B1")
    res = _pay(vendor_id=vend, amount_paise=100000, purchase_bill_id=b1["id"])
    assert res["success"]
    row = next(p for p in db.rows("purchase_payments"))
    assert row["purchase_bill_id"] == b1["id"]
    assert db.rows("purchase_payment_allocations") == []
    assert _bill_row(db, b1["id"])["status"] == "paid"


def test_the_allocation_path_leaves_the_legacy_column_null(monkeypatch):
    """Not cosmetic: reverse_payment takes the legacy branch whenever this
    column is set, and would roll back the payment's WHOLE AP relief rather
    than each allocation's own amount."""
    db, vend = _setup(monkeypatch)
    b1 = _bill(vend, 100000, "B1")
    _pay(vendor_id=vend, amount_paise=175000, allocations=[
        {"purchase_bill_id": b1["id"], "allocated_paise": 100000}])
    row = next(p for p in db.rows("purchase_payments"))
    assert row["purchase_bill_id"] is None
    assert len(db.rows("purchase_payment_allocations")) == 1


# ── A bill's payments are BOTH shapes ────────────────────────────────────────

def test_a_bill_lists_the_payment_that_settled_it_among_several(monkeypatch):
    """Filtering on the FK alone showed the bill as paid-by-nothing while its
    own paid_paise said otherwise — and "no payments" reads as a missing
    record, not as a query that could not see one."""
    db, vend = _setup(monkeypatch)
    b1, b2 = _bill(vend, 100000, "B1"), _bill(vend, 300000, "B2")
    _pay(vendor_id=vend, amount_paise=400000, allocations=[
        {"purchase_bill_id": b1["id"], "allocated_paise": 100000},
        {"purchase_bill_id": b2["id"], "allocated_paise": 300000},
    ])

    got = pp.list_purchase_payments(client_id="CLI", purchase_bill_id=b1["id"],
                                    vendor_id=None, from_date=None, to_date=None,
                                    limit=50, offset=0, current_user=CALLER)["data"]
    assert len(got) == 1
    # NOT amount_paise: a Rs 4,00,000 NEFT listed against a Rs 1,00,000 bill
    # without this reads as a gross overpayment.
    assert got[0]["allocated_to_bill_paise"] == 100000
    assert got[0]["amount_paise"] == 400000


def test_a_bill_lists_a_legacy_single_bill_payment_too(monkeypatch):
    db, vend = _setup(monkeypatch)
    b1 = _bill(vend, 100000, "B1")
    _pay(vendor_id=vend, amount_paise=100000, purchase_bill_id=b1["id"])
    got = pp.list_purchase_payments(client_id="CLI", purchase_bill_id=b1["id"],
                                    vendor_id=None, from_date=None, to_date=None,
                                    limit=50, offset=0, current_user=CALLER)["data"]
    assert len(got) == 1
    assert got[0]["allocated_to_bill_paise"] == 100000


def test_a_bill_nobody_paid_lists_nothing(monkeypatch):
    db, vend = _setup(monkeypatch)
    b1, b2 = _bill(vend, 100000, "B1"), _bill(vend, 300000, "B2")
    _pay(vendor_id=vend, amount_paise=300000, allocations=[
        {"purchase_bill_id": b2["id"], "allocated_paise": 300000}])
    assert pp.list_purchase_payments(client_id="CLI", purchase_bill_id=b1["id"],
                                     vendor_id=None, from_date=None, to_date=None,
                                    limit=50, offset=0, current_user=CALLER)["data"] == []


def test_a_voided_allocation_does_not_list(monkeypatch):
    """reverse_payment voids rather than deletes, so a reversed payment would
    otherwise keep appearing against the bill it no longer settles."""
    db, vend = _setup(monkeypatch)
    b1 = _bill(vend, 100000, "B1")
    _pay(vendor_id=vend, amount_paise=100000, allocations=[
        {"purchase_bill_id": b1["id"], "allocated_paise": 100000}])
    for a in db.rows("purchase_payment_allocations"):
        a["is_voided"] = True
    assert pp.list_purchase_payments(client_id="CLI", purchase_bill_id=b1["id"],
                                     vendor_id=None, from_date=None, to_date=None,
                                    limit=50, offset=0, current_user=CALLER)["data"] == []


# ── §43B(h) sees a bill paid the ordinary way ────────────────────────────────

def _bh_payments(db, bill_ids):
    from services.msme_43bh_service import _payments
    return _payments(db, FIRM, bill_ids)


def test_section_43bh_sees_a_bill_paid_through_the_single_bill_path(monkeypatch):
    """The live defect this found. §43B(h) disallows the deduction unless the
    sum was ACTUALLY PAID within the MSMED §15 limit; reading only the bridge
    table saw nothing for a bill paid the ordinary way and added a timely
    payment back to taxable income."""
    db, vend = _setup(monkeypatch)
    b1 = _bill(vend, 100000, "B1")
    _pay(vendor_id=vend, amount_paise=100000, purchase_bill_id=b1["id"])

    paid = _bh_payments(db, [b1["id"]])
    assert b1["id"] in paid, "a bill paid the ordinary way must count as paid"
    assert [p.amount_paise for p in paid[b1["id"]]] == [100000]
    assert [str(p.paid_on) for p in paid[b1["id"]]] == ["2026-06-20"]


def test_section_43bh_still_sees_an_allocated_payment(monkeypatch):
    db, vend = _setup(monkeypatch)
    b1 = _bill(vend, 100000, "B1")
    _pay(vendor_id=vend, amount_paise=100000, allocations=[
        {"purchase_bill_id": b1["id"], "allocated_paise": 100000}])
    paid = _bh_payments(db, [b1["id"]])
    assert [p.amount_paise for p in paid[b1["id"]]] == [100000]


def test_section_43bh_ignores_a_reversed_single_bill_payment(monkeypatch):
    """The FK shape's twin of the voided allocation. A reversed payment moved
    no money, and counting it would show a bill as paid in time that was never
    paid at all."""
    db, vend = _setup(monkeypatch)
    b1 = _bill(vend, 100000, "B1")
    _pay(vendor_id=vend, amount_paise=100000, purchase_bill_id=b1["id"])
    for p in db.rows("purchase_payments"):
        p["is_reversed"] = True
    assert _bh_payments(db, [b1["id"]]) == {}


def test_section_43bh_counts_a_bill_paid_by_both_shapes_once_each(monkeypatch):
    """Part-paid the ordinary way, the rest in a multi-bill NEFT. Neither
    reading alone is the answer."""
    db, vend = _setup(monkeypatch)
    b1 = _bill(vend, 100000, "B1")
    _pay(vendor_id=vend, amount_paise=40000, purchase_bill_id=b1["id"])
    _pay(vendor_id=vend, amount_paise=60000, allocations=[
        {"purchase_bill_id": b1["id"], "allocated_paise": 60000}])
    paid = _bh_payments(db, [b1["id"]])
    assert sorted(p.amount_paise for p in paid[b1["id"]]) == [40000, 60000]
