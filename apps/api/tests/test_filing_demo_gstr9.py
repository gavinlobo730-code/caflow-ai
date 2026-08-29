"""The GSTR-9 filing demo — the annual return walk-through, held to the
framework rules (tests/test_filing_demo_framework.py scans the module for
writes automatically; this file pins what the flow itself must teach).

WHAT IS SPECIFIC TO GSTR-9 AND PINNED HERE
    - The demo is gated on the DRAFT ROW EXISTING, not on a status: GSTR-9
      drafts only ever hold status 'draft' (there is no GSTR-9 status
      endpoint), and they live in the gstr1_returns store with
      return_type='gstr9' (migration 053).
    - The annual picture is derived from at most 24 monthly return HEADER
      rows via the pure helper gst_return_service.gstr9_summary_from_returns
      — "filed" means status 'submitted', nothing weaker.
    - The Rule 80(1) precondition (all GSTR-1/GSTR-3B filed first) is SHOWN,
      never a refusal — the demo teaches what the portal would block.
    - The §37(3)/§39(9)/§16(4) early-closure warning appears in EVERY run:
      furnishing GSTR-9 shuts the correction window at the earlier of
      30 November or the filing date (compliance_engine.
      correction_window_closes is the authority the module cites).

Also here: the list_returns return_type filter. GSTR-9 rows share
gstr1_returns with the monthly statements, and without the filter they leaked
into GSTR1Tab's list as monthly returns with an 'FY2025-26' period.
"""
from __future__ import annotations

import pytest

import routers.gst_workspace as gw
from services.filing_demo import gstr9
from services.gst_return_service import (
    gstr9_fy_periods,
    gstr9_summary_from_returns,
)
from tests.e2e_harness import FakeDB

FIRM = "FIRM-A"
CLIENT = "CLI"
FY = "2025-26"
GSTIN = "27ABCDE1234F1Z5"

FY_PERIODS = ["042025", "052025", "062025", "072025", "082025", "092025",
              "102025", "112025", "122025", "012026", "022026", "032026"]

# Per filed month, so FY totals are an exact integer-paise multiple.
MONTH_TAXABLE = 1_00_000_00
MONTH_IGST = 9_000_00
MONTH_CGST = 4_500_00
MONTH_SGST = 4_500_00
MONTH_CESS = 100_00


def _month_g1(period: str, status: str) -> dict:
    return {"id": f"G1-{period}", "firm_id": FIRM, "client_id": CLIENT,
            "period": period, "gstin": GSTIN, "status": status,
            "return_type": "gstr1",
            "total_taxable_paise": MONTH_TAXABLE,
            "total_igst_paise": MONTH_IGST, "total_cgst_paise": MONTH_CGST,
            "total_sgst_paise": MONTH_SGST, "total_cess_paise": MONTH_CESS}


def _db(all_filed: bool = False, **draft_overrides) -> FakeDB:
    """A GSTR-9 draft plus the year's monthly headers.

    Default scenario: GSTR-1 filed Apr 2025..Jan 2026 (10 months), Feb 2026
    saved but only a draft, Mar 2026 never saved; GSTR-3B filed Apr..Feb (11
    months), Mar 2026 never saved. all_filed=True files all 24.
    """
    db = FakeDB()
    draft = {"id": "R9", "firm_id": FIRM, "client_id": CLIENT,
             "return_type": "gstr9", "period": f"FY{FY}",
             "financial_year": FY, "gstin": GSTIN, "status": "draft",
             "total_taxable_paise": 12_00_000_00, "total_igst_paise": 1_08_000_00,
             "total_cgst_paise": 54_000_00, "total_sgst_paise": 54_000_00,
             "total_tax_paise": 2_16_000_00}
    draft.update(draft_overrides)
    db.seed("gstr1_returns", draft)
    for i, p in enumerate(FY_PERIODS):
        if all_filed:
            g1_status, seed_g3b = "submitted", "submitted"
        elif i < 10:
            g1_status, seed_g3b = "submitted", "submitted"
        elif i == 10:  # Feb 2026: GSTR-1 only drafted, GSTR-3B filed
            g1_status, seed_g3b = "draft", "submitted"
        else:  # Mar 2026: neither saved
            g1_status, seed_g3b = None, None
        if g1_status:
            db.seed("gstr1_returns", _month_g1(p, g1_status))
        if seed_g3b:
            db.seed("gstr3b_returns",
                    {"id": f"G3-{p}", "firm_id": FIRM, "client_id": CLIENT,
                     "period": p, "gstin": GSTIN, "status": seed_g3b})
    return db


