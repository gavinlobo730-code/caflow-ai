"""The TDS screen's "tax not yet deposited" card and its Deposit column are the challan register's answer, read by the server (POST-A-273).

WHAT WAS WRONG (found by opening the seeded demo firm in a browser, 19-10-2026)
    * the "Pending Challans / Undeposited" card counted `tds_challans.status === "unmatched"` in the browser, and `create_challan` always
      writes `deposited`, so the card was 0 for ever beside a word that says undeposited;
    * the deductions table printed a "Challan No" column from `tds_deductions.challan_no`, a field nothing writes for a deduction a
      purchase bill creates, so it was a dash for nearly every row;
    * "Total TDS Deducted: All time" read ₹0.00 before a client was chosen (and the returns and certificates cards read 0), an unknown
      shown as a value;
    * the Add Challan modal closed without saying what became of the monthly deposit obligations on the compliance calendar.

WHAT IS HELD
    * `domain/tds/deposit_state` says, per deduction, DEPOSITED, PART, NOT_DEPOSITED, NOT_RECORDED, NIL, SALARY or UNDATED, by the
      register's first-in-first-out match inside a quarter that has a challan recorded; a quarter with none is NOT RECORDED, not "not
      deposited"; a PART or NOT_DEPOSITED row says whether its deposit is yet due (not yet due is not overdue);
    * the words are the server's (the `legend`, sent once, and `words` for a sentence about one row), and the browser words nothing;
    * the card is the database's position (the reader the hub's tile uses), and the column and the card agree on one fixture, and both
      agree with Form 3CD clause 34;
    * `GET /api/tds-workspace/deposit-state` asks `rbac("tds", "read")` and the client check, reads one client's rows with firm and
      client scope and no ordering of its own, and answers an unreadable position as `position: null` (the rows are still answered)
      and never as a zero.
"""
from __future__ import annotations

import ast
import inspect

import pytest
from fastapi.testclient import TestClient

from domain.tds import deposit_state as ds
from domain.tds.deposit_state import (DEPOSITED, NIL, NOT_DEPOSITED, NOT_RECORDED, PART, SALARY, UNDATED, RowState, deduction_states,
                                      register_warnings, words)
from domain.tds.undeposited import position
from services import tds_deposit_state_service as service
from tests.e2e_harness import FakeDB

FIRM = "11111111-1111-4111-8111-111111111111"
CLIENT = "22222222-2222-4222-8222-222222222222"
OTHER_CLIENT = "33333333-3333-4333-8333-333333333333"
OTHER_FIRM = "44444444-4444-4444-8444-444444444444"


def ded(id_, on="2026-05-10", tds=10_000_00, section="194C", surcharge=0, cess=0):
    return {"id": id_, "section": section, "transaction_date": on, "tds_paise": tds, "surcharge_paise": surcharge, "cess_paise": cess}


def chl(no, fy="2026-27", quarter="Q1", tds=10_000_00, section="194C", surcharge=0, paid_on="2026-06-07", **more):
    return {"id": f"c-{no}", "challan_no": no, "section": section, "financial_year": fy, "quarter": quarter, "tds_paise": tds,
            "surcharge_paise": surcharge, "payment_date": paid_on, **more}


def state_of(rows, challans):
    return {k: v.state for k, v in deduction_states(rows, challans).items()}


# ── The five states ───────────────────────────────────────────────────────────

def test_a_deduction_the_registers_challan_covers_is_deposited_and_names_the_challan():
    got = deduction_states([ded("a")], [chl("C1")])["a"]
    assert (got.state, got.deposited_paise, got.challans) == (DEPOSITED, 10_000_00, ("C1",))
    assert (got.financial_year, got.quarter) == ("2026-27", "Q1")


def test_a_short_quarter_leaves_the_last_deductions_uncovered_first_in_first_out():
    rows = [ded("a", "2026-04-10", 5_000_00), ded("b", "2026-05-10", 5_000_00), ded("c", "2026-06-10", 5_000_00)]
    got = deduction_states(rows, [chl("C1", tds=8_000_00)])
    assert [(k, v.state, v.deposited_paise) for k, v in sorted(got.items())] == [
        ("a", DEPOSITED, 5_000_00), ("b", PART, 3_000_00), ("c", NOT_DEPOSITED, 0)]


def test_a_quarter_with_no_challan_recorded_is_not_recorded_and_not_not_deposited():
    """The books cannot say whether it was deposited: a firm that keeps its deposits elsewhere records no challan here."""
    assert state_of([ded("a")], []) == {"a": NOT_RECORDED}
    assert state_of([ded("a")], [chl("C1", quarter="Q2")]) == {"a": NOT_RECORDED}
    assert state_of([ded("a")], [chl("C1", fy="2025-26")]) == {"a": NOT_RECORDED}


def test_a_salary_challan_does_not_record_a_quarter_and_a_salary_row_is_through_payroll():
    assert state_of([ded("a")], [chl("S1", section="192")]) == {"a": NOT_RECORDED}
    assert state_of([ded("s", section="192"), ded("t", section="Sec192")], [chl("C1")]) == {"s": SALARY, "t": SALARY}


def test_a_row_with_no_usable_date_is_undated_and_never_judged_in_a_quarter():
    got = deduction_states([ded("a", on=None), ded("b", on="")], [chl("C1")])
    assert {k: v.state for k, v in got.items()} == {"a": UNDATED, "b": UNDATED}


def test_a_section_with_no_challan_in_a_quarter_that_has_others_is_not_deposited():
    """Whoever records a quarter's deposits records all of them, so a section with none beside others is a real shortfall."""
    assert state_of([ded("a", section="194C"), ded("b", section="194J")], [chl("C1", section="194C")]) == {"a": DEPOSITED, "b": NOT_DEPOSITED}


def test_a_challan_typed_with_the_parent_section_covers_a_clause_deduction():
    assert state_of([ded("a", section="194J(B)")], [chl("C1", section="194J")]) == {"a": DEPOSITED}


