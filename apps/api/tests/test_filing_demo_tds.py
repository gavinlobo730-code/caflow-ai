"""The TDS (24Q/26Q) filing demo — services/filing_demo/tds_return.py.

The framework rules (writes nothing, honest envelope, labelled realism) are
enforced package-wide by tests/test_filing_demo_framework.py; this file holds
the TDS flow to its own statutory specifics:

  - the sequence is the REAL channel's — .fvu upload on the e-filing portal
    (incometax.gov.in) under the deductor's TAN, never TRACES, which is
    post-filing only;
  - figures are the saved row's own integer paise, with the from-books
    fallback for quick-created rows that carry none — zeros are declared,
    never invented;
  - the due date and the §234E late fee both trace to the single authority,
    services/compliance_engine.py::tds_return_due_date;
  - the declaration is Form 27A's own certification, signed by the person
    responsible for paying (IT Act §204), not the CA firm.
"""
from __future__ import annotations

from datetime import date

import pytest

from services.compliance_engine import tds_return_due_date
from services.filing_demo import common, tds_return
from tests.e2e_harness import FakeDB

FIRM = "FIRM-A"
CLIENT = "CLI"


def _inr(paise: int) -> str:
    """Mirror of the module's prose formatter, so fee assertions compare the
    same rendering rather than a re-derived one drifting on separators."""
    rupees_part, paise_part = divmod(abs(int(paise)), 100)
    body = f"{rupees_part:,}" if paise_part == 0 else f"{rupees_part:,}.{paise_part:02d}"
    return f"{'-' if paise < 0 else ''}₹{body}"


def _db_with_return(**overrides):
    db = FakeDB()
    row = {
        "id": "T1", "firm_id": FIRM, "client_id": CLIENT,
        "return_type": "26Q", "financial_year": "2025-26", "quarter": "Q2",
        "status": "ca_approved",
        "total_deductions_paise": 4_50_000_00,
        "total_deposits_paise": 4_20_000_00,
        "deductee_count": 12,
    }
    row.update(overrides)
    db.seed("tds_returns", row)
    return db


def _seed_challan(db, **overrides):
    row = {
        "firm_id": FIRM, "client_id": CLIENT,
        "challan_no": "00042", "bsr_code": "0510308",
        "payment_date": "2025-08-07", "financial_year": "2025-26",
        "quarter": "Q2", "tds_paise": 4_20_000_00, "total_paise": 4_20_000_00,
        "minor_head": "200", "section": "194C", "status": "deposited",
    }
    row.update(overrides)
    return db.seed("tds_challans", row)


def _build(db, ref=None):
    # `ref if ref is not None` — an explicit empty dict must reach build()
    # as-is (it is the missing-ref refusal case), not be swapped for T1.
    return tds_return.build(db, FIRM, CLIENT,
                            ref if ref is not None else {"return_id": "T1"})


def _stage(out, kind):
    return next(s for s in out["stages"] if s["kind"] == kind)


# ── Envelope honesty ────────────────────────────────────────────────────────

def test_the_envelope_is_honest():
    out = _build(_db_with_return())
    assert out["simulated"] is True
    assert out["filed"] is False
    assert out["acknowledgement"].startswith("SIM-NOT-FILED-TDS-")
    assert "nothing has been filed" in out["disclaimer"]
    assert out["real_channel"]["software_permitted"] is False, (
        "there is no public filing API for TDS statements — claiming "
        "software may transmit one would teach a CA something false"
    )


# ── The sequence is the real channel's ──────────────────────────────────────

def test_follows_the_real_upload_sequence_with_challans():
    db = _db_with_return()
    _seed_challan(db)
    out = _build(db)
    kinds = [s["kind"] for s in out["stages"]]
    assert kinds == ["summary", "table", "warning", "declaration",
                     "signature", "otp", "transmit", "result"]


def test_without_challans_the_table_is_simply_absent():
    out = _build(_db_with_return())
    kinds = [s["kind"] for s in out["stages"]]
    assert "table" not in kinds
    assert kinds[0] == "summary" and kinds[-1] == "result"


def test_the_statement_is_never_filed_on_traces():
    """The wrong-portal error this flow exists to correct: the upload happens
    on incometax.gov.in; TRACES appears only in its real, post-filing role
    (the correction-statement route in the warning, 16/16A in the result)."""
    out = _build(_db_with_return())
    transmit = _stage(out, "transmit")
    labels = " ".join(s["label"] for s in transmit["steps"]).lower()
    assert "traces" not in labels
    assert "csi" in labels and "fvu" in labels and "e-filing" in labels
    assert "e-pay tax" in labels
    assert "TAN" in " ".join(s["label"] for s in transmit["steps"])
    assert "incometax.gov.in" in out["real_channel"]["how"] or \
           "incometax.gov.in" in " ".join(_stage(out, "result")["truth"])
    assert "post-filing" in out["real_channel"]["how"]


