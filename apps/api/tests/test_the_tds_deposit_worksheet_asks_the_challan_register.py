"""The TDS deposit worksheet asks the challan register what has been deposited (found while seeding the firm's TDS data).

WHAT WAS WRONG, driven over a real database on 19-10-2026
    `GET /api/tds-workspace/deposit-due` read "deposited" from two columns of each deduction row, `challan_date` and `status`
    (migration 014), and nothing in the product writes either. Recording a challan (`POST /challans`) never touched them. So
    after the CA paid the tax on the due date and recorded the challan, the worksheet still said the whole month was
    outstanding and charged §201(1A)(ii) interest from each deduction to TODAY, growing every day, on tax that had reached
    the government on time (a July 2025 deduction, deposited on 7 August 2025, showed ₹6,027.66 outstanding and ₹1,446.63 of
    interest when read on 19 October 2026). The quarterly statement, built on the same register, said the same tax was fully deposited.

WHAT IS HELD
    * a deduction the register's challans cover is deposited, on its first challan's date, whatever its own columns say;
    * interest on a late deposit stops at the challan's date and does not grow with the clock; on tax with no challan it runs
      to today as before;
    * the match is the quarterly statement's own (`challan_mapping`, first in first out within a section), taken over the
      QUARTER up to the month asked about, so a short earlier month moves the shortfall to the later deductions;
    * each challan a deduction drew on is judged by its own date, and a challan dated before the deduction is not counted;
    * the reads add no ordering of their own (keyset paging), and the sheet says what it read;
    * a challan settles tax and surcharge and never its own interest or penalty; a salary challan settles nothing here;
    * a challan of another quarter, another year or another client is not counted;
    * a row somebody marked deposited by hand (the old columns) still reads as deposited when the register does not cover it.
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from domain.tds import deposit_due, interest

pytestmark = pytest.mark.usefixtures("dev_header_auth")

FY = "2025-26"
CLIENT, FIRM = "client-123", "firm-1"
HEADERS = {"X-User-Email": "partner@test.com", "X-User-Role": "partner", "X-Firm-ID": FIRM}
DUE_JUNE = date(2025, 7, 7)
LATER = date(2026, 10, 19)


def _row(rid, section, day, tds, **extra):
    return {"id": rid, "section": section, "transaction_date": day, "tds_paise": tds, "surcharge_paise": 0,
            "cess_paise": 0, "payment_amount_paise": tds * 10, "status": "deducted", "deductee_name": rid, **extra}


def _challan(no, section, paid_on, tds, **extra):
    """A `tds_challans` row as `create_challan` stores it: `tds_paise` is the tax, the other components sit beside it and
    `total_paise` is the whole of what left the bank."""
    parts = {"surcharge_paise": 0, "interest_paise": 0, "penalty_paise": 0, **extra}
    return {"id": f"c-{no}", "challan_no": no, "section": section, "payment_date": paid_on, "tds_paise": tds,
            "total_paise": tds + parts["surcharge_paise"] + parts["interest_paise"] + parts["penalty_paise"], **parts}


def _sheet(rows, challans, *, month="2025-06", due=DUE_JUNE, as_at=LATER, quarter_rows=None):
    mapping = deposit_due.mapping_from_register(quarter_rows if quarter_rows is not None else rows, challans, fy=FY)
    return deposit_due.build(rows, month=month, due_date=due, as_at=as_at, deposits=mapping)


def _line(sheet, section):
    return next(s for s in sheet.sections if s.section == section)


JUNE = [_row("d1", "194J", "2025-06-04", 10000_00), _row("d2", "194J", "2025-06-20", 5000_00)]


# ── 1. a recorded challan settles the month ─────────────────────────────────

def test_a_challan_on_the_due_date_leaves_nothing_outstanding_and_no_interest():
    sheet = _sheet(JUNE, [_challan("C1", "194J", "2025-07-07", 15000_00)])
    line = _line(sheet, "194J")
    assert (line.tax_paise, line.deposited_paise, line.outstanding_paise) == (15000_00, 15000_00, 0)
    assert line.interest_paise == 0 and line.late_row_count == 0


def test_without_a_challan_the_tax_is_outstanding_and_the_interest_runs_to_today():
    early = _line(_sheet(JUNE, [], as_at=date(2025, 9, 1)), "194J")
    late = _line(_sheet(JUNE, [], as_at=LATER), "194J")
    assert early.outstanding_paise == late.outstanding_paise == 15000_00
    assert 0 < early.interest_paise < late.interest_paise, "the clock keeps running while nothing is deposited"


def test_interest_on_a_late_deposit_stops_at_the_challans_date():
    """The worked sum, row by row: each deduction's own clock, to the day the challan paid it."""
    challans = [_challan("C1", "194J", "2025-08-20", 15000_00)]
    expected = sum(interest.interest_on_late_deposit(
        tax_paise=tds, deducted_on=date.fromisoformat(day), due_date=DUE_JUNE, deposited_on=date(2025, 8, 20)).interest_paise
        for tds, day in ((10000_00, "2025-06-04"), (5000_00, "2025-06-20")))
    assert expected > 0
    for as_at in (date(2025, 9, 1), date(2026, 10, 19)):
        line = _line(_sheet(JUNE, challans, as_at=as_at), "194J")
        assert line.interest_paise == expected, "a deposited row's interest must not grow with the clock"
        assert line.outstanding_paise == 0 and line.late_row_count == 2


