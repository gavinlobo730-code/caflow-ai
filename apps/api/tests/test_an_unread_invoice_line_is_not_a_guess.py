"""AI-01 / GST-03 — an extracted line says what it read and what it did not.

`_parse_extraction_json` read `int(gst_rate_bps or 1800)` and
`float(quantity or 1)`. `0` is falsy, so a nil-rated or exempt line the model
read as 0% came back as 18%, and ITC on an exempt purchase was overstated
unless the CA spotted it on one line of a long invoice. A missing quantity
became 1, and the editor added `unit: "NOS"` and `gst_rate ?? 1800` on top, so
the screen showed three invented figures exactly as it showed the ones the
document carried.

The rule: only an ABSENT value is unknown. A genuine 0 is a reading.
"""
import json

import pytest
from fastapi import HTTPException

import routers.document_intelligence_v1 as mod
from domain import extraction_lines as X


def _parse(lines, **header):
    body = {
        "vendor_name": "V", "vendor_gstin": None, "invoice_no": "I-1",
        "invoice_date": None, "taxable_amount_paise": 0, "cgst_paise": 0,
        "sgst_paise": 0, "igst_paise": 0, "total_paise": 0,
        "line_items": lines,
    }
    body.update(header)
    return mod._parse_extraction_json(json.dumps(body))["line_items"]


FULL = {"description": "Widget", "hsn_sac": "1234", "quantity": 2, "unit": "NOS",
        "rate_paise": 10000, "gst_rate_bps": 1800}


# ── the premise: the fixture reads cleanly, so the cases below mean something ──

def test_a_fully_read_line_carries_nothing_unread():
    (li,) = _parse([FULL])
    assert li["not_read"] == []
    assert li["gst_rate_bps"] == 1800
    assert li["quantity"] == 2.0
    assert li["unit"] == "NOS"
    assert li["rate_paise"] == 10000


# ── the defect: a real 0% stays 0% ───────────────────────────────────────────

def test_a_zero_rate_stays_zero():
    """The skeptic's reproduction: gst_rate_bps 0 came back as 1800."""
    (li,) = _parse([{**FULL, "gst_rate_bps": 0}])
    assert li["gst_rate_bps"] == 0
    assert "gst_rate" not in li["not_read"]


def test_a_zero_rate_as_text_stays_zero():
    (li,) = _parse([{**FULL, "gst_rate_bps": "0"}])
    assert li["gst_rate_bps"] == 0


@pytest.mark.parametrize("bps", [250, 500, 1200, 1800, 2800, 4000])
def test_every_stated_rate_is_carried_unchanged(bps):
    (li,) = _parse([{**FULL, "gst_rate_bps": bps}])
    assert li["gst_rate_bps"] == bps
    assert li["not_read"] == []


def test_a_rate_the_model_answered_as_a_float_is_still_the_rate():
    (li,) = _parse([{**FULL, "gst_rate_bps": 1800.0}])
    assert li["gst_rate_bps"] == 1800


# ── an absent value is unknown — None, never a default ───────────────────────

@pytest.mark.parametrize("missing", [None, "", "  ", "n/a", -100])
def test_an_absent_or_unusable_rate_is_unknown_not_eighteen(missing):
    (li,) = _parse([{**FULL, "gst_rate_bps": missing}])
    assert li["gst_rate_bps"] is None
    assert li["not_read"] == ["gst_rate"]


def test_a_key_that_is_missing_altogether_is_unknown_too():
    line = {k: v for k, v in FULL.items() if k != "gst_rate_bps"}
    (li,) = _parse([line])
    assert li["gst_rate_bps"] is None
    assert "gst_rate" in li["not_read"]


@pytest.mark.parametrize("missing", [None, "", 0, -3, "x"])
def test_a_missing_or_nil_quantity_is_not_one(missing):
    (li,) = _parse([{**FULL, "quantity": missing}])
    assert li["quantity"] is None
    assert li["not_read"] == ["quantity"]


def test_a_quantity_and_a_rate_with_grouping_commas_are_read():
    (li,) = _parse([{**FULL, "quantity": "1,250", "rate_paise": "1,00,000"}])
    assert li["quantity"] == 1250.0
    assert li["rate_paise"] == 100000


def test_a_missing_rate_is_not_a_nil_rate():
    (li,) = _parse([{**FULL, "rate_paise": None}])
    assert li["rate_paise"] is None
    assert li["not_read"] == ["rate"]


def test_a_real_zero_rate_is_a_reading():
    """A free sample is a line priced at nil; it is not an unread rate."""
    (li,) = _parse([{**FULL, "rate_paise": 0}])
    assert li["rate_paise"] == 0
    assert "rate" not in li["not_read"]