def test_a_nil_row_and_a_negative_one_are_nil_in_a_recorded_quarter_and_in_an_unrecorded_one_and_are_never_missing_anything():
    """A row that owes nothing has nothing to deposit, so it is not "no challan recorded" in a quarter nobody recorded."""
    for rows, challans in (([ded("a", tds=0)], [chl("C1", section="194J")]), ([ded("a", tds=0)], []),
                           ([ded("a", tds=-5_00)], [chl("C1")]), ([ded("a", tds=-5_00)], [])):
        got = deduction_states(rows, challans)["a"]
        assert got.state == NIL and got.tax_paise == 0 and got.challans == ()


def test_a_challan_dated_before_the_tax_was_deducted_still_covers_by_the_registers_order_and_says_so():
    """The register matches by order and not by date; the deposit worksheet, which judges each challan by its date, refuses such a
    part. The column keeps the register's answer and does not disagree with the worksheet in silence."""
    row, challan = ded("a", "2026-05-20", 1_000_00), chl("CH1", tds=1_000_00, paid_on="2026-05-07")
    got = deduction_states([row], [challan])["a"]
    assert got.state == DEPOSITED and got.dated_before is True
    assert "dated before the tax was deducted" in words(got)[1]
    ok = deduction_states([ded("a", "2026-05-20", 1_000_00)], [chl("CH1", tds=1_000_00, paid_on="2026-06-07")])["a"]
    assert ok.dated_before is False and words(ok)[1] is None, "an ordinary deposited row has no sentence of its own"


def test_a_challan_serial_that_is_blank_is_not_named_and_the_sentence_does_not_stutter():
    got = deduction_states([ded("a")], [chl("  ")])["a"]
    assert got.state == DEPOSITED and got.challans == ()
    said = words(RowState(DEPOSITED, 1_00, 1_00, got.challans, "2026-27", "Q1", dated_before=True))[1]
    assert said.startswith("Covered by a recorded challan,")
    assert "challan a recorded challan" not in said


def test_each_quarter_year_and_row_is_judged_by_its_own_challans():
    rows = [ded("a", "2026-05-10"), ded("b", "2026-08-10"), ded("c", "2027-05-10")]
    assert state_of(rows, [chl("C1")]) == {"a": DEPOSITED, "b": NOT_RECORDED, "c": NOT_RECORDED}


def test_surcharge_and_cess_are_tax_to_deposit_and_the_challans_tax_includes_its_surcharge():
    row = ded("a", section="195", tds=10_000_00, surcharge=1_000_00, cess=440_00)
    assert deduction_states([row], [chl("C1", section="195", tds=10_000_00, surcharge=1_000_00)])["a"].state == PART
    assert deduction_states([row], [chl("C1", section="195", tds=10_440_00, surcharge=1_000_00)])["a"].state == DEPOSITED


def test_a_deduction_drawing_on_two_challans_names_both_in_the_order_it_drew():
    rows = [ded("a", tds=10_000_00)]
    got = deduction_states(rows, [chl("C1", tds=4_000_00), chl("C2", tds=6_000_00)])["a"]
    assert got.state == DEPOSITED and got.challans == ("C1", "C2")


# ── The words are the server's ───────────────────────────────────────────────

@pytest.mark.parametrize("row,label,needles", [
    (RowState(PART, 10_000_00, 3_000_00, ("C1",), "2026-27", "Q1"), "Part deposited",
     ["₹3,000.00 of ₹10,000.00 (tax with surcharge and cess)", "challan C1"]),
    (RowState(DEPOSITED, 10_000_00, 10_000_00, ("C1", "C2"), "2026-27", "Q1", dated_before=True), "Deposited",
     ["C1, C2", "Q1 of 2026-27", "dated before the tax was deducted"]),
])
def test_a_sentence_about_one_row_says_what_it_read(row, label, needles):
    got_label, sentence = words(row)
    assert got_label == label
    for needle in needles:
        assert needle in sentence, (label, needle, sentence)


@pytest.mark.parametrize("state,label,needles", [
    (DEPOSITED, "Deposited", ["first in first out"]),
    (PART, "Part deposited", ["Some of it is covered"]),
    (NOT_DEPOSITED, "Not deposited", ["do not reach it", "none is recorded under its section", "Record the challan"]),
    (NOT_RECORDED, "Unknown: no challan recorded", ["No challan is recorded for this deduction's quarter", "not known here"]),
    (SALARY, "Through payroll", ["deposited from payroll"]),
    (UNDATED, "No date", ["no quarter can be judged"]),
    (NIL, "Nothing to deposit", ["counts as nil", "nothing to deposit"]),
])
def test_each_state_has_its_own_label_and_a_generic_sentence_in_the_legend(state, label, needles):
    entry = ds.legend()[state]
    assert entry["label"] == label
    for needle in needles:
        assert needle in entry["sentence"], (state, needle, entry["sentence"])
    assert words(RowState(state, 5_00, 0, (), "2026-27", "Q1"))[0] == label, "the label is one definition"


def test_the_two_labels_a_column_headed_deposit_could_be_misread_from_say_what_they_mean():
    """"Nil" beside "Deposit" reads as nothing was deposited; "No challan recorded" reads as not deposited. Neither is the case."""
    assert ds.LABELS[NIL] == "Nothing to deposit"
    assert ds.LABELS[NOT_RECORDED].startswith("Unknown")


def test_no_two_states_share_a_label():
    labels = [words(RowState(s, 5_00, 1_00, ("C",), "2026-27", "Q1"))[0] for s in ds.STATES]
    assert len(set(labels)) == len(labels)


# ── The column, the card, the tile and Form 3CD clause 34 are one answer ─────────────────────────────────────

