"""An extracted invoice is checked on its LINES, its GSTIN and its tax heads, not only
its five header totals (ai-02).

WHAT WAS WRONG
    `check_totals` tested taxable + CGST + SGST + IGST against the total — and its
    own docstring said what it did NOT test: the rate, and CGST = SGST. So a
    misread digit that moved two header figures together passed, a bill whose
    lines did not sum to its taxable value passed, a CGST that was not its SGST
    passed. And the supplier GSTIN — fifteen characters the model TYPES — was never
    run through the check digit every GSTIN a human types goes through; the editor
    then matched a vendor on it. A misread GSTIN or a wrong tax split looked
    exactly like a correct one on the screen.

WHAT THIS ASSERTS
    * lines that do not sum to the taxable value: `agrees` false, with a NAMED
      reason carrying both amounts (and the header check, separately, still
      agrees);
    * each line's tax at its own rate against the header heads, through
      `domain/sales/line_tax.compute_line_gst` — and per HEAD on an intra-State
      bill, which is what catches a CGST that is not its SGST;
    * a transposed GSTIN digit returns a GSTIN finding and confidence "low";
    * IGST charged between two same-State registrations (and CGST+SGST between
      two different ones) is flagged, with the exceptions named in the sentence;
    * every check that cannot run SAYS why and does not count against the bill;
    * a check REPORTS: the extraction is byte-for-byte what the model read.
"""
from __future__ import annotations

import ast
import copy
import pathlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.document_intelligence_v1 as v1
from core.auth import get_current_user
from domain import extraction_checks as C
from domain import extraction_totals as T

API = pathlib.Path(__file__).resolve().parents[1]

# 27AAPFU0939F1ZV is a real-shaped GSTIN with a CORRECT check digit; swapping two
# characters inside the PAN keeps the shape and breaks the digit.
MAHARASHTRA = "27AAPFU0939F1ZV"
TRANSPOSED = "27AAPFU0399F1ZV"
KARNATAKA = "29AAPFU0939F1ZR"


def _line(qty=2, rate=50_000, bps=1800, desc="Widget"):
    return {"description": desc, "hsn_sac": "1234", "quantity": qty, "unit": "NOS",
            "rate_paise": rate, "gst_rate_bps": bps, "not_read": []}


def _bill(lines=None, taxable=1_00_000, cgst=9_000, sgst=9_000, igst=0, total=None, gstin=MAHARASHTRA):
    total = taxable + cgst + sgst + igst if total is None else total
    return {"vendor_name": "Acme", "vendor_gstin": gstin, "invoice_no": "I-1",
            "invoice_date": "2026-06-01", "taxable_amount_paise": taxable, "cgst_paise": cgst,
            "sgst_paise": sgst, "igst_paise": igst, "total_paise": total,
            "line_items": [_line()] if lines is None else lines}


def _check(out, name):
    return next(c for c in out["checks"] if c["name"] == name)


# ── the premise: a bill that is right passes everything ──────────────────────

def test_a_consistent_bill_passes_every_check_and_reports_nothing():
    out = T.check_totals(_bill())
    assert out["checked"] is True and out["agrees"] is True
    assert out["failures"] == [] and out["note"] is None
    assert all(c["ran"] and c["agrees"] for c in out["checks"]), out["checks"]


def test_a_two_rate_bill_adds_up_line_by_line():
    lines = [_line(qty=1, rate=60_000, bps=1800), _line(qty=1, rate=40_000, bps=1200)]
    # 18% of 60,000 = 10,800; 12% of 40,000 = 4,800 -> 15,600 -> 7,800 + 7,800
    out = T.check_totals(_bill(lines, taxable=1_00_000, cgst=7_800, sgst=7_800))
    assert out["agrees"] is True, out["failures"]


def test_a_fractional_quantity_is_multiplied_exactly():
    out = T.check_totals(_bill([_line(qty=2.5, rate=40_000)], taxable=1_00_000, cgst=9_000, sgst=9_000))
    assert out["agrees"] is True


