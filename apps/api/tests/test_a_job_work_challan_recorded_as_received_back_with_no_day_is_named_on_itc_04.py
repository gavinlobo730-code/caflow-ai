"""
POST-A-422 — a job-work challan recorded as received back with NO DAY is named on the FORM GST ITC-04 statement.

WHAT WAS WRONG
    `itc_04.balances` skips a challan whose status says the goods are back, and `table_5a` needs a day (`received_back_on`, or a
    return line's own `returned_on`). A row whose status says `received_back` and which records neither (it takes a status-only
    amendment from before POST-A-383, which refuses one now) was therefore not a Table 5A row, not an outstanding row and not a
    line of the statement's gaps: the Delivery Challans tab named it (a gap and the box that gives it a day) and the statement
    itself said nothing, so a CA who built the statement from the statement screen did not learn that goods the product itself
    records as sent were on none of its lists.

WHAT THIS ASSERTS
    * the statement's gaps carry one sentence naming such a challan, when there is one and only then;
    * a challan whose lines are all itemised by return lines is NOT one (Table 5A carries those lots with their own days), a
      challan partly itemised IS (the rest has no day), and so is one with no return at all;
    * a challan with a day, one still out, a draft, a cancelled one and one that is not job work are NOT;
    * a challan sent in another year is that year's gap, not this one's;
    * the sentence names the challans (a few, then a count), says "is" for one and "are" for several, and the fixed gaps stay;
    * it adds nothing to Table 5A or to what is outstanding: it is a gap and not a figure (a quantity nobody dated is not guessed).
"""
from __future__ import annotations

from datetime import date

import pytest

import services.itc_04_service as svc
from domain.gst import itc_04 as itc
from tests.e2e_harness import FakeDB

FIRM = "FIRM-J"
CLIENT = "CLI-MFG"
TODAY = date(2026, 10, 1)
WORKER_GSTIN = "29BBBBB1111B1ZR"


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    monkeypatch.setattr(svc, "ist_today", lambda: TODAY)


@pytest.fixture
def db():
    x = FakeDB()
    x.seed("clients", {"id": CLIENT, "firm_id": FIRM, "client_name": "Mfg Co"})
    return x


def _challan(db, no, sent_on, *, reason="job_work", status="received_back", received_back_on=None, **extra):
    return db.seed("delivery_challans", {
        "firm_id": FIRM, "client_id": CLIENT, "document_no": no, "document_date": sent_on, "reason": reason,
        "status": status, "goods_kind": "inputs", "received_back_on": received_back_on, "extended_to": None,
        "consignee_name": "Precision Castings", "consignee_gstin": WORKER_GSTIN, "place_of_supply": "29",
        "is_inter_state": False, **extra})


def _line(db, challan, qty="10"):
    return db.seed("delivery_challan_lines", {
        "firm_id": FIRM, "client_id": CLIENT, "challan_id": challan["id"], "line_order": 0, "description": "Castings",
        "hsn_sac": "7214", "quantity": qty, "unit": "NOS", "taxable_amount_paise": 5_00_000, "gst_rate_percent": "18"})


def _back(db, challan, line, qty, on="2026-08-20"):
    return db.seed("delivery_challan_returns", {
        "firm_id": FIRM, "client_id": CLIENT, "challan_id": challan["id"], "challan_line_id": line["id"],
        "returned_on": on, "quantity_returned": qty, "quantity_lost_or_wasted": "0", "job_worker_challan_no": "JW/22",
        "job_worker_challan_date": "2026-08-21", "nature_of_job_work": "Machining"})


def _statement(db, **kw):
    kw.setdefault("as_at", TODAY)
    return svc.statement(db, FIRM, CLIENT, "2026-27", **kw)


def _named(out):
    """The gap sentences that are about a received-back challan with no day."""
    return [g for g in out["gaps"] if "received back with no day" in g]


def test_a_challan_whose_status_says_back_and_which_records_no_day_is_named_and_is_on_no_list(db):
    c = _challan(db, "JW/001", "2026-05-10")
    _line(db, c)

    out = _statement(db, window="2026-27:H1")

    assert len(_named(out)) == 1 and "JW/001" in _named(out)[0] and _named(out)[0].startswith("1 job-work challan is recorded")
    assert "the goods on it that no lot accounts for are on neither" in _named(out)[0]
    assert out["table_5a"]["rows"] == [], "nothing is invented for a quantity nobody dated"
    assert out["outstanding"] == [], "the status says the goods are back, so it is not shown as still out"
    assert [r["challan_no"] for r in out["table_4"]["rows"]] == ["JW/001"], "the challan is still on Table 4: the goods did leave"
    for fixed in itc.statement_gaps():
        assert fixed in out["gaps"], "the gaps every answer carries are still there"


