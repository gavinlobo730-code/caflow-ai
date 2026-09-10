"""
TDS-06 — the challan on a 26Q/24Q deductee row, and the deposited column.

WHAT WAS WRONG

    services/tds_return_service.py stamped every deductee row with

        next(c for c in challans if parent_of(c["section"]) == parent_of(section))

    — the FIRST challan for the section, in an `.order("id")` order arbitrary
    with respect to time. Rule 30(2) gives a quarter THREE monthly deposits,
    all carrying the same section, so every June deductee was labelled with
    April's BSR code and serial. The FVU cross-checks a deductee row against
    the challan it sits under, so the statement is rejected — or accepted with
    the wrong challan, and every one of those deductees' 26AS entries is booked
    'U' (unmatched), which they then chase the client about. The salary mirror
    was blunter: `challans[0]`.

    The deposited COLUMN was a second wrong answer. It apportioned the
    section's whole quarterly deposit across the section's deductions by
    largest-remainder weight, so a bill fully deposited on 7 May read as partly
    deposited whenever the QUARTER as a whole was short.

WHAT IS ASSERTED

    That the row names the challan that actually paid it, that a fully-paid
    month stays whole when a later month is short, and that a shortfall is
    reported rather than smeared. domain/tds/challan_mapping.py holds the
    reasoning; these drive it through the real return builders.
"""
import routers.purchase_bills as pb
import routers.payroll as payroll_mod
import services.tds_return_service as trs
from domain.tds import challan_mapping
from models.invoices import PurchaseBillIn, PurchaseBillLineIn
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "id": "u-int", "auth_user_id": "auth", "email": "ca@f.test", "role": "Partner"}
FY = "2025-26"
Q = "Q1"                       # 2025-04-01 .. 2025-06-30
TAN = "MUMF12345G"


def _setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [pb, payroll_mod])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27AAAAA0000A1Z5"})
    db.seed("vendors", {
        "id": "VEND1", "firm_id": FIRM, "client_id": "CLI", "name": "Sharma Consulting Pvt Ltd",
        "state_code": "27", "gstin": "27CCCCC2222C1Z5", "pan": "AAACS1234C",
        "tds_applicable": True, "tds_section": "194J", "tds_rate_bps": 1000,
    })
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI",
                                  "name": "Professional Services", "kind": "service"})
    return db


def _bill(db, no, rate, on):
    res = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id="VEND1", bill_date=on, bill_no=no,
        lines=[PurchaseBillLineIn(service_catalogue_id="SVC-1", description="Consulting",
                                  hsn_sac="9982", quantity=1, rate_paise=rate,
                                  gst_rate_percent=0.0)],
    ), CALLER)
    assert res["success"] is True, res
    bill = res["data"]
    assert pb.receive_purchase_bill(bill["id"], CALLER)["success"] is True
    return bill


def _challan(db, no, paid_on, tds_paise, section="194J"):
    return db.seed("tds_challans", {
        "firm_id": FIRM, "client_id": "CLI", "challan_no": no, "bsr_code": f"BSR{no}",
        "payment_date": paid_on, "financial_year": FY, "quarter": Q,
        "section": section, "tds_paise": tds_paise, "total_paise": tds_paise,
        "status": "deposited",
    })


def _26q(db):
    return trs.tds_26q_from_books(db, FIRM, "CLI", FY, Q, TAN,
                                  "Apex Trading Solutions", "AAACA1234B", "Mumbai")


def _by_bill(out, bill_no):
    return next(d for d in out["deductees"] if bill_no in d["nature_of_payment"])


# ── The challan on the row ─────────────────────────────────────────────────

def test_each_month_names_its_own_challan_not_the_first_one(monkeypatch):
    """Three monthly deposits under Rule 30(2), three different CINs."""
    db = _setup(monkeypatch)
    apr = _bill(db, "B-APR", 1_00_000_00, "2025-04-15")     # ₹10,000 TDS
    may = _bill(db, "B-MAY", 2_00_000_00, "2025-05-15")     # ₹20,000
    jun = _bill(db, "B-JUN", 3_00_000_00, "2025-06-15")     # ₹30,000
    # Each bill crosses the §194J aggregate as the year builds, so the
    # deducted figures are the year's catch-up rather than 10% of each bill.
    _challan(db, "C-APR", "2025-05-07", apr["tds_paise"])
    _challan(db, "C-MAY", "2025-06-07", may["tds_paise"])
    _challan(db, "C-JUN", "2025-07-07", jun["tds_paise"])

    out = _26q(db)
    assert _by_bill(out, "B-APR")["challan_no"] == "C-APR"
    assert _by_bill(out, "B-MAY")["challan_no"] == "C-MAY"
    assert _by_bill(out, "B-JUN")["challan_no"] == "C-JUN"
    assert _by_bill(out, "B-JUN")["bsr_code"] == "BSRC-JUN"
    assert out["challan_gaps"] == []