# ── Figures ─────────────────────────────────────────────────────────────────

def test_the_figures_are_the_records_own_paise_exact():
    out = _build(_db_with_return())
    by_label = {f["label"]: f for f in _stage(out, "summary")["figures"]}
    assert by_label["TDS deducted"]["paise"] == 4_50_000_00
    assert by_label["TDS deposited"]["paise"] == 4_20_000_00
    assert by_label["Deductees"]["text"] == "12"
    assert by_label["Form"]["text"] == "26Q"


def test_the_due_date_comes_from_the_single_authority():
    out = _build(_db_with_return())
    by_label = {f["label"]: f for f in _stage(out, "summary")["figures"]}
    # FY 2025-26 → Mar 31 falls in 2026; the figure must equal what
    # compliance_engine answers, not a date restated in the flow module.
    assert by_label["Due date (Rule 31A)"]["text"] == \
        tds_return_due_date("Q2", 2026).isoformat()


def test_a_zero_figure_row_falls_back_to_the_books():
    """Quick-created rows carry zeros; the demo computes the quarter from the
    posted books (same service as the Compute screen) rather than showing
    zeros that are false or inventing figures that are worse."""
    db = _db_with_return(total_deductions_paise=0, total_deposits_paise=0,
                         deductee_count=0)
    db.seed("purchase_bills", {
        "firm_id": FIRM, "client_id": CLIENT, "status": "paid",
        "bill_date": "2025-08-15", "vendor_id": "V1", "bill_no": "B-9",
        "taxable_amount_paise": 2_50_000_00, "tds_paise": 5_000_00,
        "tds_section": "194C", "tds_rate_bps": 200,
    })
    db.seed("vendors", {"id": "V1", "firm_id": FIRM,
                        "name": "Alpha Works", "pan": "AAACA1234A"})
    out = _build(db)
    by_label = {f["label"]: f for f in _stage(out, "summary")["figures"]}
    assert by_label["TDS deducted"]["paise"] == 5_000_00
    assert by_label["Deductees"]["text"] == "1"
    assert "computed from the posted books" in _stage(out, "summary")["note"]


def test_zeros_with_empty_books_are_declared_not_invented():
    out = _build(_db_with_return(total_deductions_paise=0,
                                 total_deposits_paise=0, deductee_count=0))
    by_label = {f["label"]: f for f in _stage(out, "summary")["figures"]}
    assert by_label["TDS deducted"]["paise"] == 0
    assert "zeros are real, not placeholders" in _stage(out, "summary")["note"]


def test_a_failed_fallback_still_shows_honest_zeros(monkeypatch):
    from services import tds_return_service
    def boom(*a, **k):
        raise RuntimeError("books unavailable")
    monkeypatch.setattr(tds_return_service, "tds_26q_from_books", boom)
    out = _build(_db_with_return(total_deductions_paise=0,
                                 total_deposits_paise=0, deductee_count=0))
    by_label = {f["label"]: f for f in _stage(out, "summary")["figures"]}
    assert by_label["TDS deducted"]["paise"] == 0
    assert "rather than invented numbers" in _stage(out, "summary")["note"]


# ── Challan table ───────────────────────────────────────────────────────────

def test_challans_show_paise_exact_with_the_statements_sections_only():
    """26Q carries the non-salary challans; the §192 (salary) one belongs to
    24Q — the same split services/tds_return_service.py applies."""
    db = _db_with_return()
    _seed_challan(db, challan_no="00042", section="194C", total_paise=4_20_000_00)
    _seed_challan(db, challan_no="00099", section="192", total_paise=1_00_000_00)
    out = _build(db)
    table = _stage(out, "table")
    assert table["columns"] == ["Challan no", "BSR code", "Deposit date",
                                "Minor head", "Amount"]
    assert [row[0]["text"] for row in table["rows"]] == ["00042"]
    assert table["rows"][0][4]["paise"] == 4_20_000_00
    assert table["footer"][4]["paise"] == 4_20_000_00
    assert "ITNS 281" in table["note"] and "e-Pay Tax" in table["note"]


def test_a_24q_statement_takes_only_the_salary_challan():
    db = _db_with_return(return_type="24Q")
    _seed_challan(db, challan_no="00042", section="194C")
    _seed_challan(db, challan_no="00099", section="192", total_paise=1_00_000_00)
    out = _build(db)
    table = _stage(out, "table")
    assert [row[0]["text"] for row in table["rows"]] == ["00099"]
    assert table["footer"][4]["paise"] == 1_00_000_00


# ── §234E late fee — honest arithmetic or silence ───────────────────────────