def test_a_short_challan_covers_the_earliest_deductions_and_the_rest_stays_outstanding():
    line = _line(_sheet(JUNE, [_challan("C1", "194J", "2025-07-07", 10000_00)]), "194J")
    assert (line.deposited_paise, line.outstanding_paise) == (10000_00, 5000_00)
    assert line.late_row_count == 1, "only the uncovered deduction is late"
    only_the_last = interest.interest_on_late_deposit(
        tax_paise=5000_00, deducted_on=date(2025, 6, 20), due_date=DUE_JUNE, deposited_on=None, as_at=LATER)
    assert line.interest_paise == only_the_last.interest_paise


def test_one_deduction_partly_covered_has_its_covered_part_judged_by_the_challan_and_the_rest_as_unpaid():
    rows = [_row("d1", "194J", "2025-06-04", 10000_00)]
    line = _line(_sheet(rows, [_challan("C1", "194J", "2025-07-07", 6000_00)]), "194J")
    assert (line.deposited_paise, line.outstanding_paise) == (6000_00, 4000_00)
    assert line.late_row_count == 1
    assert line.interest_paise == interest.interest_on_late_deposit(
        tax_paise=4000_00, deducted_on=date(2025, 6, 4), due_date=DUE_JUNE, deposited_on=None, as_at=LATER).interest_paise


# ── 2. the match is the statement's, over the quarter ───────────────────────

def test_a_short_earlier_month_moves_its_shortfall_to_the_later_deductions():
    """April's challan is short; first in first out puts the shortfall on May's deduction, which the worksheet for MAY must
    show, and which a match over May's rows alone would hide."""
    april = _row("a1", "194C", "2025-04-10", 5000_00)
    may = _row("m1", "194C", "2025-05-03", 5000_00)
    challans = [_challan("C-APR", "194C", "2025-05-07", 3000_00), _challan("C-MAY", "194C", "2025-06-06", 5000_00)]
    quarter = [april, may]
    in_context = _line(_sheet([may], challans, month="2025-05", due=date(2025, 6, 7), quarter_rows=quarter), "194C")
    alone = _line(_sheet([may], challans, month="2025-05", due=date(2025, 6, 7)), "194C")
    # 8,000 deposited against 10,000 deducted: April is covered (3,000 + 2,000 of May's challan), May is 2,000 short.
    assert (in_context.deposited_paise, in_context.outstanding_paise) == (3000_00, 2000_00)
    assert (alone.deposited_paise, alone.outstanding_paise) == (5000_00, 0), "the control: without the quarter it is wrong"


