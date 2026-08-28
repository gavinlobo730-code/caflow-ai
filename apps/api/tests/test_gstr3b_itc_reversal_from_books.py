"""A purchase cancelled in a later month reverses its ITC in THAT month's 3B.

WHAT WAS WRONG
    gstr3b_from_books passed no reversals at all, and Table 4(B) was filed as
    an empty list. Two separate consequences, both seen on a live firm:

      * The RETURN said no credit had been given back in a month when the books
        had given some back. Apex cancelled four FY2025-26 purchase bills on
        17 July 2026; the July GSTR-3B declared Rs 0 reversed.
      * The books-vs-ledger RECONCILIATION reported a difference of exactly the
        reversed tax — Rs 88,141.67 — because the ledger's gst_input movement is
        net of the cancellation credit and the books comparator was not.

    And the same four bills broke their ORIGINAL month too, from the other
    direction: _posted_bills filtered on status, so once the bill read
    "cancelled" it vanished from February's Table 4(A) while February's ledger
    kept the debit it had always had.

    Neither shows up in a total. The tax payable came out right in both months;
    what was wrong was which month the credit was declared in, and a
    reconciliation that told a CA their books disagreed with their ledger when
    they did not.

WHY THIS TEST POSTS REAL DOCUMENTS
    The claim is about agreement between two independently derived numbers —
    documents on one side, posted journal lines on the other. A fake that is
    handed both sides cannot test it. This drives routers/purchase_bills.py
    through the e2e harness so the GL movement is the one the posting kernel
    actually writes.
"""
from datetime import datetime, timezone

import pytest

import routers.sales_invoices as si
import routers.purchase_bills as pb
import routers.credit_notes as cn
import routers.sales_debit_notes as sdn
import routers.purchase_credit_notes as pcn
import services.gst_return_service as grs
from models.invoices import PurchaseBillIn, PurchaseBillLineIn
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "id": "u-int", "auth_user_id": "auth",
          "email": "ca@f.test", "role": "Partner"}
GSTIN = "27AAAAA0000A1Z5"

JUNE, JULY = "062025", "072025"
BILL_TAX = 90000            # Rs 5,000 @ 18% intra-state -> 45000 CGST + 45000 SGST


def _setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [si, pb, cn, sdn, pcn])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": GSTIN,
                        "financial_year_start": "2025-04-01"})
    db.seed("vendors", {"id": "VEND1", "firm_id": FIRM, "client_id": "CLI",
                        "name": "Supplier", "state_code": "27",
                        "gstin": "27CCCCC2222C1Z5", "tds_applicable": False})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI",
                                  "name": "Materials", "kind": "good"})
    return db


def _receive_bill(db, no, rate, date):
    res = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id="VEND1", bill_date=date, bill_no=no,
        lines=[PurchaseBillLineIn(service_catalogue_id="SVC-1", description="mat",
                                  rate_paise=rate, quantity=1, gst_rate_percent=18.0)],
    ), CALLER)
    assert res["success"] is True
    assert pb.receive_purchase_bill(res["data"]["id"], CALLER)["success"] is True
    return res["data"]["id"]


def _cancel_on(monkeypatch, bill_id, when: str):
    """Cancel with the clock set, so the reversal journal and cancelled_at both
    land on `when` — the router dates the reversal 'today'."""
    class _Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(int(when[:4]), int(when[5:7]), int(when[8:10]),
                            tzinfo=tz or timezone.utc)
    monkeypatch.setattr(pb, "datetime", _Clock)
    res = pb.cancel_purchase_bill(bill_id, CALLER)
    assert res["success"] is True


def _3b(db, period):
    return grs.gstr3b_from_books(db, FIRM, "CLI", period, GSTIN)


def _rev(out):
    return {r["ty"]: r for r in out["payload"]["itc_elg"]["itc_rev"]}


def _avl(out, ty="OTH"):
    """Table 4(A) is five rows; ordinary purchase credit is "All other ITC"."""
    return {r["ty"]: r for r in out["payload"]["itc_elg"]["itc_avl"]}[ty]


# ── the fixture has to actually move the ledger ──────────────────────────────