def _build(db=None, ref=None):
    return gstr9.build(db or _db(), FIRM, CLIENT,
                       {"return_id": "R9"} if ref is None else ref)


# ── Rule 2: the envelope is honest ──────────────────────────────────────────

def test_envelope_is_honest():
    out = _build()
    assert out["simulated"] is True
    assert out["filed"] is False
    assert out["acknowledgement"].startswith("SIM-NOT-FILED-GSTR9-")
    assert "nothing has been filed" in out["disclaimer"]
    assert out["real_channel"]["software_permitted"] is False, (
        "GSTN filing needs a GSP; claiming software may file GSTR-9 today "
        "would teach a CA something false")
    assert out["flow"] == "gstr9"
    assert f"FY {FY}" in out["subtitle"]


# ── The portal's sequence ───────────────────────────────────────────────────

def test_follows_the_portal_sequence_with_months_missing():
    """summary → month table → precondition warning (months missing) →
    correction-window warning → declaration → signature → otp → transmit →
    result. No payment stage: GSTR-9 liabilities are paid through DRC-03, a
    separate ceremony this walk-through does not pretend to include."""
    out = _build()
    kinds = [s["kind"] for s in out["stages"]]
    assert kinds == ["summary", "table", "warning", "warning", "declaration",
                     "signature", "otp", "transmit", "result"]


def test_all_filed_drops_the_precondition_but_never_the_window_warning():
    """The early-closure warning is the one thing this demo exists to teach,
    so it survives a perfectly-filed year; only the Rule 80(1) precondition
    warning is conditional."""
    out = _build(_db(all_filed=True))
    kinds = [s["kind"] for s in out["stages"]]
    assert kinds == ["summary", "table", "warning", "declaration",
                     "signature", "otp", "transmit", "result"]
    warning = next(s for s in out["stages"] if s["kind"] == "warning")
    assert "whichever is EARLIER" in warning["text"]
    assert "30 November 2026" in warning["text"], (
        "FY 2025-26's statutory outer limit, quoted from "
        "compliance_engine.november_30_cutoff(2026)")
    assert "§37(3)" in warning["text"] and "§16(4)" in warning["text"]


def test_the_precondition_names_the_missing_months_and_does_not_refuse():
    """A draft GSTR-1 is prepared, not filed — Feb 2026 must be listed as
    missing alongside the never-saved Mar 2026."""
    out = _build()
    warnings = [s for s in out["stages"] if s["kind"] == "warning"]
    precondition, window = warnings[0], warnings[1]
    assert "GSTR-1 for Feb 2026, Mar 2026" in precondition["text"]
    assert "GSTR-3B for Mar 2026" in precondition["text"]
    assert "stops here" in precondition["text"]
    assert "whichever is EARLIER" in window["text"]


# ── The figures ─────────────────────────────────────────────────────────────

def test_figures_are_the_filed_months_own_paise_exact():
    """FY totals come from the ten FILED GSTR-1 headers only — the Feb 2026
    draft's figures must not leak in (draft figures can still change; the
    portal auto-populates from what was FILED)."""
    out = _build()
    by_label = {f["label"]: f for f in out["stages"][0]["figures"]}
    assert by_label["Taxable value (filed GSTR-1)"]["paise"] == 10 * MONTH_TAXABLE
    assert by_label["IGST"]["paise"] == 10 * MONTH_IGST
    assert by_label["CGST"]["paise"] == 10 * MONTH_CGST
    assert by_label["SGST"]["paise"] == 10 * MONTH_SGST
    assert by_label["Cess"]["paise"] == 10 * MONTH_CESS
    assert by_label["GSTR-1 filed"]["text"] == "10 of 12 months"
    assert by_label["GSTR-3B filed"]["text"] == "11 of 12 months"