# ── (a) the lines against the taxable value ──────────────────────────────────

def test_lines_that_do_not_sum_to_the_taxable_value_are_a_named_failure():
    """One line read as 2 x 5,000 instead of 2 x 50,000: the header is internally
    consistent (taxable + tax = total) and the old check passed it."""
    bill = _bill([_line(qty=2, rate=5_000)])
    out = T.check_totals(bill)

    assert out["agrees"] is False
    sub = _check(out, T.LINES_VS_TAXABLE)
    assert sub["ran"] is True and sub["agrees"] is False
    assert sub["difference_paise"] == 10_000 - 1_00_000
    assert "The lines come to ₹100.00" in sub["reason"]      # 2 x Rs 50.00
    assert "₹1,000.00" in sub["reason"]                    # the taxable value read
    assert "discount, freight or round-off" in sub["reason"]    # the honest alternative
    assert sub["reason"] in out["failures"]
    # and the header, which HAS no fault, still says so:
    assert _check(out, T.HEADER_SUM)["agrees"] is True
    assert out["checked"] is True and out["difference_paise"] == 0


def test_the_note_carries_the_line_findings_for_a_screen_that_shows_only_the_note():
    out = T.check_totals(_bill([_line(qty=2, rate=5_000)]))
    assert "The lines come to" in out["note"]


@pytest.mark.parametrize("off,agrees", [(-100, True), (100, True), (101, False), (-101, False)])
def test_the_one_rupee_tolerance_applies_to_the_lines_too(off, agrees):
    bill = _bill([_line(qty=1, rate=1_00_000 + off)], cgst=9_000, sgst=9_000)
    out = T.check_totals(bill)
    assert _check(out, T.LINES_VS_TAXABLE)["agrees"] is agrees


# ── (b) the tax at each line's own rate ──────────────────────────────────────

def test_tax_that_is_not_the_lines_rates_is_a_named_failure():
    bill = _bill(cgst=4_500, sgst=4_500, total=1_09_000)      # 9% charged, lines say 18%
    out = T.check_totals(bill)
    sub = _check(out, T.TAX_AT_LINE_RATES)
    assert sub["ran"] and sub["agrees"] is False
    assert "Tax at the lines' own rates comes to ₹180.00" in sub["reason"]
    assert "tax read from the document is ₹90.00" in sub["reason"]
    assert out["agrees"] is False


def test_a_cgst_that_is_not_its_sgst_is_caught_per_head_though_the_total_agrees():
    """18,000 of tax in total is right for the lines; 10,000 + 8,000 is not what
    an intra-State supply at one rate gives. The total check alone cannot see it."""
    out = T.check_totals(_bill(cgst=10_000, sgst=8_000))
    sub = _check(out, T.TAX_AT_LINE_RATES)
    assert sub["agrees"] is False
    assert "CGST" in sub["reason"] and "SGST" in sub["reason"]
    assert _check(out, T.HEADER_SUM)["agrees"] is True, "the header sum is blind to this"


def test_an_inter_state_bill_is_judged_on_igst():
    ok = T.check_totals(_bill(cgst=0, sgst=0, igst=18_000))
    assert ok["agrees"] is True
    bad = T.check_totals(_bill(cgst=0, sgst=0, igst=9_000, total=1_09_000))
    assert _check(bad, T.TAX_AT_LINE_RATES)["agrees"] is False


def test_a_nil_rated_bill_with_no_tax_agrees():
    out = T.check_totals(_bill([_line(bps=0)], cgst=0, sgst=0, igst=0, total=1_00_000))
    assert out["agrees"] is True


def test_a_bill_charging_no_tax_against_lines_that_carry_a_rate_is_flagged():
    out = T.check_totals(_bill(cgst=0, sgst=0, igst=0, total=1_00_000))
    assert _check(out, T.TAX_AT_LINE_RATES)["agrees"] is False


