"""TDS deducted and not yet deposited is the challan register's answer, not a column nothing writes (the hub's TDS tile).

The tile summed `tds_deductions.tds_paise WHERE challan_no IS NULL`. `POST /challans` records the challan and never touches the
deductions it paid, so nothing ever wrote `challan_no` and every deduction counted as undeposited: the seeded demo firm, with every
deduction paid in by a recorded challan, read Rs 1,94,614.98 on its dashboard and Rs 63,647.88 on a client's overview.

`domain/tds/undeposited.py` is the Python twin of migration 522's `public.tds_undeposited_paise` (mock mode, local dev and the in-memory
suites have no SQL functions); `test_the_undeposited_tds_asks_the_challan_register_pg.py` holds the two identical over a real Postgres.
This module holds the RULE: what the twin answers for each arrangement of deductions and challans, and that the hub's tile asks it.
"""
from __future__ import annotations

import pytest

from domain.tds.undeposited import fy_label_of, quarter_of, undeposited_paise
from datetime import date

A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def ded(client=A, section="194C", on="2026-05-10", tds=10_000_00, surcharge=0, cess=0, id_=None):
    return {"id": id_ or f"d-{client[:1]}-{section}-{on}-{tds}", "client_id": client, "section": section, "transaction_date": on,
            "tds_paise": tds, "surcharge_paise": surcharge, "cess_paise": cess}


def chl(client=A, section="194C", fy="2026-27", quarter="Q1", tds=10_000_00, surcharge=0, paid_on="2026-06-07", no="C1"):
    return {"id": f"c-{no}", "client_id": client, "section": section, "financial_year": fy, "quarter": quarter, "tds_paise": tds,
            "surcharge_paise": surcharge, "payment_date": paid_on, "challan_no": no}


# ── The quarter and the year a deduction belongs to ────────────────────────────

@pytest.mark.parametrize("on,fy,q", [
    ("2026-04-01", "2026-27", "Q1"), ("2026-06-30", "2026-27", "Q1"),
    ("2026-07-01", "2026-27", "Q2"), ("2026-09-30", "2026-27", "Q2"),
    ("2026-10-01", "2026-27", "Q3"), ("2026-12-31", "2026-27", "Q3"),
    ("2027-01-01", "2026-27", "Q4"), ("2027-03-31", "2026-27", "Q4"),
    ("2027-04-01", "2027-28", "Q1"),
    ("2099-03-31", "2098-99", "Q4"), ("2099-04-01", "2099-00", "Q1"),
])
def test_a_date_belongs_to_the_financial_year_and_quarter_rule_31a_gives_it(on, fy, q):
    d = date.fromisoformat(on)
    assert (fy_label_of(d), quarter_of(d)) == (fy, q)


# ── The answer ────────────────────────────────────────────────────────────────

def test_nothing_deducted_is_nothing_undeposited():
    assert undeposited_paise([], []) == 0
    assert undeposited_paise([], [chl()]) == 0


def test_a_deduction_with_no_challan_is_wholly_undeposited():
    assert undeposited_paise([ded()], []) == 10_000_00


def test_a_challan_that_pays_the_deduction_in_full_leaves_nothing():
    assert undeposited_paise([ded()], [chl()]) == 0


def test_a_short_challan_leaves_the_difference():
    assert undeposited_paise([ded()], [chl(tds=6_000_00)]) == 4_000_00


def test_a_surplus_challan_is_not_a_negative_figure():
    assert undeposited_paise([ded()], [chl(tds=25_000_00)]) == 0


def test_the_surplus_of_one_group_does_not_pay_another():
    """Rs 15,000 deposited against a Rs 10,000 §194C deduction does not settle the Rs 7,500 §194J one beside it, nor a deduction
    of the next quarter: a challan pays the deductions of its own section, financial year and quarter."""
    rows = [ded(section="194C", tds=10_000_00), ded(section="194J", on="2026-05-12", tds=7_500_00),
            ded(section="194C", on="2026-08-02", tds=3_000_00)]
    assert undeposited_paise(rows, [chl(tds=15_000_00)]) == 7_500_00 + 3_000_00


