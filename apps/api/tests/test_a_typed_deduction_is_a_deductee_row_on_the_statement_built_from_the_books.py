"""A deduction typed on the TDS screen is a deductee row on the 26Q built from the books (POST-A-078, the carrying half).

WHAT WAS WRONG
    `tds_26q_from_books` read posted purchase bills and withholding advances only. A deduction a CA typed on the TDS screen is a deduction the deductor made (a
    register row neither a bill nor an advance wrote), and it was NAMED on the statement and never carried, with a sentence telling the CA to key it from the register
    by hand. Since a typed row that names a supplier also lowers that supplier's later bills' withholding (migration 594), a statement keyed without it under-reported
    tax the books had already counted. And the statement's challan fill ignored the typed rows that the register's own readers (the deposit worksheet, Form 3CD
    clause 34, the TDS screen) put in the same fill, so the two disagreed about which deduction a challan paid.

WHAT IS HELD HERE
    * a typed row is a deductee row with the payee the register recorded (or the supplier's own record where it names one), the section, the date, the payment, the
      rate and the tax it stored, and the certificate it was made under; the row says it was recorded by the TDS register;
    * it is filled from the quarter's challans by the same FIFO as a bill's, in date order with the register's tie-break, so the statement and the register agree
      about which deduction a challan paid;
    * the statement's totals hold the typed tax, and the tie-out with the TDS Payable account compares the documents' tax alone (`books_paise`), with the typed tax
      beside it (`typed_paise`), because no journal stands behind a typed deduction;
    * a row naming a non-resident supplier is excluded to the non-resident note like a bill, and a row recorded for another statement is named and not carried;
    * a typed row that may be a document already on the statement is named, never dropped; the note says which rows name no supplier;
    * a 2025-Act statement carries the row's payment code (or names why not), and 27Q and 24Q carry no typed rows.
"""
from __future__ import annotations

from domain.tds import deposit_due
from services.tds_return_service import tds_26q_from_books
from tests.e2e_harness import FakeDB

FIRM = "F1"
CLIENT = "C1"
PAN_COMPANY = "AAACA1234A"
PAN_PERSON = "AAGPP7788R"


def _typed(rid, *, day="2025-10-12", section="194J", pan=PAN_COMPANY, name="Acme Services", payment=1_00_000_00, tds=10_000_00,
           vendor=None, rate=10, lower=False, cert=None, return_type="26Q", nature=None):
    return {"id": rid, "firm_id": FIRM, "client_id": CLIENT, "deductee_name": name, "deductee_pan": pan, "section": section, "transaction_date": day,
            "payment_amount_paise": payment, "tds_paise": tds, "tds_rate_pct": rate, "is_lower_deduction": lower, "lower_deduction_cert": cert,
            "nature_of_payment": nature, "vendor_id": vendor, "return_type": return_type, "purchase_bill_id": None, "purchase_payment_id": None}


def _bill(db, bid="b1", *, day="2025-10-25", taxable=18_000_00, tds=360_00, vendor="v1", section="194C", no="BILL-1"):
    db.seed("purchase_bills", {"id": bid, "firm_id": FIRM, "client_id": CLIENT, "vendor_id": vendor, "bill_no": no, "bill_date": day, "status": "received",
                               "taxable_amount_paise": taxable, "total_paise": taxable, "tds_paise": tds, "tds_rate_bps": 200, "tds_section": section,
                               "journal_entry_id": None})


def _vendor(db, vid="v1", *, name="Pinnacle Engineering", pan="AAGCP7788R", status="resident"):
    db.seed("vendors", {"id": vid, "firm_id": FIRM, "name": name, "pan": pan, "residential_status": status})


def _challan(db, no, paid_on, tds, *, section="194J", fy="2025-26", q="Q3"):
    db.seed("tds_challans", {"id": f"ch-{no}", "firm_id": FIRM, "client_id": CLIENT, "challan_no": no, "bsr_code": f"BSR{no}", "payment_date": paid_on,
                             "financial_year": fy, "quarter": q, "section": section, "tds_paise": tds, "total_paise": tds, "status": "deposited"})


def _build(db, *, fy="2025-26", quarter="Q3"):
    return tds_26q_from_books(db, FIRM, CLIENT, fy, quarter, "MUMP12345A", "Client Pvt Ltd", "AAACC1111C", "Mumbai")


def _row(out, name):
    return next(d for d in out["deductees"] if d["deductee_name"] == name)


# ── a typed row is a deductee row ────────────────────────────────────────────

