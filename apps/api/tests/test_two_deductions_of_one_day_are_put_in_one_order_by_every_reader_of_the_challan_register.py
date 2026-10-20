"""Which of two same-day deductions a short challan leaves unpaid is decided one way, by the statement and by the register (POST-A-277).

WHAT WAS WRONG
    `domain/tds/challan_mapping.assign` fills the deductions of a section first in, first out and orders them by the day and then
    by a tie-break. The tie-break was the document number, and its two callers did not agree on what that was: the quarterly
    statement (`services/tds_return_service`) put `bill_no or id` there, the register's reader (`deposit_due.mapping_from_register`,
    behind the deposit worksheet, Form 3CD clause 34 and the TDS screen) put the register row's own id, a different string for the
    same deduction. With two deductions on one day and a challan that covered one of them, the row the TDS screen called Not
    deposited could be a different deductee from the one the 26Q left without a challan.

WHAT IS HELD
    * the tie-break is the id of the document the deduction came from, on both sides: the statement's events are the bills and
      payments themselves and a register row names its bill (`purchase_bill_id`) or its payment (`purchase_payment_id`), so the
      same string orders the same deduction wherever it is read; the document number takes no part in the order;
    * the statement and the register, driven over ONE set of bills, leave the same deductions without a challan;
    * a hand-entered register row, which has no document, is ordered by its own id as before.
"""
from __future__ import annotations

import pytest

from domain.tds import challan_mapping, deposit_due
from tests.test_a_deductee_row_names_the_challan_that_paid_it import FY, _26q, _bill, _challan, _setup

DAY = "2025-06-10"


# ── the rule ─────────────────────────────────────────────────────────────────

def _event(row_id, on_date, tds, **extra):
    return {"id": row_id, "section": "194J", "on_date": on_date, "tds_paise": tds, **extra}


def _challan_row(tds):
    return {"id": "c1", "challan_no": "C1", "section": "194J", "payment_date": "2025-07-07", "tds_paise": tds}


def test_two_deductions_of_one_day_are_ordered_by_their_source_id_and_the_document_number_takes_no_part():
    events = [_event("b-9", DAY, 100, doc_no="A-1"), _event("b-1", DAY, 100, doc_no="Z-9")]
    got = challan_mapping.assign(events, [_challan_row(100)], fy=FY)
    assert got.for_deduction("b-1").deposited_paise == 100, "the lower source id is first in the queue"
    assert got.for_deduction("b-9").deposited_paise == 0


def test_the_day_still_comes_before_the_tie_break():
    events = [_event("b-1", "2025-06-12", 100), _event("b-9", "2025-06-11", 100)]
    got = challan_mapping.assign(events, [_challan_row(100)], fy=FY)
    assert got.for_deduction("b-9").deposited_paise == 100 and got.for_deduction("b-1").deposited_paise == 0


def test_a_row_that_names_a_source_is_ordered_by_it_and_not_by_its_own_id():
    events = [_event("row-1", DAY, 100, source_id="bill-9"), _event("row-9", DAY, 100, source_id="bill-1")]
    got = challan_mapping.assign(events, [_challan_row(100)], fy=FY)
    assert got.for_deduction("row-9").deposited_paise == 100, "its bill sorts first, though its own id sorts last"
    assert challan_mapping.source_id_of({"id": "r", "source_id": "s"}) == "s"
    assert challan_mapping.source_id_of({"id": "r"}) == "r" and challan_mapping.source_id_of({}) == ""


def _register_row(row_id, **extra):
    return {"id": row_id, "section": "194J", "transaction_date": DAY, "tds_paise": 100, "surcharge_paise": 0, "cess_paise": 0,
            **extra}


@pytest.mark.parametrize("link", ["purchase_bill_id", "purchase_payment_id"])
def test_the_register_names_a_row_by_its_bill_or_its_payment(link):
    rows = [_register_row("row-1", **{link: "doc-9"}), _register_row("row-9", **{link: "doc-1"})]
    got = deposit_due.mapping_from_register(rows, [_challan_row(100)], fy=FY)
    assert got.for_deduction("row-9").deposited_paise == 100 and got.for_deduction("row-1").deposited_paise == 0


def test_a_hand_entered_register_row_is_ordered_by_its_own_id():
    rows = [_register_row("row-9"), _register_row("row-1")]
    got = deposit_due.mapping_from_register(rows, [_challan_row(100)], fy=FY)
    assert got.for_deduction("row-1").deposited_paise == 100


# ── the statement and the register over one set of bills ────────────────────

@pytest.fixture
def descending_ids(monkeypatch):
    """Every id the fake database makes sorts BEFORE the one made earlier, so the bill created first (B-1) has the highest id and
    the order of the ids is the opposite of the order of the bill numbers. A reader that still ordered by the document number
    would put B-1 first and a reader that ordered by id would put B-6 first, deterministically."""
    import itertools
    import uuid
    counter = itertools.count(10 ** 9, -1)
    monkeypatch.setattr(uuid, "uuid4", lambda: uuid.UUID(int=next(counter)))