def test_the_tax_is_worked_out_by_the_one_implementation_of_the_split():
    """CLAUDE.md: a line is taxed once, in `domain/sales/line_tax`. A second copy
    here would drift from the bill this extraction is about to become."""
    src = (API / "domain" / "extraction_totals.py").read_text()
    tree = ast.parse(src)
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
                and n.module == "domain.sales.line_tax" for a in n.names}
    assert "compute_line_gst" in imported
    assert "// 10000" not in src and "/ 10000" not in src, "the tax arithmetic is restated here"


# ── a check that cannot run says why, and is not a disagreement ──────────────

def test_lines_with_no_quantity_or_rate_cannot_be_added_up_and_that_is_not_a_failure():
    unread = {"description": "x", "quantity": None, "rate_paise": None, "gst_rate_bps": 1800,
              "unit": None, "not_read": ["quantity", "rate", "unit"]}
    out = T.check_totals(_bill([unread]))
    sub = _check(out, T.LINES_VS_TAXABLE)
    assert sub["ran"] is False and sub["agrees"] is None
    assert "no quantity or rate read" in sub["reason"]
    assert out["agrees"] is True and out["failures"] == []


def test_a_line_with_no_gst_rate_stops_the_tax_check_and_names_the_gap():
    line = _line(bps=None)
    out = T.check_totals(_bill([line]))
    assert _check(out, T.LINES_VS_TAXABLE)["ran"] is True
    sub = _check(out, T.TAX_AT_LINE_RATES)
    assert sub["ran"] is False and "no GST rate" in sub["reason"]
    assert out["agrees"] is True


def test_no_lines_means_no_line_checks_and_the_header_verdict_is_unchanged():
    out = T.check_totals(_bill([]))
    assert out["agrees"] is True
    assert not _check(out, T.LINES_VS_TAXABLE)["ran"] and not _check(out, T.TAX_AT_LINE_RATES)["ran"]


def test_an_unread_total_with_failing_lines_is_still_reported():
    out = T.check_totals(_bill([_line(qty=2, rate=5_000)], total=0))
    assert out["checked"] is False, "the header could not be checked"
    assert out["agrees"] is False, "but the lines still disagree with the taxable value"
    assert "could not be read" in out["note"] and "The lines come to" in out["note"]


def test_garbage_in_the_lines_never_raises():
    bill = _bill()
    bill["line_items"] = [{"quantity": "x", "rate_paise": object()}, "not a dict", None]
    T.check_totals(bill)


def test_a_check_reports_and_never_rewrites_what_was_read():
    bill = _bill([_line(qty=2, rate=5_000)], gstin=TRANSPOSED)
    before = copy.deepcopy(bill)
    T.check_totals(bill)
    C.check_supplier(bill, {"gstin": MAHARASHTRA})
    assert bill == before


# ── (c) the supplier GSTIN's check digit ─────────────────────────────────────

def test_a_valid_gstin_passes_and_offers_its_state():
    out = C.check_gstin(_bill())
    assert out["valid"] is True and out["problem"] is None and out["state_code"] == "27"


def test_a_transposed_digit_is_a_gstin_finding_that_names_the_problem():
    out = C.check_gstin(_bill(gstin=TRANSPOSED))
    assert out["valid"] is False
    assert "check digit" in out["problem"]
    assert TRANSPOSED in out["note"] and "misread" in out["note"]
    assert out["state_code"] is None, "a doubtful GSTIN's state is as doubtful as the rest"


def test_a_malformed_gstin_is_a_finding_too():
    assert C.check_gstin(_bill(gstin="27AAPFU0939"))["valid"] is False


@pytest.mark.parametrize("blank", [None, "", "   "])
def test_no_gstin_is_not_checked_and_not_a_failure(blank):
    out = C.check_gstin(_bill(gstin=blank))
    assert out["checked"] is False and out["valid"] is None
    assert C.check_supplier(_bill(gstin=blank), {"gstin": MAHARASHTRA})["agrees"] is True