FIXTURE_ROWS = [
    ded("a1", "2025-05-10", 10_000_00, "194C"), ded("a2", "2025-06-10", 5_000_00, "194J"), ded("a3", "2025-06-20", 2_000_00, "194C"),
    ded("b1", "2025-08-10", 3_000_00, "194C"),
    ded("c1", "2025-11-10", 2_000_00, "194J"),
    ded("d1", "2026-02-10", 700_00, "194C"),
    ded("s1", "2025-05-10", 9_00, "192"),
]
FIXTURE_CHALLANS = [chl("1", "2025-26", "Q1", 6_000_00, "194C"), chl("2", "2025-26", "Q3", 2_000_00, "194J"),
                    chl("3", "2025-26", "Q4", 100_00, "192")]


def test_the_column_the_card_and_the_clause_say_the_same_for_one_year_of_one_client():
    """The sum of what the column leaves uncovered in recorded quarters is the card's figure; the tax in NOT_RECORDED rows is what the
    card's caveat names; and both are Form 3CD clause 34's two figures. Held to one fixture so they cannot drift apart."""
    from services.form_3cd_service import _clause_34
    states = deduction_states(FIXTURE_ROWS, FIXTURE_CHALLANS)
    column_short = sum(v.tax_paise - v.deposited_paise for v in states.values() if v.state in (PART, NOT_DEPOSITED))
    column_unknown = sum(v.tax_paise for v in states.values() if v.state == NOT_RECORDED)
    card = position([{**r, "client_id": CLIENT} for r in FIXTURE_ROWS], [{**c, "client_id": CLIENT} for c in FIXTURE_CHALLANS])
    assert (column_short, column_unknown) == (card.undeposited_paise, card.not_recorded_paise) == (4_000_00 + 5_000_00 + 2_000_00, 3_000_00 + 700_00)

    db = FakeDB()
    db.seed("client_statutory_identity", {"firm_id": FIRM, "client_id": CLIENT, "tan": "MUMB12345A"})
    for r in FIXTURE_ROWS:
        db.seed("tds_deductions", {**r, "firm_id": FIRM, "client_id": CLIENT, "payment_amount_paise": r["tds_paise"] * 50})
    for c in FIXTURE_CHALLANS:
        db.seed("tds_challans", {**c, "firm_id": FIRM, "client_id": CLIENT})
    value, _note = _clause_34(db, FIRM, CLIENT, "2025-26")
    assert sum(r["tax_deducted_not_deposited_paise"] for r in value["by_section"]) == column_short
    assert sum(r["deposit_not_recorded_paise"] for r in value["by_section"]) == column_unknown


def test_the_registry_key_by_key_the_column_and_the_cards_figure_agree():
    from domain.tds import section_rates
    rows, challans = [], []
    for fy, rates in sorted(section_rates.TDS_RATES_BY_FY.items()):
        year = int(fy[:4])
        for key in sorted(rates.sections):
            n = len(rows) + 1
            rows.append(ded(f"r{n}", f"{year}-05-10", n * 1_00, key))
            if n % 2 == 0:
                challans.append(chl(f"P{n}", fy, "Q1", n * 1_00 - 50, section_rates.parent_of(key, fy)))
            elif n % 3 == 0:
                challans.append(chl(f"K{n}", fy, "Q1", n * 1_00, key))
    assert len(rows) >= 40
    states = deduction_states(rows, challans)
    short = sum(v.tax_paise - v.deposited_paise for v in states.values() if v.state in (PART, NOT_DEPOSITED))
    card = position([{**r, "client_id": CLIENT} for r in rows], [{**c, "client_id": CLIENT} for c in challans])
    assert short == card.undeposited_paise and card.undeposited_paise > 0


# ── The service ────────────────────────────────────────────────────────────

def _world():
    db = FakeDB()
    for r in FIXTURE_ROWS:
        db.seed("tds_deductions", {**r, "firm_id": FIRM, "client_id": CLIENT})
    for c in FIXTURE_CHALLANS:
        db.seed("tds_challans", {**c, "firm_id": FIRM, "client_id": CLIENT})
    # Another client's and another firm's rows, which must not be read
    db.seed("tds_deductions", {**ded("x1", "2025-05-10", 99_999_00), "firm_id": FIRM, "client_id": OTHER_CLIENT})
    db.seed("tds_deductions", {**ded("x2", "2025-05-10", 88_888_00), "firm_id": OTHER_FIRM, "client_id": CLIENT})
    db.seed("tds_challans", {**chl("X", "2025-26", "Q2", 77_777_00), "firm_id": OTHER_FIRM, "client_id": CLIENT})
    return db


def test_the_service_answers_the_position_the_rows_and_the_caveat_for_one_client_only():
    got = service.read(_world(), FIRM, CLIENT)
    assert got["client_id"] == CLIENT
    assert got["position"]["undeposited_paise"] == 11_000_00 and got["position"]["not_recorded_paise"] == 3_700_00
    assert got["position"]["figure_known"] is True
    assert got["position"]["basis"] == service.BASIS_JUDGED
    assert "₹3,700.00" in got["position"]["caveat"] and "Record the challan" in got["position"]["caveat"]
    assert got["totals"]["deducted_paise"] == sum(r["tds_paise"] for r in FIXTURE_ROWS), "the total is this client's, salary row included"
    assert set(got["deductions"]) == {r["id"] for r in FIXTURE_ROWS}, "another client's and another firm's rows are not in the answer"
    rows, legend = got["deductions"], got["legend"]
    assert rows["c1"] == {"state": "deposited", "challans": ["2"], "paid_late": True,
                          "due_note": "Paid late: the latest payment was on 7 Jun 2026, after the date it fell due."}, \
        "the fixture's challans are dated after the deposits fell due: a deposited row is its state, its serials and that it was late"
    assert rows["a1"]["state"] == "part" and rows["a1"]["challans"] == ["1"] and "₹6,000.00 of ₹10,000.00" in rows["a1"]["detail"]
    assert rows["a3"]["state"] == "not_deposited" and rows["a2"]["state"] == "not_deposited"
    assert rows["a2"]["due_note"] == "Was due on 7 Jul 2025." and rows["a2"]["overdue"] is True
    assert rows["b1"] == {"state": "not_recorded"} and rows["s1"] == {"state": "salary"}
    assert legend["not_recorded"]["label"] == "Unknown: no challan recorded" and legend["salary"]["label"] == "Through payroll"
    assert set(legend) == set(ds.STATES) and all(legend[s]["label"] and legend[s]["sentence"] for s in ds.STATES)
    assert got["read"] == "7 deductions and 3 challans of this client."


