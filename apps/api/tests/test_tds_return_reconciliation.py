"""
TDS returns derive from posted books and reconcile to the General Ledger,
mirroring test_gst_return_reconciliation.py's pattern (audit H8 for TDS):

  - Form 26Q (vendor/non-salary TDS, IT Act §194 series) from posted purchase
    bills, reconciled to the "TDS Payable" GL account.
  - Form 24Q (salary TDS, IT Act §192) from finalized payroll runs,
    reconciled to the "TDS Payable - Salary" GL account.

We post real purchase bills / finalize real payroll runs through their actual
routers (so the journals are the SAME ones production posts), then derive the
return from books and assert it reconciles to those exact journal entries.
"""
import routers.purchase_bills as pb
import routers.payroll as payroll_mod
import services.tds_return_service as trs
from models.invoices import PurchaseBillIn, PurchaseBillLineIn
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "id": "u-int", "auth_user_id": "auth", "email": "ca@f.test", "role": "Partner"}
PERIOD_FY = "2025-26"
PERIOD_Q = "Q1"  # 2025-04-01 .. 2025-06-30
TAN = "MUMF12345G"


def _setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [pb, payroll_mod])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27AAAAA0000A1Z5", "financial_year_start": "2025-04-01"})
    # Company PAN (4th char != P/H) — non-individual rate applies.
    db.seed("vendors", {
        "id": "VEND1", "firm_id": FIRM, "client_id": "CLI", "name": "Sharma Consulting Pvt Ltd",
        "state_code": "27", "gstin": "27CCCCC2222C1Z5", "pan": "AAACS1234C",
        "tds_applicable": True, "tds_section": "194J", "tds_rate_bps": 1000,
        "opening_balance_paise": 0,
    })
    seed_standard_coa(db, FIRM, "CLI")  # includes "TDS Payable" (system_key="tds_payable")
    # Payroll accounts — not part of seed_standard_coa (accounting-cycle
    # focused); journal_for_payroll resolves these by name only.
    for name in ("TDS Payable - Salary", "Salaries Expense", "Net Salary Payable",
                 "PF Payable", "ESI Payable", "PT Payable"):
        db.seed("chart_of_accounts", {
            "firm_id": FIRM, "client_id": "CLI", "account_name": name, "is_active": True,
        })
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI",
                                  "name": "Professional Services", "kind": "service"})
    return db


def _receive_bill(db, no, rate, bill_date="2025-05-10"):
    res = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id="VEND1", bill_date=bill_date, bill_no=no,
        lines=[PurchaseBillLineIn(service_catalogue_id="SVC-1", description="consulting",
                                  rate_paise=rate, quantity=1, gst_rate_percent=18.0)],
    ), CALLER)
    assert res["success"] is True
    bill_id = res["data"]["id"]
    assert pb.receive_purchase_bill(bill_id, CALLER)["success"] is True
    return res["data"]


def test_26q_from_books_reconciles_to_tds_payable(monkeypatch):
    db = _setup(monkeypatch)
    bill = _receive_bill(db, "BILL-1", rate=5_00_000_00)  # ₹5,00,000 @18% intra, 194J TDS
    assert bill["tds_paise"] > 0  # sanity: TDS actually applied

    out = trs.tds_26q_from_books(db, FIRM, "CLI", PERIOD_FY, PERIOD_Q, TAN, "Apex Trading Solutions", "AAACA1234B", "Mumbai")
    rec = out["reconciliation"]

    assert out["form"] == "26Q"
    assert out["deductee_count"] == 1
    assert out["total_tds_deducted_paise"] == bill["tds_paise"]
    assert rec["account_found"] is True
    assert rec["books_paise"] == bill["tds_paise"]
    assert rec["ledger_paise"] == bill["tds_paise"]
    assert rec["matched"] is True
    d = out["deductees"][0]
    assert d["deductee_name"] == "Sharma Consulting Pvt Ltd"
    assert d["deductee_pan"] == "AAACS1234C"
    assert d["section"] == "194J"


def test_26q_apportions_deposited_challan_across_bills(monkeypatch):
    db = _setup(monkeypatch)
    bill1 = _receive_bill(db, "BILL-1", rate=5_00_000_00, bill_date="2025-04-15")
    bill2 = _receive_bill(db, "BILL-2", rate=5_00_000_00, bill_date="2025-05-15")
    total_tds = bill1["tds_paise"] + bill2["tds_paise"]

    db.seed("tds_challans", {
        "firm_id": FIRM, "client_id": "CLI", "challan_no": "CHN-1", "bsr_code": "1234567",
        "payment_date": "2025-06-07", "financial_year": PERIOD_FY, "quarter": PERIOD_Q,
        "section": "194J", "tds_paise": total_tds, "total_paise": total_tds, "status": "deposited",
    })

    out = trs.tds_26q_from_books(db, FIRM, "CLI", PERIOD_FY, PERIOD_Q, TAN, "Apex Trading Solutions", "AAACA1234B", "Mumbai")
    assert out["total_tds_deposited_paise"] == total_tds  # fully deposited, apportioned across both
    assert sum(d["tds_deposited_paise"] for d in out["deductees"]) == total_tds
    assert out["reconciliation"]["matched"] is True