# ── the unit is read only where it IS one of CBIC's codes ────────────────────

def test_no_unit_is_reported_not_read_and_is_never_nos():
    line = {k: v for k, v in FULL.items() if k != "unit"}
    (li,) = _parse([line])
    assert li["unit"] is None
    assert li["not_read"] == ["unit"]
    assert "unit_as_printed" not in li


def test_a_unit_in_the_wrong_case_is_the_code():
    (li,) = _parse([{**FULL, "unit": " kgs "}])
    assert li["unit"] == "KGS"
    assert li["not_read"] == []


def test_a_word_that_is_not_a_code_is_not_converted_but_is_kept_as_printed():
    """`uqc.closest_code` is a suggestion and never a substitution."""
    (li,) = _parse([{**FULL, "unit": "Kg"}])
    assert li["unit"] is None
    assert li["unit_as_printed"] == "Kg"
    assert li["not_read"] == ["unit"]


def test_the_unread_fields_of_one_line_are_all_named():
    (li,) = _parse([{"description": "x"}])
    assert li["not_read"] == ["quantity", "unit", "gst_rate", "rate"]


def test_not_read_is_always_present_even_when_empty():
    """An absent key and an empty list read the same to `not_read ?? []` and are
    different states: empty says the check ran and found nothing."""
    (li,) = _parse([FULL])
    assert "not_read" in li and li["not_read"] == []


# ── the parser no longer falls over on the model's worst output ──────────────

def test_a_null_line_item_list_is_no_lines_not_a_crash():
    data = mod._parse_extraction_json(json.dumps({
        "vendor_name": "V", "line_items": None}))
    assert data["line_items"] == []


# ── the from-document door agrees with the editor's door ─────────────────────

def test_from_document_refuses_a_line_whose_rate_nobody_read():
    """It used to read `int(x or 0)` and book the line at 0%, while the editor
    path defaulted the same unknown to 18% — two doors, one unknown, two
    answers."""
    import routers.purchase_bills as pb
    with pytest.raises(HTTPException) as ei:
        pb._lines_from_extraction({"line_items": [
            {"description": "Widget", "quantity": 1, "rate_paise": 100000}]})
    assert ei.value.status_code == 422
    assert "GST rate" in ei.value.detail
    assert "line 1" in ei.value.detail


def test_from_document_accepts_a_real_zero_rate():
    import routers.purchase_bills as pb
    (line,) = pb._lines_from_extraction({"line_items": [
        {"description": "Exempt goods", "quantity": 1, "rate_paise": 100000,
         "gst_rate_bps": 0}]})
    assert line["gst_rate_percent"] == 0.0


def test_from_document_names_every_unread_field_of_every_line():
    import routers.purchase_bills as pb
    with pytest.raises(HTTPException) as ei:
        pb._lines_from_extraction({"line_items": [
            {"description": "A", "quantity": 1, "rate_paise": 1, "gst_rate_bps": 1800},
            {"description": "B"},
        ]})
    detail = ei.value.detail
    assert "line 2" in detail and "line 1" not in detail
    assert "quantity" in detail and "GST rate" in detail and "rate" in detail


def test_from_document_does_not_require_a_unit():
    """The unit is optional there and the function invents none."""
    import routers.purchase_bills as pb
    (line,) = pb._lines_from_extraction({"line_items": [
        {"description": "A", "quantity": 1, "rate_paise": 1, "gst_rate_bps": 1800}]})
    assert line["unit"] is None


def test_the_editors_extraction_output_is_accepted_by_from_document():
    """The shape one door emits has to be the shape the other door reads."""
    import routers.purchase_bills as pb
    (li,) = _parse([FULL])
    (line,) = pb._lines_from_extraction({"line_items": [li]})
    assert line["quantity"] == 2.0
    assert line["rate_paise"] == 10000
    assert line["gst_rate_percent"] == 18.0


# ── the prompt stops inviting the guess ──────────────────────────────────────

def test_the_prompt_asks_for_null_not_a_guess():
    p = mod._EXTRACTION_PROMPT
    assert '"unit"' in p
    assert "NEVER guess" in p
    # 0 is named as an answer, so a model that reads "0%" is told to say so.
    assert "0 = the document prints 0%" in p


# ── the module's own vocabulary ──────────────────────────────────────────────

def test_every_field_name_has_a_sentence_for_the_ca():
    assert set(X.LABELS) == {X.QUANTITY, X.UNIT, X.GST_RATE, X.RATE}
