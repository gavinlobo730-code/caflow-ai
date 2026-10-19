"""Form 3CD clause 34: "tax deducted and not deposited" is the CHALLAN REGISTER's answer, not two columns nothing writes.

`services/form_3cd_service._clause_34` counted a deduction as deposited when its `status` was `deposited` or `filed` or its
`challan_no` was set. A deduction a purchase bill writes never carries either (`POST /challans` records the challan and never
touches the deductions it paid), so for nearly every deduction the clause said the whole tax was deducted and not deposited,
in the statutory output a tax auditor signs. It asks the register now: `deposit_due.mapping_from_register`, the match the
quarterly statements and the deposit worksheet make (a challan pays the deductions of its own financial year and quarter under
its own section, first in first out).
"""
from __future__ import annotations

import ast
import inspect

import pytest

from domain.tds import challan_mapping, deposit_due
from services import form_3cd_service
from services.form_3cd_service import _clause_34
from tests.e2e_harness import FakeDB

FIRM = "11111111-1111-4111-8111-111111111111"
CLIENT = "22222222-2222-4222-8222-222222222222"
OTHER_CLIENT = "33333333-3333-4333-8333-333333333333"
OTHER_FIRM = "44444444-4444-4444-8444-444444444444"
FY = "2025-26"


def ded(section="194C", on="2025-05-10", tds=10_000_00, surcharge=0, cess=0, client=CLIENT, firm=FIRM, **more):
    return {"firm_id": firm, "client_id": client, "section": section, "transaction_date": on,
            "payment_amount_paise": tds * 50, "tds_paise": tds, "surcharge_paise": surcharge, "cess_paise": cess, **more}


def chl(section="194C", quarter="Q1", fy=FY, tds=10_000_00, surcharge=0, client=CLIENT, firm=FIRM, no="C1", paid_on="2025-06-07"):
    return {"firm_id": firm, "client_id": client, "section": section, "challan_no": no, "financial_year": fy, "quarter": quarter,
            "tds_paise": tds, "surcharge_paise": surcharge, "payment_date": paid_on}


def clause(deductions, challans=(), fy=FY):
    db = FakeDB()
    db.seed("client_statutory_identity", {"firm_id": FIRM, "client_id": CLIENT, "tan": "MUMB12345A"})
    for d in deductions:
        db.seed("tds_deductions", d)
    for c in challans:
        db.seed("tds_challans", c)
    value, note = _clause_34(db, FIRM, CLIENT, fy)
    return value, note, {r["section"]: r for r in value["by_section"]}


def total_not_deposited(value) -> int:
    """Everything the register does not cover, whichever column it lands in."""
    return sum(r["tax_deducted_not_deposited_paise"] + r["deposit_not_recorded_paise"] for r in value["by_section"])


def not_covered(row) -> int:
    return row["tax_deducted_not_deposited_paise"] + row["deposit_not_recorded_paise"]


# ── The defect, stated as the rule ────────────────────────────────────────────────────────────────────────────────────

def test_a_deduction_a_challan_paid_is_deposited_though_the_deduction_itself_carries_nothing():
    value, note, by = clause([ded()], [chl()])
    assert by["194C"]["total_tds_deducted_paise"] == 10_000_00
    assert by["194C"]["total_tds_deposited_paise"] == 10_000_00
    assert by["194C"]["tax_deducted_not_deposited_paise"] == 0
    assert value["challans_read"] == 1


def test_a_deduction_with_no_challan_in_its_quarter_is_not_recorded_and_is_not_a_deposit_default():
    """THE BOOKS CANNOT SAY: with no challan recorded for the quarter (a firm that keeps its deposits in Tally, say) the tax is
    reported apart as not recorded and not as tax deducted and not deposited. An unknown is never shown as a value."""
    value, note, by = clause([ded()])
    assert by["194C"]["tax_deducted_not_deposited_paise"] == 0
    assert by["194C"]["deposit_not_recorded_paise"] == 10_000_00
    assert by["194C"]["total_tds_deposited_paise"] == 0
    assert value["challans_read"] == 0
    assert "no challan is recorded for FY 2025-26" in note and "NOT RECORDED" in note


