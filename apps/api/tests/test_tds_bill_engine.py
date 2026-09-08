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
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI",
                                  "name": "Services", "kind": "service"})
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
        lines=[PurchaseBillLineIn(service_catalogue_id="SVC-1", description="svc", rate_paise=rate, quantity=1, gst_rate_percent=18.0)],
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
    """The bill that crosses the §194C aggregate withholds on the AGGREGATE.

    IT Act §194C(5): no deduction while a single sum stays within ₹30,000 and
    "the aggregate of the amounts of such sums credited or paid ... does not
    exceed one lakh rupees". Once it does, the liability is on that aggregate —
    the earlier bills are not forgiven, they simply had not been taxed yet.

    This assertion used to read ₹500 — 2% of the crossing bill alone. Five
    ₹25,000 bills then withheld ₹500 in total against ₹2,500 due on the
    ₹1,25,000 aggregate: an 80% short deduction, carrying §201(1A) interest
    at 1% a month and a §40(a)(ia) disallowance of 30% of the expenditure.
    """
    db = _setup(monkeypatch)
    v = _vendor(db, "194C")                        # single ₹30k, aggregate ₹1L
    # Four ₹25,000 bills: each below single threshold, aggregate never exceeds ₹1L.
    for i in range(4):
        bi = _bill(db, v, 25_000_00, f"C{i}")
        assert bi["tds_paise"] == 0
    # Fifth ₹25,000 bill tips the FY aggregate past ₹1,00,000 → TDS now applies,
    # on the whole ₹1,25,000 aggregate at the company rate, less the nil already
    # withheld on the four bills before it.
    b5 = _bill(db, v, 25_000_00, "C5")
    assert b5["tds_paise"] == 2_500_00            # 2% (company PAN) of ₹1,25,000
    assert b5["tds_rate_bps"] == 200
    # And every bill AFTER the crossing one charges the new aggregate less what
    # is already withheld (IT Act §200), so it settles back to 2% of the bill.
    # This is what pins the other half of the fix: _resolve_bill_resident_tds
    # must sum the FY's prior tds_paise, not just its prior taxable value. With
    # only the taxable half passed, the sixth bill re-charges the whole growing
    # aggregate from zero and withholds ₹3,000 instead of ₹500, and the seventh
    # ₹3,500 instead of ₹500 — over-withholding that grows with every bill.
    b6 = _bill(db, v, 25_000_00, "C6")
    assert b6["tds_paise"] == 500_00              # 2% of ₹1,50,000 less ₹2,500 held
    b7 = _bill(db, v, 25_000_00, "C7")
    assert b7["tds_paise"] == 500_00              # 2% of ₹1,75,000 less ₹3,000 held
    # Five bills' worth of aggregate, withheld once: ₹2,500 + ₹500 + ₹500 is
    # exactly 2% of the ₹1,75,000 credited to this vendor in the year.
    assert b5["tds_paise"] + b6["tds_paise"] + b7["tds_paise"] == 1_75_000_00 * 200 // 10000


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
