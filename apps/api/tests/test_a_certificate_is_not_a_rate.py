"""
PUR-07 ≡ TDS-13 — the IT Act §197 lower-deduction certificate.

WHAT WAS MISSING

    A transport contractor produces a certificate allowing deduction at 0.5%
    instead of 2%. There was nowhere to record it: `vendors` had no certificate
    column of any kind, and `resolve_tds` took no certificate parameter, so a
    certificate holder was always withheld at the full section rate. The CA's
    only options were to turn TDS off on the vendor — losing the register row,
    the 26Q deductee line and the challan — or to accept the over-deduction and
    leave the vendor to claim a refund.

    `tds_deductions.is_lower_deduction` and `.lower_deduction_cert` have existed
    since migration 037 and nothing had ever written to them, so Form 26Q's own
    lower-deduction fields were permanently blank — and the FVU requires the
    certificate number wherever a below-normal rate is used.

WHY A BARE PERCENTAGE COULD NEVER HAVE DONE IT

    §197(1) lets the Assessing Officer certify a lower rate "or no deduction of
    tax", and Rule 28AA(4) makes the certificate an AMOUNT and a PERIOD as well.
    So it is four facts. PUR-06 deleted `vendors.tds_rate_bps` from the vendor
    form rather than honouring it precisely because one number cannot carry
    them: a CA typed 1%, saw "1.0%" in the list, and every bill deducted 2%.
"""
import pytest
from fastapi import HTTPException

import routers.purchase_bills as pb
import routers.purchase_payments as pp
from domain.tds import lower_deduction
from models.invoices import (
    PurchaseBillIn, PurchaseBillLineIn, PurchasePaymentIn,
)
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "id": "u1", "auth_user_id": "auth", "email": "ca@f.test", "role": "Partner"}
FY_FROM, FY_TO = "2025-04-01", "2026-03-31"


def _setup(monkeypatch, section="194C", pan="AAACB1234C"):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [pb, pp])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27AAAAA0000A1Z5"})
    db.seed("vendors", {
        "id": "VEND", "firm_id": FIRM, "client_id": "CLI",
        "name": "Bharat Transport Pvt Ltd", "state_code": "27", "pan": pan,
        "is_active": True, "tds_applicable": True, "tds_section": section,
        "residential_status": "resident",
    })
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI",
                                  "name": "Freight", "kind": "service"})
    return db


def _certificate(db, *, no="197/2025/00042", section="194C", rate_bps=50,
                 valid_from=FY_FROM, valid_to=FY_TO, ceiling=50_00_000_00):
    return db.seed("tds_lower_deduction_certificates", {
        "firm_id": FIRM, "client_id": "CLI", "vendor_id": "VEND",
        "section": section, "certificate_no": no, "rate_bps": rate_bps,
        "valid_from": valid_from, "valid_to": valid_to,
        "ceiling_paise": ceiling,
    })


def _bill(db, no, taxable, on="2025-06-10"):
    res = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id="VEND", bill_date=on, bill_no=no,
        lines=[PurchaseBillLineIn(service_catalogue_id="SVC-1", description="Freight",
                                  hsn_sac="9965", quantity=1, rate_paise=taxable,
                                  gst_rate_percent=0.0)],
    ), CALLER)
    assert res["success"] is True, res
    return res["data"]


def _preview(db, taxable, on="2025-06-10"):
    res = pb.preview_purchase_bill_tds(PurchaseBillIn(
        client_id="CLI", vendor_id="VEND", bill_date=on, bill_no="PREVIEW",
        lines=[PurchaseBillLineIn(service_catalogue_id="SVC-1", description="Freight",
                                  hsn_sac="9965", quantity=1, rate_paise=taxable,
                                  gst_rate_percent=0.0)],
    ), current_user=CALLER)   # exclude_bill_id sits between the two — keyword it
    assert res["success"] is True, res
    return res["data"]


# ── The certificate applies ─────────────────────────────────────────────────

def test_a_certificate_lowers_the_rate(monkeypatch):
    """0.5% instead of 2% — ₹5,000 on ₹10,00,000, not ₹20,000."""
    db = _setup(monkeypatch)
    _certificate(db)
    bill = _bill(db, "B-1", 10_00_000_00)
    assert bill["tds_paise"] == 5_000_00
    assert bill["tds_certificate_no"] == "197/2025/00042"
    # Form 26Q's annexure has ONE rate column, and the whole base is certified,
    # so the rate on the row is the certified one — which with the number is
    # what the FVU requires whenever a below-normal rate is used.
    assert bill["tds_rate_bps"] == 50