def test_the_register_speaks_for_a_quarter_in_which_any_challan_is_recorded_and_not_for_one_with_none():
    """Q1 holds a short challan, Q3 holds none: Q1's shortfall is NOT DEPOSITED, Q3's tax is NOT RECORDED."""
    rows = [ded(on="2025-05-10", tds=10_000_00), ded(on="2025-11-10", tds=4_000_00)]
    value, _, by = clause(rows, [chl(quarter="Q1", tds=6_000_00)])
    assert by["194C"]["tax_deducted_not_deposited_paise"] == 4_000_00
    assert by["194C"]["deposit_not_recorded_paise"] == 4_000_00
    assert by["194C"]["total_tds_deposited_paise"] == 6_000_00
    assert by["194C"]["total_tds_deducted_paise"] == 14_000_00


def test_a_challan_number_and_a_deposited_status_typed_on_a_hand_keyed_deduction_are_notes_and_deposit_nothing():
    """The manual deduction form can carry `challan_no`; nothing about the register changes for it. The statement, the deposit
    worksheet and the hub's TDS tile ask the register too, so the four agree and the CA is told to record the challan."""
    row = ded(challan_no="0510001-12345", challan_date="2025-06-07", status="deposited")
    value, note, by = clause([row])
    assert by["194C"]["total_tds_deposited_paise"] == 0
    assert not_covered(by["194C"]) == 10_000_00
    assert "A challan number typed on a deduction is not read" in note


def test_a_short_challan_pays_the_earliest_deduction_and_leaves_the_later_one():
    rows = [ded(on="2025-04-10", tds=6_000_00), ded(on="2025-05-10", tds=4_000_00)]
    value, note, by = clause(rows, [chl(tds=6_000_00)])
    assert by["194C"]["total_tds_deposited_paise"] == 6_000_00
    assert by["194C"]["tax_deducted_not_deposited_paise"] == 4_000_00


def test_a_challan_pays_only_the_deductions_of_its_own_quarter_year_section_and_client():
    for other in (chl(quarter="Q2"), chl(fy="2024-25"), chl(section="194J"), chl(client=OTHER_CLIENT), chl(firm=OTHER_FIRM)):
        value, _, by = clause([ded()], [other])
        assert by["194C"]["total_tds_deposited_paise"] == 0, other
        assert not_covered(by["194C"]) == 10_000_00, other


def test_the_surplus_of_one_group_pays_nothing_in_another():
    rows = [ded(section="194C", tds=10_000_00), ded(section="194J", on="2025-05-12", tds=7_500_00),
            ded(section="194C", on="2025-08-02", tds=3_000_00)]
    value, _, by = clause(rows, [chl(tds=15_000_00)])
    assert not_covered(by["194C"]) == 3_000_00           # the Q2 deduction, not paid by Q1's surplus (Q2 has no challan: not recorded)
    assert by["194C"]["deposit_not_recorded_paise"] == 3_000_00
    assert by["194J"]["tax_deducted_not_deposited_paise"] == 7_500_00      # Q1 has a challan, so the register speaks
    assert total_not_deposited(value) == 10_500_00
    assert [w["code"] for w in value["register_warnings"]] == ["challan_exceeds_deductions"]


def test_a_challan_typed_with_the_parent_section_pays_a_clause_deduction_and_the_row_keeps_its_own_label():
    value, _, by = clause([ded(section="194J(B)", tds=2_000_00)], [chl(section="194J", tds=2_000_00)])
    assert by["194J(B)"]["tax_deducted_not_deposited_paise"] == 0
    assert "194J" not in by