def test_a_challan_of_another_quarter_or_year_settles_nothing_here():
    assert undeposited_paise([ded()], [chl(quarter="Q2")]) == 10_000_00
    assert undeposited_paise([ded()], [chl(fy="2025-26")]) == 10_000_00


def test_the_year_decides_not_the_quarter_label_alone():
    """April 2027 is Q1 of 2027-28, and a Q1 challan of 2026-27 does not pay it."""
    assert undeposited_paise([ded(on="2027-04-20")], [chl()]) == 10_000_00
    assert undeposited_paise([ded(on="2027-04-20")], [chl(fy="2027-28")]) == 0


def test_a_challan_typed_with_the_parent_section_pays_a_clause_deduction():
    """A challan records what somebody typed, and a CA types 194J whichever limb the bill was under."""
    assert undeposited_paise([ded(section="194J(B)", tds=2_000_00)], [chl(section="194J", tds=2_000_00)]) == 0
    assert undeposited_paise([ded(section="194J(a)", tds=2_000_00)], [chl(section="194J(b)", tds=2_000_00)]) == 0


def test_the_deductions_surcharge_and_cess_are_tax_to_deposit_and_the_challans_tax_includes_its_surcharge():
    """A section 195 payment: the deduction owes tax, surcharge and cess; the challan's capacity is its tax plus surcharge
    (a cess paid on the challan sits inside its tax head: the form has no cess field)."""
    d = ded(section="195", tds=10_000_00, surcharge=1_000_00, cess=440_00)
    assert undeposited_paise([d], [chl(section="195", tds=10_000_00, surcharge=1_000_00)]) == 440_00
    assert undeposited_paise([d], [chl(section="195", tds=10_440_00, surcharge=1_000_00)]) == 0


def test_salary_is_deposited_from_payroll_and_is_in_neither_side_of_this_register():
    for label in ("192", "Sec192", "S192", " 192", "192 "):
        assert undeposited_paise([ded(section=label)], []) == 0, label
    assert undeposited_paise([ded(section="192"), ded(section="194C", tds=1_00)], [chl(section="192", tds=9_99)]) == 1_00


def test_a_salary_challan_pays_no_deduction_even_one_typed_with_a_clause():
    """The salary spellings are left out of both sides by name, so a `192` challan is not a deposit for a row typed `192(1)`."""
    assert undeposited_paise([ded(section="192(1)", tds=7_00)], [chl(section="192", tds=7_00)]) == 7_00


def test_a_deduction_with_no_usable_date_is_left_out_as_the_worksheet_leaves_it():
    """There is no quarter to place it in, and inventing one would put it in a group a challan could pay."""
    assert undeposited_paise([ded(on=None), ded(on="")], []) == 0


def test_a_timestamp_is_dated_by_its_day():
    assert undeposited_paise([ded(on="2026-05-10T23:30:00+05:30")], [chl()]) == 0


def test_a_negative_row_neither_pays_nor_owes():
    """challan_mapping.assign counts each deduction and each challan at least nil, and the SQL function does the same."""
    assert undeposited_paise([ded(tds=-5_00), ded(on="2026-05-11", tds=4_00)], [chl(tds=-3_00)]) == 4_00


def test_a_blank_section_is_its_own_group_and_a_challan_must_name_none_to_pay_it():
    assert undeposited_paise([ded(section=""), ded(section=None, on="2026-05-11", tds=1_00)], []) == 10_000_00 + 1_00
    assert undeposited_paise([ded(section="")], [chl(section="")]) == 10_000_00     # the two spell "no section" differently


def test_each_client_is_its_own_group():
    """A challan of one client pays nothing of another's, whatever the section and quarter."""
    assert undeposited_paise([ded(client=A), ded(client=B)], [chl(client=A)]) == 10_000_00


# ── The port is the register's own match, for every section the registry holds ────────────────────────────────────────