def test_a_client_with_nothing_recorded_gets_no_caveat_and_no_rows():
    got = service.read(_world(), FIRM, "55555555-5555-4555-8555-555555555555", position=(0, 0))
    assert got["position"] == {"undeposited_paise": 0, "not_recorded_paise": 0, "figure_known": True,
                               "basis": service.BASIS_NOTHING_OWED, "caveat": None}
    assert got["deductions"] == {} and got["totals"] == {"deducted_paise": 0} and got["warnings"] == []
    assert got["read"] == "0 deductions and 0 challans of this client."


def test_when_tax_was_deducted_but_no_quarter_of_it_has_a_challan_the_figure_is_not_known_and_says_why():
    """A headline of nil over a sentence in small type is the unknown shown as a value: the server says nothing was judged."""
    rows = [ded("a", "2026-05-10", 3_000_00), ded("b", "2026-08-10", 1_000_00)]
    got = service.assemble(CLIENT, rows, [], (0, 4_000_00))
    assert got["position"]["figure_known"] is False and got["position"]["basis"] == service.BASIS_NOTHING_JUDGED
    assert got["position"]["not_recorded_paise"] == 4_000_00 and "₹4,000.00" in got["position"]["caveat"]
    # With one quarter recorded the nil is a judgement of that quarter, and the caveat covers the rest
    some = service.assemble(CLIENT, rows, [chl("C1", tds=3_000_00)], (0, 1_000_00))
    assert some["position"]["figure_known"] is True and some["position"]["basis"] == service.BASIS_JUDGED


def test_the_totals_count_tax_surcharge_and_cess_so_both_cards_count_tax_the_same_way():
    rows = [ded("a", section="195", tds=10_000_00, surcharge=1_000_00, cess=440_00), ded("b", section="192", tds=500_00)]
    assert service.assemble(CLIENT, rows, [], (0, 0))["totals"]["deducted_paise"] == 10_000_00 + 1_000_00 + 440_00 + 500_00


def test_a_negative_row_neither_adds_to_nor_takes_from_the_total_deducted():
    """The position counts a negative row as nothing (it neither pays nor owes), so the card that says what was deducted must too,
    or the undeposited figure could exceed the total beside it."""
    rows = [ded("a", tds=10_000_00), ded("b", tds=-5_000_00)]
    assert service.assemble(CLIENT, rows, [], (0, 0))["totals"]["deducted_paise"] == 10_000_00


def test_a_deposited_row_whose_challan_is_dated_before_the_tax_carries_its_sentence_in_the_answer():
    """An ordinary deposited row carries none (it would restate its serials); this one is an exception the screen must show."""
    rows = [ded("a", "2026-05-20", 1_000_00)]
    got = service.assemble(CLIENT, rows, [chl("CH1", tds=1_000_00, paid_on="2026-05-07")], (0, 0))["deductions"]["a"]
    assert got["state"] == "deposited" and got["dated_before"] is True
    assert got["detail"] and "dated before the tax was deducted" in got["detail"]


def test_a_challan_larger_than_the_deductions_never_shows_a_row_as_covered_beyond_its_tax():
    """The surplus stays on the challan (the register reports it as a gap) and is not a deposit of any row: this is what lets the
    state module take the register's figure as it is."""
    rows = [ded("a", "2026-05-10", 1_000_00), ded("b", "2026-05-12", 2_000_00)]
    for row in deduction_states(rows, [chl("BIG", tds=9_000_00)]).values():
        assert 0 <= row.deposited_paise <= row.tax_paise
    got = deduction_states(rows, [chl("BIG", tds=9_000_00)])
    assert got["a"].deposited_paise == 1_000_00 and got["b"].deposited_paise == 2_000_00


def test_the_registers_own_warnings_travel_with_the_answer():
    challans = [chl("DUP", bsr_code="0000000"), chl("DUP", bsr_code="0000000"), chl("DEM", minor_head="400"), chl("OK", minor_head=" 200 ")]
    codes = sorted(w["code"] for w in register_warnings(challans))
    assert codes == ["challan_against_a_demand", "challan_recorded_more_than_once"]
    got = service.assemble(CLIENT, [ded("a")], challans, (0, 0))
    assert set(codes) <= {w["code"] for w in got["warnings"]}
    assert any("DEM" in w["message"] and "minor head 400" in w["message"] for w in got["warnings"])


# ── Not yet due is not overdue ───────────────────────────────────────────────────────

def _judge(rows, challans, today):
    from services.compliance_engine import tds_deposit_due_date
    return ds.judge(rows, challans, due_date_of=lambda d: tds_deposit_due_date(d.year, d.month), today=today)


def test_tax_deducted_this_month_is_not_deposited_and_is_not_late_until_the_seventh_of_the_next():
    """Rule 30(2). On the 25th of June a June deduction is not yet deposited and is not overdue; the screen must not draw it as a
    failure. Q1 counts as recorded because the April challan is."""
    from datetime import date
    rows = [ded("apr", "2026-04-10", 1_000_00), ded("jun", "2026-06-20", 2_000_00)]
    challans = [chl("C1", tds=1_000_00, paid_on="2026-05-07")]
    early = _judge(rows, challans, date(2026, 6, 25)).states["jun"]
    assert early.state == NOT_DEPOSITED and early.overdue is False and early.due_on == date(2026, 7, 7)
    assert ds.due_note(early) == "Not due yet: due by 7 Jul 2026."
    late = _judge(rows, challans, date(2026, 7, 8)).states["jun"]
    assert late.overdue is True and ds.due_note(late) == "Was due on 7 Jul 2026."
    on_the_day = _judge(rows, challans, date(2026, 7, 7)).states["jun"]
    assert on_the_day.overdue is False, "the seventh itself is in time"


