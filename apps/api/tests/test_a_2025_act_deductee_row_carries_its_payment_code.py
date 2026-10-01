"""A Form 140 row carries the payment code the product already knew (TDS-31).

WHAT WAS WRONG

    `domain/tds/vocabulary.payment_code_for` has answered fourteen sections from
    the Protean specification since 25-09-2026 and NOTHING CALLED IT. The three
    statement builders emitted `section` and `section_1961` on each deductee row
    and no `payment_code`, so a FY 2026-27 statement told the CA in one
    return-level sentence that "some lines' codes are not filled in" and showed
    no line that had one — while the portal wants a numeric code on every row of
    Form 138, 140 and 144 from April 2026.

WHAT THIS PINS

    * a 2025-Act row carries `payment_code` where the table answers it;
    * s.194C's two rows are read off the CONTRACTOR'S PAN, not off the rate the
      row happened to be deducted at — a no-PAN row deducted at 20% and a §197
      row at a lower rate still have a knowable class, and a missing PAN is a
      named gap rather than "other";
    * a section the table cannot answer is a NAMED gap with its own reason (194A
      and 194J(b) split on facts nobody records), never a guess;
    * a 1961-Act period carries NO code and NO gap — nothing is asked of it;
    * the keying sheet names the rows that still need a code keyed by hand.
"""
from __future__ import annotations

import pytest

import routers.purchase_bills as pb
import routers.purchase_payments as pp
import services.tds_return_service as trs
from domain.tds import deductee_payment_code as dpc
from domain.tds import keying_sheet
from domain.tds import vocabulary as v
from domain.tds.tds_computer import TDSDeducteeRecord
from models.invoices import PurchaseBillIn, PurchaseBillLineIn
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "id": "u1", "auth_user_id": "auth",
          "email": "ca@f.test", "role": "Partner"}
TAN = "MUMF12345G"

OLD_FY, OLD_Q, OLD_DATE = "2025-26", "Q1", "2025-05-12"
NEW_FY, NEW_Q, NEW_DATE = "2026-27", "Q1", "2026-05-12"

# PAN fourth character: P individual, C company, H HUF.
PAN_INDIVIDUAL = "AAAPB1234C"
PAN_COMPANY = "AAACB1234C"
PAN_HUF = "AAAHB1234C"


def _vendor(vid, section, pan):
    return {"id": vid, "firm_id": FIRM, "client_id": "CLI", "name": f"Vendor {vid}",
            "state_code": "27", "pan": pan, "is_active": True,
            "tds_applicable": True, "tds_section": section,
            "residential_status": "resident"}


@pytest.fixture
def db(monkeypatch):
    d = FakeDB()
    wire_e2e(monkeypatch, d, [pb, pp])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    d.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27AAAAA0000A1Z2"})
    for vid, section, pan in [
        ("C-IND", "194C", PAN_INDIVIDUAL),
        ("C-HUF", "194C", PAN_HUF),
        ("C-CO", "194C", PAN_COMPANY),
        ("C-NOPAN", "194C", None),
        ("H", "194H", PAN_COMPANY),
        ("A", "194A", PAN_INDIVIDUAL),
        ("J-B", "194J(B)", PAN_COMPANY),
        ("J-BARE", "194J", PAN_COMPANY),
    ]:
        d.seed("vendors", _vendor(vid, section, pan))
    seed_standard_coa(d, FIRM, "CLI")
    d.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI",
                                 "name": "Services", "kind": "service"})
    return d


def _bill(db, vendor_id, on, taxable=5_00_000_00):
    res = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id=vendor_id, bill_date=on, bill_no=f"B-{vendor_id}",
        lines=[PurchaseBillLineIn(service_catalogue_id="SVC-1", description="Work",
                                  hsn_sac="9987", quantity=1, rate_paise=taxable,
                                  gst_rate_percent=0.0)],
    ), CALLER)
    assert res["success"] is True, res
    assert pb.receive_purchase_bill(res["data"]["id"], CALLER)["success"] is True
    return res["data"]


def _26q(db, fy, q):
    return trs.tds_26q_from_books(db, FIRM, "CLI", fy, q, TAN,
                                  "Apex", "AAACA1234B", "Mumbai")


def _row(out, vendor_name):
    return next(d for d in out["deductees"] if d["deductee_name"] == vendor_name)


# ── the fixture has to produce rows at all ───────────────────────────────────

def test_the_fixture_really_files_a_row_per_vendor(db):
    """Guard — with no rows every assertion below is vacuous."""
    for vid in ("C-IND", "H", "A"):
        _bill(db, vid, NEW_DATE)
    out = _26q(db, NEW_FY, NEW_Q)
    assert len(out["deductees"]) == 3
    assert all(d["tds_deducted_paise"] > 0 for d in out["deductees"])


# ── a 2025-Act row carries its code ──────────────────────────────────────────