def test_the_whole_year_is_read_four_quarters_and_the_edges_of_the_window():
    rows = [ded(on="2025-04-01", tds=1_00), ded(on="2025-06-30", tds=2_00), ded(on="2025-07-01", tds=4_00),
            ded(on="2025-09-30", tds=8_00), ded(on="2025-10-01", tds=16_00), ded(on="2025-12-31", tds=32_00),
            ded(on="2026-01-01", tds=64_00), ded(on="2026-03-31", tds=128_00),
            ded(on="2025-03-31", tds=9_999_00), ded(on="2026-04-01", tds=9_999_00)]        # outside the year: not read
    pays = [chl(quarter="Q1", tds=3_00, no="1"), chl(quarter="Q2", tds=12_00, no="2"),
            chl(quarter="Q3", tds=48_00, no="3"), chl(quarter="Q4", tds=192_00, no="4")]
    value, _, by = clause(rows, pays)
    assert by["194C"]["count"] == 8
    assert by["194C"]["total_tds_deducted_paise"] == 255_00
    assert by["194C"]["total_tds_deposited_paise"] == 255_00
    assert total_not_deposited(value) == 0


def test_a_neighbouring_quarter_challan_does_not_pay_a_boundary_date():
    """1 July is Q2 and 30 June is Q1: each boundary date is judged against a challan labelled for its own quarter."""
    for on, own, other in (("2025-06-30", "Q1", "Q2"), ("2025-07-01", "Q2", "Q1"), ("2025-12-31", "Q3", "Q4"), ("2026-01-01", "Q4", "Q3")):
        assert total_not_deposited(clause([ded(on=on)], [chl(quarter=own)])[0]) == 0, (on, own)
        assert total_not_deposited(clause([ded(on=on)], [chl(quarter=other)])[0]) == 10_000_00, (on, other)


def test_salary_is_deposited_from_payroll_and_is_left_out_and_counted_not_shown_as_undeposited():
    value, note, by = clause([ded(section="192", tds=5_00), ded(section="Sec192", tds=6_00), ded(tds=1_00)],
                             [chl(section="192", tds=9_99), chl(tds=1_00, no="2")])
    assert "192" not in by and "Sec192" not in by
    assert value["salary_rows_left_out"] == 2
    assert value["challans_read"] == 1                    # the salary challan is not read
    assert total_not_deposited(value) == 0
    assert "section 192" in note


def test_where_a_row_carries_surcharge_or_cess_the_split_is_approximate_and_says_so():
    """Section 195, two rows: tax 100 + surcharge 10 + cess 4, and tax 100. A challan of tax 200 plus surcharge 0 covers 200 of
    the 214 the two owe; first in first out puts that 200 on the first row's 114 and 86 of the second's 100, so the clause's tax
    column reads 186 deposited and 14 not. The register's cover is of tax, surcharge and cess together, the clause's column is the
    tax alone, and the section is marked approximate rather than shown as exact."""
    rows = [ded(section="195", on="2025-05-10", tds=100_00, surcharge=10_00, cess=4_00, id="s1"),
            ded(section="195", on="2025-05-11", tds=100_00, id="s2")]
    value, note, by = clause(rows, [chl(section="195", tds=200_00)])
    assert by["195"]["total_tds_deposited_paise"] == 186_00
    assert by["195"]["tax_deducted_not_deposited_paise"] == 14_00
    assert by["195"]["surcharge_or_cess_makes_the_split_approximate"] is True
    assert "surcharge or cess" in note
    # The challan's own surcharge is capacity too: tax 180 plus surcharge 10 is 190, which covers the first row's 114 and 76 of the
    # second's 100, so 176 of the tax column reads deposited (tax 180 alone would cover 66, and read 166).
    value, _, by = clause(rows, [chl(section="195", tds=180_00, surcharge=10_00)])
    assert by["195"]["total_tds_deposited_paise"] == 176_00
    assert by["195"]["tax_deducted_not_deposited_paise"] == 24_00
    # A section with no surcharge or cess is not marked.
    assert clause([ded()], [chl()])[2]["194C"]["surcharge_or_cess_makes_the_split_approximate"] is False