def test_the_section_typed_on_a_challan_matches_whichever_limb_the_deduction_was_under():
    rows = [_row("d1", "194J(B)", "2025-06-04", 10000_00)]
    line = _line(_sheet(rows, [_challan("C1", "194J", "2025-07-07", 10000_00)]), "194J(B)")
    assert (line.deposited_paise, line.outstanding_paise) == (10000_00, 0)


def test_a_challan_under_another_section_settles_nothing():
    line = _line(_sheet(JUNE, [_challan("C1", "194C", "2025-07-07", 15000_00)]), "194J")
    assert (line.deposited_paise, line.outstanding_paise) == (0, 15000_00)


def test_the_interest_and_penalty_on_a_challan_settle_no_deduction():
    """Challan 281 carries tax, surcharge, interest and a fee. `total_paise` is what left the bank; only the tax part pays a
    deduction, so a challan that included ₹500 of interest does not cover ₹500 more of tax."""
    challan = _challan("C1", "194J", "2025-08-20", 14500_00, interest_paise=500_00)
    assert challan["total_paise"] == 15000_00
    line = _line(_sheet(JUNE, [challan]), "194J")
    assert (line.deposited_paise, line.outstanding_paise) == (14500_00, 500_00)


def test_the_surcharge_and_cess_are_part_of_the_tax_a_challan_pays():
    rows = [_row("d1", "195", "2025-06-04", 10000_00, surcharge_paise=1000_00, cess_paise=400_00)]
    # What `create_challan` stores for a ₹11,400 payment with ₹1,000 entered as surcharge: tax is the remainder.
    challan = _challan("C1", "195", "2025-07-07", 10400_00, surcharge_paise=1000_00)
    line = _line(_sheet(rows, [challan]), "195")
    assert line.tax_paise == 11400_00
    assert (line.deposited_paise, line.outstanding_paise) == (11400_00, 0)


def test_a_salary_challan_settles_nothing_here_and_a_salary_row_is_not_matched():
    rows = JUNE + [_row("s1", "192", "2025-06-30", 3000_00, deductee_name="Employee")]
    sheet = _sheet(rows, [_challan("C-SAL", "192", "2025-07-07", 3000_00)])
    assert (_line(sheet, "194J").deposited_paise, _line(sheet, "192").deposited_paise) == (0, 0)
    assert any(g["kind"] == deposit_due.GAP_SALARY_ROW_IN_THIS_REGISTER for g in sheet.statutory_gaps)


def test_a_challan_with_no_date_cannot_be_run_to_and_counts_for_nothing():
    challan = _challan("C1", "194J", None, 15000_00)
    line = _line(_sheet(JUNE, [challan]), "194J")
    assert (line.deposited_paise, line.outstanding_paise) == (0, 15000_00)


# ── 3. the old columns are a fallback and the register wins ─────────────────

def test_a_row_marked_deposited_by_hand_still_reads_deposited_when_the_register_does_not_cover_it():
    rows = [_row("d1", "194J", "2025-06-04", 10000_00, challan_date="2025-07-07", status="deposited")]
    line = _line(_sheet(rows, []), "194J")
    assert (line.deposited_paise, line.outstanding_paise, line.interest_paise) == (10000_00, 0, 0)


def test_where_both_speak_the_register_is_believed():
    rows = [_row("d1", "194J", "2025-06-04", 10000_00, challan_date="2025-07-07", status="deposited")]
    line = _line(_sheet(rows, [_challan("C1", "194J", "2025-08-20", 10000_00)]), "194J")
    assert line.interest_paise > 0, "the register says the deposit was on 20 August, and that is the date interest runs to"