def _the_registers_answer(deductions, challans):
    """What the deposit worksheet's own match (`deposit_due.mapping_from_register`) says, quarter by quarter."""
    from domain.tds import challan_mapping, deposit_due
    placed: dict = {}
    for d in deductions:
        on = date.fromisoformat(str(d["transaction_date"])[:10])
        placed.setdefault((d["client_id"], fy_label_of(on), quarter_of(on)), []).append(d)
    total = 0
    for (client, fy, quarter), rows in placed.items():
        theirs = [c for c in challans if c["client_id"] == client and c["financial_year"] == fy and c["quarter"] == quarter]
        mapping = deposit_due.mapping_from_register(rows, theirs, fy=fy)
        total += sum(g["shortfall_paise"] for g in mapping.gaps if g["code"] == challan_mapping.GAP_DEDUCTIONS_NOT_DEPOSITED)
    return total


def test_every_section_the_registry_holds_is_grouped_as_the_register_groups_it():
    """A deduction under each key of both years, half of them paid by a challan typed with the key's PARENT and a third by one
    typed with the key itself: the port and the worksheet's match say the same."""
    from domain.tds import section_rates
    deductions, challans = [], []
    for fy, rates in sorted(section_rates.TDS_RATES_BY_FY.items()):
        year = int(fy[:4])
        for key in sorted(rates.sections):
            n = len(deductions) + 1
            deductions.append(ded(section=key, on=f"{year}-05-10", tds=n * 1_00, id_=f"reg-{n}"))
            if n % 2 == 0:
                challans.append(chl(section=section_rates.parent_of(key, fy), fy=fy, tds=n * 1_00 - 50, no=f"P{n}"))
            elif n % 3 == 0:
                challans.append(chl(section=key, fy=fy, tds=n * 1_00, no=f"K{n}"))
    assert len(deductions) >= 40, "the registry shrank or this loop went blind"
    got = undeposited_paise(deductions, challans)
    assert got == _the_registers_answer(deductions, challans)
    assert got > 0


def test_a_clause_deduction_is_paid_by_the_parent_challan_exactly_as_the_register_pays_it():
    rows = [ded(section="194J(B)", tds=2_000_00, id_="a"), ded(section="194I(a)", on="2026-05-11", tds=500_00, id_="b")]
    pays = [chl(section="194J", tds=2_000_00, no="1"), chl(section="194I(b)", tds=300_00, no="2")]
    assert undeposited_paise(rows, pays) == _the_registers_answer(rows, pays) == 200_00


# ── Where the port and the statement differ, on purpose ───────────────────────────────────────────────────────────────

def test_a_section_the_registry_does_not_hold_is_grouped_by_its_bracket_stripped_text_and_the_statement_does_not():
    """The SQL cannot ask the registry, so a deduction under an unknown "194Z(A)" is paid by a challan typed "194Z" here. The
    statement groups an unknown section by its own text and calls that deduction unpaid. The difference is recorded in the design
    record and in migration 522's header; this pins it so it cannot change by accident."""
    rows = [ded(section="194Z(A)", tds=10_00, id_="z")]
    pays = [chl(section="194Z", tds=10_00, no="z1")]
    assert undeposited_paise(rows, pays) == 0
    assert _the_registers_answer(rows, pays) == 10_00


@pytest.mark.parametrize("typed,grouped", [
    ("194J(B)", "194J"), (" 194j(a) ", "194J"), ("194J(a)(b)", "194J"), ("194J()", "194J"), ("194J (B)", "194J "),
    ("(b)", "(B)"), ("194C", "194C"), ("194C(", "194C("), ("\t194C\n", "194C"),
])
def test_a_section_is_grouped_as_typed_trimmed_upper_cased_with_a_trailing_bracketed_limb_dropped(typed, grouped):
    from domain.tds.undeposited import section_group
    assert section_group(typed) == grouped


def test_the_whitespace_that_is_trimmed_is_ascii_whitespace_only():
    """A non-breaking space is part of the text, in the SQL and here alike (Python's own `strip()` would trim it)."""
    from domain.tds.undeposited import section_group
    assert section_group("\u00a0194C") == "\u00a0194C"
    assert undeposited_paise([ded(section="\u00a0194C")], [chl(section="194C")]) == 10_000_00


def test_a_blank_section_reads_as_no_section_on_a_deduction_and_as_nothing_on_a_challan():
    from domain.tds.undeposited import NO_SECTION, section_group
    assert section_group("  ", blank=NO_SECTION) == NO_SECTION and section_group("  ") == ""