def test_a_cess_on_the_deduction_is_part_of_what_the_challan_has_to_cover():
    row = ded(section="195", tds=100_00, cess=4_00)
    value, _, by = clause([row], [chl(section="195", tds=100_00)])
    assert by["195"]["total_tds_deposited_paise"] == 100_00 and by["195"]["tax_deducted_not_deposited_paise"] == 0
    value, _, by = clause([ded(section="195", tds=100_00, cess=4_00), ded(section="195", on="2025-05-11", tds=50_00)],
                          [chl(section="195", tds=104_00)])
    assert by["195"]["total_tds_deposited_paise"] == 150_00 - 50_00
    assert by["195"]["tax_deducted_not_deposited_paise"] == 50_00


# ── What the register itself warns about travels with the figure ──────────────────────────────────────────────────────

def test_a_challan_recorded_twice_is_named_because_it_would_otherwise_count_as_two_deposits():
    rows = [ded(on="2025-04-10", tds=10_000_00), ded(on="2025-05-10", tds=10_000_00)]
    twice = [chl(tds=10_000_00, no="C1", paid_on="2025-06-07") | {"bsr_code": "0510001"},
             chl(tds=10_000_00, no="C1", paid_on="2025-06-07") | {"bsr_code": "0510001"}]
    value, _, by = clause(rows, twice)
    assert by["194C"]["total_tds_deposited_paise"] == 20_000_00         # counted twice, and the figure says so by naming it
    assert [(w["code"], w["challan_no"], w["times"]) for w in value["register_warnings"]] == [
        ("challan_recorded_more_than_once", "C1", 2)]
    # A challan is identified by branch code, serial and date together: change any one and it is a different challan.
    for other in ({"challan_no": "C2"}, {"bsr_code": "0510002"}, {"payment_date": "2025-06-08"}):
        distinct = [twice[0], {**twice[1], **other}]
        assert not [w for w in clause(rows, distinct)[0]["register_warnings"]
                    if w["code"] == "challan_recorded_more_than_once"], other


def test_a_challan_recorded_under_the_wrong_quarter_is_a_warning_beside_a_deduction_that_is_not_recorded():
    """A 20 June deduction and a challan that paid it, labelled Q2: the deduction's quarter holds no challan (not recorded) and
    Q2's challan paid more than Q2 deducted, which is what a mislabelled challan looks like."""
    value, _, by = clause([ded(on="2025-06-20")], [chl(quarter="Q2", paid_on="2025-07-05")])
    assert by["194C"]["deposit_not_recorded_paise"] == 10_000_00
    warnings = value["register_warnings"]
    assert [(w["code"], w["quarter"]) for w in warnings] == [("challan_exceeds_deductions", "Q2")]
    assert warnings[0]["surplus_paise"] == 10_000_00


def test_a_clean_year_carries_no_warnings():
    assert clause([ded()], [chl()])[0]["register_warnings"] == []


def test_another_clients_and_another_firms_rows_are_not_in_the_clause():
    value, _, by = clause([ded(), ded(client=OTHER_CLIENT, tds=99_000_00), ded(firm=OTHER_FIRM, tds=88_000_00)], [chl()])
    assert by["194C"]["total_tds_deducted_paise"] == 10_000_00
    assert total_not_deposited(value) == 0


# ── The clause agrees with the match the statements and the worksheet make ────────────────────────────────────────────