def test_a_fully_paid_month_stays_whole_when_a_later_one_is_short(monkeypatch):
    """The shortfall lands on the LAST deductions, not on everybody a bit.

    April was deposited in full on 7 May. Whether June was paid has nothing to
    do with that, and a proportion across the quarter said otherwise.
    """
    db = _setup(monkeypatch)
    apr = _bill(db, "B-APR", 1_00_000_00, "2025-04-15")
    jun = _bill(db, "B-JUN", 3_00_000_00, "2025-06-15")
    _challan(db, "C-APR", "2025-05-07", apr["tds_paise"])   # June never deposited

    out = _26q(db)
    assert _by_bill(out, "B-APR")["tds_deposited_paise"] == apr["tds_paise"]
    assert _by_bill(out, "B-APR")["challan_no"] == "C-APR"
    assert _by_bill(out, "B-JUN")["tds_deposited_paise"] == 0
    assert _by_bill(out, "B-JUN")["challan_no"] == ""

    gaps = [g for g in out["challan_gaps"]
            if g["code"] == challan_mapping.GAP_DEDUCTIONS_NOT_DEPOSITED]
    assert len(gaps) == 1
    assert gaps[0]["section"] == "194J"
    assert gaps[0]["shortfall_paise"] == jun["tds_paise"]
    assert "201(1A)" in gaps[0]["message"]


def test_one_challan_covering_two_months_is_not_split_by_month(monkeypatch):
    """A catch-up deposit is a real thing and the RPU allows it.

    An earlier draft of the mapping gave every challan a deduction MONTH under
    Rule 30(2). It read a single 7 June challan paying both April's and May's
    tax as leaving April unpaid, which is a wrong return — the RPU's challan
    row has no deduction-month field at all.
    """
    db = _setup(monkeypatch)
    apr = _bill(db, "B-APR", 1_00_000_00, "2025-04-15")
    may = _bill(db, "B-MAY", 2_00_000_00, "2025-05-15")
    both = apr["tds_paise"] + may["tds_paise"]
    _challan(db, "C-ONE", "2025-06-07", both)

    out = _26q(db)
    assert out["total_tds_deposited_paise"] == both
    assert _by_bill(out, "B-APR")["tds_deposited_paise"] == apr["tds_paise"]
    assert _by_bill(out, "B-MAY")["tds_deposited_paise"] == may["tds_paise"]
    assert _by_bill(out, "B-APR")["challan_no"] == "C-ONE"
    assert out["challan_gaps"] == []


def test_a_challan_depositing_more_than_the_books_deducted_is_reported(monkeypatch):
    """Either a deduction is missing, or interest was booked as tax."""
    db = _setup(monkeypatch)
    apr = _bill(db, "B-APR", 1_00_000_00, "2025-04-15")
    _challan(db, "C-BIG", "2025-05-07", apr["tds_paise"] + 5_000_00)

    out = _26q(db)
    gaps = [g for g in out["challan_gaps"]
            if g["code"] == challan_mapping.GAP_CHALLAN_EXCEEDS_DEDUCTIONS]
    assert len(gaps) == 1
    assert gaps[0]["surplus_paise"] == 5_000_00
    assert gaps[0]["challan_nos"] == ["C-BIG"]


def test_a_challan_for_another_section_pays_nothing_here(monkeypatch):
    """§194C money does not settle a §194J deduction."""
    db = _setup(monkeypatch)
    apr = _bill(db, "B-APR", 1_00_000_00, "2025-04-15")
    _challan(db, "C-194C", "2025-05-07", apr["tds_paise"], section="194C")

    out = _26q(db)
    assert _by_bill(out, "B-APR")["tds_deposited_paise"] == 0
    assert _by_bill(out, "B-APR")["challan_no"] == ""
    codes = {g["code"] for g in out["challan_gaps"]}
    assert challan_mapping.GAP_DEDUCTIONS_NOT_DEPOSITED in codes
    assert challan_mapping.GAP_CHALLAN_EXCEEDS_DEDUCTIONS in codes