def test_a_challan_number_typed_on_a_hand_keyed_deduction_is_a_note_and_not_a_deposit():
    """The manual deduction form can carry `challan_no`. The statement and the deposit worksheet ignore it, and so does this: the
    challan register is the one record of a deposit. A hand-keyed deduction with a number and no recorded challan is undeposited
    here exactly as it is on the statement."""
    row = {**ded(), "challan_no": "0510001-12345", "challan_date": "2026-06-07", "status": "deposited"}
    assert undeposited_paise([row], []) == 10_000_00


# ── Whose clients ──────────────────────────────────────────────────────────────

def test_none_is_every_client_a_list_is_those_clients_and_an_empty_list_is_nobody():
    rows = [ded(client=A, tds=1_00), ded(client=B, tds=20_00)]
    assert undeposited_paise(rows, []) == 21_00
    assert undeposited_paise(rows, [], client_ids=None) == 21_00
    assert undeposited_paise(rows, [], client_ids=[A]) == 1_00
    assert undeposited_paise(rows, [], client_ids=[B]) == 20_00
    assert undeposited_paise(rows, [], client_ids=[A, B]) == 21_00
    assert undeposited_paise(rows, [], client_ids=[]) == 0
    assert undeposited_paise(rows, [], client_ids=()) == 0


def test_a_scoped_answer_does_not_read_another_clients_challan():
    rows = [ded(client=A)]
    assert undeposited_paise(rows, [chl(client=B)], client_ids=[A]) == 10_000_00


# ── Order does not matter ──────────────────────────────────────────────────────

def test_the_answer_is_the_same_whatever_order_the_rows_arrive_in_or_the_challans_are_cut_in():
    """first in first out decides WHICH deduction a short challan leaves part-paid, never HOW MUCH is left."""
    rows = [ded(on="2026-04-07", tds=5_000_00), ded(on="2026-05-07", tds=5_000_00), ded(on="2026-06-07", tds=5_000_00)]
    challans = [chl(tds=4_000_00, no="C1", paid_on="2026-05-07"), chl(tds=4_000_00, no="C2", paid_on="2026-06-07")]
    expected = 15_000_00 - 8_000_00
    assert undeposited_paise(rows, challans) == expected
    assert undeposited_paise(list(reversed(rows)), list(reversed(challans))) == expected


def test_a_challan_cut_before_the_deduction_still_counts_here_exactly_as_the_statements_own_match_counts_it():
    """The match is by order and by group, not by date: a challan dated before a deduction is flagged by the statement's note, and is
    not what the tile is asked (it asks whether the register covers the tax, as the quarter's challan gap does)."""
    assert undeposited_paise([ded(on="2026-05-10")], [chl(paid_on="2026-04-01")]) == 0


# ── The tile ──────────────────────────────────────────────────────────────────

class _Rpc:
    def __init__(self, data):
        self.data = data

    def execute(self):
        return self


class _Db:
    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def rpc(self, name, params):
        self.calls.append((name, params))
        return _Rpc(self.answer)


@pytest.mark.parametrize("answer,expected", [
    (0, 0), (4_000_00, 4_000_00), ("400000", 4_000_00), ([4_000_00], 4_000_00), ([0], 0),
    ("9007199254740993", 9_007_199_254_740_993),        # 2**53 + 1: a bigint comes back as a string and is never read as a float
])
def test_the_tile_reads_what_the_function_answers(monkeypatch, answer, expected):
    from services import hub_service
    db = _Db(answer)
    monkeypatch.setattr(hub_service, "_db", lambda: db)
    assert hub_service._tds_undeposited(A, [B]) == expected
    assert db.calls == [("tds_undeposited_paise", {"p_firm_id": A, "p_client_ids": [B]})]


@pytest.mark.parametrize("answer", [None, []])
def test_an_answer_that_is_absent_is_a_tile_with_no_figure_and_never_a_zero(monkeypatch, answer):
    """A read that did not happen is unknown. `_safely` is what turns the refusal into a signal of None."""
    from services import hub_service
    monkeypatch.setattr(hub_service, "_db", lambda: _Db(answer))
    with pytest.raises(RuntimeError):
        hub_service._tds_undeposited(A, None)
    assert hub_service._safely("tds", lambda: hub_service._tds_undeposited(A, None)) is None