def test_234e_fee_matches_the_single_authority():
    # FY 2023-24 Q4: due 31 May 2024 per compliance_engine — long past, so
    # the fee is days × ₹200, uncapped at this deducted amount.
    out = _build(_db_with_return(financial_year="2023-24", quarter="Q4"))
    due = tds_return_due_date("Q4", 2024)
    fee = min((date.today() - due).days * 200_00, 4_50_000_00)
    text = _stage(out, "warning")["text"]
    assert "§234E" in text
    assert due.isoformat() in text
    assert _inr(fee) in text


def test_234e_fee_caps_at_the_tds_amount():
    # ₹100 of TDS deducted, years late: §234E's fee caps at the TDS amount.
    out = _build(_db_with_return(financial_year="2023-24", quarter="Q4",
                                 total_deductions_paise=10_000))
    text = _stage(out, "warning")["text"]
    assert _inr(10_000) in text
    assert "capped at the TDS amount" in text


def test_no_fee_is_shown_before_the_due_date():
    # A genuinely-future FY, derived from the clock so the suite never ages
    # into its own due date: Q4 of FY starting next year is due 31 May two
    # years out at the earliest. A fee line here would be an invented number.
    start = date.today().year + 1
    fy = f"{start}-{(start + 1) % 100:02d}"
    out = _build(_db_with_return(financial_year=fy, quarter="Q4"))
    text = _stage(out, "warning")["text"]
    assert "§234E" not in text
    assert "correction statement" in text, (
        "the warning must name the lawful fix, not read as a dead end")


# ── Declaration and signature ceremony ──────────────────────────────────────

def test_the_declaration_is_form_27as_own_certification():
    out = _build(_db_with_return())
    decl = _stage(out, "declaration")
    assert ("hereby certify that all the particulars furnished above are "
            "correct and complete") in decl["text"]
    assert "§204" in decl["signatory_label"] or "§204" in decl["note"]
    assert "person responsible for paying" in decl["note"], (
        "whose signature this is — the one thing every demo must teach"
    )


def test_dsc_skips_the_otp_and_evc_requires_it():
    out = _build(_db_with_return())
    methods = {m["key"]: m for m in _stage(out, "signature")["methods"]}
    assert methods["dsc"]["otp"] is False, "a DSC upload has no OTP leg"
    assert methods["evc"]["otp"] is True
    assert any(s["kind"] == "otp" for s in out["stages"]), (
        "EVC is offered, so the flow must carry the otp stage for the "
        "wizard to route through"
    )


# ── The result panel ────────────────────────────────────────────────────────

def test_the_specimen_is_a_15_digit_token_with_its_note():
    out = _build(_db_with_return())
    result = _stage(out, "result")
    assert result["specimen"] == common.specimen_tds_prn("T1")
    assert len(result["specimen"]) == 15 and result["specimen"].isdigit()
    assert "SPECIMEN" in result["specimen_note"]
    assert "not issued" in result["specimen_note"]
    assert any("Nothing was filed" in t for t in result["truth"])
    assert any("Mark as Filed" in t for t in result["truth"]), (
        "the truth lines must point at the genuine path — file on the "
        "portal, then record the Token/PRN here"
    )


# ── Refusals: every one an answer, never an incident ────────────────────────

def test_a_missing_ref_is_refused():
    with pytest.raises(ValueError, match="return_id"):
        _build(_db_with_return(), ref={})


def test_an_unknown_return_is_refused():
    with pytest.raises(ValueError, match="not found"):
        _build(_db_with_return(), ref={"return_id": "NOPE"})


def test_another_clients_return_is_out_of_reach():
    """Scope is part of the SELECT, not an afterthought — a return id from a
    different client of the same firm answers exactly like a missing row."""
    with pytest.raises(ValueError, match="not found"):
        _build(_db_with_return(client_id="OTHER-CLIENT"))


def test_another_firms_return_is_out_of_reach():
    with pytest.raises(ValueError, match="not found"):
        _build(_db_with_return(firm_id="FIRM-B"))


def test_an_unapproved_return_is_refused():
    with pytest.raises(ValueError, match="CA-approved"):
        _build(_db_with_return(status="prepared"))
    with pytest.raises(ValueError, match="CA-approved"):
        _build(_db_with_return(status="pending"))


def test_a_filed_return_is_refused():
    with pytest.raises(ValueError, match="already recorded as filed"):
        _build(_db_with_return(status="filed"))


def test_an_undemoed_form_type_is_refused():
    with pytest.raises(ValueError, match="27Q"):
        _build(_db_with_return(return_type="27Q"))
    with pytest.raises(ValueError, match="24Q and 26Q"):
        _build(_db_with_return(return_type="27EQ"))