def test_the_worksheet_without_a_register_behaves_as_it_did():
    """`deposits=None` is the old call, kept for callers that have no register to pass."""
    rows = [_row("d1", "194J", "2025-06-04", 10000_00, challan_date="2025-07-07", status="deposited"),
            _row("d2", "194J", "2025-06-20", 5000_00)]
    sheet = deposit_due.build(rows, month="2025-06", due_date=DUE_JUNE, as_at=LATER)
    line = _line(sheet, "194J")
    assert (line.deposited_paise, line.outstanding_paise) == (10000_00, 5000_00)


# ── 4. the door: record a challan, read the worksheet ───────────────────────

@pytest.fixture
def client():
    from main import app
    return TestClient(app)


@pytest.fixture(autouse=True)
def clean_stores():
    from routers.tds_workspace import _MOCK_CHALLANS, _MOCK_DEDUCTIONS
    _MOCK_CHALLANS.clear()
    _MOCK_DEDUCTIONS.clear()
    yield
    _MOCK_CHALLANS.clear()
    _MOCK_DEDUCTIONS.clear()


def _seed_deductions(rows, client_id=CLIENT):
    from routers.tds_workspace import _MOCK_DEDUCTIONS
    for r in rows:
        _MOCK_DEDUCTIONS[r["id"]] = {**r, "client_id": client_id, "firm_id": FIRM}


def _record_challan(client, *, on, amount, section="194J", quarter="Q1", fy=FY, client_id=CLIENT, **extra):
    resp = client.post("/api/tds-workspace/challans", headers=HEADERS, json={
        "client_id": client_id, "bsr_code": "0000000", "challan_date": on, "amount_paise": amount,
        "challan_no": f"SEED-{on}", "section": section, "financial_year": fy, "quarter": quarter, **extra})
    assert resp.status_code == 200 and resp.json()["success"] is True, resp.text


def _worksheet(client, month="2025-06", client_id=CLIENT):
    resp = client.get(f"/api/tds-workspace/deposit-due?client_id={client_id}&month={month}", headers=HEADERS)
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def test_recording_the_challan_settles_the_worksheet_the_regression_that_was_found():
    """The whole defect in one sequence, through the doors a CA presses."""
    client = TestClient(__import__("main").app)
    _seed_deductions(JUNE)
    before = _worksheet(client)["totals"]
    assert before["outstanding_paise"] == 15000_00 and before["interest_paise"] > 0
    _record_challan(client, on="2025-07-07", amount=15000_00)
    after = _worksheet(client)["totals"]
    assert (after["deposited_paise"], after["outstanding_paise"], after["interest_paise"]) == (15000_00, 0, 0)
    assert after["late_row_count"] == 0 and after["payable_paise"] == 0


def test_a_late_challan_fixes_the_interest_at_its_own_date():
    client = TestClient(__import__("main").app)
    _seed_deductions(JUNE)
    _record_challan(client, on="2025-08-20", amount=15000_00)
    totals = _worksheet(client)["totals"]
    assert totals["outstanding_paise"] == 0 and totals["interest_paise"] > 0 and totals["late_row_count"] == 2


def test_a_challan_for_another_quarter_year_or_client_is_not_counted():
    client = TestClient(__import__("main").app)
    _seed_deductions(JUNE)
    _record_challan(client, on="2025-07-07", amount=15000_00, quarter="Q2")
    _record_challan(client, on="2025-07-07", amount=15000_00, fy="2024-25")
    _record_challan(client, on="2025-07-07", amount=15000_00, client_id="client-other")
    assert _worksheet(client)["totals"]["deposited_paise"] == 0


def test_the_april_shortfall_shows_on_the_may_worksheet_through_the_door():
    client = TestClient(__import__("main").app)
    _seed_deductions([_row("a1", "194C", "2025-04-10", 5000_00), _row("m1", "194C", "2025-05-03", 5000_00)])
    _record_challan(client, on="2025-05-07", amount=3000_00, section="194C")
    _record_challan(client, on="2025-06-06", amount=5000_00, section="194C")
    may = _worksheet(client, month="2025-05")["totals"]
    assert (may["deposited_paise"], may["outstanding_paise"]) == (3000_00, 2000_00)
    april = _worksheet(client, month="2025-04")["totals"]
    assert (april["deposited_paise"], april["outstanding_paise"]) == (5000_00, 0)


