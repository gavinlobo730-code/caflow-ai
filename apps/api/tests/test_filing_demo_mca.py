"""The MCA annual-filing demo (services/filing_demo/mca) against the
framework's three rules and its own statutory specifics.

What is particular to MCA and pinned here:
  - the DUAL SIGNATURE on AOC-4 and MGT-7 — a director's declaration and
    DSC, then a practising professional's certification and DSC, two
    declaration+signature pairs with NO otp stage anywhere (MCA V3 signs
    with DSC only);
  - MGT-7A and ADT-1 drop the professional certification;
  - annual forms only — an event form is refused by name;
  - an already-filed form is refused;
  - the late-filing warning appears only when the AGM date lets the window
    be computed honestly, says ₹100/day for §137/§92 forms, and does NOT
    make that claim for ADT-1 (whose additional fee is slab-based);
  - AOC-4 figures come from a validated XBRL package when one exists, else
    the year-end Schedule III engine — whose ValueError (an unbalanced
    balance sheet) surfaces as an honest note, not a refusal and not a 500.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

import services.year_end_financial_service as ye
from services.filing_demo import common, mca
from tests.e2e_harness import FakeDB

FIRM = "FIRM-A"
CLIENT = "CLI"
CIN = "U74999MH2020PTC123456"

_FUTURE_AGM = (date.today() + timedelta(days=1)).isoformat()


def _db(directors: bool = True, company: bool = True, **filing_overrides):
    db = FakeDB()
    filing = {
        "id": "F1", "firm_id": FIRM, "client_id": CLIENT,
        "form_type": "AOC-4", "status": "in_progress",
        "financial_year": "2024-25", "company_cin": CIN,
        # Due dates hang off the AGM; a future AGM keeps the baseline flows
        # inside their windows so the warning stage only appears where a
        # test puts it there.
        "agm_date": _FUTURE_AGM,
    }
    filing.update(filing_overrides)
    db.seed("mca_filings", filing)
    if company:
        db.seed("mca_companies", {
            "id": "CO1", "firm_id": FIRM, "client_id": CLIENT,
            "cin": CIN, "company_name": "Demo Widgets Pvt Ltd",
            "authorized_capital_paise": 1_00_00_000_00,
            "paid_up_capital_paise": 50_00_000_00,
        })
    if directors:
        db.seed("mca_directors", {
            "firm_id": FIRM, "client_id": CLIENT,
            "director_name": "Asha Mehta", "din": "01234567",
            "is_active": True})
        db.seed("mca_directors", {
            "firm_id": FIRM, "client_id": CLIENT,
            "director_name": "Rohan Iyer", "din": "07654321",
            "is_active": True})
    return db


def _flat_statements():
    """A tiny Schedule III result shaped like the year-end engine's, so the
    fallback figure tests do not depend on that module's mock values."""
    return {
        "balance_sheet": {"total_assets_paise": 9_87_654_00},
        "profit_loss": {
            "income": {"revenue_from_operations": 12_34_567_00},
            "profit_after_tax_paise": 1_11_111_00,
        },
    }


# ── Rule 2: the envelope is honest ──────────────────────────────────────────

def test_mca_envelope_is_honest():
    out = mca.build(_db(), FIRM, CLIENT, {"filing_id": "F1"})
    assert out["simulated"] is True
    assert out["filed"] is False
    assert out["acknowledgement"].startswith("SIM-NOT-FILED-MCA-")
    assert "nothing has been filed" in out["disclaimer"]
    assert out["real_channel"]["software_permitted"] is False, (
        "MCA V3 is a portal-login flow with no public filing API — claiming "
        "software may transmit an ROC form would teach a CA something false"
    )


# ── The dual signature — the flow's reason to exist ─────────────────────────

def test_aoc4_has_two_declaration_signature_pairs_and_no_otp():
    out = mca.build(_db(), FIRM, CLIENT, {"filing_id": "F1"})
    kinds = [s["kind"] for s in out["stages"]]
    assert kinds == ["summary", "declaration", "signature",
                     "declaration", "signature", "transmit", "result"]
    assert "otp" not in kinds, "MCA signs with DSC only — no OTP route exists"
    for stage in out["stages"]:
        if stage["kind"] == "signature":
            assert all(m["otp"] is False for m in stage["methods"])


