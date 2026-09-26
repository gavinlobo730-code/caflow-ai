"""domain/tds/keying_sheet.py — TDS-16.

`build()` derives nothing: it groups the deductee rows `tds_26q_from_books` /
`tds_27q_from_books` / `tds_24q_from_books` already computed under the RPU's
own Challan Detail / Deductee Detail hierarchy, and names what a CA still has
to decide for themselves (the FVU's own Remarks code, an unmatched deductee).
It never produces the government's own upload file — see the module docstring
for why, and `test_no_fvu_file_is_produced_is_always_present` below for the
one sentence that must never go missing.
"""
from __future__ import annotations

from domain.tds import keying_sheet


def _data(**over) -> dict:
    base = {
        "form": "26Q", "act": "Income-tax Act, 1961",
        "financial_year": "2025-26", "quarter": "Q2",
        "tan": "MUMB12345C", "deductor_name": "Acme Traders",
        "deductor_pan": "AAAAA0000A", "deductor_address": "12 MG Road, Mumbai",
        "deductees": [], "challans": [],
    }
    base.update(over)
    return base


def _deductee(**over) -> dict:
    base = {
        "deductee_name": "Vendor A", "deductee_pan": "BBBBB1111B",
        "section": "194J", "section_1961": "194J",
        "nature_of_payment": "Professional fees",
        "payment_date": "2025-08-01", "payment_amount_paise": 10_00_000,
        "tds_rate_pct": 10.0, "tds_deducted_paise": 1_00_000,
        "tds_deposited_paise": 1_00_000,
        "challan_no": "00042", "bsr_code": "0510308", "challan_date": "2025-09-07",
        "is_lower_deduction": False, "lower_deduction_cert": None,
    }
    base.update(over)
    return base


def _challan(**over) -> dict:
    base = {"bsr_code": "0510308", "challan_no": "00042", "payment_date": "2025-09-07",
            "amount_paise": 1_00_000, "section": "194J"}
    base.update(over)
    return base


def test_no_fvu_file_is_produced_is_always_present():
    sheet = keying_sheet.build(_data())
    assert keying_sheet.NO_FVU_FILE_IS_PRODUCED in sheet["gaps"]


def test_the_batch_header_carries_the_deductors_own_identity():
    sheet = keying_sheet.build(_data())
    assert sheet["deductor"] == {
        "tan": "MUMB12345C", "deductor_name": "Acme Traders",
        "deductor_pan": "AAAAA0000A", "deductor_address": "12 MG Road, Mumbai",
    }


def test_record_type_labels_name_the_rpus_own_hierarchy():
    sheet = keying_sheet.build(_data())
    assert sheet["record_types"]["challan_detail"] == keying_sheet.RECORD_CHALLAN_DETAIL
    assert sheet["record_types"]["deductee_detail"] == keying_sheet.RECORD_DEDUCTEE_DETAIL


def test_a_deductee_is_grouped_under_its_matching_challan():
    data = _data(deductees=[_deductee()], challans=[_challan()])
    sheet = keying_sheet.build(data)
    assert len(sheet["challan_sections"]) == 1
    section = sheet["challan_sections"][0]
    assert section["challan"]["challan_no"] == "00042"
    assert len(section["deductees"]) == 1
    assert section["deductees"][0]["deductee_name"] == "Vendor A"
    assert sheet["unmatched_deductees"] == []


def test_two_deductees_under_two_different_challans_do_not_merge():
    data = _data(
        deductees=[
            _deductee(deductee_name="Vendor A", bsr_code="0510308", challan_no="00042"),
            _deductee(deductee_name="Vendor B", bsr_code="0510308", challan_no="00099"),
        ],
        challans=[_challan(challan_no="00042"), _challan(challan_no="00099")],
    )
    sheet = keying_sheet.build(data)
    assert len(sheet["challan_sections"]) == 2
    names = sorted(s["deductees"][0]["deductee_name"] for s in sheet["challan_sections"])
    assert names == ["Vendor A", "Vendor B"]


def test_a_deductee_with_no_challan_reference_is_named_not_dropped():
    data = _data(deductees=[_deductee(bsr_code="", challan_no="")], challans=[])
    sheet = keying_sheet.build(data)
    assert sheet["challan_sections"] == []
    assert len(sheet["unmatched_deductees"]) == 1
    assert any("no matching challan" in g for g in sheet["gaps"])


def test_a_deductee_referencing_a_challan_not_in_the_list_is_its_own_section():
    # The challan register is short a row — not the same defect as an
    # unmatched deductee, and it gets a different sentence.
    data = _data(deductees=[_deductee(bsr_code="9999999", challan_no="77777")], challans=[])
    sheet = keying_sheet.build(data)
    assert len(sheet["challan_sections"]) == 1
    assert sheet["challan_sections"][0]["challan"] is None
    assert sheet["challan_sections"][0]["challan_reference"]["bsr_code"] == "9999999"
    assert any("not among the challans" in g for g in sheet["gaps"])


def test_a_lower_deduction_row_names_the_missing_remark_code():
    data = _data(deductees=[_deductee(is_lower_deduction=True, lower_deduction_cert="LDC123")],
                 challans=[_challan()])
    sheet = keying_sheet.build(data)
    assert any("Remarks" in g and "1 deductee" in g for g in sheet["gaps"])


def test_a_27q_non_deduction_reason_also_names_the_missing_remark_code():
    data = _data(form="27Q", deductees=[_deductee(
        is_lower_deduction=False, lower_deduction_cert=None,
        non_deduction_reason="No PE in India; not chargeable under s.195")],
        challans=[_challan()])
    sheet = keying_sheet.build(data)
    assert any("Remarks" in g for g in sheet["gaps"])


def test_a_clean_return_names_no_remark_gap():
    data = _data(deductees=[_deductee()], challans=[_challan()])
    sheet = keying_sheet.build(data)
    assert not any("Remarks" in g for g in sheet["gaps"])


def test_counts_are_reported():
    data = _data(deductees=[_deductee(), _deductee(deductee_name="Vendor B")],
                 challans=[_challan()])
    sheet = keying_sheet.build(data)
    assert sheet["deductee_count"] == 2
    assert sheet["challan_count"] == 1


def test_an_empty_return_still_builds_a_sheet():
    sheet = keying_sheet.build(_data())
    assert sheet["challan_sections"] == []
    assert sheet["unmatched_deductees"] == []
    assert sheet["deductee_count"] == 0