def test_tax_deducted_in_march_falls_due_on_the_thirtieth_of_april():
    from datetime import date
    rows = [ded("mar", "2026-03-10", 1_000_00), ded("jan", "2026-01-10", 1_000_00)]
    got = _judge(rows, [chl("C1", "2025-26", "Q4", 1_000_00, paid_on="2026-02-07")], date(2026, 4, 20)).states
    assert got["mar"].due_on == date(2026, 4, 30) and got["mar"].overdue is False


def test_a_part_says_when_the_rest_falls_due_and_a_deposited_row_has_no_due_date():
    from datetime import date
    rows = [ded("a", "2026-06-20", 2_000_00)]
    part = _judge(rows, [chl("C1", tds=500_00)], date(2026, 6, 25)).states["a"]
    assert part.state == PART and "not due yet: due by 7 Jul 2026" in words(part)[1]
    late = _judge(rows, [chl("C1", tds=500_00)], date(2026, 8, 1)).states["a"]
    assert "The deposit was due on 7 Jul 2026" in words(late)[1]
    done = _judge(rows, [chl("C1", tds=2_000_00)], date(2026, 8, 1)).states["a"]
    assert done.due_on is None and done.overdue is False


def test_a_due_date_without_a_today_says_nothing_about_lateness():
    """Without both the rule and the clock, no row says whether it is late: not a date, not a flag, not a note."""
    got = ds.judge([ded("a", "2025-06-20")], [chl("C1", "2025-26", "Q1", section="194J")], due_date_of=lambda d: d).states["a"]
    assert got.state == NOT_DEPOSITED and got.due_on is None and got.overdue is False and ds.due_note(got) is None


def test_without_a_date_to_judge_by_no_row_says_whether_it_is_late():
    got = deduction_states([ded("a")], [chl("C1", section="194J")])["a"]
    assert got.state == NOT_DEPOSITED and got.due_on is None and got.overdue is False and ds.due_note(got) is None


def test_a_deposited_nil_not_recorded_or_salary_row_carries_no_due_note():
    from datetime import date
    rows = [ded("ok", "2026-05-10"), ded("nil", "2026-05-11", tds=0), ded("sal", "2026-05-12", section="192")]
    states = _judge(rows, [chl("C1")], date(2027, 1, 1)).states
    assert all(ds.due_note(v) is None for v in states.values())
    assert ds.due_note(_judge([ded("x", "2026-08-10")], [chl("C1")], date(2027, 1, 1)).states["x"]) is None, "not recorded: no due note"


def test_the_service_answers_a_late_not_deposited_row_with_its_due_note_and_overdue_flag():
    rows = [ded("a", "2025-06-20", 2_000_00)]
    got = service.assemble(CLIENT, rows, [chl("C1", "2025-26", "Q1", tds=500_00)], (1_500_00, 0))["deductions"]["a"]
    assert got["state"] == "part" and got["overdue"] is True and "The deposit was due on 7 Jul 2025" in got["detail"]


# ── The register's warnings are about the register ──────────────────────────────────────

def test_a_salary_challan_is_not_warned_about_because_the_register_ignores_it():
    """The Add Challan form offers section 192. Neither a salary challan recorded twice nor one under minor head 400 is "counted as a
    deposit" by this register, which skips salary, so saying so would be false."""
    challans = [chl("S1", section="192", bsr_code="0000000"), chl("S1", section="192", bsr_code="0000000"),
                chl("S2", section="192", minor_head="400")]
    assert register_warnings(challans) == []
    assert ds.duplicate_challan_warnings(challans) == [] and ds.demand_challan_warnings(challans) == []
    mixed = challans + [chl("D1", section="194C", minor_head="400")]
    assert [w["challan_no"] for w in register_warnings(mixed)] == ["D1"]


def test_a_challan_larger_than_the_deductions_of_its_quarter_is_one_sign_of_the_wrong_quarter():
    """A June deposit made on 7 July and recorded for Q2 (the quarter it was paid in) leaves Q1's June deduction unrecorded and Q2
    holding a challan with nothing to pay: the one warning that points at it."""
    rows = [ded("jul", "2025-07-10", 1_000_00)]
    got = ds.judge(rows, [chl("JUNE", "2025-26", "Q2", 3_000_00, paid_on="2025-07-07")])
    (w,) = got.surplus
    assert w["code"] == "challan_exceeds_deductions" and w["quarter"] == "Q2" and w["financial_year"] == "2025-26"
    assert w["section"] == "194C" and w["surplus_paise"] == 2_000_00 and w["challan_nos"] == ["JUNE"]
    assert "₹2,000.00 more than the tax deducted" in w["message"]
    assert "check the quarter, financial year and section it was recorded for" in w["message"]
    assert got.states["jul"].state == DEPOSITED


def test_a_quarter_with_a_challan_and_no_deduction_at_all_is_all_surplus():
    got = ds.judge([], [chl("LONE", "2025-26", "Q3", 500_00)])
    assert [(w["quarter"], w["surplus_paise"]) for w in got.surplus] == [("Q3", 500_00)]


def test_a_challan_that_exactly_pays_its_quarter_and_a_salary_challan_raise_no_surplus_warning():
    rows = [ded("a", "2025-05-10", 1_000_00)]
    assert ds.judge(rows, [chl("C1", "2025-26", "Q1", 1_000_00)]).surplus == []
    assert ds.judge(rows, [chl("C1", "2025-26", "Q1", 1_000_00), chl("SAL", "2025-26", "Q1", 9_999_00, section="192")]).surplus == []


