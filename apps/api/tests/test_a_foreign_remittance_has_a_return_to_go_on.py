"""
TDS-09 — Form 27Q, and the advance that reaches 26Q.

WHAT WAS WRONG

    §195 deductions were computed by domain/tds/section_195.py, registered in
    full (country, TIN, surcharge, cess, the reason a nil was nil), EXCLUDED
    from 26Q by name with a reason — Rule 31A(4)(a) gives 26Q the payments to
    residents — and given a deadline on the compliance calendar. There was
    nothing to file them on. A client pays a Singapore consultant, the platform
    gets every part of it right, and then the CA rebuilds the statement by hand
    from the deduction list.

    And a second, newer hole: migration 358 made a vendor ADVANCE withhold,
    because §194/§195 charge at credit or payment whichever is EARLIER. Those
    deductions posted to TDS Payable and reached the register, and
    `tds_26q_from_books` read only `purchase_bills` — so a real deduction was in
    the ledger, in the register, and off the statement.

WHAT IS ASSERTED

    That both charging events reach the return they belong on, that residency
    routes a row rather than the section number, that a NIL remittance is a row
    with a reason on 27Q and no row at all on 26Q, and that the two returns
    reconcile against the same control account without double-counting a
    quarter.
"""
import pytest

import routers.purchase_bills as pb
import routers.purchase_payments as pp
import services.tds_return_service as trs
from models.invoices import (
    PurchaseBillIn, PurchaseBillLineIn, PurchasePaymentIn,
)
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "id": "u1", "auth_user_id": "auth", "email": "ca@f.test", "role": "Partner"}
FY = "2025-26"
Q = "Q1"
TAN = "MUMF12345G"


def _setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [pb, pp])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27AAAAA0000A1Z5"})
    # A resident contractor and a non-resident consultant, in one client's books.
    db.seed("vendors", {
        "id": "RES", "firm_id": FIRM, "client_id": "CLI", "name": "Bharat Constructions Pvt Ltd",
        "state_code": "27", "pan": "AAACB1234C", "is_active": True,
        "tds_applicable": True, "tds_section": "194C", "residential_status": "resident",
    })
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI",
                                  "name": "Civil works", "kind": "service"})
    return db


def _non_resident(db, **extra):
    row = {
        "id": "NRI", "firm_id": FIRM, "client_id": "CLI", "name": "Lion City Advisors Pte Ltd",
        "state_code": "97", "pan": None, "is_active": True, "tds_applicable": True,
        "tds_section": "195", "residential_status": "non_resident",
        "country_of_residence": "SG", "tax_identification_number": "SG-201512345K",
        "email": "ap@lioncity.example", "phone": "+6561234567",
        "address": "1 Raffles Place, Singapore",
        "non_resident_payee_class": "foreign_company",
    }
    row.update(extra)
    return db.seed("vendors", row)


def _bill(db, vendor_id, no, taxable, on):
    res = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id=vendor_id, bill_date=on, bill_no=no,
        lines=[PurchaseBillLineIn(service_catalogue_id="SVC-1", description="Work",
                                  hsn_sac="9954", quantity=1, rate_paise=taxable,
                                  gst_rate_percent=0.0)],
    ), CALLER)
    assert res["success"] is True, res
    bill = res["data"]
    assert pb.receive_purchase_bill(bill["id"], CALLER)["success"] is True
    return bill


def _advance(db, vendor_id, amount, on):
    res = pp.create_purchase_payment(PurchasePaymentIn(
        client_id="CLI", vendor_id=vendor_id, payment_date=on, amount_paise=amount,
    ), CALLER)
    assert res["success"] is True, res
    return res["data"]


def _26q(db):
    return trs.tds_26q_from_books(db, FIRM, "CLI", FY, Q, TAN, "Apex", "AAACA1234B", "Mumbai")


def _27q(db):
    return trs.tds_27q_from_books(db, FIRM, "CLI", FY, Q, TAN, "Apex", "AAACA1234B", "Mumbai")


# ── The advance reaching 26Q ───────────────────────────────────────────────

def test_an_advance_appears_on_26q_and_reconciles(monkeypatch):
    """§194C charges at credit OR payment, whichever is earlier.

    Before migration 358 nothing withheld on an advance so nothing was missing.
    Once it does, a return that reads only purchase_bills leaves a real
    deduction off the statement while the GL and the register both hold it —
    and then the reconciliation fails, because the GL movement includes it.
    """
    db = _setup(monkeypatch)
    adv = _advance(db, "RES", 5_00_000_00, "2025-04-10")
    assert adv["tds_paise"] == 10_000_00

    out = _26q(db)
    assert out["deductee_count"] == 1
    row = out["deductees"][0]
    assert row["tds_deducted_paise"] == 10_000_00
    assert row["payment_amount_paise"] == 5_00_000_00     # the advance, not the whole payment
    assert row["section"] == "194C"
    assert "Advance" in row["nature_of_payment"]
    assert out["reconciliation"]["matched"] is True
    assert out["source"] == "posted_purchase_bills_and_advances"