def test_the_gap_is_there_without_choosing_a_window(db):
    c = _challan(db, "JW/001", "2026-05-10")
    _line(db, c)
    assert len(_named(_statement(db))) == 1, "it does not wait for a window to be chosen"


def test_a_challan_with_every_line_itemised_is_not_one(db):
    c = _challan(db, "JW/002", "2026-05-10")
    ln = _line(db, c, "10")
    _back(db, c, ln, "6", "2026-07-01")
    _back(db, c, ln, "4", "2026-08-01")

    out = _statement(db, window="2026-27:H1")

    assert _named(out) == [], "Table 5A carries those lots with their own days"
    assert len(out["table_5a"]["rows"]) == 2


def test_a_challan_partly_itemised_is_one_because_the_rest_has_no_day(db):
    c = _challan(db, "JW/003", "2026-05-10")
    ln = _line(db, c, "10")
    _back(db, c, ln, "6", "2026-07-01")

    out = _statement(db, window="2026-27:H1")

    assert len(_named(out)) == 1 and "JW/003" in _named(out)[0]
    assert len(out["table_5a"]["rows"]) == 1, "the lot that has a day is still a row"


def test_a_second_line_left_unitemised_counts_even_when_the_first_is_covered(db):
    c = _challan(db, "JW/004", "2026-05-10")
    first = _line(db, c, "10")
    _line(db, c, "5")
    _back(db, c, first, "10", "2026-07-01")

    assert len(_named(_statement(db))) == 1


@pytest.mark.parametrize("why, kwargs", [
    ("a challan with the day recorded", {"received_back_on": "2026-08-20"}),
    ("a challan still out", {"status": "issued"}),
    ("a draft", {"status": "draft"}),
    ("a cancelled challan", {"status": "cancelled"}),
    ("a delivery that is not job work", {"reason": "supply_on_approval"}),
])
def test_what_is_not_a_received_back_challan_with_no_day_is_not_named(db, why, kwargs):
    c = _challan(db, "X/001", "2026-05-10", **kwargs)
    _line(db, c)
    assert _named(_statement(db)) == [], why


def test_a_challan_sent_in_another_year_is_that_years_gap_and_not_this_ones(db):
    c = _challan(db, "OLD/001", "2025-05-10")
    _line(db, c)
    assert _named(_statement(db)) == []
    assert len(_named(svc.statement(db, FIRM, CLIENT, "2025-26", as_at=TODAY))) == 1


def test_another_clients_challan_is_not_named(db):
    db.seed("clients", {"id": "CLI-OTHER", "firm_id": FIRM, "client_name": "Other Co"})
    c = _challan(db, "ELSE/001", "2026-05-10", client_id="CLI-OTHER")
    db.seed("delivery_challan_lines", {"firm_id": FIRM, "client_id": "CLI-OTHER", "challan_id": c["id"], "line_order": 0,
                                       "description": "Castings", "hsn_sac": "7214", "quantity": "10", "unit": "NOS",
                                       "taxable_amount_paise": 1, "gst_rate_percent": "18"})
    assert _named(_statement(db)) == []


def test_several_are_counted_and_named_in_the_order_they_left_and_a_few_are_shown(db):
    for i in range(7):
        _line(db, _challan(db, f"JW/{i + 10}", f"2026-05-{i + 1:02d}"))

    [gap] = _named(_statement(db))

    assert gap == ("7 job-work challans are recorded as received back with no day (JW/10, JW/11, JW/12, JW/13, JW/14 and 2 more), so the goods on them that no lot "
                   "accounts for are on neither the Table 5A rows nor the outstanding list. Record the day the goods came back on the Delivery Challans tab.")
    assert "lots" not in gap.split("accounts for")[1], "no remedy the screen cannot give: a lot cannot be recorded on a challan whose status says it is back"


def test_the_pure_function_orders_by_the_day_the_goods_left_and_names_nothing_for_none():
    challans = [
        {"id": "b", "document_no": "B", "document_date": "2026-06-01", "reason": "job_work", "status": "received_back", "received_back_on": None},
        {"id": "a", "document_no": "A", "document_date": "2026-05-01", "reason": "job_work", "status": "received_back", "received_back_on": None},
    ]
    lines = [{"id": "la", "challan_id": "a", "quantity": "1"}, {"id": "lb", "challan_id": "b", "quantity": "1"}]
    assert [r["challan_no"] for r in itc.received_back_without_a_day(challans, lines, [])] == ["A", "B"]
    assert itc.received_back_without_a_day_gap([]) is None
    assert itc.received_back_without_a_day([], [], []) == []


def test_a_challan_with_no_lines_is_not_named_because_nothing_sent_can_be_missing():
    challans = [{"id": "a", "document_no": "A", "document_date": "2026-05-01", "reason": "job_work", "status": "received_back", "received_back_on": None}]
    assert itc.received_back_without_a_day(challans, [], []) == []