def test_the_surplus_warning_travels_with_the_answer_in_the_servers_words():
    got = service.assemble(CLIENT, [ded("a", "2025-05-10", 1_000_00)], [chl("C1", "2025-26", "Q1", 1_700_00)], (0, 0))
    assert [w["code"] for w in got["warnings"]] == ["challan_exceeds_deductions"]
    assert got["warnings"][0]["surplus_paise"] == 700_00


# ── Salary tax is not judged, and the card says so ───────────────────────────────────

def test_a_client_whose_only_tax_is_salary_gets_no_figure_and_the_reason():
    got = service.assemble(CLIENT, [ded("s", section="192", tds=5_000_00)], [], (0, 0))
    assert got["position"]["figure_known"] is False and got["position"]["basis"] == service.BASIS_ONLY_SALARY
    assert got["totals"]["deducted_paise"] == 5_000_00, "the total card still counts the salary tax"


def test_a_figure_always_says_salary_tax_is_not_in_it_because_payroll_deducts_it_outside_this_register():
    """Payroll writes no `tds_deductions` row, so a client who runs payroll and has no other deduction would read ₹0.00 and
    'nothing is waiting'. The words never leave salary out silently."""
    judged = [ded("a", "2025-05-10", 1_000_00)]
    plain = service.assemble(CLIENT, judged, [chl("C1", "2025-26", "Q1", 1_000_00)], (0, 0))["position"]
    assert plain["basis"] == service.BASIS_JUDGED and "salary tax is not in this figure" in plain["basis"]
    nothing = service.assemble(CLIENT, [], [], (0, 0))["position"]
    assert nothing["basis"] == service.BASIS_NOTHING_OWED and "salary tax is not in this figure" in nothing["basis"]
    nil_salary = service.assemble(CLIENT, [ded("s", section="192", tds=0)], [], (0, 0))["position"]
    assert nil_salary["basis"] == service.BASIS_NOTHING_OWED and nil_salary["figure_known"] is True, "a nil salary row is no tax"


# ── The answer is sized by its rows ─────────────────────────────────────────────────

def test_a_year_of_unrecorded_deductions_is_a_state_a_row_and_the_words_once():
    import json
    import uuid
    rows = [ded(str(uuid.uuid4()), "2026-05-10", 100) for _ in range(5_000)]
    answer = service.assemble(CLIENT, rows, [], (0, 500_000))
    assert all(r == {"state": "not_recorded"} for r in answer["deductions"].values())
    assert len(json.dumps(answer)) < 400_000, len(json.dumps(answer))   # about 0.34 MB with real ids; 1.6 MB with a sentence a row
    assert answer["legend"]["not_recorded"]["sentence"], "the sentence is said once, in the legend"


# ── A deposit made after the date is deposited, and it is not on time ──────────────────

def test_a_row_covered_by_a_challan_paid_after_the_date_is_deposited_and_says_it_was_late():
    """The deposit worksheet charges §201(1A) interest on it; a plain green 'Deposited' hid that."""
    from datetime import date
    rows = [ded("a", "2026-05-10", 1_000_00)]
    late = _judge(rows, [chl("C1", tds=1_000_00, paid_on="2026-08-20")], date(2026, 9, 1)).states["a"]
    assert late.state == DEPOSITED and late.late_on == date(2026, 8, 20) and late.due_on is None
    assert ds.due_note(late) == "Paid late: the latest payment was on 20 Aug 2026, after the date it fell due."
    on_time = _judge(rows, [chl("C1", tds=1_000_00, paid_on="2026-06-07")], date(2026, 9, 1)).states["a"]
    assert on_time.late_on is None and ds.due_note(on_time) is None, "the seventh itself is in time"
    assert _judge(rows, [chl("C1", tds=1_000_00, paid_on="2026-06-08")], date(2026, 9, 1)).states["a"].late_on == date(2026, 6, 8)


def test_a_part_paid_late_says_so_and_a_challan_dated_before_the_tax_is_not_a_late_one():
    from datetime import date
    rows = [ded("a", "2026-05-10", 2_000_00)]
    part = _judge(rows, [chl("C1", tds=500_00, paid_on="2026-07-01")], date(2026, 9, 1)).states["a"]
    assert part.state == PART and part.late_on == date(2026, 7, 1) and ds.due_note(part).startswith("Paid late")
    before = _judge([ded("a", "2026-05-20", 1_000_00)], [chl("C1", tds=1_000_00, paid_on="2026-05-07")], date(2026, 9, 1)).states["a"]
    assert before.dated_before is True and before.late_on is None, "a payment before the deduction is not after the due date"


def test_the_registers_order_can_give_one_months_row_the_next_months_late_challan_and_the_row_says_what_it_was_given():
    """April paid on time, May's challan never recorded, June's paid on 5 July: first in first out gives May's row June's challan.
    The row says the payment was late, which is what the deposit worksheet reports for May, and the order is the register's."""
    from datetime import date
    rows = [ded("apr", "2026-04-10", 1_000_00), ded("may", "2026-05-10", 1_000_00), ded("jun", "2026-06-10", 1_000_00)]
    challans = [chl("C-APR", tds=1_000_00, paid_on="2026-05-07"), chl("C-JUN", tds=1_000_00, paid_on="2026-07-05")]
    got = _judge(rows, challans, date(2026, 7, 20)).states
    assert got["apr"].late_on is None
    assert got["may"].state == DEPOSITED and got["may"].late_on == date(2026, 7, 5) and got["may"].challans == ("C-JUN",)
    assert got["jun"].state == NOT_DEPOSITED and got["jun"].overdue is True