def test_a_bill_and_an_advance_are_two_rows_not_one(monkeypatch):
    """Two charging events, two deductee lines, one reconciled quarter."""
    db = _setup(monkeypatch)
    _advance(db, "RES", 5_00_000_00, "2025-04-10")
    _bill(db, "RES", "B-1", 5_00_000_00, "2025-05-05")    # absorbs the advance, withholds 0
    _bill(db, "RES", "B-2", 3_00_000_00, "2025-06-05")    # 2% of its own value

    out = _26q(db)
    # The bill that absorbed the advance withheld nothing, so it is not a
    # deduction and 26Q does not report it — the same asymmetry a
    # sub-threshold bill has always had.
    assert out["deductee_count"] == 2
    assert out["total_tds_deducted_paise"] == 16_000_00
    assert out["reconciliation"]["matched"] is True


def test_a_sub_threshold_advance_is_not_a_26q_deductee(monkeypatch):
    """26Q reports DEDUCTIONS. A ₹25,000 advance under §194C's single limb
    counts toward the year's aggregate and is not one."""
    db = _setup(monkeypatch)
    adv = _advance(db, "RES", 25_000_00, "2025-04-10")
    assert adv["tds_paise"] == 0 and adv["tds_base_paise"] == 25_000_00

    out = _26q(db)
    assert out["deductee_count"] == 0


# ── 27Q itself ─────────────────────────────────────────────────────────────

def test_a_foreign_remittance_is_on_27q_and_off_26q(monkeypatch):
    """Rule 31A(4): (a) residents on 26Q, (b) non-residents on 27Q."""
    db = _setup(monkeypatch)
    _non_resident(db, trc_on_file=True, form_10f_on_file=True,
                  section_195_nature_of_income="fees_for_technical_services")
    db.seed("dtaa_treaty_rates", {
        "firm_id": FIRM, "country_code": "SG", "nature": "fees_for_technical_services",
        "rate_bps": 1000, "no_article": False,
    })
    bill = _bill(db, "NRI", "F-1", 10_00_000_00, "2025-05-10")
    assert bill["tds_section"] == "195"
    assert bill["tds_paise"] > 0

    q26 = _26q(db)
    assert q26["deductee_count"] == 0
    assert q26["excluded_non_resident"]["bill_count"] == 1
    assert "27Q" in q26["excluded_non_resident"]["reason"]

    q27 = _27q(db)
    assert q27["deductee_count"] == 1
    row = q27["deductees"][0]
    assert row["section"] == "195"
    assert row["country_of_residence"] == "SG"
    assert row["deductee_tin"] == "SG-201512345K"
    assert row["tds_deducted_paise"] == bill["tds_paise"]
    assert row["non_deduction_reason"] is None
    assert q27["form"] == "27Q"


def test_a_nil_remittance_is_a_row_with_a_reason(monkeypatch):
    """An import from a supplier with no PE is not chargeable under §195.

    *GE India Technology Centre (P) Ltd v. CIT* (2010) 327 ITR 456 — §195 reaches
    only a sum "chargeable under the provisions of this Act", so the right
    withholding is NIL. 27Q reports the remittance anyway, with its basis; 26Q
    would not report it at all, and neither would a return keyed on tds_paise.
    """
    db = _setup(monkeypatch)
    # The nature key the rate table actually prices — domain/tds/section_195_-
    # rates.NATURE_BUSINESS_PROFITS_NO_PE. It exists and resolves to zero so the
    # nil is a priced ANSWER rather than a missing rate.
    _non_resident(db, no_pe_declaration_on_file=True,
                  section_195_nature_of_income="business_profits_no_pe")
    bill = _bill(db, "NRI", "F-NIL", 10_00_000_00, "2025-05-10")
    assert bill["tds_paise"] == 0
    assert bill["tds_section"] == "195"

    q27 = _27q(db)
    assert q27["deductee_count"] == 1
    assert q27["nil_deduction_count"] == 1
    row = q27["deductees"][0]
    assert row["tds_deducted_paise"] == 0
    assert row["non_deduction_reason"] is not None
    assert "Nil withheld under section 195" in row["non_deduction_reason"]
    # It reconciles at zero against zero, because a nil moves no ledger.
    assert q27["reconciliation"]["matched"] is True
    assert any("withheld nothing" in w for w in q27["warnings"])