def test_mgt7_is_dual_but_mgt7a_drops_the_professional_certification():
    dual = mca.build(_db(form_type="MGT-7"), FIRM, CLIENT, {"filing_id": "F1"})
    assert [s["kind"] for s in dual["stages"]] == [
        "summary", "declaration", "signature",
        "declaration", "signature", "transmit", "result"]
    assert "hereby certified" in str(dual["stages"])

    single = mca.build(_db(form_type="MGT-7A"), FIRM, CLIENT,
                       {"filing_id": "F1"})
    assert [s["kind"] for s in single["stages"]] == [
        "summary", "declaration", "signature", "transmit", "result"]
    assert "hereby certified" not in str(single["stages"]), (
        "MGT-7A (OPCs and small companies, proviso to §92(1)) carries no "
        "practising-professional certification"
    )


def test_mgt7s_certifier_is_a_company_secretary_specifically():
    """§92(1) proviso / Form MGT-7: the annual return's professional
    certification belongs to a practising Company Secretary alone — offering
    a CA the option would teach a CA they can sign something they cannot.
    AOC-4 keeps the CA / CS / cost accountant trio (§137)."""
    mgt7 = mca.build(_db(form_type="MGT-7"), FIRM, CLIENT, {"filing_id": "F1"})
    certifier = mgt7["stages"][3]
    assert certifier["kind"] == "declaration"
    assert certifier["signatory_options"] == [
        "Company Secretary (in whole-time practice)"]
    assert "Company Secretary in whole-time practice" in certifier["note"]

    aoc4 = mca.build(_db(form_type="AOC-4"), FIRM, CLIENT, {"filing_id": "F1"})
    aoc4_certifier = aoc4["stages"][3]
    assert len(aoc4_certifier["signatory_options"]) == 3
    assert any("Chartered Accountant" in o
               for o in aoc4_certifier["signatory_options"])


def test_a_prefixed_financial_year_still_parses_to_fy_bounds():
    """mca_filings sometimes carries the year as period='FY 2024-25' with
    financial_year blank (migration 038's documented format). That must parse
    to real FY bounds — telling the CA 'no financial year is recorded' while
    displaying one was the bug."""
    assert mca._fy_bounds("FY 2024-25") == ("2024-04-01", "2025-03-31")
    assert mca._fy_bounds("FY2024-25") == ("2024-04-01", "2025-03-31")
    assert mca._fy_bounds("2024-25") == ("2024-04-01", "2025-03-31")
    assert mca._fy_bounds("March 2025") is None
    assert mca._fy_bounds("") is None


def test_adt1_is_single_signature_and_names_the_auditor():
    out = mca.build(_db(form_type="ADT-1", auditor_name="S Rao & Co"),
                    FIRM, CLIENT, {"filing_id": "F1"})
    assert [s["kind"] for s in out["stages"]] == [
        "summary", "declaration", "signature", "transmit", "result"]
    summary = out["stages"][0]
    by_label = {f["label"]: f.get("text") for f in summary["figures"]}
    assert by_label["Auditor appointed"] == "S Rao & Co"


def test_the_declarations_are_the_forms_own_wording():
    out = mca.build(_db(), FIRM, CLIENT, {"filing_id": "F1"})
    decls = [s for s in out["stages"] if s["kind"] == "declaration"]
    director, professional = decls
    assert "true, correct and complete" in director["text"]
    assert "suppressed or concealed" in director["text"]
    assert "DIRECTOR" in director["note"], (
        "whose signature this is — the one thing every demo must teach"
    )
    assert "hereby certified" in professional["text"]
    assert "verified the above particulars" in professional["text"]
    assert "membership number" in professional["note"]


def test_the_director_options_carry_din_and_exclude_the_ceased():
    db = _db()
    db.seed("mca_directors", {
        "firm_id": FIRM, "client_id": CLIENT,
        "director_name": "Gone Person", "din": "00000001",
        "is_active": True, "date_of_cessation": "2024-01-01"})
    db.seed("mca_directors", {
        "firm_id": FIRM, "client_id": CLIENT,
        "director_name": "Deactivated Person", "din": "00000002",
        "is_active": False})
    out = mca.build(db, FIRM, CLIENT, {"filing_id": "F1"})
    options = out["stages"][1]["signatory_options"]
    assert "Asha Mehta (DIN 01234567)" in options
    assert "Rohan Iyer (DIN 07654321)" in options
    assert not any("Gone Person" in o or "Deactivated" in o for o in options)


# ── Refusals: answers, not incidents ────────────────────────────────────────