def test_the_service_judges_lateness_by_the_cas_day_in_india_and_by_rule_30_2(monkeypatch):
    """`assemble` takes its clock from `ist_today` (a date a person reads is the Indian one) and its date from the compliance
    engine: June's tax is in time on 7 July and late on the 8th, and March's is due on 30 April, not 7 April."""
    from datetime import date
    june = [ded("a", "2025-06-20", 2_000_00)]
    recorded = [chl("C1", "2025-26", "Q1", tds=500_00, section="194J")]
    for today, overdue in ((date(2025, 7, 7), None), (date(2025, 7, 8), True)):
        monkeypatch.setattr(service, "ist_today", lambda today=today: today)
        row = service.assemble(CLIENT, june, recorded, (0, 0))["deductions"]["a"]
        assert row.get("overdue") is overdue, (today, row)
    march = [ded("m", "2026-03-10", 1_000_00)]
    q4 = [chl("C2", "2025-26", "Q4", tds=100_00, section="194J")]
    monkeypatch.setattr(service, "ist_today", lambda: date(2026, 4, 20))
    row = service.assemble(CLIENT, march, q4, (0, 0))["deductions"]["m"]
    assert row["due_note"] == "Not due yet: due by 30 Apr 2026." and "overdue" not in row
    monkeypatch.setattr(service, "ist_today", lambda: date(2026, 5, 1))
    assert service.assemble(CLIENT, march, q4, (0, 0))["deductions"]["m"]["overdue"] is True


def test_a_row_paid_in_two_late_parts_names_the_latest_payment():
    from datetime import date
    rows = [ded("a", "2026-05-10", 1_000_00)]
    got = _judge(rows, [chl("C1", tds=400_00, paid_on="2026-07-01"), chl("C2", tds=600_00, paid_on="2026-08-20")], date(2026, 9, 1))
    assert got.states["a"].late_on == date(2026, 8, 20) and "20 Aug 2026" in ds.due_note(got.states["a"])


def test_without_a_clock_no_row_is_called_late():
    got = deduction_states([ded("a", "2026-05-10", 1_000_00)], [chl("C1", tds=1_000_00, paid_on="2026-12-20")])["a"]
    assert got.late_on is None and ds.due_note(got) is None


def test_the_service_answers_a_late_deposited_row_with_a_paid_late_flag_and_its_note():
    answer = service.assemble(CLIENT, [ded("a", "2025-05-10", 1_000_00)], [chl("C1", "2025-26", "Q1", 1_000_00, paid_on="2025-08-20")], (0, 0))
    row = answer["deductions"]["a"]
    assert row == {"state": "deposited", "due_note": "Paid late: the latest payment was on 20 Aug 2025, after the date it fell due.",
                   "paid_late": True, "challans": ["C1"]}


# ── The card and the column group a section the same way ─────────────────────────────

@pytest.mark.parametrize("deducted_as,paid_as", [
    ("194Z(A)", "194Z"), ("194Z", "194Z(A)"), ("194Z(A)", "194Z(B)"), (" 194c ", "194C"), ("194c", "194C(1)"), ("206C(1H)", "206C"),
    ("194LBA(1)", "194LBA"),
])
def test_a_section_typed_with_a_bracketed_limb_is_grouped_as_the_card_groups_it(deducted_as, paid_as):
    """A deduction typed '194Z(A)' and a challan typed '194Z' are one group in the SQL behind the card; the column used the registry's
    parent and read them as two for a section the registry does not hold, so the card said deposited and the row said not."""
    rows = [{**ded("a", "2025-05-10", 1_000_00), "section": deducted_as}]
    challans = [{**chl("C1", "2025-26", "Q1", 1_000_00), "section": paid_as}]
    column = deduction_states(rows, challans)["a"]
    card = position([{**r, "client_id": CLIENT} for r in rows], [{**c, "client_id": CLIENT} for c in challans])
    assert (column.state == DEPOSITED) == (card.undeposited_paise == 0), (deducted_as, paid_as, column.state, card)


def test_a_surplus_with_no_section_says_so_and_does_not_leave_a_blank():
    got = ds.judge([], [{**chl("LONE", "2025-26", "Q3", 500_00), "section": ""}])
    (w,) = got.surplus
    assert " with no section " in w["message"] and "under  " not in w["message"]


# ── Answers to recording a challan say whether somebody has something to do ────────────

@pytest.mark.parametrize("answers,expected", [
    ([{"state": "closed", "closed": True, "month": "2025-07"}], [False]),
    ([{"state": "already_filed", "closed": False, "month": "2025-07"}], [False]),
    ([{"state": "not_closed", "closed": False, "month": "2025-08"}], [True]),
    ([{"state": "not_allowed", "closed": False}], [True]),
    ([{"state": "not_on_the_calendar", "closed": False}], [False]),
    ([{"state": "not_on_the_calendar", "closed": False, "month": "2025-09"}], [True]),
])
def test_a_calendar_answer_says_whether_somebody_has_something_to_do(monkeypatch, answers, expected):
    """The screen draws attention from this and does not read the state words: a Partner without Compliance access, whose every
    month stays open, must not get a calm note."""
    from services import tds_deposit_closes_obligation as closes
    monkeypatch.setattr(closes, "_close", lambda **kw: answers)
    out = closes.close_for_recorded_challan(db=None, firm_id=FIRM, client_id=CLIENT, financial_year="2025-26", quarter="Q2",
                                            challan_id="c", section="194C", actor=None, may_write_compliance=True)
    assert [a["needs_action"] for a in out] == expected


# ── The live branch of the route reads this firm's rows of this client ────────────────