def test_a_nil_with_no_basis_recorded_is_a_validation_error(monkeypatch):
    """Rule 31A(4) reports a nil WITH its reason. A blank leaves the deductor
    an assessee in default under §201(1) with nothing on the record."""
    from domain.tds.tds_computer import TDSComputer, TDS27QDeducteeRecord
    payload = TDSComputer().compute_27q(
        tan=TAN, deductor_name="Apex", deductor_pan="AAACA1234B",
        deductor_address="Mumbai", financial_year=FY, quarter=Q,
        deductees=[TDS27QDeducteeRecord(
            deductee_name="Lion City Advisors Pte Ltd", deductee_pan="PANNOTAVBL",
            section="195", nature_of_payment="business_profits",
            payment_date="2025-05-10", payment_amount_paise=10_00_000_00,
            tds_rate_pct=0.0, tds_deducted_paise=0, tds_deposited_paise=0,
            challan_no="", bsr_code="", challan_date="",
            country_of_residence="SG", deductee_tin="SG-1",
            non_deduction_reason=None)],
        challans=[])
    assert any("no reason is recorded" in e for e in payload.validation_errors)


def test_a_payee_with_no_pan_needs_a_country_and_a_tin(monkeypatch):
    """The FVU identifies a non-PAN payee by country and TIN.

    §206AA's 20% floor is deliberately NOT re-asserted here — §206AA(7) with
    Rule 37BC lets a non-resident out of it on six particulars, which
    domain/tds/section_195.py has already weighed. Re-checking the floor would
    reject the very returns the carve-out exists for.
    """
    from domain.tds.tds_computer import TDSComputer, TDS27QDeducteeRecord
    payload = TDSComputer().compute_27q(
        tan=TAN, deductor_name="Apex", deductor_pan="AAACA1234B",
        deductor_address="Mumbai", financial_year=FY, quarter=Q,
        deductees=[TDS27QDeducteeRecord(
            deductee_name="Anon Ltd", deductee_pan="PANNOTAVBL", section="195",
            nature_of_payment="royalty", payment_date="2025-05-10",
            payment_amount_paise=10_00_000_00, tds_rate_pct=10.0,
            tds_deducted_paise=1_04_000_00, tds_deposited_paise=1_04_000_00,
            challan_no="C-1", bsr_code="1234567", challan_date="2025-06-07")],
        challans=[])
    assert any("no country of residence" in e for e in payload.validation_errors)
    assert any("tax identification number" in e for e in payload.validation_errors)
    # Not the §206AA floor — a 10% treaty rate is exactly what Rule 37BC allows.
    assert not any("206AA" in e for e in payload.validation_errors)


def test_the_surcharge_and_cess_survive_to_the_deductee_row(monkeypatch):
    """27Q's annexure reports tax, surcharge and cess in three columns.

    §195 charges "at the rates in force" under Part II of the First Schedule
    with §115A, and Part II carries surcharge ladders and a 4% cess the
    resident series does not. So the three figures do not multiply out, and
    tds_rate_pct is the BASE rate — restating any of them to make the
    arithmetic close would put a figure in the return that is not what
    happened.
    """
    db = _setup(monkeypatch)
    _non_resident(db, section_195_nature_of_income="royalty")
    bill = _bill(db, "NRI", "F-ROY", 1_00_00_000_00, "2025-05-10")
    assert bill["tds_paise"] > 0

    q27 = _27q(db)
    row = q27["deductees"][0]
    assert row["cess_paise"] > 0
    assert row["tds_deducted_paise"] == (
        bill["tds_paise"])
    assert q27["total_cess_paise"] == row["cess_paise"]
    assert q27["total_surcharge_paise"] == row["surcharge_paise"]
    # The base rate alone does not reproduce the tax.
    assert row["tds_deducted_paise"] != int(
        row["payment_amount_paise"] * row["tds_rate_pct"] / 100)


def test_the_unverified_rate_registry_says_so_on_the_return(monkeypatch):
    """Every year in domain/tds/section_195_rates.py carries verified=False —
    reconciled against §115A and Part II, not confirmed line by line. Said on
    the return the figures are going into, not only in the module."""
    db = _setup(monkeypatch)
    _non_resident(db, section_195_nature_of_income="royalty")
    _bill(db, "NRI", "F-1", 10_00_000_00, "2025-05-10")
    q27 = _27q(db)
    assert any("confirmed line by line" in w for w in q27["warnings"])
