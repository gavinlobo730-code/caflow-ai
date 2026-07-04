"""
Production Readiness Phase 2 — purchase-bill TDS routes through the central engine
(audit H5 threshold+aggregation, H6 payee-type rate + persisted rate, L1 rate bound,
L6 unknown-section error). Driven through the real create_purchase_bill path.
"""
import pytest
from fastapi import HTTPException

import routers.purchase_bills as pb
from models.invoices import PurchaseBillIn, PurchaseBillLineIn
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "id": "u", "auth_user_id": "auth", "email": "ca@f.test", "role": "Partner"}


def _setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [pb])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27AAAAA0000A1Z5"})
    seed_standard_coa(db, FIRM, "CLI")
    return db


def _vendor(db, section, pan="ABCCD1234E", applicable=True):
    return db.seed("vendors", {
        "id": f"V-{section}-{pan[3]}", "firm_id": FIRM, "client_id": "CLI", "name": "Vendor",
        "state_code": "27", "gstin": "27CCCCC2222C1Z5",
        "tds_applicable": applicable, "tds_section": section, "pan": pan,
    })["id"]


def _bill(db, vendor_id, rate, no):
    return pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id=vendor_id, bill_date="2025-06-10", bill_no=no,
        lines=[PurchaseBillLineIn(description="svc", rate_paise=rate, quantity=1, gst_rate_percent=18.0)],
    ), CALLER)["data"]


def test_h5_below_threshold_no_tds(monkeypatch):
    db = _setup(monkeypatch)
    v = _vendor(db, "194J")                       # threshold ₹50,000 (FA 2025)
    b = _bill(db, v, 40_000_00, "B1")             # ₹40,000 ≤ 50k — was taxable
    assert b["tds_paise"] == 0 and b["tds_rate_bps"] == 0   # under the pre-2025 ₹30k limit


def test_h5_h6_above_threshold_deducts_and_persists_rate(monkeypatch):
    db = _setup(monkeypatch)
    v = _vendor(db, "194J")
    b = _bill(db, v, 60_000_00, "B1")             # ₹60,000 > 50k (FA 2025) → 10%
    assert b["tds_paise"] == 6_000_00             # ₹6,000
    assert b["tds_rate_bps"] == 1000              # H6: applied rate persisted
    assert b["tds_section"] == "194J"


def test_h5_194c_aggregate_threshold_across_bills(monkeypatch):
    db = _setup(monkeypatch)
    v = _vendor(db, "194C")                        # single ₹30k, aggregate ₹1L
    # Four ₹25,000 bills: each below single threshold, aggregate never exceeds ₹1L.
    for i in range(4):
        bi = _bill(db, v, 25_000_00, f"C{i}")
        assert bi["tds_paise"] == 0
    # Fifth ₹25,000 bill tips the FY aggregate past ₹1,00,000 → TDS now applies.
    b5 = _bill(db, v, 25_000_00, "C5")
    assert b5["tds_paise"] == 500_00              # 2% (company PAN) of ₹25,000
    assert b5["tds_rate_bps"] == 200


def test_h6_individual_vs_company_rate_194c(monkeypatch):
    db = _setup(monkeypatch)
    v_ind = _vendor(db, "194C", pan="ABCPD1234E")  # 4th char P → individual → 1%
    b = _bill(db, v_ind, 50_000_00, "I1")          # >30k single
    assert b["tds_rate_bps"] == 100 and b["tds_paise"] == 500_00

    v_co = _vendor(db, "194C", pan="ABCCD1234E")   # 4th char C → company → 2%
    b2 = _bill(db, v_co, 50_000_00, "C1")
    assert b2["tds_rate_bps"] == 200 and b2["tds_paise"] == 1_000_00


def test_206aa_no_pan_vendor_gets_the_floored_rate_not_the_section_rate(monkeypatch):
    """R3.10: previously create_purchase_bill's resolve_tds() call had zero
    PAN awareness -- a no-PAN vendor's bill silently deducted at the
    ordinary 194J rate (10%) instead of Section 206AA's 20% floor. Driven
    through the real bill-creation path, not just the domain function
    directly, to prove the actual production bug is fixed end to end."""
    db = _setup(monkeypatch)
    v = _vendor(db, "194J", pan="PANNOTAVBL")      # no real PAN on file
    b = _bill(db, v, 60_000_00, "B1")              # > ₹50,000 (FA 2025) threshold
    assert b["tds_rate_bps"] == 2000                # floored to 20%, not 194J's ordinary 10%
    assert b["tds_paise"] == 12_000_00              # 20% of ₹60,000, not ₹6,000


def test_l1_tds_never_reaches_full_taxable(monkeypatch):
    db = _setup(monkeypatch)
    for section in ("194C", "194J", "194I", "194H"):
        v = _vendor(db, section)
        b = _bill(db, v, 5_00_000_00, f"L1-{section}")   # ₹5,00,000
        assert 0 < b["tds_paise"] < b["taxable_amount_paise"]   # rate-bounded


def test_l6_unknown_section_rejected(monkeypatch):
    db = _setup(monkeypatch)
    v = _vendor(db, "194ZZ")                        # not a real section
    with pytest.raises(HTTPException) as ex:
        _bill(db, v, 40_000_00, "X1")
    assert ex.value.status_code == 422
    assert "Unknown TDS section" in str(ex.value.detail)


def test_tds_applicable_without_section_rejected(monkeypatch):
    db = _setup(monkeypatch)
    v = _vendor(db, None, applicable=True)          # applicable but no section
    with pytest.raises(HTTPException) as ex:
        _bill(db, v, 40_000_00, "N1")
    assert ex.value.status_code == 422


def test_non_tds_vendor_no_deduction(monkeypatch):
    db = _setup(monkeypatch)
    v = _vendor(db, "194J", applicable=False)
    b = _bill(db, v, 40_000_00, "NT1")
    assert b["tds_paise"] == 0 and b["tds_rate_bps"] == 0