def test_the_cancellation_really_reverses_the_ledger(monkeypatch):
    """Guard. If cancelling posted no reversal, every assertion below would be
    comparing two zeros and would hold with the fix removed."""
    db = _setup(monkeypatch)
    bill = _receive_bill(db, "B-1", 5_00000, "2025-06-12")
    assert _3b(db, JUNE)["reconciliation"]["itc"]["ledger_paise"] == BILL_TAX
    _cancel_on(monkeypatch, bill, "2025-07-15")
    assert _3b(db, JULY)["reconciliation"]["itc"]["ledger_paise"] == -BILL_TAX, (
        "the cancellation did not credit gst_input in July")


# ── the month the credit is given back ───────────────────────────────────────

def test_july_declares_the_reversal_in_table_4b1(monkeypatch):
    db = _setup(monkeypatch)
    bill = _receive_bill(db, "B-1", 5_00000, "2025-06-12")
    _cancel_on(monkeypatch, bill, "2025-07-15")

    out = _3b(db, JULY)
    rev = _rev(out)
    # 4(B)(1): permanent. The credit on a cancelled purchase is not coming back,
    # so declaring it in 4(B)(2) would leave a balance in the electronic credit
    # reversal and re-claimed statement that never clears.
    assert rev["RUL"]["camt"] == 45000 // 100
    assert rev["RUL"]["samt"] == 45000 // 100
    assert rev["OTH"]["camt"] == 0 and rev["OTH"]["samt"] == 0

    perm = out["working"]["itc_reversal"]["permanent_paise"]
    assert perm["cgst_paise"] == 45000 and perm["sgst_paise"] == 45000
    reasons = out["working"]["itc_reversal"]["reasons"]
    assert len(reasons) == 1 and "B-1" in reasons[0]["reason"], reasons


def test_july_reconciles_to_the_ledger_after_the_reversal(monkeypatch):
    db = _setup(monkeypatch)
    bill = _receive_bill(db, "B-1", 5_00000, "2025-06-12")
    _cancel_on(monkeypatch, bill, "2025-07-15")

    itc = _3b(db, JULY)["reconciliation"]["itc"]
    assert itc["books_paise"] == -BILL_TAX
    assert itc["ledger_paise"] == -BILL_TAX
    assert itc["difference_paise"] == 0, (
        "the books side is not net of the reversal — this is the Rs 88,141.67 "
        "difference the CA was shown on a return they were about to file")
    assert itc["matched"] is True


# ── and the month the credit was taken must not change ───────────────────────

def test_the_original_month_still_claims_the_credit_it_claimed(monkeypatch):
    db = _setup(monkeypatch)
    bill = _receive_bill(db, "B-1", 5_00000, "2025-06-12")
    before = _avl(_3b(db, JUNE))["camt"]
    _cancel_on(monkeypatch, bill, "2025-07-15")
    after = _3b(db, JUNE)

    assert _avl(after)["camt"] == before == 45000 // 100, (
        "cancelling in July retroactively removed the bill from June's Table "
        "4(A) — a return that was filed claiming that credit")
    assert after["reconciliation"]["itc"]["books_paise"] == BILL_TAX
    assert after["reconciliation"]["itc"]["matched"] is True
    # And June must not ALSO declare the reversal; that belongs to July alone.
    assert _rev(after)["RUL"]["camt"] == 0


# ── raised and cancelled in the same month ───────────────────────────────────

def test_a_bill_cancelled_in_its_own_month_reverses_nothing(monkeypatch):
    """Its receive journal and its reversal both sit in July, netting to zero,
    and Table 4(A) never claimed it. A 4(B) entry would deduct a credit that was
    never taken and put the reconciliation out by the tax."""
    db = _setup(monkeypatch)
    bill = _receive_bill(db, "B-2", 5_00000, "2025-07-03")
    _cancel_on(monkeypatch, bill, "2025-07-20")

    out = _3b(db, JULY)
    assert _avl(out)["camt"] == 0
    assert _rev(out)["RUL"]["camt"] == 0
    itc = out["reconciliation"]["itc"]
    assert itc["ledger_paise"] == 0 and itc["books_paise"] == 0
    assert itc["matched"] is True


# ── a month with no cancellations is untouched ───────────────────────────────

def test_an_ordinary_month_is_unchanged(monkeypatch):
    db = _setup(monkeypatch)
    _receive_bill(db, "B-3", 5_00000, "2025-06-12")
    out = _3b(db, JUNE)
    assert out["reconciliation"]["itc"]["matched"] is True
    assert _rev(out)["RUL"]["camt"] == 0 and _rev(out)["OTH"]["camt"] == 0
    assert out["working"]["itc_reversal"]["reasons"] == []
