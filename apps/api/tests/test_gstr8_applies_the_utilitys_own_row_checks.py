"""GSTR-8 applies the offline utility's own checks on who a supplier is and how long an amount may be (POST-A-458).

WHAT WAS WRONG
    `domain/gst/gstr8.py` checked the tax a CA recorded on each Table 3 / 4 row the way the GSTN offline utility does, and none of the
    utility's checks on WHO the row names or on the SIZE of an amount: the utility's ValidateMod.bas.txt refuses a supplier GSTIN equal
    to the collector's own (`MainMod.DeductorCheck`), a supplier of another State (`MainMod.samestateCheck`, `Left(..., 2)`), an Enrolment
    ID not of `MainMod.ES_ID_REGEX` (`^[0-9]{12}[E][S][0-9a-zA-Z]{1}$`) or of another State, and an amount with more than 13 digits
    before the decimal point. Migration 421's comment says no Enrolment ID shape is recorded; MainMod.bas.txt records one.

WHAT THIS HOLDS
    * each check, on each table the utility applies it to, as a finding beside the row in the utility's terms;
    * the constants are the VBA's own text, read from the recorded source files;
    * without the collector's GSTIN the identity checks are not asked (and say nothing), while the shape and length checks still are;
    * a clean row of the operator's own State has no finding, and the statement built by the service passes the registration's GSTIN.

NEGATIVE CONTROL: against the code before this change all 9 tests here fail (the clean-row one because the function took no collector
GSTIN); the existing statement test was updated, since its fixtures name a seller of another State and an Enrolment ID "E-1".
"""
from __future__ import annotations

from pathlib import Path

from domain.gst import gstr8

SOURCES = Path(__file__).resolve().parents[3] / "docs" / "compliance" / "sources" / "gst-offline-utilities" / "gstr8"
OPERATOR = "27AAACA1234C1ZG"
SAME_STATE = "27AABCU9603R1ZX"
OTHER_STATE = "29AABCU9603R1ZJ"
GOOD_EID = "270000000001ES1"
JUNE = "062026"


def _row(**over) -> gstr8.SupplyRow:
    base = dict(supplier_gstin=SAME_STATE, place_of_supply="27", gross_registered_paise=1_00_000, returns_registered_paise=0,
                gross_unregistered_paise=0, returns_unregistered_paise=0, igst_paise=0, cgst_paise=250, sgst_paise=250)
    base.update(over)
    return gstr8.SupplyRow(**base)


def _amend(**over) -> gstr8.AmendmentRow:
    base = dict(original_period="042026", original_supplier_gstin=SAME_STATE, original_place_of_supply="27", supplier_gstin=SAME_STATE,
                place_of_supply="27", gross_registered_paise=1_00_000, returns_registered_paise=0, gross_unregistered_paise=0,
                returns_unregistered_paise=0, igst_paise=0, cgst_paise=250, sgst_paise=250, action="add")
    base.update(over)
    return gstr8.AmendmentRow(**base)


def _uamend(**over) -> gstr8.UnregisteredAmendmentRow:
    base = dict(original_period="042026", original_enrolment_id=GOOD_EID, enrolment_id=GOOD_EID, gross_value_paise=9_000,
                returns_paise=0, action="add")
    base.update(over)
    return gstr8.UnregisteredAmendmentRow(**base)


def _problems(stmt, *, amend=False) -> dict[str, list[str]]:
    return {f.supplier_gstin: f.problems for f in (stmt.amendment_findings if amend else stmt.findings)}


def test_the_constants_are_the_utilitys_own_text():
    main = (SOURCES / "MainMod.bas.txt").read_text(encoding="utf-8", errors="replace")
    validate = (SOURCES / "ValidateMod.bas.txt").read_text(encoding="utf-8", errors="replace")
    assert f'Public Const ES_ID_REGEX = "{gstr8.ES_ID_REGEX.pattern}"' in main
    assert f"length1 = {gstr8.AMOUNT_MAX_INTEGER_DIGITS}" in validate
    assert "Supplier GSTIN can’t be same as Tax collector GSTIN in Home sheet" in validate
    assert "ded = Left(Sheets(\"Home\").Cells(6, 2).value, 2)" in main, "the same-State check compares the first two characters"


def test_a_clean_row_of_the_operators_state_has_no_finding():
    stmt = gstr8.compute_gstr8(period=JUNE, supply_rows=[_row()], collector_gstin=OPERATOR,
                               unregistered_rows=[gstr8.UnregisteredSupplyRow(GOOD_EID, 5_000, 0)])
    assert stmt.findings == []