def test_month_table_is_twelve_rows_april_first():
    out = _build()
    table = next(s for s in out["stages"] if s["kind"] == "table")
    assert table["columns"] == ["Month", "GSTR-1", "GSTR-3B"]
    assert len(table["rows"]) == 12
    assert table["rows"][0][0]["text"] == "Apr 2025"
    assert table["rows"][-1][0]["text"] == "Mar 2026"
    assert table["rows"][0][1]["text"] == "Filed"
    assert table["rows"][10][1]["text"] == "draft", (
        "a saved-but-unfiled month shows its real status, not 'Filed'")
    assert table["rows"][11][1]["text"] == "Not filed"
    assert table["rows"][11][2]["text"] == "Not filed"


def test_statutory_copy_names_the_due_date_and_the_optionality():
    """CGST Act §44 (due 31 December following the FY — compliance_engine.
    gstr9_due_date), §47(2) (late fee), and the proviso to §44(1)
    (₹2 crore optionality notifications)."""
    out = _build()
    note = out["stages"][0]["note"]
    assert "due 31 December 2026" in note
    assert "₹2 crore" in note
    assert "§47(2)" in note
    result = next(s for s in out["stages"] if s["kind"] == "result")
    assert any("31 December 2026" in t for t in result["truth"])


# ── Declaration and signature ceremony ──────────────────────────────────────

def test_declaration_is_the_forms_own_wording():
    """FORM GSTR-9's verification, verbatim — including the anti-profiteering
    rider (§171) that GSTR-1's declaration does not carry."""
    out = _build()
    decl = next(s for s in out["stages"] if s["kind"] == "declaration")
    assert "solemnly affirm and declare" in decl["text"]
    assert ("benefit thereof has been/will be passed on to the recipient "
            "of supply") in decl["text"]
    assert "taxpayer's signatory" in decl["note"], (
        "whose signature this is — the one thing every demo must teach")


def test_signature_methods_evc_takes_otp_dsc_does_not():
    out = _build()
    methods = {m["key"]: m for s in out["stages"] if s["kind"] == "signature"
               for m in s["methods"]}
    assert methods["evc"]["otp"] is True
    assert methods["dsc"]["otp"] is False
    # One otp stage for the EVC route; the wizard skips it for DSC.
    assert [s["kind"] for s in out["stages"]].count("otp") == 1


def test_result_specimen_never_travels_without_its_note():
    out = _build()
    result = next(s for s in out["stages"] if s["kind"] == "result")
    assert len(result["specimen"]) == 15
    assert result["specimen"].startswith("AA27"), (
        "GSTN ARN shape, state code from the GSTIN")
    assert "SPECIMEN" in result["specimen_note"]
    assert "not issued" in result["specimen_note"]
    assert any("Nothing was filed" in t for t in result["truth"])
    assert any("correction window" in t for t in result["truth"]), (
        "the result must say the window is untouched — the demo just spent a "
        "whole warning stage on it")


# ── Refusals: answers, not incidents ────────────────────────────────────────

def test_a_missing_ref_is_an_answer():
    with pytest.raises(ValueError, match="return_id"):
        _build(ref={})


def test_an_unknown_return_is_an_answer():
    with pytest.raises(ValueError, match="not found"):
        _build(ref={"return_id": "NOPE"})


def test_a_monthly_gstr1_row_is_refused_by_name():
    """Walking a monthly statement through an annual return ceremony would
    teach the wrong filing."""
    with pytest.raises(ValueError, match="not a GSTR-9 annual return"):
        _build(ref={"return_id": "G1-042025"})


def test_a_wrong_firm_or_client_sees_nothing():
    db = _db()
    with pytest.raises(ValueError, match="not found"):
        gstr9.build(db, "FIRM-B", CLIENT, {"return_id": "R9"})
    with pytest.raises(ValueError, match="not found"):
        gstr9.build(db, FIRM, "OTHER-CLIENT", {"return_id": "R9"})


def test_a_garbled_financial_year_is_an_answer():
    db = _db(financial_year="garbage", period="FYgarbage")
    with pytest.raises(ValueError, match="Financial year"):
        gstr9.build(db, FIRM, CLIENT, {"return_id": "R9"})