def test_the_check_digit_is_asked_of_the_one_authority():
    src = (API / "domain" / "extraction_checks.py").read_text()
    assert "gstin_rule.problem_with(" in src or "gstin.problem_with(" in src
    assert "re.compile" not in src, "a GSTIN pattern is an invitation to answer the cheap way"


# ── (d) IGST against CGST + SGST for the States involved ─────────────────────

CLIENT_MH = {"gstin": MAHARASHTRA, "state_code": "27"}
CLIENT_KA = {"gstin": KARNATAKA}


def test_igst_between_two_same_state_registrations_is_flagged():
    out = C.check_supplier(_bill(cgst=0, sgst=0, igst=18_000), CLIENT_MH)
    pos = out["place_of_supply"]
    assert pos["checked"] and pos["agrees"] is False and pos["expected"] == "intra"
    assert out["agrees"] is False
    assert any(f["check"] == C.PLACE_OF_SUPPLY for f in out["failures"])
    assert "same State" in pos["reason"] and "place of supply" in pos["reason"]


def test_cgst_and_sgst_between_two_different_states_is_flagged():
    out = C.check_supplier(_bill(), CLIENT_KA)            # supplier 27, client 29
    pos = out["place_of_supply"]
    assert pos["agrees"] is False and pos["expected"] == "inter"
    assert "different States" in pos["reason"]


def test_the_right_head_for_the_states_involved_passes():
    assert C.check_supplier(_bill(), CLIENT_MH)["agrees"] is True
    assert C.check_supplier(_bill(cgst=0, sgst=0, igst=18_000), CLIENT_KA)["agrees"] is True


def test_the_clients_state_comes_from_the_recorded_column_when_it_has_no_gstin():
    out = C.check_supplier(_bill(cgst=0, sgst=0, igst=18_000), {"state_code": "27"})
    assert out["place_of_supply"]["client_state"] == "27"
    assert out["place_of_supply"]["agrees"] is False


def test_no_client_state_means_the_check_does_not_run_and_says_why():
    out = C.check_supplier(_bill(cgst=0, sgst=0, igst=18_000), {"gstin": None})
    pos = out["place_of_supply"]
    assert pos["checked"] is False and "not recorded" in pos["reason"]
    assert out["agrees"] is True
    assert C.check_supplier(_bill(), None)["agrees"] is True


def test_an_invalid_gstin_is_reported_once_and_the_state_check_stands_down():
    out = C.check_supplier(_bill(cgst=0, sgst=0, igst=18_000, gstin=TRANSPOSED), CLIENT_MH)
    assert [f["check"] for f in out["failures"]] == [C.GSTIN]
    assert out["place_of_supply"]["checked"] is False
    assert "not valid" in out["place_of_supply"]["reason"]


def test_a_bill_mixing_igst_and_cgst_is_not_judged():
    out = C.check_supplier(_bill(cgst=4_500, sgst=4_500, igst=9_000), CLIENT_MH)
    assert out["place_of_supply"]["checked"] is False and out["agrees"] is True


def test_a_bill_with_no_tax_has_no_head_to_check():
    out = C.check_supplier(_bill(cgst=0, sgst=0, igst=0), CLIENT_MH)
    assert out["place_of_supply"]["checked"] is False


# ── it reaches the response, the confidence and the vendor match ─────────────

def _app():
    app = FastAPI()
    app.include_router(v1.router)
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "u1", "auth_user_id": "u1", "firm_id": "F-2", "role": "Partner", "email": "p@f"}
    return TestClient(app, raise_server_exceptions=False)