# ── 5. the live reads ask for what the match needs ──────────────────────────

class _Recorder:
    """A query builder that records every call made on it and answers nothing: the test reads the calls."""

    def __init__(self, log, table):
        self.log, self.table = log, table

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.log.append((self.table, name, args))
            return self
        return call


def test_the_live_worksheet_reads_the_quarters_deductions_and_the_quarters_challans_for_this_client_only(monkeypatch):
    import core.supabase_client as sc
    import routers.tds_workspace as tw
    calls: list = []
    monkeypatch.setattr(tw, "_USE_MOCK", False)
    monkeypatch.setattr(sc, "get_supabase", lambda: type("Db", (), {"table": lambda self, t: _Recorder(calls, t)})())
    answers = {"tds.deposit_due": [_row("d1", "194J", "2025-07-23", 10000_00)],
               "tds.deposit_due.challans": [_challan("C1", "194J", "2025-08-07", 10000_00)]}
    monkeypatch.setattr(tw, "fetch_all", lambda make_query, key="id", *, label="", stats=None:
                        (make_query(), answers[label])[1])
    out = tw.deposit_due(client_id=CLIENT, month="2025-07", current_user={"firm_id": FIRM, "id": "u1", "role": "Partner"})
    assert out["success"] is True
    assert out["data"]["totals"]["deposited_paise"] == 10000_00 and out["data"]["totals"]["interest_paise"] == 0
    seen = {(t, m, a) for t, m, a in calls}
    # July is in Q2 (1 July to 30 September): the deductions are read from the QUARTER'S first day to the month's last.
    for expected in (("tds_deductions", "eq", ("firm_id", FIRM)), ("tds_deductions", "eq", ("client_id", CLIENT)),
                     ("tds_deductions", "gte", ("transaction_date", "2025-07-01")),
                     ("tds_deductions", "lte", ("transaction_date", "2025-07-31")),
                     ("tds_challans", "eq", ("firm_id", FIRM)), ("tds_challans", "eq", ("client_id", CLIENT)),
                     ("tds_challans", "eq", ("financial_year", FY)), ("tds_challans", "eq", ("quarter", "Q2"))):
        assert expected in seen, f"the live read never asked {expected}"
    selects = [a[0] for t, m, a in calls if t == "tds_deductions" and m == "select"]
    assert selects and all(c in selects[0] for c in ("id", "section", "transaction_date", "tds_paise", "surcharge_paise",
                                                      "cess_paise", "challan_date")), "the read drops a column the match needs"


def test_the_live_worksheet_for_a_later_month_reads_from_the_start_of_its_quarter(monkeypatch):
    import core.supabase_client as sc
    import routers.tds_workspace as tw
    calls: list = []
    monkeypatch.setattr(tw, "_USE_MOCK", False)
    monkeypatch.setattr(sc, "get_supabase", lambda: type("Db", (), {"table": lambda self, t: _Recorder(calls, t)})())
    monkeypatch.setattr(tw, "fetch_all", lambda make_query, key="id", *, label="", stats=None: (make_query(), [])[1])
    tw.deposit_due(client_id=CLIENT, month="2025-09", current_user={"firm_id": FIRM, "id": "u1", "role": "Partner"})
    gte = [a for t, m, a in calls if t == "tds_deductions" and m == "gte"]
    assert gte == [("transaction_date", "2025-07-01")], "September's match has to include July and August"
    quarter = [a for t, m, a in calls if t == "tds_challans" and m == "eq" and a[0] == "quarter"]
    assert quarter == [("quarter", "Q2")]