def test_a_held_section_carries_its_code_on_the_row(db):
    _bill(db, "H", NEW_DATE)
    out = _26q(db, NEW_FY, NEW_Q)
    row = _row(out, "Vendor H")
    assert row["section"] == "393(1)"
    assert row["section_1961"] == "194H"
    assert row["payment_code"] == "1006"
    assert row["payment_code_gap"] is None
    assert row["payment_code_assumption"] is None


@pytest.mark.parametrize("vendor_id,name,expected", [
    ("C-IND", "Vendor C-IND", "1023"),   # individual contractor
    ("C-HUF", "Vendor C-HUF", "1023"),   # HUF is the other half of 1023
    ("C-CO", "Vendor C-CO", "1024"),     # any other contractor
])
def test_194c_is_read_off_the_contractors_pan(db, vendor_id, name, expected):
    _bill(db, vendor_id, NEW_DATE)
    row = _row(_26q(db, NEW_FY, NEW_Q), name)
    assert row["payment_code"] == expected
    assert row["payment_code_gap"] is None


def test_194c_with_no_pan_is_a_named_gap_not_other(db):
    """`is_company_pan` answers True for a missing PAN because that is the safe
    direction for a RATE. For a LABEL on a filed statement it would be a guess:
    the contractor may be an individual whose PAN was never recorded."""
    _bill(db, "C-NOPAN", NEW_DATE)
    row = _row(_26q(db, NEW_FY, NEW_Q), "Vendor C-NOPAN")
    assert row["payment_code"] is None
    assert "no PAN" in row["payment_code_gap"]
    assert "1023" in row["payment_code_gap"] and "1024" in row["payment_code_gap"]


@pytest.mark.parametrize("deducted_at_pct", [20.0, 0.5, 0.0])
def test_the_contractor_class_does_not_depend_on_the_rate_the_row_was_deducted_at(
        deducted_at_pct):
    """The reason the class is read off the PAN and not off `tds_rate_pct`: a
    row at 20% (§206AA) or at a lower §197 rate carries a stored rate that is
    neither 1% nor 2%, and reading the rate would turn a knowable class into a
    gap on exactly the rows most likely to be questioned."""
    row = _record("194C", pan=PAN_INDIVIDUAL, rate_pct=deducted_at_pct)
    rows, _notes = trs._payment_codes(NEW_FY, [row])
    assert rows[0]["payment_code"] == "1023"
    # The vocabulary's own entry point still refuses a rate that is neither
    # of the section's, which is what it was written to do.
    assert v.payment_code_for("194C", rate_bps=int(deducted_at_pct * 100))[0] is None


@pytest.mark.parametrize("pan", ["AAA1B1234C", "AAA-B1234C", "AAAXB1234C"])
def test_194c_with_a_pan_that_has_no_holder_type_is_refused(pan):
    ans = dpc.for_line(NEW_FY, "194C", deductee_pan=pan)
    assert ans.code is None
    assert "not a PAN holder type" in ans.gap


# ── what the table cannot answer ─────────────────────────────────────────────

def test_194a_is_a_named_gap_with_its_own_reason(db):
    _bill(db, "A", NEW_DATE)
    row = _row(_26q(db, NEW_FY, NEW_Q), "Vendor A")
    assert row["payment_code"] is None
    assert "1020" in row["payment_code_gap"], "the three codes the section splits into"
    assert "age" in row["payment_code_gap"]


def test_194j_b_is_a_named_gap_naming_the_director_fee_split(db):
    _bill(db, "J-B", NEW_DATE)
    row = _row(_26q(db, NEW_FY, NEW_Q), "Vendor J-B")
    assert row["payment_code"] is None
    assert "1027" in row["payment_code_gap"] and "1028" in row["payment_code_gap"]


def test_a_bare_194j_says_to_record_the_clause(db):
    _bill(db, "J-BARE", NEW_DATE)
    row = _row(_26q(db, NEW_FY, NEW_Q), "Vendor J-BARE")
    assert row["payment_code"] is None
    assert "194J(a)" in row["payment_code_gap"]


def test_the_three_reasons_are_three():
    """194A, 194J(b) and bare 194J are different reasons and must not collapse
    into one paragraph."""
    reasons = {s: v.payment_code_for(s)[1].note
               for s in ("194A", "194J(B)", "194J", "194I", "194K")}
    assert len(set(reasons.values())) == len(reasons)


# ── the statement says it, once per section ──────────────────────────────────

def test_the_statement_names_the_sections_it_could_not_answer(db):
    _bill(db, "H", NEW_DATE)
    _bill(db, "A", NEW_DATE)
    out = _26q(db, NEW_FY, NEW_Q)
    notes = [g for g in out["statutory_gaps"] if "no payment code" in g]
    assert len(notes) == 1
    assert "s.194A" in notes[0] and "1 line " in notes[0]
    # The blanket sentence is still there: the table is held only in part.
    assert any("1001" in g for g in out["statutory_gaps"])