def _post(monkeypatch, extraction, client=CLIENT_MH):
    monkeypatch.setattr(v1, "_GEMINI_KEY", "k")
    monkeypatch.setattr(v1, "_gemini_extract_image", lambda *a, **k: copy.deepcopy(extraction))
    monkeypatch.setattr(v1, "_client_for_checks", lambda client_id, firm_id: client)
    return _app().post("/api/document-intelligence-v1/extract-invoice",
                       files={"file": ("b.jpg", b"\xff\xd8\xff x", "image/jpeg")},
                       data={"client_id": "c-1"})


def test_a_bill_that_is_right_comes_back_high_with_clean_checks(monkeypatch):
    r = _post(monkeypatch, _bill())
    data = r.json()["data"]
    assert data["confidence"] == "high"
    assert data["totals_check"]["agrees"] is True and data["supplier_check"]["agrees"] is True


def test_the_response_for_a_bill_whose_lines_do_not_sum_names_the_reason(monkeypatch):
    r = _post(monkeypatch, _bill([_line(qty=2, rate=5_000)]))
    data = r.json()["data"]
    assert data["totals_check"]["agrees"] is False
    assert any("The lines come to" in f for f in data["totals_check"]["failures"])
    assert data["confidence"] == "low"


def test_a_transposed_gstin_returns_a_gstin_warning_and_confidence_low(monkeypatch):
    """The verify line, as an HTTP request."""
    r = _post(monkeypatch, _bill(gstin=TRANSPOSED))
    data = r.json()["data"]
    assert data["totals_check"]["agrees"] is True, "everything else about the bill is right"
    assert data["supplier_check"]["gstin"]["valid"] is False
    assert [f["check"] for f in data["supplier_check"]["failures"]] == ["gstin"]
    assert data["confidence"] == "low"
    # and the reading is what the model read, not a corrected one:
    assert data["extracted"]["vendor_gstin"] == TRANSPOSED


def test_igst_on_a_same_state_vendor_is_flagged_and_confidence_low(monkeypatch):
    r = _post(monkeypatch, _bill(cgst=0, sgst=0, igst=18_000))
    data = r.json()["data"]
    assert [f["check"] for f in data["supplier_check"]["failures"]] == ["place_of_supply"]
    assert data["confidence"] == "low"


def test_the_client_row_is_read_firm_scoped_and_a_failed_read_costs_nothing(monkeypatch):
    seen = {}

    class _Repo:
        def find_by_id(self, cid, firm_id=None):
            seen["args"] = (cid, firm_id)
            raise RuntimeError("database down")

    import repositories.client_repository as cr
    monkeypatch.setattr(cr, "client_repo", _Repo())
    assert v1._client_for_checks("c-1", "F-2") is None
    assert seen["args"] == ("c-1", "F-2"), "the read must carry the firm"


def test_the_confidence_rule_takes_both_checks_and_ignores_a_check_that_did_not_run():
    full = _bill()
    assert v1._estimate_confidence(full, T.check_totals(full), C.check_supplier(full, CLIENT_MH)) == "high"
    assert v1._estimate_confidence(full, T.check_totals(full), {"agrees": False}) == "low"
    unran = C.check_supplier(_bill(gstin=None), None)
    assert v1._estimate_confidence(_bill(gstin=None), T.check_totals(_bill(gstin=None)), unran) != "low"


# ── the editor reads the server's verdict ────────────────────────────────────

_EDITOR = API.parents[1] / "apps" / "web" / "components" / "purchases" / "PurchaseBillEditor.tsx"


@pytest.mark.skipif(not _EDITOR.is_file(), reason="needs apps/web")
def test_the_editor_does_not_match_a_vendor_on_a_gstin_the_server_found_wrong():
    import re
    src = _EDITOR.read_text()
    code = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    code = re.sub(r"^\s*//.*$", "", code, flags=re.M)
    assert "supplier_check" in code and "valid !== false" in code
    assert "gstinTrusted" in code
    # and it renders the failures the server sent rather than composing its own:
    assert "aiSupplier" in code and "failures" in code