# ── 6. the review's findings, each pinned ───────────────────────────────────

def test_a_deduction_paid_by_two_challans_bears_interest_on_the_part_that_was_paid_late():
    """₹100 deducted on 20 April, ₹60 paid by the 7 May due date and the other ₹40 on 20 August. The statement names the
    first challan for the row; the interest cannot: the ₹40 was late by April to August, five part-months at 1.5%, ₹3.00."""
    rows = [_row("d1", "194C", "2025-04-20", 100_00)]
    challans = [_challan("C-A", "194C", "2025-05-07", 60_00), _challan("C-B", "194C", "2025-08-20", 40_00)]
    line = _line(_sheet(rows, challans, month="2025-04", due=date(2025, 5, 7)), "194C")
    assert (line.deposited_paise, line.outstanding_paise) == (100_00, 0)
    assert line.interest_paise == 3_00 and line.late_row_count == 1


def test_a_challan_dated_before_the_deduction_is_not_counted_and_the_sheet_says_why():
    """The match is by order and not by date: the only challan of the quarter is April's payment, dated 7 May, and May's
    deduction on 20 May drew on it. Tax cannot have been paid before it was deducted; counting it would show the deduction
    deposited on 7 May with no interest, silently."""
    rows = [_row("m1", "194C", "2025-05-20", 1000_00, deductee_name="Vendor")]
    sheet = _sheet(rows, [_challan("C-APR", "194C", "2025-05-07", 1000_00)], month="2025-05", due=date(2025, 6, 7))
    line = _line(sheet, "194C")
    assert (line.deposited_paise, line.outstanding_paise) == (0, 1000_00)
    assert line.interest_paise > 0, "it is still unpaid as far as the books show, and the clock runs"
    gap = next(g for g in sheet.statutory_gaps if g["kind"] == deposit_due.GAP_CHALLAN_BEFORE_DEDUCTION)
    assert gap["deductees"] == ["Vendor"]


def test_a_challan_dated_the_same_day_as_the_deduction_is_counted():
    rows = [_row("d1", "194C", "2025-05-07", 1000_00)]
    line = _line(_sheet(rows, [_challan("C1", "194C", "2025-05-07", 1000_00)], month="2025-05", due=date(2025, 6, 7)), "194C")
    assert (line.deposited_paise, line.outstanding_paise) == (1000_00, 0)


def test_the_sheet_says_what_it_read_so_a_cas_outstanding_tax_can_be_traced():
    client = TestClient(__import__("main").app)
    _seed_deductions(JUNE)
    assert "No non-salary challan is recorded for Q1 FY 2025-26" in _worksheet(client)["deposits_read_from"]
    _record_challan(client, on="2025-07-07", amount=15000_00)
    assert _worksheet(client)["deposits_read_from"].startswith("1 non-salary challan recorded for Q1 FY 2025-26")


@pytest.mark.parametrize("month, deducted, challan_on, quarter, fy, due", [
    ("2026-01", "2026-01-15", "2026-02-07", "Q4", "2025-26", "2026-02-07"),
    ("2026-03", "2026-03-20", "2026-04-28", "Q4", "2025-26", "2026-04-30"),
    ("2026-07", "2026-07-10", "2026-08-07", "Q2", "2026-27", "2026-08-07"),
])
def test_the_quarter_and_year_follow_the_month_across_the_year_end_and_into_the_next_year(
        month, deducted, challan_on, quarter, fy, due):
    """January to March are the LAST quarter of the year that began in April; March's tax is due on 30 April."""
    client = TestClient(__import__("main").app)
    _seed_deductions([_row("d1", "194C", deducted, 50000_00)])
    _record_challan(client, on=challan_on, amount=50000_00, section="194C", quarter=quarter, fy=fy)
    sheet = _worksheet(client, month=month)
    assert sheet["due_date"] == due
    assert (sheet["totals"]["deposited_paise"], sheet["totals"]["outstanding_paise"], sheet["totals"]["interest_paise"]) \
        == (50000_00, 0, 0)
    assert f"{quarter} FY {fy}" in sheet["deposits_read_from"]