def test_both_sides_are_folded_to_the_parent_section(monkeypatch):
    """A CA types "194J" whichever limb the bill was under.

    Same rule CLAUDE.md states for the 2025-Act fork ("challan matching accepts
    BOTH labels in every period"), applied to a clause key: matching on the
    exact string would leave every §194J(A) deduction with a blank CIN,
    invisible until FVU validation.

    Asserted through a stub rather than a real limb key, because there is no
    limb key to use — `section_rates.parent_of` is deliberately the identity for
    every section the registry holds today, and
    tests/test_a_section_with_two_limbs_says_which_one_it_priced.py pins it that
    way so that adding one is a visible act. What can be pinned now is that the
    fold is APPLIED, to the challan as well as to the deduction, so the day a
    limb exists the matching follows it.
    """
    monkeypatch.setattr(challan_mapping, "parent_of",
                        lambda s, fy=None: str(s).split("(")[0])
    m = challan_mapping.assign(
        [{"id": "d1", "section": "194J(A)", "on_date": "2025-04-15",
          "doc_no": "B-1", "tds_paise": 10_000_00}],
        [{"id": "c1", "section": "194J", "challan_no": "C-1",
          "payment_date": "2025-05-07", "tds_paise": 10_000_00}])
    assert m.for_deduction("d1").challan["challan_no"] == "C-1"
    assert m.for_deduction("d1").deposited_paise == 10_000_00
    assert m.gaps == []


def test_interest_and_penalty_on_a_challan_never_pay_a_deductee(monkeypatch):
    """tds_paise is the capacity, not total_paise.

    §201(1A) interest and a §271C penalty are the DEDUCTOR's own liability and
    appear against no deductee. Counting them would report a vendor's tax as
    deposited out of the deductor's fine.
    """
    m = challan_mapping.assign(
        [{"id": "d1", "section": "194J", "on_date": "2025-04-15",
          "doc_no": "B-1", "tds_paise": 10_000_00}],
        [{"id": "c1", "section": "194J", "challan_no": "C-1",
          "payment_date": "2025-05-07",
          "tds_paise": 6_000_00, "interest_paise": 3_000_00,
          "penalty_paise": 1_000_00, "total_paise": 10_000_00}])
    assert m.for_deduction("d1").deposited_paise == 6_000_00
    assert m.gaps[0]["shortfall_paise"] == 4_000_00


# ── The salary mirror, which was blunter ───────────────────────────────────

def test_the_salary_return_names_the_challan_too(monkeypatch):
    """24Q used `challans[0]` — the first §192 challan of the quarter, full stop.

    Every employee in the quarter carried it, so an April payslip and a June
    payslip pointed at the same CIN and the same BSR code. Rule 30(2) makes
    those two different deposits.
    """
    m = challan_mapping.assign(
        [{"id": "slip-apr", "section": "192", "on_date": "2025-04-30",
          "doc_no": "E1", "tds_paise": 5_000_00},
         {"id": "slip-may", "section": "192", "on_date": "2025-05-31",
          "doc_no": "E1", "tds_paise": 5_000_00},
         {"id": "slip-jun", "section": "192", "on_date": "2025-06-30",
          "doc_no": "E1", "tds_paise": 5_000_00}],
        [{"id": "c1", "section": "192", "challan_no": "S-APR",
          "payment_date": "2025-05-07", "tds_paise": 5_000_00},
         {"id": "c2", "section": "192", "challan_no": "S-MAY",
          "payment_date": "2025-06-07", "tds_paise": 5_000_00},
         {"id": "c3", "section": "192", "challan_no": "S-JUN",
          "payment_date": "2025-07-07", "tds_paise": 5_000_00}])
    assert m.for_deduction("slip-apr").challan["challan_no"] == "S-APR"
    assert m.for_deduction("slip-may").challan["challan_no"] == "S-MAY"
    assert m.for_deduction("slip-jun").challan["challan_no"] == "S-JUN"
    assert m.gaps == []


def test_a_deduction_straddling_two_challans_is_reported_under_the_first(monkeypatch):
    """26Q's annexure asks for the amount credited on a date, not an instalment.

    Splitting one bill into two deductee rows to match two challans would
    report a payment that was never made twice. The RPU allows a deductee row
    under one challan; the deposited figure still says how much was covered.
    """
    m = challan_mapping.assign(
        [{"id": "d1", "section": "194J", "on_date": "2025-04-15",
          "doc_no": "B-1", "tds_paise": 10_000_00}],
        [{"id": "c1", "section": "194J", "challan_no": "C-1",
          "payment_date": "2025-05-07", "tds_paise": 4_000_00},
         {"id": "c2", "section": "194J", "challan_no": "C-2",
          "payment_date": "2025-05-20", "tds_paise": 6_000_00}])
    assert m.for_deduction("d1").challan["challan_no"] == "C-1"
    assert m.for_deduction("d1").deposited_paise == 10_000_00
    assert m.gaps == []