def test_an_event_form_is_refused_by_name():
    with pytest.raises(ValueError, match="DIR-12"):
        mca.build(_db(form_type="DIR-12"), FIRM, CLIENT, {"filing_id": "F1"})
    with pytest.raises(ValueError, match="annual"):
        mca.build(_db(form_type="CHG-1"), FIRM, CLIENT, {"filing_id": "F1"})


def test_an_already_filed_form_is_refused():
    with pytest.raises(ValueError, match="already"):
        mca.build(_db(status="filed", srn="T12345678"), FIRM, CLIENT,
                  {"filing_id": "F1"})


def test_missing_ref_and_missing_record_are_refused():
    with pytest.raises(ValueError, match="filing_id"):
        mca.build(_db(), FIRM, CLIENT, {})
    with pytest.raises(ValueError, match="not found"):
        mca.build(_db(), FIRM, CLIENT, {"filing_id": "NOPE"})


def test_the_read_is_scoped_to_firm_and_client():
    with pytest.raises(ValueError, match="not found"):
        mca.build(_db(), "FIRM-B", CLIENT, {"filing_id": "F1"})
    with pytest.raises(ValueError, match="not found"):
        mca.build(_db(), FIRM, "OTHER-CLIENT", {"filing_id": "F1"})


def test_no_active_directors_is_a_refusal_a_ca_understands():
    with pytest.raises(ValueError, match="director"):
        mca.build(_db(directors=False), FIRM, CLIENT, {"filing_id": "F1"})


# ── The late-filing warning: honest or absent ───────────────────────────────

def test_overdue_aoc4_warns_of_the_per_day_fee():
    out = mca.build(_db(agm_date="2023-09-30"), FIRM, CLIENT,
                    {"filing_id": "F1"})
    kinds = [s["kind"] for s in out["stages"]]
    assert kinds[1] == "warning"
    warning = out["stages"][1]
    # Companies (Registration Offices and Fees) Rules 2014 with §137(3):
    # ₹100 for every day of delay, uncapped.
    assert "₹100" in warning["text"]
    assert "no upper cap" in warning["text"]


def test_overdue_adt1_warns_without_claiming_the_per_day_fee():
    out = mca.build(_db(form_type="ADT-1", agm_date="2023-09-30"),
                    FIRM, CLIENT, {"filing_id": "F1"})
    warning = next(s for s in out["stages"] if s["kind"] == "warning")
    assert "₹100" not in warning["text"], (
        "ADT-1's additional fee is the slab of multiples, not ₹100/day — "
        "the demo must not teach the wrong fee"
    )
    assert "139" in warning["text"]


def test_no_warning_inside_the_window_or_without_an_agm_date():
    inside = mca.build(_db(), FIRM, CLIENT, {"filing_id": "F1"})
    assert "warning" not in [s["kind"] for s in inside["stages"]]
    # No AGM date on the filing or the company: the window cannot be
    # computed honestly, so the warning is omitted rather than guessed.
    no_agm = mca.build(_db(agm_date=None, company=False), FIRM, CLIENT,
                       {"filing_id": "F1"})
    assert "warning" not in [s["kind"] for s in no_agm["stages"]]


# ── The summary's figures are the records' own, in integer paise ────────────

def test_summary_shows_cin_agm_date_and_capital():
    out = mca.build(_db(), FIRM, CLIENT, {"filing_id": "F1"})
    summary = out["stages"][0]
    text_by_label = {f["label"]: f.get("text") for f in summary["figures"]}
    paise_by_label = {f["label"]: f.get("paise") for f in summary["figures"]}
    assert text_by_label["CIN"] == CIN
    assert text_by_label["AGM date"] == _FUTURE_AGM
    assert paise_by_label["Authorised capital"] == 1_00_00_000_00
    assert paise_by_label["Paid-up capital"] == 50_00_000_00


def test_aoc4_prefers_the_validated_xbrl_package():
    db = _db()
    db.seed("xbrl_packages", {
        "firm_id": FIRM, "client_id": CLIENT, "financial_year": "2024-25",
        "status": "validated", "taxonomy_version": "MCA_2023",
        "balance_sheet_json": {"BalanceSheet.Equity.ShareCapital": 50_00_000_00},
        "pnl_json": {"ProfitAndLoss.Revenue.RevenueFromOperations": 2_50_00_000_00},
    })
    out = mca.build(db, FIRM, CLIENT, {"filing_id": "F1"})
    summary = out["stages"][0]
    by_label = {f["label"]: f.get("paise") for f in summary["figures"]}
    assert by_label["Revenue from operations"] == 2_50_00_000_00
    assert by_label["Share capital"] == 50_00_000_00
    assert "XBRL" in summary["note"], "the package is named as evidence"
    assert "validated XBRL" in summary["note"]