# ── 7. paging: the reads are keyset-paged, so they add no ordering of their own ──

def test_no_fetch_all_query_orders_for_itself():
    """`fetch_all` pages by keyset on `id` and appends its own `.order("id")`; a query that orders by another column first
    makes the cursor (the last row's id) skip and repeat rows once there is a second page. Found in this worksheet's first
    version by the independent review: 2,500 rows came back as 4,173 with 701 missing. The rule, over every caller."""
    import ast
    import pathlib
    api = pathlib.Path(__file__).resolve().parent.parent
    calls, offenders = 0, []
    for folder in ("routers", "services", "domain", "jobs", "repositories", "core"):
        for path in sorted((api / folder).rglob("*.py")):
            text = path.read_text()
            if "fetch_all" not in text:
                continue
            for node in ast.walk(ast.parse(text)):
                if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) == "fetch_all" \
                        and node.args:
                    calls += 1
                    if ".order(" in (ast.get_source_segment(text, node.args[0]) or ""):
                        offenders.append(f"{path.relative_to(api)}:{node.lineno}")
    assert calls >= 20, f"only {calls} fetch_all calls found: the scan has gone blind"
    assert not offenders, f"these fetch_all queries order for themselves, which breaks the keyset cursor: {offenders}"


class _KeysetTable:
    """A PostgREST table with the semantics the paging depends on: filters, ordering by a LIST of columns (a second
    `.order()` adds a column; it does not replace), a limit, and a strict greater-than."""

    def __init__(self, rows):
        self.rows, self.filters, self.orders, self.cap = rows, [], [], None

    def select(self, *a, **k): return self
    def eq(self, c, v): self.filters.append((c, "eq", v)); return self
    def gte(self, c, v): self.filters.append((c, "gte", v)); return self
    def lte(self, c, v): self.filters.append((c, "lte", v)); return self
    def gt(self, c, v): self.filters.append((c, "gt", v)); return self
    def order(self, c): self.orders.append(c); return self
    def limit(self, n): self.cap = n; return self

    def execute(self):
        ops = {"eq": lambda a, b: a == b, "gte": lambda a, b: a >= b, "lte": lambda a, b: a <= b, "gt": lambda a, b: a > b}
        rows = [r for r in self.rows if all(ops[o](r.get(c), v) for c, o, v in self.filters)]
        rows.sort(key=lambda r: tuple(r.get(c) for c in self.orders))

        class _Result: ...
        out = _Result()
        out.data = rows[:self.cap]
        return out


def test_a_quarter_with_more_rows_than_a_page_is_read_whole_and_summed_once(monkeypatch):
    import random
    import uuid

    import core.db_paging as paging
    import core.supabase_client as sc
    import routers.tds_workspace as tw
    monkeypatch.setattr(paging, "PAGE", 40)
    rng = random.Random(7)
    deductions = [{**_row(str(uuid.UUID(int=rng.getrandbits(128))), "194C", f"2025-06-{1 + i % 28:02d}", 100_00),
                   "client_id": CLIENT, "firm_id": FIRM} for i in range(130)]
    tables = {"tds_deductions": deductions, "tds_challans": []}
    monkeypatch.setattr(tw, "_USE_MOCK", False)
    monkeypatch.setattr(sc, "get_supabase", lambda: type("Db", (), {"table": lambda self, t: _KeysetTable(tables[t])})())
    out = tw.deposit_due(client_id=CLIENT, month="2025-06", current_user={"firm_id": FIRM, "id": "u1", "role": "Partner"})
    totals = out["data"]["totals"]
    assert totals["deductee_count"] == 130 and totals["tax_paise"] == 130 * 100_00, (
        "a page boundary skipped or repeated rows")