def _bills_one_day_and_a_challan_for_half(monkeypatch, count=6):
    db = _setup(monkeypatch)
    bills = [_bill(db, f"B-{n}", 2_00_000_00, DAY) for n in range(1, count + 1)]
    assert len({b["tds_paise"] for b in bills}) == 1, "equal bills deduct equally, so a challan can cover exactly half"
    assert [b["id"] for b in bills] == sorted((b["id"] for b in bills), reverse=True), "the ids run opposite to the numbers"
    challan = _challan(db, "C1", "2025-07-07", bills[0]["tds_paise"] * (count // 2))
    return db, bills, challan


def _undeposited_in_the_statement(db, bills):
    out = _26q(db)
    by_no = {b["bill_no"]: b["id"] for b in bills}
    return {by_no[d["nature_of_payment"].split("Bill ")[1]] for d in out["deductees"] if not d.get("challan_no")}


def _undeposited_in_the_register(db, challan):
    mapping = deposit_due.mapping_from_register(db.rows("tds_deductions"), [challan], fy=FY)
    return {r["purchase_bill_id"] for r in db.rows("tds_deductions")
            if mapping.for_deduction(r["id"]).deposited_paise < r["tds_paise"]}


def test_the_statement_and_the_register_leave_the_same_deductions_without_a_challan(monkeypatch, descending_ids):
    db, bills, challan = _bills_one_day_and_a_challan_for_half(monkeypatch)
    in_the_statement = _undeposited_in_the_statement(db, bills)
    in_the_register = _undeposited_in_the_register(db, challan)
    assert len(in_the_statement) == 3, "half the bills are paid and half are not"
    assert in_the_statement == in_the_register


def test_the_deductions_left_without_a_challan_are_the_last_by_id_and_not_the_last_by_bill_number(monkeypatch, descending_ids):
    """B-6 has the lowest id and so is first in the queue and paid; B-1 to B-3 have the highest ids and are left. The bill number
    would have left B-4 to B-6."""
    db, bills, challan = _bills_one_day_and_a_challan_for_half(monkeypatch)
    expected = {b["id"] for b in bills[:3]}
    assert _undeposited_in_the_statement(db, bills) == expected
    assert _undeposited_in_the_register(db, challan) == expected


# ── the readers read the columns the order depends on ───────────────────────

def test_the_deposit_worksheet_and_the_screens_state_order_same_day_deductions_as_the_statement_does(monkeypatch, descending_ids):
    """The first version of this change passed every test and did nothing in production: the three register reads each selected a
    list of columns that left out `purchase_bill_id` and `purchase_payment_id`, so `source_id` fell back to the row's own id there.
    These run the readers' OWN reads (the fake database projects columns as PostgREST does) and not rows handed to them whole."""
    from services import tds_deposit_state_service as state, tds_deposit_worksheet_service as worksheet
    db, bills, challan = _bills_one_day_and_a_challan_for_half(monkeypatch)
    expected = {b["id"] for b in bills[:3]}
    assert _undeposited_in_the_statement(db, bills) == expected
    link = {r["id"]: r["purchase_bill_id"] for r in db.rows("tds_deductions")}

    quarter_rows, challans = worksheet.read_register(db, "FIRM-A", "CLI", worksheet.month_window(2025, 6))
    assert all("purchase_bill_id" in r for r in quarter_rows), "the worksheet's read leaves the bill out of its rows"
    mapping = deposit_due.mapping_from_register(quarter_rows, challans, fy=FY)
    assert {link[r["id"]] for r in quarter_rows if mapping.for_deduction(r["id"]).deposited_paise < r["tds_paise"]} == expected

    answer = state.read(db, "FIRM-A", "CLI", position=(0, 0))
    assert {link[rid] for rid, row in answer["deductions"].items() if row["state"] == "not_deposited"} == expected


@pytest.mark.parametrize("path", ["services/tds_deposit_worksheet_service.py", "services/form_3cd_service.py",
                                  "services/tds_deposit_state_service.py"])
def test_every_read_that_feeds_the_register_match_selects_the_document_a_row_came_from(path):
    """Form 3CD clause 34 sums by section, so its totals do not show the order of two rows; its read is held by the source."""
    import re
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / path).read_text(encoding="utf-8")
    reads = [m.start() for m in re.finditer(r'table\("tds_deductions"\)', src)]
    assert reads, f"{path} no longer reads tds_deductions"
    for at in reads:
        chain = src[at:at + 900].split("label=")[0]
        assert "purchase_bill_id" in chain and "purchase_payment_id" in chain, (
            f"{path}: a read of tds_deductions that feeds the challan match leaves out the bill or payment each row came from")