def test_table_3_names_a_supplier_who_is_the_collector_and_one_of_another_state():
    stmt = gstr8.compute_gstr8(period=JUNE, supply_rows=[_row(supplier_gstin=OPERATOR), _row(supplier_gstin=OTHER_STATE)],
                               unregistered_rows=[], collector_gstin=OPERATOR)
    found = _problems(stmt)
    assert any("this operator's own GSTIN" in p for p in found[OPERATOR])
    assert any("of State 29" in p and "of State 27" in p for p in found[OTHER_STATE])


def test_table_3_names_an_amount_with_more_than_13_digits_and_not_one_with_13():
    big = 10 ** 13 * 100                          # ₹10,00,00,00,00,00,000: fourteen digits
    edge = (10 ** 13 - 1) * 100                   # thirteen nines
    stmt = gstr8.compute_gstr8(period=JUNE, supply_rows=[_row(gross_unregistered_paise=big), _row(supplier_gstin=SAME_STATE[:-1] + "Y",
                                                                                                 gross_registered_paise=edge)],
                               unregistered_rows=[], collector_gstin=OPERATOR)
    found = _problems(stmt)
    assert any("value of supplies to unregistered persons" in p and "more than 13 digits" in p for p in found[SAME_STATE])
    assert not any("13 digits" in p for p in found.get(SAME_STATE[:-1] + "Y", []))


def test_table_3_1_names_an_enrolment_id_of_the_wrong_shape_or_state_and_an_amount_too_long():
    rows = [gstr8.UnregisteredSupplyRow("EID123", 5_000, 0), gstr8.UnregisteredSupplyRow("290000000001ES1", 5_000, 0),
            gstr8.UnregisteredSupplyRow("270000000002ES1", 10 ** 13 * 100, 0)]
    found = _problems(gstr8.compute_gstr8(period=JUNE, supply_rows=[], unregistered_rows=rows, collector_gstin=OPERATOR))
    assert any("not in the form the offline utility accepts" in p for p in found["EID123"])
    assert any("of State 29" in p for p in found["290000000001ES1"])
    assert any("more than 13 digits" in p for p in found["270000000002ES1"])


def test_table_4_names_the_original_and_the_revised_supplier():
    stmt = gstr8.compute_gstr8(period=JUNE, supply_rows=[], unregistered_rows=[], collector_gstin=OPERATOR,
                               amendment_rows=[_amend(original_supplier_gstin=OPERATOR, supplier_gstin=OTHER_STATE)])
    (problems,) = _problems(stmt, amend=True).values()
    assert any("original supplier's GSTIN is this operator's own" in p for p in problems)
    assert any("revised supplier's GSTIN is of State 29" in p for p in problems)


def test_table_4_names_an_amount_too_long():
    stmt = gstr8.compute_gstr8(period=JUNE, supply_rows=[], unregistered_rows=[], collector_gstin=OPERATOR,
                               amendment_rows=[_amend(returns_registered_paise=10 ** 13 * 100)])
    (problems,) = _problems(stmt, amend=True).values()
    assert any("value returned by registered persons" in p and "13 digits" in p for p in problems)


def test_table_4_1_names_both_enrolment_ids_and_an_amount_too_long():
    stmt = gstr8.compute_gstr8(period=JUNE, supply_rows=[], unregistered_rows=[], collector_gstin=OPERATOR,
                               unregistered_amendment_rows=[_uamend(original_enrolment_id="E-1", enrolment_id="290000000001ES1",
                                                                    gross_value_paise=10 ** 13 * 100)])
    (problems,) = _problems(stmt, amend=True).values()
    assert any("original Enrolment ID (E-1)" in p for p in problems)
    assert any("revised Enrolment ID is of State 29" in p for p in problems)
    assert any("gross value" in p and "13 digits" in p for p in problems)


def test_without_the_collectors_gstin_the_identity_checks_are_not_asked_and_the_shape_still_is():
    stmt = gstr8.compute_gstr8(period=JUNE, supply_rows=[_row(supplier_gstin=OTHER_STATE)],
                               unregistered_rows=[gstr8.UnregisteredSupplyRow("EID123", 5_000, 0),
                                                  gstr8.UnregisteredSupplyRow("290000000001ES1", 5_000, 0)])
    found = _problems(stmt)
    assert OTHER_STATE not in found and "290000000001ES1" not in found, "a check that cannot be asked says nothing"
    assert any("not in the form" in p for p in found["EID123"])