def test_the_clause_says_what_the_registers_own_match_says_for_one_fixture_across_the_year():
    rows = [ded(section="194C", on="2025-04-10", tds=6_000_00, id="a"), ded(section="194C", on="2025-05-10", tds=4_000_00, id="b"),
            ded(section="194J(B)", on="2025-05-11", tds=2_500_00, id="c"), ded(section="194I(a)", on="2025-08-11", tds=900_00, id="d"),
            ded(section="194C", on="2025-11-10", tds=1_234_56, id="e"), ded(section="194H", on="2026-02-03", tds=777_00, id="f")]
    pays = [chl(quarter="Q1", tds=7_000_00, no="1"), chl(section="194J", quarter="Q1", tds=2_000_00, no="2"),
            chl(section="194I", quarter="Q2", tds=900_00, no="3"), chl(section="194C", quarter="Q3", tds=1_000_00, no="4"),
            chl(section="194H", quarter="Q1", tds=777_00, no="5")]          # the wrong quarter for the Q4 deduction
    value, _, _ = clause(rows, pays)
    expected = 0
    for quarter, months in (("Q1", (4, 5, 6)), ("Q2", (7, 8, 9)), ("Q3", (10, 11, 12)), ("Q4", (1, 2, 3))):
        quarter_rows = [r for r in rows if int(r["transaction_date"][5:7]) in months]
        mapping = deposit_due.mapping_from_register(quarter_rows, [c for c in pays if c["quarter"] == quarter], fy=FY)
        expected += sum(g["shortfall_paise"] for g in mapping.gaps if g["code"] == challan_mapping.GAP_DEDUCTIONS_NOT_DEPOSITED)
    assert expected > 0
    assert total_not_deposited(value) == expected


def test_the_clause_and_the_worksheet_agree_about_one_month():
    rows = [ded(on="2025-07-10", tds=5_000_00, id="w1"), ded(section="194J", on="2025-07-12", tds=3_000_00, id="w2")]
    pays = [chl(quarter="Q2", tds=5_000_00, no="W", paid_on="2025-08-07")]
    mapping = deposit_due.mapping_from_register(rows, pays, fy=FY)
    from datetime import date
    sheet = deposit_due.build(rows, month="2025-07", due_date=date(2025, 8, 7), as_at=date(2025, 8, 7), deposits=mapping)
    value, _, _ = clause(rows, pays)
    assert sheet.totals["outstanding_paise"] == total_not_deposited(value) == 3_000_00
    assert sum(r["tax_deducted_not_deposited_paise"] for r in value["by_section"]) == 3_000_00   # Q2 has a challan: not just "not recorded"


def test_a_challan_dated_before_the_deduction_is_counted_here_as_the_statements_deductee_row_counts_it():
    """The clause asks how much of the tax the register covers, not whether the deposit was on time (the worksheet and the
    purchase-return note judge the date and report a pre-dated challan): it is the one place they differ, on purpose."""
    value, _, by = clause([ded(on="2025-07-10")], [chl(quarter="Q2", paid_on="2025-06-07")])
    assert by["194C"]["tax_deducted_not_deposited_paise"] == 0


# ── The rule, stated so that the next reader of those columns is caught ───────────────────────────────────────────────

def test_clause_34_reads_neither_the_status_nor_the_challan_number_of_a_deduction():
    """Every `select(` string in the two functions, so a column added back to the deductions' projection is red."""
    tree = ast.parse(inspect.getsource(form_3cd_service))
    selects: list[tuple[str, str]] = []
    for fn in tree.body:
        if isinstance(fn, ast.FunctionDef) and fn.name in ("_clause_34", "_deposits_by_deduction"):
            for node in ast.walk(fn):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "select"
                        and node.args and isinstance(node.args[0], ast.Constant)):
                    selects.append((fn.name, node.args[0].value))
    deductions = [cols for _, cols in selects if "payment_amount_paise" in cols]
    challans = [cols for _, cols in selects if "payment_date" in cols]
    assert len(deductions) == 1 and len(challans) == 1, selects
    for forbidden in ("status", "challan_no", "challan_date"):
        assert forbidden not in deductions[0], f"clause 34 reads tds_deductions.{forbidden}, a column nothing writes"


def test_the_module_still_exposes_the_helper_the_clause_uses():
    assert callable(form_3cd_service._deposits_by_deduction) and callable(deposit_due.is_salary)


@pytest.mark.parametrize("section", ["192", "SEC192", "s192", " 192 ", "Sec 192"])
def test_the_salary_spellings_are_the_one_definition_the_worksheet_uses(section):
    assert deposit_due.is_salary(section)