def test_out_of_quarter_bills_excluded_from_26q(monkeypatch):
    db = _setup(monkeypatch)
    _receive_bill(db, "BILL-Q1", rate=5_00_000_00, bill_date="2025-05-10")
    _receive_bill(db, "BILL-Q2", rate=9_00_000_00, bill_date="2025-07-10")  # Q2, not Q1

    out = trs.tds_26q_from_books(db, FIRM, "CLI", PERIOD_FY, PERIOD_Q, TAN, "Apex Trading Solutions", "AAACA1234B", "Mumbai")
    assert out["deductee_count"] == 1
    assert out["reconciliation"]["matched"] is True


def _finalize_payroll(db, month="2025-05", basic_paise=3_00_000_00, pan="ABCDE1234F"):
    emp = db.seed("payroll_employees", {
        "firm_id": FIRM, "client_id": "CLI", "name": "Rahul Sharma", "pan": pan,
        "basic_paise": basic_paise, "hra_percent": 0.0, "da_percent": 0.0,
        "other_allowances_paise": 0, "lta_paise": 0, "medical_paise": 0,
        "special_allowance_paise": 0, "pf_applicable": False, "esi_applicable": False,
        "pt_applicable": False, "is_active": True, "status": "active",
    })
    # Attendance is entered, not defaulted. Migration 328 blocks a finalise with
    # an unresolved gap, and "nobody entered attendance" is one — this fixture
    # is about the 24Q reconciliation, so it takes the clean path rather than
    # the Partner override, which is exercised on its own elsewhere.
    year, mon = int(month[:4]), int(month[5:7])
    db.seed("attendance", {"firm_id": FIRM, "employee_id": emp["id"],
                           "month": mon, "year": year,
                           "working_days": 26, "days_present": 26,
                           "casual_leaves": 0, "sick_leaves": 0, "earned_leaves": 0,
                           "lop_days": 0})
    res = payroll_mod.create_run(payroll_mod.PayrollRunIn(client_id="CLI", month=month), CALLER)
    assert res["success"] is True
    run_id = res["data"]["id"]
    fin = payroll_mod.finalize_run(run_id, CALLER)
    assert fin["success"] is True
    slip = next(s for s in db.rows("payroll_slips") if s["run_id"] == run_id)
    return run_id, slip, emp


def test_24q_from_books_reconciles_to_tds_payable_salary(monkeypatch):
    db = _setup(monkeypatch)
    run_id, slip, emp = _finalize_payroll(db)
    assert slip["tds_paise"] > 0  # sanity: high enough salary to actually withhold TDS

    out = trs.tds_24q_from_books(db, FIRM, "CLI", PERIOD_FY, PERIOD_Q, TAN, "Apex Trading Solutions", "AAACA1234B", "Mumbai")
    rec = out["reconciliation"]

    assert out["form"] == "24Q"
    assert out["deductee_count"] == 1
    assert out["total_tds_deducted_paise"] == slip["tds_paise"]
    assert rec["account_found"] is True
    assert rec["books_paise"] == slip["tds_paise"]
    assert rec["ledger_paise"] == slip["tds_paise"]
    assert rec["matched"] is True
    d = out["deductees"][0]
    assert d["deductee_name"] == "Rahul Sharma"
    assert d["deductee_pan"] == "ABCDE1234F"
    assert d["section"] == "192"


def test_24q_late_finalized_run_still_reconciles(monkeypatch):
    """Reconciliation keys off the run's own journal_entry_id, never a calendar
    date-range scan.

    This test was written when journal_for_payroll dated the accrual to the day
    it was FINALIZED rather than to the payroll period, which made a late
    finalisation the ordinary case. That is fixed — the accrual is now dated to
    the payroll month's end (core.ist_clock.month_end_date) — but the property
    still has to hold and the test is still worth its keep, because the entry
    date can legitimately move: a correction reverses and reposts, and a CA can
    re-date a manual journal. The forced 2025-09-15 below is now a deliberately
    hostile date rather than a simulation of normal behaviour."""
    db = _setup(monkeypatch)
    run_id, slip, emp = _finalize_payroll(db, month="2025-06")  # Q1 payroll month
    # Simulate the journal having actually been dated well after Q1 closed —
    # exactly the "late finalization" scenario this reconciliation must survive.
    je = next(j for j in db.rows("journal_entries") if j["id"] == db.rows("payroll_runs")[0]["journal_entry_id"])
    je["entry_date"] = "2025-09-15"

    out = trs.tds_24q_from_books(db, FIRM, "CLI", PERIOD_FY, PERIOD_Q, TAN, "Apex Trading Solutions", "AAACA1234B", "Mumbai")
    assert out["reconciliation"]["matched"] is True