# ── The pure helper, without a database ─────────────────────────────────────

def test_fy_periods_run_april_to_march():
    assert gstr9_fy_periods(FY) == FY_PERIODS
    for bad in ("2025", "2025-27", "garbage", "", None):
        with pytest.raises(ValueError):
            gstr9_fy_periods(bad)


def test_summary_ignores_what_is_not_a_monthly_gstr1_of_this_fy():
    g1 = [
        _month_g1("042025", "submitted"),
        # The annual draft itself lives in the same store — never a month.
        {"period": f"FY{FY}", "return_type": "gstr9", "status": "draft",
         "total_taxable_paise": 99_99_999_99},
        # A month of the WRONG year.
        {**_month_g1("042024", "submitted"), "period": "042024"},
        # A row predating migration 053 carries no return_type; the DB
        # column default is 'gstr1', so it counts as a monthly statement.
        {"period": "052025", "status": "submitted",
         "total_taxable_paise": MONTH_TAXABLE, "total_igst_paise": 0,
         "total_cgst_paise": 0, "total_sgst_paise": 0, "total_cess_paise": 0},
    ]
    s = gstr9_summary_from_returns(FY, g1, [])
    assert s["gstr1_filed_months"] == 2
    assert s["totals"]["taxable_paise"] == 2 * MONTH_TAXABLE
    assert s["gstr3b_filed_months"] == 0
    assert len(s["missing_gstr3b"]) == 12
    assert "Apr 2025" not in s["missing_gstr1"]
    assert "Jun 2025" in s["missing_gstr1"]


# ── list_returns: the shared-store leak ─────────────────────────────────────

USER = {"id": "U1", "firm_id": FIRM, "role": "Partner",
        "email": "partner@example.com"}


@pytest.fixture(autouse=True)
def _clean_mock_stores():
    gw._MOCK_GSTR1.clear()
    gw._MOCK_GSTR3B.clear()
    yield
    gw._MOCK_GSTR1.clear()
    gw._MOCK_GSTR3B.clear()


def _seed_shared_store():
    # As save_gstr1 stores it: no return_type key at all (the DB column's
    # default supplies 'gstr1' in Postgres).
    gw._MOCK_GSTR1["M1"] = {"id": "M1", "firm_id": FIRM, "client_id": CLIENT,
                            "period": "042025", "gstin": GSTIN,
                            "status": "draft", "total_taxable_paise": 0}
    # As save_gstr9 stores it: same store, return_type='gstr9'.
    gw._MOCK_GSTR1["A1"] = {"id": "A1", "firm_id": FIRM, "client_id": CLIENT,
                            "period": f"FY{FY}", "financial_year": FY,
                            "return_type": "gstr9", "gstin": GSTIN,
                            "status": "draft", "total_taxable_paise": 0}


def test_gstr9_rows_do_not_leak_into_the_gstr1_list():
    """The bug this filter exists for: gstr1_returns holds BOTH monthly
    GSTR-1 statements and GSTR-9 annual drafts, and GSTR1Tab's list showed an
    annual draft as a monthly return with period 'FY2025-26'."""
    _seed_shared_store()
    out = gw.list_returns(client_id=CLIENT, return_type="gstr1",
                          limit=50, offset=0, current_user=USER)
    assert out["success"] is True
    assert [r["id"] for r in out["data"]["gstr1"]] == ["M1"]


def test_without_the_filter_the_list_keeps_its_historical_shape():
    """Callers that never pass return_type still get every row of the shared
    store — the fix narrows only callers that ask."""
    _seed_shared_store()
    out = gw.list_returns(client_id=CLIENT, return_type=None,
                          limit=50, offset=0, current_user=USER)
    assert {r["id"] for r in out["data"]["gstr1"]} == {"M1", "A1"}


def test_the_filter_can_also_select_the_annual_drafts():
    _seed_shared_store()
    out = gw.list_returns(client_id=CLIENT, return_type="gstr9",
                          limit=50, offset=0, current_user=USER)
    assert [r["id"] for r in out["data"]["gstr1"]] == ["A1"]