def test_a_typed_row_is_a_deductee_row_with_what_the_register_recorded():
    db = FakeDB()
    db.seed("tds_deductions", _typed("t1", nature="Professional fee for the audit", lower=True, cert="CERT-9"))
    out = _build(db)
    assert out["deductee_count"] == 1
    d = out["deductees"][0]
    assert (d["deductee_name"], d["deductee_pan"], d["section"], d["section_1961"]) == ("Acme Services", PAN_COMPANY, "194J", "194J")
    assert (d["payment_date"], d["payment_amount_paise"], d["tds_rate_pct"], d["tds_deducted_paise"]) == ("2025-10-12", 1_00_000_00, 10.0, 10_000_00)
    assert d["nature_of_payment"] == "Professional fee for the audit"
    assert d["is_lower_deduction"] is True and d["lower_deduction_cert"] == "CERT-9", "the s.197 certificate travels as a bill's does"
    assert d["recorded_by"] == "tds_register"
    assert out["total_payment_paise"] == 1_00_000_00 and out["total_tds_deducted_paise"] == 10_000_00
    assert out["source"] == "posted_purchase_bills_and_advances_and_typed_deductions"


def test_a_typed_row_with_no_pan_is_filed_under_the_placeholder_the_statement_uses_for_a_bill():
    db = FakeDB()
    db.seed("tds_deductions", _typed("t1", pan=None, rate=20))
    d = _build(db)["deductees"][0]
    assert d["deductee_pan"] == "PANNOTAVBL"


def test_a_typed_row_that_names_a_supplier_takes_the_suppliers_own_name_and_pan_as_a_bill_does():
    db = FakeDB()
    _vendor(db, "v7", name="Pinnacle Engineering Pvt Ltd", pan="AAGCP7788R")
    db.seed("tds_deductions", _typed("t1", vendor="v7", name="an old snapshot name", pan="AAAAA0000A"))
    d = _build(db)["deductees"][0]
    assert (d["deductee_name"], d["deductee_pan"]) == ("Pinnacle Engineering Pvt Ltd", "AAGCP7788R")


def test_the_two_kinds_of_row_are_told_apart_by_what_recorded_them():
    db = FakeDB()
    _vendor(db)
    _bill(db)
    db.seed("tds_deductions", _typed("t1"))
    out = _build(db)
    assert {d["deductee_name"]: d["recorded_by"] for d in out["deductees"]} == {"Pinnacle Engineering": "purchase_bill", "Acme Services": "tds_register"}


# ── the challan fill is the register's ───────────────────────────────────────

def test_a_typed_row_is_filled_from_the_quarters_challans_in_date_order_with_the_bills():
    """One challan of Rs 10,000 under 194J pays the EARLIER deduction, the typed one (12 October), and leaves the later bill's tax (25 October, Rs 3,600 under the
    same section) undeposited: the statement used to ignore the typed row, hand the challan to the bill and show the bill deposited."""
    db = FakeDB()
    _vendor(db)
    _bill(db, taxable=36_000_00, tds=3_600_00, section="194J")
    db.seed("tds_deductions", _typed("t1", tds=10_000_00))
    _challan(db, "111", "2025-11-07", 10_000_00)
    out = _build(db)
    typed, bill = _row(out, "Acme Services"), _row(out, "Pinnacle Engineering")
    assert (typed["tds_deposited_paise"], typed["challan_no"], typed["bsr_code"], typed["challan_date"]) == (10_000_00, "111", "BSR111", "2025-11-07")
    assert (bill["tds_deposited_paise"], bill["challan_no"]) == (0, "")
    assert out["total_tds_deposited_paise"] == 10_000_00
    assert any("exceeds deposited" in e for e in out["validation_errors"]), "the typed and billed tax together are more than the challan paid"


def test_the_statement_and_the_registers_own_reader_agree_about_which_deduction_a_challan_paid():
    """The deposit worksheet reads the register's rows and the statement reads the documents and the typed rows; both order two deductions of one day by the same
    key (POST-A-277). A typed row and a bill of one day, one challan that covers one of them: the same one is paid on both sides."""
    db = FakeDB()
    _vendor(db, "v1")
    _bill(db, "b1", day="2025-10-12", taxable=36_000_00, tds=3_600_00, section="194J")
    db.seed("tds_deductions", _typed("t1", day="2025-10-12", tds=3_600_00))
    # the register holds the bill's row too, as the bill path writes it
    db.seed("tds_deductions", {**_typed("r1", day="2025-10-12", tds=3_600_00, name="Pinnacle Engineering"), "purchase_bill_id": "b1"})
    _challan(db, "111", "2025-11-07", 3_600_00)
    out = _build(db)
    on_statement = {d["deductee_name"]: d["tds_deposited_paise"] for d in out["deductees"]}
    register_rows = [r for r in db.rows("tds_deductions")]
    mapping = deposit_due.mapping_from_register(register_rows, db.rows("tds_challans"), fy="2025-26")
    in_register = {r["id"]: mapping.for_deduction(r["id"]).deposited_paise for r in register_rows}
    paid_typed_on_statement = on_statement["Acme Services"] > 0
    paid_typed_in_register = in_register["t1"] > 0
    assert paid_typed_on_statement == paid_typed_in_register, (on_statement, in_register)
    assert (on_statement["Acme Services"] > 0) != (on_statement["Pinnacle Engineering"] > 0), "the challan covers exactly one of the two"