def test_a_statement_with_every_row_coded_names_no_per_row_gap(db):
    _bill(db, "H", NEW_DATE)
    out = _26q(db, NEW_FY, NEW_Q)
    assert not [g for g in out["statutory_gaps"] if "no payment code" in g]


# ── a 1961-Act period asks for no code ───────────────────────────────────────

def test_a_1961_act_row_carries_no_code_and_no_gap(db):
    """The old forms cite the alphabetic section code. A null `payment_code`
    with no gap says 'nothing is asked'; a gap here would send the CA looking
    for a code that does not exist."""
    _bill(db, "H", OLD_DATE)
    _bill(db, "A", OLD_DATE)
    out = _26q(db, OLD_FY, OLD_Q)
    for row in out["deductees"]:
        assert row["payment_code"] is None
        assert row["payment_code_gap"] is None
        assert row["payment_code_assumption"] is None
    assert not [g for g in out["statutory_gaps"] if "payment code" in g]


def test_the_keys_are_always_present(db):
    """An absent key and a null key read the same to a screen and are
    different bugs."""
    _bill(db, "H", OLD_DATE)
    row = _26q(db, OLD_FY, OLD_Q)["deductees"][0]
    for key in ("payment_code", "payment_code_gap", "payment_code_assumption"):
        assert key in row


# ── 24Q and 27Q rows, through the same helper ────────────────────────────────

def _record(section, pan="AAAPB1234C", rate_pct=1.0):
    return TDSDeducteeRecord(
        deductee_name="X", deductee_pan=pan, section=section,
        nature_of_payment="n", payment_date="2026-05-01",
        payment_amount_paise=1, tds_rate_pct=rate_pct, tds_deducted_paise=1,
        tds_deposited_paise=1, challan_no="", bsr_code="", challan_date="")


def test_a_salary_row_carries_1002_on_a_stated_default():
    rows, notes = trs._payment_codes(NEW_FY, [_record("192")])
    assert rows[0]["payment_code"] == "1002"
    assert "government department" in rows[0]["payment_code_assumption"]
    assert any("1001" in n and "1003" in n for n in notes), (
        "the default is named on the statement, not only on the row")


def test_the_assumption_is_named_once_however_many_rows_carry_it():
    _rows, notes = trs._payment_codes(NEW_FY, [_record("192"), _record("192"),
                                               _record("192")])
    assert len([n for n in notes if "1002" in n]) == 1


def test_a_27q_row_for_s195_is_a_named_gap():
    """s.195's own table (Form 144) carries codes per nature of remittance
    that the specification read here did not answer."""
    rows, notes = trs._payment_codes(NEW_FY, [_record("195")])
    assert rows[0]["payment_code"] is None
    assert rows[0]["payment_code_gap"]
    assert any("s.195" in n for n in notes)


def test_a_1961_act_period_is_silent_through_the_helper():
    rows, notes = trs._payment_codes(OLD_FY, [_record("194C"), _record("192")])
    assert rows == [{"payment_code": None, "payment_code_gap": None,
                     "payment_code_assumption": None}] * 2
    assert notes == []


# ── the keying sheet ─────────────────────────────────────────────────────────

def _data(deductees):
    return {"form": "140", "act": "Income-tax Act, 2025", "financial_year": NEW_FY,
            "quarter": "Q1", "tan": TAN, "deductor_name": "Apex",
            "deductor_pan": "AAACA1234B", "deductor_address": "Mumbai",
            "deductees": deductees, "challans": []}


def _dd(section, **over):
    row = {"deductee_name": "V", "deductee_pan": PAN_COMPANY, "section": "393(1)",
           "section_1961": section, "payment_amount_paise": 1,
           "tds_deducted_paise": 1, "bsr_code": "", "challan_no": "",
           "challan_date": "", "payment_code": None, "payment_code_gap": None}
    row.update(over)
    return row


def test_the_keying_sheet_names_the_rows_that_need_a_code_keyed_by_hand():
    sheet = keying_sheet.build(_data([
        _dd("194H", payment_code="1006"),
        _dd("194A", payment_code_gap="no code"),
        _dd("194A", payment_code_gap="no code"),
    ]))
    gap = next(g for g in sheet["gaps"] if "payment code" in g)
    assert gap.startswith("2 deductee row(s)")
    assert "194A" in gap and "194H" not in gap


def test_a_fully_coded_sheet_names_no_payment_code_gap():
    sheet = keying_sheet.build(_data([_dd("194H", payment_code="1006")]))
    assert not [g for g in sheet["gaps"] if "payment code" in g]


def test_a_snapshot_saved_before_the_field_existed_reads_as_nothing_known():
    """No `payment_code_gap` key at all: not a row with a gap and not a row
    with a code — and `tds_returns.fvu_json` holds such snapshots."""
    row = _dd("194A")
    del row["payment_code"], row["payment_code_gap"]
    sheet = keying_sheet.build(_data([row]))
    assert not [g for g in sheet["gaps"] if "payment code" in g]