def test_a_lot_beyond_what_one_line_sent_does_not_cover_another_line_that_has_none(db):
    """The door refuses a lot larger than the line, but a stored row can carry one: its excess must not offset the other line's missing quantity."""
    c = _challan(db, "JW/005", "2026-05-10")
    first = _line(db, c, "10")
    _line(db, c, "5")
    _back(db, c, first, "15", "2026-07-01")

    assert len(_named(_statement(db))) == 1


def test_the_pure_function_asks_for_job_work_itself_and_does_not_lean_on_the_query_that_fed_it():
    """The statement only loads job-work challans, but the function is pure and is named for what it finds: a goods-on-approval challan is not a job-work one."""
    challans = [{"id": "a", "document_no": "A", "document_date": "2026-05-01", "reason": "supply_on_approval", "status": "received_back", "received_back_on": None}]
    lines = [{"id": "la", "challan_id": "a", "quantity": "1"}]
    assert itc.received_back_without_a_day(challans, lines, []) == []


def test_the_sentence_sits_before_the_closing_line_that_nothing_is_filed(db):
    _line(db, _challan(db, "JW/001", "2026-05-10"))
    gaps = _statement(db)["gaps"]
    assert gaps[-1] == itc.NOTHING_IS_FILED and len(_named({"gaps": gaps[:-1]})) == 1 and gaps[:5] == itc.statement_gaps()[:5]
    assert itc.statement_gaps() == [*itc.statement_gaps()[:-1], itc.NOTHING_IS_FILED] and len(itc.statement_gaps()) == 6


def test_a_challan_whose_lots_are_all_dated_in_a_later_year_is_not_named_in_the_year_it_was_sent(db):
    """The statement's own read of lots is the year's. A challan judged on it would be named for lots it cannot see."""
    c = _challan(db, "JW/006", "2026-05-10")
    ln = _line(db, c, "10")
    _back(db, c, ln, "10", "2027-05-01")

    assert _named(_statement(db)) == []


def test_a_challan_sent_in_an_earlier_year_with_a_lot_in_this_one_is_judged_on_all_its_lots(db):
    c = _challan(db, "JW/007", "2025-05-10")
    ln = _line(db, c, "10")
    _back(db, c, ln, "6", "2025-09-01")
    _back(db, c, ln, "4", "2026-05-01")

    assert _named(_statement(db)) == [], "the lot of 2025-26 is out of this year's read but it is on the challan"
    assert _named(svc.statement(db, FIRM, CLIENT, "2025-26", as_at=TODAY)) == []


def test_a_challan_sent_in_an_earlier_year_that_is_not_fully_itemised_is_named_once_in_its_own_year(db):
    c = _challan(db, "JW/008", "2025-05-10")
    ln = _line(db, c, "10")
    _back(db, c, ln, "6", "2025-09-01")
    _back(db, c, ln, "2", "2026-05-01")

    assert len(_named(_statement(db))) == 1, "it is loaded here because a lot falls in this year, and 2 of 10 are still undated"


def test_a_challan_whose_only_lot_is_waste_is_named_and_the_lot_is_still_a_table_5a_row(db):
    c = _challan(db, "JW/009", "2026-05-10")
    ln = _line(db, c, "10")
    db.seed("delivery_challan_returns", {
        "firm_id": FIRM, "client_id": CLIENT, "challan_id": c["id"], "challan_line_id": ln["id"], "returned_on": "2026-07-01",
        "quantity_returned": "0", "quantity_lost_or_wasted": "10", "job_worker_challan_no": "JW/22",
        "job_worker_challan_date": "2026-07-01", "nature_of_job_work": "Machining"})

    out = _statement(db, window="2026-27:H1")

    assert len(_named(out)) == 1, "waste is never subtracted, so nothing came back"
    assert [r["lost_or_wasted_quantity"] for r in out["table_5a"]["rows"]] == ["10.000"]


def test_tools_and_moulds_are_named_with_the_fact_that_the_tab_offers_them_no_box(db):
    _line(db, _challan(db, "JW/020", "2026-05-10", goods_kind="moulds_dies_jigs_fixtures_tools"))
    _line(db, _challan(db, "JW/021", "2026-05-11", goods_kind="inputs"))

    [gap] = _named(_statement(db))

    assert "That tab offers no box for tools, moulds, dies, jigs and fixtures (JW/020)" in gap
    assert "so for that one the day cannot be recorded from a screen yet" in gap and "JW/021" in gap.split("That tab")[0]


def test_no_tools_clause_when_every_named_challan_has_a_period(db):
    _line(db, _challan(db, "JW/022", "2026-05-10", goods_kind="inputs"))
    [gap] = _named(_statement(db))
    assert "That tab offers no box" not in gap