def test_the_ceiling_is_a_ceiling_and_the_excess_pays_the_section_rate(monkeypatch):
    """Rule 28AA(4): the certificate is issued for a SPECIFIED AMOUNT.

    ₹50,00,000 certified at 0.5% is ₹25,000; the ₹10,00,000 beyond it is at the
    section's 2%, another ₹20,000. Substituting the rate outright — the obvious
    implementation — would withhold ₹30,000 on ₹60,00,000 and under-deduct by
    ₹15,000 exactly where the AO stopped certifying.
    """
    db = _setup(monkeypatch)
    _certificate(db, ceiling=50_00_000_00)
    first = _bill(db, "B-1", 50_00_000_00, on="2025-05-10")
    assert first["tds_paise"] == 25_000_00

    second = _bill(db, "B-2", 10_00_000_00, on="2025-06-10")
    # Aggregate ₹60,00,000: ₹25,000 certified + ₹20,000 at 2%, less ₹25,000
    # already withheld (§200).
    assert second["tds_paise"] == 20_000_00
    # The first bill consumed the whole ceiling, so nothing on THIS bill was
    # withheld at a below-normal rate — and the FVU wants the certificate
    # number only where one was. Its 26Q row is a plain section-rate deduction.
    assert second["tds_certificate_no"] is None
    assert second["tds_rate_bps"] == 200


def test_a_bill_outside_the_validity_period_pays_the_section_rate(monkeypatch):
    """Rule 28AA(4) caps validity at the financial year, and §197(2) obliges
    the certified rate only 'until such certificate is cancelled'.

    AND THE EARLIER CERTIFIED SLICE SURVIVES. The §194 series charges on the
    year's AGGREGATE, so this bill recomputes the whole year — and an engine
    that dropped the certificate because THIS bill is outside the window
    re-charged the earlier ₹10,00,000 at 2%, withholding ₹40,000 across the
    year where ₹25,000 was due. The §200 credit does not undo that: the
    cumulative it is subtracted from was already wrong. Caught by this test
    while it was being written.
    """
    db = _setup(monkeypatch)
    _certificate(db, valid_from="2025-04-01", valid_to="2025-09-30")
    inside = _bill(db, "B-IN", 10_00_000_00, on="2025-06-10")
    assert inside["tds_paise"] == 5_000_00

    outside = _bill(db, "B-OUT", 10_00_000_00, on="2025-11-10")
    # Aggregate ₹20,00,000 with only ₹10,00,000 certified: ₹5,000 + ₹20,000,
    # less the ₹5,000 already withheld.
    assert outside["tds_paise"] == 20_000_00
    assert outside["tds_certificate_no"] is None
    assert outside["tds_rate_bps"] == 200
    # ₹25,000 across the year on ₹20,00,000, not ₹40,000.
    assert inside["tds_paise"] + outside["tds_paise"] == 25_000_00


def test_a_nil_certificate_withholds_nothing_and_is_still_a_register_row(monkeypatch):
    """§197(1) allows 'no deduction of tax', and 26Q reports it.

    A resident bill below its threshold gets no register row — that is a sum
    the section never charged. A §197 nil is a deduction the Assessing Officer
    RELIEVED, and Form 26Q's annexure carries it with the certificate number.
    """
    db = _setup(monkeypatch)
    _certificate(db, rate_bps=0, no="197/2025/NIL")
    bill = _bill(db, "B-NIL", 10_00_000_00)
    assert bill["tds_paise"] == 0
    assert bill["tds_certificate_no"] == "197/2025/NIL"

    resp = pb.receive_purchase_bill(bill["id"], CALLER)
    assert resp["success"] is True, resp
    rows = db.table("tds_deductions").select("*").execute().data
    assert len(rows) == 1
    assert rows[0]["is_lower_deduction"] is True
    assert rows[0]["lower_deduction_cert"] == "197/2025/NIL"
    assert "197" in (rows[0]["non_deduction_reason"] or "")


def test_the_register_carries_the_certificate(monkeypatch):
    """Both columns have existed since migration 037 and nothing ever set them,
    so the FVU's lower-deduction fields were permanently blank."""
    db = _setup(monkeypatch)
    _certificate(db)
    bill = _bill(db, "B-1", 10_00_000_00)
    assert pb.receive_purchase_bill(bill["id"], CALLER)["success"] is True

    row = db.table("tds_deductions").select("*").execute().data[0]
    assert row["is_lower_deduction"] is True
    assert row["lower_deduction_cert"] == "197/2025/00042"
    assert row["tds_rate_pct"] == 0.5