def test_the_live_branch_hands_the_reader_the_firm_then_the_client(monkeypatch):
    """Every other route test runs in mock mode, which reads neither. Swapping the two ids reads nothing and answers a clean
    zero: the false 'nothing is waiting' this change exists to prevent."""
    import routers.tds_workspace as tw
    monkeypatch.setattr(tw, "_USE_MOCK", False)
    monkeypatch.setattr("core.supabase_client.get_supabase", _world)
    monkeypatch.setattr(tw, "assert_client_access", lambda user, client_id: None)
    mine = tw.deposit_state(client_id=CLIENT, current_user={"id": "u", "firm_id": FIRM, "role": "Partner"})
    assert mine["success"] is True
    assert mine["data"]["position"]["undeposited_paise"] == 11_000_00 and mine["data"]["totals"]["deducted_paise"] > 0
    assert set(mine["data"]["deductions"]) == {r["id"] for r in FIXTURE_ROWS}
    theirs = tw.deposit_state(client_id=CLIENT, current_user={"id": "u", "firm_id": OTHER_FIRM, "role": "Partner"})
    assert set(theirs["data"]["deductions"]) == {"x2"} and theirs["data"]["totals"]["deducted_paise"] == 88_888_00


# ── The module's helpers are the product's, not copies that could drift ─────────────

def test_the_quarter_the_year_and_the_salary_spellings_agree_with_their_authorities_for_every_day():
    """`undeposited` carries its own FY label, quarter and salary test (it is the SQL's twin). `judge` decides which quarter a row is
    in by them, so they are held to `core.ist_clock`, `compliance_engine` and `deposit_due` over every day of twelve years."""
    from datetime import date, timedelta
    from core.ist_clock import ist_fy_label
    from domain.tds import deposit_due, undeposited
    from services.compliance_engine import tds_quarter_of_month
    day = date(2020, 1, 1)
    while day <= date(2031, 12, 31):
        assert undeposited.fy_label_of(day) == ist_fy_label(day), day
        assert undeposited.quarter_of(day) == tds_quarter_of_month(day.month), day
        day += timedelta(days=1)
    for spelling in ("192", "Sec 192", " s192 ", "SEC192", "192A", "194C", "", None, "1 9 2"):
        assert undeposited.is_salary(spelling) == deposit_due.is_salary(str(spelling or "")), spelling


def test_an_unreadable_position_is_none_and_never_a_zero_and_the_rows_are_still_answered(monkeypatch):
    """A deployment where migration 523 has not applied, or a failed call, loses the card and keeps the column."""
    from services import tds_position_service

    def boom(*a, **k):
        raise RuntimeError("tds_deposit_position answered nothing")
    monkeypatch.setattr(tds_position_service, "read", boom)
    got = service.read(_world(), FIRM, CLIENT)
    assert got["position"] is None
    assert got["deductions"]["c1"]["state"] == DEPOSITED and got["totals"]["deducted_paise"] > 0


def test_the_reads_carry_firm_and_client_scope_name_real_columns_and_add_no_ordering_of_their_own():
    src = inspect.getsource(service.read)
    tree = ast.parse(src)
    assert "order(" not in src, "fetch_all pages by keyset and adds its own ordering; a second one makes the cursor skip and repeat rows"
    assert src.count('.eq("firm_id", firm_id).eq("client_id", client_id)') == 2
    selects = [n.args[0].value for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "select"
               and n.args and isinstance(n.args[0], ast.Constant)]
    assert len(selects) == 2, selects
    assert "minor_head" in selects[1] and "bsr_code" in selects[1], "the register's warnings need the branch code and the minor head"
    assert all(c in selects[0] for c in ("id", "section", "transaction_date", "tds_paise", "surcharge_paise", "cess_paise"))
    assert all(c in selects[1] for c in ("challan_no", "financial_year", "quarter", "tds_paise", "payment_date"))
    assert "challan_date" not in " ".join(selects), "a hand-typed deduction challan field is a note and is not read"


def test_the_service_reads_neither_the_status_nor_the_challan_number_of_a_deduction():
    deductions_select = inspect.getsource(service.read).split('.table("tds_deductions")')[1].split("label=")[0]
    assert "status" not in deductions_select and "challan_no" not in deductions_select and "challan_date" not in deductions_select


# ── The route ───────────────────────────────────────────────────────────────

HEADERS = {"X-User-Email": "partner@test.com", "X-User-Role": "partner", "X-Firm-ID": FIRM}


@pytest.mark.usefixtures("dev_header_auth")
def test_the_route_answers_in_mock_mode_from_the_in_memory_register(monkeypatch):
    import routers.tds_workspace as tw
    from main import app
    monkeypatch.setattr(tw, "_MOCK_DEDUCTIONS", {
        **{r["id"]: {**r, "client_id": CLIENT, "firm_id": FIRM} for r in FIXTURE_ROWS},
        "other": {**ded("other", "2025-05-10", 99_999_00), "client_id": OTHER_CLIENT, "firm_id": FIRM}})
    monkeypatch.setattr(tw, "_MOCK_CHALLANS", {c["id"]: {**c, "client_id": CLIENT, "firm_id": FIRM} for c in FIXTURE_CHALLANS})
    resp = TestClient(app).get(f"/api/tds-workspace/deposit-state?client_id={CLIENT}", headers=HEADERS)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    data = body["data"]
    assert data["position"]["undeposited_paise"] == 11_000_00 and data["position"]["not_recorded_paise"] == 3_700_00
    assert data["deductions"]["c1"]["state"] == DEPOSITED and data["deductions"]["a1"]["state"] == PART
    assert "other" not in data["deductions"], "another client's deduction is in the answer"


@pytest.mark.usefixtures("dev_header_auth")
def test_the_route_needs_a_client_and_is_read_gated():
    from main import app
    assert TestClient(app).get("/api/tds-workspace/deposit-state", headers=HEADERS).status_code == 422
    import routers.tds_workspace as tw
    src = inspect.getsource(tw.deposit_state)
    assert 'rbac("tds", "read")' in src and "assert_client_access(current_user, client_id)" in src


def test_the_route_is_one_function_and_does_no_arithmetic_of_its_own():
    import routers.tds_workspace as tw
    tree = ast.parse(inspect.getsource(tw.deposit_state))
    ops = [n for n in ast.walk(tree) if isinstance(n, ast.BinOp)]
    assert not ops, "the route does arithmetic; the figures are the database's and the module's"