def test_a_reviewed_package_is_evidence_but_not_called_validated():
    """routers/xbrl_engine.py::review_package sets status='reviewed' with no
    precondition that validation ever ran — the note must say what the row
    actually is, not upgrade it."""
    db = _db()
    db.seed("xbrl_packages", {
        "firm_id": FIRM, "client_id": CLIENT, "financial_year": "2024-25",
        "status": "reviewed", "taxonomy_version": "MCA_2023",
        "balance_sheet_json": {"BalanceSheet.Equity.ShareCapital": 1_00_00},
        "pnl_json": {},
    })
    out = mca.build(db, FIRM, CLIENT, {"filing_id": "F1"})
    note = out["stages"][0]["note"]
    assert "CA-reviewed XBRL" in note
    assert "validated XBRL" not in note


def test_a_draft_xbrl_package_is_not_evidence(monkeypatch):
    db = _db()
    db.seed("xbrl_packages", {
        "firm_id": FIRM, "client_id": CLIENT, "financial_year": "2024-25",
        "status": "draft",
        "pnl_json": {"ProfitAndLoss.Revenue.RevenueFromOperations": 1},
    })
    monkeypatch.setattr(ye, "generate_financial_statements",
                        lambda *a, **k: _flat_statements())
    out = mca.build(db, FIRM, CLIENT, {"filing_id": "F1"})
    summary = out["stages"][0]
    by_label = {f["label"]: f.get("paise") for f in summary["figures"]}
    assert by_label["Revenue from operations"] == 12_34_567_00, (
        "an unvalidated draft must fall through to the Schedule III engine"
    )
    assert "XBRL" not in summary["note"]


def test_aoc4_falls_back_to_the_year_end_engine_paise_exact(monkeypatch):
    monkeypatch.setattr(ye, "generate_financial_statements",
                        lambda *a, **k: _flat_statements())
    out = mca.build(_db(), FIRM, CLIENT, {"filing_id": "F1"})
    summary = out["stages"][0]
    by_label = {f["label"]: f.get("paise") for f in summary["figures"]}
    assert by_label["Total assets (Schedule III)"] == 9_87_654_00
    assert by_label["Revenue from operations"] == 12_34_567_00
    assert by_label["Profit after tax"] == 1_11_111_00


def test_unbalanced_books_surface_as_a_note_not_a_refusal(monkeypatch):
    def _raise(*_a, **_k):
        raise ValueError(
            "Balance Sheet does not balance: Assets=100 paise, "
            "Equity+Liabilities=99 paise, Difference=1 paise.")
    monkeypatch.setattr(ye, "generate_financial_statements", _raise)
    out = mca.build(_db(), FIRM, CLIENT, {"filing_id": "F1"})
    summary = out["stages"][0]
    assert "could not be produced" in summary["note"]
    assert "does not balance" in summary["note"]
    # The walk-through still runs, and still tells the truth.
    assert out["simulated"] is True and out["filed"] is False


def test_mgt7_fetches_no_figures_source():
    """Only AOC-4 carries Schedule III figures; the annual return does not
    reach for the year-end engine or the XBRL store at all."""
    db = _db(form_type="MGT-7")
    out = mca.build(db, FIRM, CLIENT, {"filing_id": "F1"})
    labels = [f["label"] for f in out["stages"][0]["figures"]]
    assert "Revenue from operations" not in labels
    assert "Total assets (Schedule III)" not in labels


# ── Rule 3: realism is labelled ─────────────────────────────────────────────

def test_the_specimen_srn_matches_mcas_format_and_carries_its_note():
    out = mca.build(_db(), FIRM, CLIENT, {"filing_id": "F1"})
    result = out["stages"][-1]
    assert result["kind"] == "result"
    assert result["specimen"] == common.specimen_mca_srn("F1")
    assert len(result["specimen"]) == 9
    assert result["specimen"][0].isalpha()
    assert result["specimen"][1:].isdigit()
    assert "SPECIMEN" in result["specimen_note"]
    assert "MCA" in result["specimen_note"]
    assert any("Nothing was filed" in t for t in result["truth"])
    assert any("Mark Filed" in t for t in result["truth"]), (
        "the truth lines must point at the genuine path: file on the "
        "portal, then record the SRN here"
    )