# ── the tie-out is the documents' ────────────────────────────────────────────

def test_the_tie_out_compares_the_documents_tax_and_reports_the_typed_tax_beside_it():
    db = FakeDB()
    _vendor(db)
    _bill(db)
    db.seed("tds_deductions", _typed("t1"))
    db.seed("chart_of_accounts", {"id": "acc-tds", "firm_id": FIRM, "client_id": CLIENT, "account_name": "TDS Payable", "is_active": True})
    out = _build(db)
    assert out["total_tds_deducted_paise"] == 360_00 + 10_000_00
    rec = out["reconciliation"]
    assert rec["books_paise"] == 360_00 and rec["typed_paise"] == 10_000_00
    assert rec["difference_paise"] == rec["books_paise"] - rec["ledger_paise"], "the difference is the documents' alone, never the typed tax"


def test_a_quarter_with_no_typed_row_reports_a_typed_tax_of_nothing():
    db = FakeDB()
    _vendor(db)
    _bill(db)
    assert _build(db)["reconciliation"]["typed_paise"] == 0


# ── what is not carried, and what is named ───────────────────────────────────

def test_a_typed_row_naming_a_non_resident_supplier_goes_to_the_non_resident_note_like_a_bill():
    db = FakeDB()
    _vendor(db, "v-nr", name="Overseas Co", pan=None, status="non_resident")
    db.seed("tds_deductions", _typed("t1", vendor="v-nr"))
    out = _build(db)
    assert out["deductee_count"] == 0 and out["typed_on_statement"]["count"] == 0
    assert out["excluded_non_resident"]["bill_count"] == 1 and out["excluded_non_resident"]["tds_paise"] == 10_000_00
    assert out["excluded_non_resident"]["bills"][0]["kind"] == "typed"
    assert out["excluded_non_resident"]["bills"][0]["bill_no"] == "TDS register entry of 2025-10-12", "named by its day, not by a bare id"
    assert out["reconciliation"]["typed_paise"] == 0


def test_a_typed_row_recorded_for_another_statement_is_named_and_not_carried():
    db = FakeDB()
    db.seed("tds_deductions", _typed("t1", return_type="27Q"))
    out = _build(db)
    assert out["deductee_count"] == 0 and out["typed_on_statement"]["count"] == 0
    assert out["excluded_typed"]["count"] == 1 and out["excluded_typed"]["tds_paise"] == 10_000_00
    assert "another statement" in out["excluded_typed"]["reason"]


def test_a_salary_row_is_never_carried():
    db = FakeDB()
    db.seed("tds_deductions", _typed("t1", section="192"))
    out = _build(db)
    assert out["deductee_count"] == 0 and out["typed_on_statement"]["count"] == 0 and out["excluded_typed"]["count"] == 0


def test_another_clients_and_another_firms_typed_rows_are_not_this_statements():
    db = FakeDB()
    db.seed("tds_deductions", {**_typed("t1"), "client_id": "C2"})
    db.seed("tds_deductions", {**_typed("t2"), "firm_id": "F2"})
    assert _build(db)["deductee_count"] == 0


# ── the note says what is different about these rows ─────────────────────────

def test_the_note_names_a_row_that_may_be_a_bill_already_on_the_statement_and_does_not_drop_it():
    db = FakeDB()
    _vendor(db, "v1")
    _bill(db, "b1", day="2025-10-25", taxable=18_000_00, tds=360_00)
    db.seed("tds_deductions", _typed("t1", vendor="v1", day="2025-10-25", payment=18_000_00, tds=360_00, section="194C", rate=2))
    out = _build(db)
    assert out["deductee_count"] == 2, "named, never guessed away"
    assert "may be the same payment reported twice" in out["typed_on_statement"]["reason"]
    gap = [g for g in out["statutory_gaps"] if "same day and amount" in g]
    assert len(gap) == 1 and "BILL-1" in gap[0] and "remove the typed deduction from the register before filing" in gap[0]
    assert "for Pinnacle Engineering" in gap[0] and "Acme Services" not in gap[0], "the supplier is named as the deductee row names it"