def test_an_advance_is_certified_too(monkeypatch):
    """§194 charges at credit OR payment, whichever is earlier — so the earlier
    event is certified by the same certificate."""
    db = _setup(monkeypatch)
    _certificate(db)
    res = pp.create_purchase_payment(PurchasePaymentIn(
        client_id="CLI", vendor_id="VEND", payment_date="2025-06-10",
        amount_paise=10_00_000_00,
    ), CALLER)
    assert res["success"] is True, res
    pay = res["data"]
    assert pay["tds_paise"] == 5_000_00
    assert pay["tds_certificate_no"] == "197/2025/00042"


# ── The three refusals ──────────────────────────────────────────────────────

def test_a_certificate_against_a_section_197_does_not_reach_is_refused(monkeypatch):
    """§197(1) names the provisions it reaches, and §194Q is not among them."""
    db = _setup(monkeypatch, section="194Q")
    _certificate(db, section="194Q", rate_bps=1)
    bill = _bill(db, "B-1", 60_00_000_00)
    assert bill["tds_certificate_no"] is None
    # §194Q(1) charges 0.1% of the sum EXCEEDING ₹50,00,000 — the certificate
    # changed nothing.
    assert bill["tds_paise"] == 1_000_00


def test_a_certificate_without_a_pan_is_refused_and_206aa_stands(monkeypatch):
    """§206AA(4) bars a §197 certificate where the application has no PAN.

    Honouring it would defeat the 20% floor in exactly the case the floor
    exists for, and Rule 28AA(2) requires the PAN on the application anyway.
    """
    db = _setup(monkeypatch, pan=None)
    _certificate(db)
    bill = _bill(db, "B-1", 10_00_000_00)
    assert bill["tds_certificate_no"] is None
    assert bill["tds_paise"] == 2_00_000_00        # 20%, §206AA


def test_two_certificates_in_force_are_refused_rather_than_guessed(monkeypatch):
    """A fresh certificate issued before the old one expires is a real
    situation, and picking the lower one would be the flattering guess."""
    db = _setup(monkeypatch)
    _certificate(db, no="197/A", rate_bps=50)
    _certificate(db, no="197/B", rate_bps=100)
    bill = _bill(db, "B-1", 10_00_000_00)
    assert bill["tds_certificate_no"] is None
    assert bill["tds_paise"] == 20_000_00          # the section rate


# ── What the CA is told ─────────────────────────────────────────────────────

def test_the_preview_says_the_certificate_was_applied(monkeypatch):
    """A figure a CA cannot check is a figure a CA will not trust — and a
    certificate that was refused looks, from the number alone, exactly like the
    software ignoring one they know they recorded."""
    db = _setup(monkeypatch)
    _certificate(db)
    out = _preview(db, 10_00_000_00)
    assert "197" in out["tds_basis"]
    assert "197/2025/00042" in out["tds_basis"]


def test_the_preview_says_why_a_certificate_was_refused(monkeypatch):
    db = _setup(monkeypatch)
    _certificate(db, no="197/A")
    _certificate(db, no="197/B", rate_bps=100)
    out = _preview(db, 10_00_000_00)
    assert "197/A" in out["tds_basis"] and "197/B" in out["tds_basis"]
    assert "end one of the validity periods" in out["tds_basis"]


# ── The domain module on its own ────────────────────────────────────────────

def test_section_197_reaches_the_sections_the_sub_section_names(monkeypatch):
    """A literal list, and one that can BE a literal: §197's own list changes
    only when §197 is amended, never by a Finance Act — unlike a rate."""
    for s in ("194C", "194J", "194I", "194H", "195", "194A"):
        assert s in lower_deduction.SECTIONS_197
    for s in ("194Q", "194B", "192"):
        assert s not in lower_deduction.SECTIONS_197


def test_an_exhausted_certificate_reaches_nothing(monkeypatch):
    from datetime import date
    cert = lower_deduction.Certificate(
        certificate_no="C", section="194C", rate_bps=50,
        valid_from=date(2025, 4, 1), valid_to=date(2026, 3, 31),
        ceiling_paise=50_00_000_00)
    assert lower_deduction.certified_base(
        cert, consumed_paise=50_00_000_00, charge_base_paise=10_00_000_00) == 0
    assert lower_deduction.certified_base(
        cert, consumed_paise=60_00_000_00, charge_base_paise=10_00_000_00) == 0
    assert lower_deduction.certified_base(
        cert, consumed_paise=45_00_000_00, charge_base_paise=10_00_000_00) == 5_00_000_00