def test_the_total_of_a_bill_matches_too_because_the_boxs_label_is_the_gross_payment():
    db = FakeDB()
    _vendor(db, "v1")
    db.seed("purchase_bills", {"id": "b1", "firm_id": FIRM, "client_id": CLIENT, "vendor_id": "v1", "bill_no": "BILL-1", "bill_date": "2025-10-25",
                               "status": "received", "taxable_amount_paise": 15_000_00, "total_paise": 17_700_00, "tds_paise": 300_00, "tds_rate_bps": 200,
                               "tds_section": "194C", "journal_entry_id": None})
    db.seed("tds_deductions", _typed("t1", vendor="v1", day="2025-10-25", payment=17_700_00, tds=354_00, section="194C", rate=2))
    assert len([g for g in _build(db)["statutory_gaps"] if "same day and amount" in g]) == 1


def test_a_typed_row_naming_the_same_supplier_on_another_day_is_not_a_mirror():
    db = FakeDB()
    _vendor(db, "v1")
    _bill(db, "b1", day="2025-10-25", taxable=18_000_00, tds=360_00)
    db.seed("tds_deductions", _typed("t1", vendor="v1", day="2025-10-26", payment=18_000_00, tds=360_00, section="194C", rate=2))
    out = _build(db)
    assert not [g for g in out["statutory_gaps"] if "same day and amount" in g]
    assert "may be the same payment" not in out["typed_on_statement"]["reason"]


def test_the_note_says_how_many_name_no_supplier():
    db = FakeDB()
    _vendor(db, "v1")
    db.seed("tds_deductions", _typed("t1", vendor="v1"))
    db.seed("tds_deductions", _typed("t2", day="2025-11-05", name="A Shareholder", section="194"))
    db.seed("tds_deductions", _typed("t3", day="2025-11-06", name="Another Shareholder", section="194"))
    from services.tds_return_service import TYPED_ON_STATEMENT_REASON
    reason = _build(db)["typed_on_statement"]["reason"]
    assert reason.startswith(TYPED_ON_STATEMENT_REASON)
    assert "2 of them name no supplier" in reason and "deductions typed for its PAN alone" in reason


def test_a_row_with_no_supplier_under_a_section_that_also_reaches_a_non_resident_says_its_residence_is_not_recorded():
    db = FakeDB()
    db.seed("tds_deductions", _typed("t1", section="194B", name="A Winner", rate=30))
    reason = _build(db)["typed_on_statement"]["reason"]
    assert "residence is not recorded" in reason and "194B" in reason
    assert "Rule 31A(4)(b)" in reason, "the rule the repo already cites for which statement a payment to a non-resident goes on"


def test_a_resident_only_section_says_nothing_about_residence():
    db = FakeDB()
    db.seed("tds_deductions", _typed("t1", section="194J"))
    assert "residence" not in _build(db)["typed_on_statement"]["reason"]


# ── the 2025 Act ─────────────────────────────────────────────────────────────

def test_a_2025_act_statement_gives_a_typed_row_its_payment_code_or_names_why_not():
    db = FakeDB()
    db.seed("tds_deductions", _typed("t1", day="2026-05-12", section="194J"))
    out = _build(db, fy="2026-27", quarter="Q1")
    d = out["deductees"][0]
    assert {"payment_code", "payment_code_gap", "payment_code_assumption"} <= set(d), "the three keys are always present"
    assert d["payment_code"] is not None or d["payment_code_gap"], "a code, or the reason there is none"
    assert d["section"] == "393(1)" and d["section_1961"] == "194J"


def test_a_1961_act_statement_asks_a_typed_row_for_no_code():
    db = FakeDB()
    db.seed("tds_deductions", _typed("t1"))
    d = _build(db)["deductees"][0]
    assert d["payment_code"] is None and d["payment_code_gap"] is None


# ── the other builders, and the read ─────────────────────────────────────────

def test_the_27q_and_24q_builders_carry_no_typed_rows():
    import inspect
    from services import tds_return_service as m
    for fn in (m.tds_27q_from_books, m.tds_24q_from_books):
        src = inspect.getsource(fn)
        assert "typed_on_statement" not in src and "_typed_deductions_in_quarter" not in src


def test_the_typed_read_asks_for_everything_the_row_is_built_from():
    import inspect
    from services import tds_return_service as m
    src = inspect.getsource(m._typed_deductions_in_quarter)
    for column in ("tds_rate_pct", "is_lower_deduction", "lower_deduction_cert", "nature_of_payment", "vendor_id", "return_type"):
        assert column in src, column
