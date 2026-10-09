"""A schedule says which period each due date covers, and when it is due (PRE-B-002 part 1).

WHAT WAS WRONG
    `scheduled_reports` (migration 031) holds a frequency and a day of the month, and nothing in `apps/api` reads it,
    so "which period does the report due on the 5th cover" had no answer anywhere: the screen promised a mail and the
    row could not say what it was a mail OF. `domain/reporting/report_schedule.py` is the answer and reads no clock,
    no table and no mail provider; this module holds it.

THE RULES UNDER TEST
    * A due date is the chosen day (1 to 28 only) of the month AFTER the period ends: monthly covers the previous
      calendar month, quarterly the financial-year quarter that ended last month (due July, October, January,
      April), yearly the financial year that ended 31 March (due April).
    * The FIRST slot is the first due date strictly after the day the schedule was created, in IST. A schedule made
      on the 20th does not owe the 5th; one made on the 5th does not owe that day's.
    * After downtime only the LATEST owed slot is prepared and the older unrecorded ones are returned as missed.
    * Nothing is defaulted: a day that is NULL, 0, 29 to 31 or not a whole number is "not schedulable", and a NULL
      `is_active` reads as off.
    * The module is handed `today`. It never reads the clock, and it converts a stored UTC stamp to its IST day.

THE TABLES BELOW ARE FROZEN DATES; THE PROPERTIES AT THE END HOLD THE SAME RULES FOR ANY DATE. Both are needed: a
table shows the rule is the one the statute-style description says, a property shows it for the dates nobody wrote.
"""
from __future__ import annotations

import ast
from datetime import date, timedelta
from pathlib import Path

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from core.ist_clock import fy_bounds, fy_quarters
from domain.reporting import report_schedule as R
from tests._property import kernel

API = Path(__file__).resolve().parents[1]
MODULE = API / "domain" / "reporting" / "report_schedule.py"

D = date.fromisoformat


def slots(frequency, day, since, today):
    return [(s.due_on.isoformat(), s.period.key) for s in
            R.slots_owed(frequency, day, since=D(since), today=D(today))]


# ═══ The due dates, as a table of frozen dates ═══════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("frequency, day, since, today, expected", [
    # Monthly: the previous calendar month, due on the day of the month after.
    ("monthly", 5, "2026-09-20", "2026-10-04", []),
    ("monthly", 5, "2026-09-20", "2026-10-05", [("2026-10-05", "2026-09")]),
    ("monthly", 5, "2026-09-20", "2026-11-05", [("2026-10-05", "2026-09"), ("2026-11-05", "2026-10")]),
    # A schedule made on the 20th with day 5 does NOT back-fill the 5th that had passed.
    ("monthly", 5, "2026-10-20", "2026-10-21", []),
    ("monthly", 5, "2026-10-20", "2026-11-04", []),
    ("monthly", 5, "2026-10-20", "2026-11-05", [("2026-11-05", "2026-10")]),
    # Created the day BEFORE the due day: that day is owed. Created ON it: it is not (strictly after).
    ("monthly", 5, "2026-10-04", "2026-10-05", [("2026-10-05", "2026-09")]),
    ("monthly", 5, "2026-10-05", "2026-10-05", []),
    ("monthly", 5, "2026-10-05", "2026-11-05", [("2026-11-05", "2026-10")]),
    # A day later in the month than the creation day is still ahead, in the SAME month.
    ("monthly", 25, "2026-10-20", "2026-10-25", [("2026-10-25", "2026-09")]),
    # Month ends, the 28th and a leap February (29 February 2028 is the last day of a 29-day period).
    ("monthly", 28, "2027-02-01", "2027-03-28", [("2027-02-28", "2027-01"), ("2027-03-28", "2027-02")]),
    ("monthly", 28, "2028-02-01", "2028-03-28", [("2028-02-28", "2028-01"), ("2028-03-28", "2028-02")]),
    ("monthly", 5, "2026-01-31", "2026-03-05", [("2026-02-05", "2026-01"), ("2026-03-05", "2026-02")]),
    # Calendar-year rollover: December's report is due in January.
    ("monthly", 5, "2026-11-10", "2027-01-06", [("2026-12-05", "2026-11"), ("2027-01-05", "2026-12")]),
    # Financial-year boundary: March falls due in April, and April's period starts on 1 April.
    ("monthly", 10, "2027-03-31", "2027-05-10", [("2027-04-10", "2027-03"), ("2027-05-10", "2027-04")]),
    # Quarterly: the FY quarter that ended last month, due July / October / January / April.
    ("quarterly", 10, "2026-03-31", "2027-04-10",
     [("2026-04-10", "2025-26-Q4"), ("2026-07-10", "2026-27-Q1"), ("2026-10-10", "2026-27-Q2"),
      ("2027-01-10", "2026-27-Q3"), ("2027-04-10", "2026-27-Q4")]),
    ("quarterly", 10, "2026-10-15", "2027-01-09", []),
    ("quarterly", 10, "2026-10-15", "2027-01-10", [("2027-01-10", "2026-27-Q3")]),
    # Yearly: the FY that ended on 31 March, due in April.
    ("yearly", 5, "2026-03-31", "2027-04-05", [("2026-04-05", "2025-26"), ("2027-04-05", "2026-27")]),
    ("yearly", 5, "2026-04-05", "2027-04-04", []),
    ("yearly", 5, "2026-04-05", "2027-04-05", [("2027-04-05", "2026-27")]),
    ("yearly", 1, "2026-04-02", "2027-04-01", [("2027-04-01", "2026-27")]),
])
def test_a_due_date_is_the_chosen_day_of_the_month_after_the_period_ends(frequency, day, since, today, expected):
    assert slots(frequency, day, since, today) == expected


def test_a_period_is_the_one_that_has_ended_and_says_what_it_covers():
    """The covered stretch for each frequency, read straight off the slot (key, start and end are all stated)."""
    monthly = R.slots_owed("monthly", 5, since=D("2028-02-10"), today=D("2028-03-05"))[0].period
    assert (monthly.key, monthly.start, monthly.end) == ("2028-02", D("2028-02-01"), D("2028-02-29"))
    assert monthly.label == "February 2028"
    quarter = R.slots_owed("quarterly", 5, since=D("2026-08-01"), today=D("2026-10-05"))[0].period
    assert (quarter.key, quarter.start, quarter.end) == ("2026-27-Q2", D("2026-07-01"), D("2026-09-30"))
    assert quarter.label == "Q2 of FY 2026-27"
    year = R.slots_owed("yearly", 5, since=D("2026-04-10"), today=D("2027-04-05"))[0].period
    assert (year.key, year.start, year.end) == ("2026-27", D("2026-04-01"), D("2027-03-31"))
    assert year.label == "FY 2026-27"


def test_the_quarters_and_the_year_are_read_off_the_clock_module_and_not_restated():
    """The periods and the months they fall due in come from `core.ist_clock`, so a change to what a financial year
    is cannot leave the schedule describing the old one."""
    for fy in ("2025-26", "2026-27", "2031-32"):
        quarters = [p for p in R._quarter_periods(fy)]
        assert [(p.start.isoformat(), p.end.isoformat()) for p in quarters] == [(s, e) for _, s, e in fy_quarters(fy)]
        year = R._year_period(fy)
        assert (year.start.isoformat(), year.end.isoformat()) == fy_bounds(fy)
    # And the months a quarterly schedule falls due in are the months AFTER each quarter ends.
    assert R._due_months(R.QUARTERLY) == ["July", "October", "January", "April"]
    assert R._due_months(R.YEARLY) == ["April"]


# ═══ The next slot ═══════════════════════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("frequency, day, since, today, expected", [
    ("monthly", 5, "2026-09-20", "2026-10-04", ("2026-10-05", "2026-09")),
    # A slot due today is owed today, so the next one is the following one.
    ("monthly", 5, "2026-09-20", "2026-10-05", ("2026-11-05", "2026-10")),
    # Created today on its own due day: the next is next month's, not today's.
    ("monthly", 5, "2026-10-05", "2026-10-05", ("2026-11-05", "2026-10")),
    ("monthly", 5, "2026-12-20", "2026-12-21", ("2027-01-05", "2026-12")),
    ("quarterly", 5, "2026-07-06", "2026-07-06", ("2026-10-05", "2026-27-Q2")),
    ("yearly", 5, "2026-04-06", "2026-06-01", ("2027-04-05", "2026-27")),
])
def test_the_next_slot_is_the_first_one_after_both_today_and_the_day_the_schedule_began(
        frequency, day, since, today, expected):
    nxt = R.next_slot(frequency, day, since=D(since), today=D(today))
    assert (nxt.due_on.isoformat(), nxt.period.key) == expected


# ═══ The IST day, and the stored stamp ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("stamp, expected", [
    # 18:30 UTC is IST midnight: from there to 24:00 UTC the UTC date is the day BEFORE the Indian one.
    ("2026-10-04T18:29:59+00:00", "2026-10-04"),
    ("2026-10-04T18:30:00+00:00", "2026-10-05"),
    ("2026-10-04T23:59:59+00:00", "2026-10-05"),
    ("2026-10-05T00:00:00+00:00", "2026-10-05"),
    ("2026-10-04T18:40:00Z", "2026-10-05"),
    # PostgREST trims trailing zeros of the fraction, so it can have any number of digits.
    ("2026-10-04T18:40:00.12345+00:00", "2026-10-05"),
    ("2026-10-04T18:40:00.1+00:00", "2026-10-05"),
    # A naive stamp is read as UTC (the server's convention); an offset is honoured.
    ("2026-10-04T18:40:00", "2026-10-05"),
    ("2026-10-05T01:00:00+05:30", "2026-10-05"),
    ("2026-10-04T23:00:00-05:00", "2026-10-05"),
    # A bare date is that day.
    ("2026-10-05", "2026-10-05"),
])
def test_a_stored_timestamp_is_converted_to_its_indian_day(stamp, expected):
    assert R.created_on(stamp).isoformat() == expected


@pytest.mark.parametrize("junk", [None, "", "   ", "not a date", "2026-13-40", 12345, [], {}])
def test_a_stamp_that_cannot_be_read_is_none_and_never_today(junk):
    assert R.created_on(junk) is None


def test_a_schedule_created_just_after_indian_midnight_does_not_owe_that_days_slot():
    """00:10 IST on the 5th is 18:40 UTC on the 4th. A UTC-date reading puts the creation on the 4th and owes the 5th
    at once; the Indian day is the 5th, so the first slot is next month's. 23:50 IST on the 4th is the other side."""
    after = {"report_type": "trial_balance", "frequency": "monthly", "day_of_month": 5, "client_id": "c",
             "is_active": True, "created_at": "2026-10-04T18:40:00+00:00"}
    before = {**after, "created_at": "2026-10-04T18:20:00+00:00"}
    today = D("2026-10-05")
    assert R.plan_for(after, today=today).prepare is None
    assert R.plan_for(after, today=today).upcoming.due_on == D("2026-11-05")
    assert R.plan_for(before, today=today).prepare.due_on == D("2026-10-05")


# ═══ Which slot is prepared, and which are written down as missed ═════════════════════════════════════════════════

def _plan(recorded=(), since="2026-01-10", today="2026-10-06", frequency="monthly", day=5):
    return R.plan(frequency, day, since=D(since), today=D(today), recorded=recorded)


def test_only_the_latest_owed_slot_is_prepared_and_every_older_unrecorded_one_is_missed_oldest_first():
    p = _plan()
    assert p.prepare.period.key == "2026-09" and p.prepare.due_on == D("2026-10-05")
    assert [s.period.key for s in p.missed] == [f"2026-0{m}" for m in range(1, 9)]
    assert p.upcoming.due_on == D("2026-11-05")


def test_an_older_slot_with_a_run_recorded_is_not_missed():
    p = _plan(recorded={"2026-03", "2026-04"})
    assert "2026-03" not in {s.period.key for s in p.missed}
    assert "2026-04" not in {s.period.key for s in p.missed}
    assert p.prepare.period.key == "2026-09"
    assert len(p.missed) == 6


def test_when_the_latest_slot_is_already_handled_nothing_is_prepared_but_the_gap_still_shows():
    """Preparing an older slot after the newest was dealt with would mail last quarter's figures as new ones."""
    p = _plan(recorded={"2026-09"})
    assert p.prepare is None
    assert [s.period.key for s in p.missed] == [f"2026-0{m}" for m in range(1, 9)]


def test_nothing_owed_means_nothing_to_prepare_and_nothing_missed():
    p = _plan(since="2026-10-06", today="2026-10-06")
    assert (p.prepare, p.missed) == (None, ())
    assert p.upcoming.due_on == D("2026-11-05")


def test_a_second_sweep_with_the_run_recorded_prepares_nothing():
    first = _plan(since="2026-09-20", today="2026-10-05")
    assert first.prepare.period.key == "2026-09"
    second = _plan(since="2026-09-20", today="2026-10-05", recorded={first.prepare.period.key})
    assert (second.prepare, second.missed) == (None, ())


# ═══ A stored row, read in the safe direction ════════════════════════════════════════════════════════════════════

GOOD = {"report_type": "trial_balance", "frequency": "monthly", "day_of_month": 5, "client_id": "client-1",
        "is_active": True, "created_at": "2026-09-20T05:00:00+00:00"}


def test_a_good_row_is_planned():
    p = R.plan_for(GOOD, today=D("2026-10-05"))
    assert p.problem is None
    assert p.prepare.period.key == "2026-09"


@pytest.mark.parametrize("change, code", [
    ({"day_of_month": None}, "day_not_schedulable"),
    ({"day_of_month": 0}, "day_not_schedulable"),
    ({"day_of_month": 29}, "day_not_schedulable"),
    ({"day_of_month": 30}, "day_not_schedulable"),
    ({"day_of_month": 31}, "day_not_schedulable"),
    ({"day_of_month": -3}, "day_not_schedulable"),
    ({"day_of_month": True}, "day_not_schedulable"),
    ({"day_of_month": "5"}, "day_not_schedulable"),
    ({"day_of_month": 5.0}, "day_not_schedulable"),
    ({"is_active": None}, "inactive"),
    ({"is_active": False}, "inactive"),
    ({"is_active": "true"}, "inactive"),
    ({"client_id": None}, "no_client"),
    ({"client_id": ""}, "no_client"),
    ({"frequency": "weekly"}, "unknown_frequency"),
    ({"frequency": None}, "unknown_frequency"),
    ({"report_type": "mystery"}, "unknown_report"),
    ({"report_type": None}, "unknown_report"),
    ({"report_type": "gst_summary"}, "report_unavailable"),
    ({"report_type": "ledger"}, "report_not_schedulable"),
    ({"created_at": None}, "created_unknown"),
    ({"created_at": "garbage"}, "created_unknown"),
])
def test_a_row_nobody_can_interpret_is_blocked_with_its_own_reason_and_prepares_nothing(change, code):
    row = {**GOOD, **change}
    p = R.plan_for(row, today=D("2027-10-05"))
    assert p.problem is not None and p.problem.code == code, p.problem
    assert (p.prepare, p.missed, p.upcoming) == (None, (), None)
    assert p.problem.sentence and p.problem.sentence[-1] in ".?"


def test_a_row_missing_a_field_entirely_reads_the_same_as_a_null_one():
    for key in ("is_active", "client_id", "day_of_month", "frequency", "report_type", "created_at"):
        row = {k: v for k, v in GOOD.items() if k != key}
        assert R.plan_for(row, today=D("2027-10-05")).problem is not None, key


def test_every_problem_a_row_has_is_listed_and_the_create_door_does_not_ask_about_the_switch():
    row = {"report_type": "gst_summary", "frequency": "daily", "day_of_month": 31, "client_id": None,
           "is_active": None}
    codes = [p.code for p in R.schedule_problems(row)]
    assert codes == ["inactive", "no_client", "report_unavailable", "unknown_frequency", "day_not_schedulable"]
    assert [p.code for p in R.schedule_problems(row, check_active=False)] == codes[1:]
    assert R.schedule_problem(GOOD) is None
    assert R.schedule_problem({**GOOD, "is_active": None}, check_active=False) is None


def test_the_five_problems_that_block_a_row_are_five_different_sentences():
    sentences = {p.sentence for p in R.schedule_problems(
        {"report_type": "gst_summary", "frequency": "daily", "day_of_month": 31, "client_id": None,
         "is_active": None})}
    assert len(sentences) == 5


def test_the_low_level_functions_refuse_an_unusable_frequency_or_day_rather_than_defaulting_one():
    for bad_frequency, day in (("weekly", 5), (None, 5), ("monthly", 0), ("monthly", 31), ("monthly", None)):
        with pytest.raises(ValueError):
            R.slots_owed(bad_frequency, day, since=D("2026-01-01"), today=D("2026-12-31"))
        with pytest.raises(ValueError):
            R.next_slot(bad_frequency, day, since=D("2026-01-01"), today=D("2026-12-31"))
        with pytest.raises(ValueError):
            R.schedule_sentence(bad_frequency, day)


# ═══ The words ═══════════════════════════════════════════════════════════════════════════════════════════════════

def test_the_schedule_is_described_in_the_servers_words():
    assert R.schedule_sentence("monthly", 5) == "Every month on the 5th. Covers the previous calendar month."
    assert R.schedule_sentence("quarterly", 21) == (
        "Every quarter on the 21st of July, October, January and April. "
        "Covers the financial-year quarter that has just ended.")
    assert R.schedule_sentence("yearly", 22) == (
        "Every year on the 22nd of April. Covers the financial year that ended on 31 March.")


@pytest.mark.parametrize("day, written", [
    (1, "1st"), (2, "2nd"), (3, "3rd"), (4, "4th"), (10, "10th"), (11, "11th"), (12, "12th"), (13, "13th"),
    (14, "14th"), (20, "20th"), (21, "21st"), (22, "22nd"), (23, "23rd"), (24, "24th"), (28, "28th"),
])
def test_the_day_is_written_as_an_ordinal(day, written):
    assert f"on the {written}." in R.schedule_sentence("monthly", day)


def test_a_slot_is_described_by_what_the_report_shows():
    slot = R.slots_owed("monthly", 5, since=D("2026-09-20"), today=D("2026-10-05"))[0]
    assert R.slot_sentence("cash_flow", slot) == "Due 5 Oct 2026. Covers 1 Sep 2026 to 30 Sep 2026 (September 2026)."
    # A trial balance is the position at the END of the period, rebuilt from what was recorded up to it.
    assert R.slot_sentence("trial_balance", slot) == (
        "Due 5 Oct 2026. Shows the position as at 30 Sep 2026, the end of September 2026.")
    # An ageing lists what is open on the day it is PREPARED: the period only names the run, and the sentence does
    # not say the report looks back to it (the books cannot say what a document owed on an earlier day).
    for live in ("ar_ageing", "ap_ageing"):
        assert R.slot_sentence(live, slot) == (
            "Due 5 Oct 2026. Lists the documents open on the day it is prepared, aged from that day. It does not "
            "look back to 30 Sep 2026, the end of September 2026; that only says which due date this report is for.")
        assert R.slot_sentence(live, slot, prepared_on=D("2026-10-07")) == (
            "Due 5 Oct 2026. Lists the documents open on 7 Oct 2026, the day it was prepared, aged from that day. "
            "It does not look back to 30 Sep 2026, the end of September 2026; that only says which due date this "
            "report is for.")


def test_a_position_is_claimed_only_for_a_kind_whose_shape_says_it_is_one():
    """The rule behind the table above: 'the position as at' appears in a sentence exactly when the kind's shape is
    AS_AT, and a LIVE kind's sentence never states a date as the one its figures are of."""
    slot = R.slots_owed("monthly", 5, since=D("2026-09-20"), today=D("2026-10-05"))[0]
    for kind in (k for k in R.REPORT_KINDS if k.available):
        sentence = R.slot_sentence(kind.id, slot)
        assert ("position as at" in sentence) == (kind.shape == R.AS_AT), kind.id
        assert ("Lists the documents open" in sentence) == (kind.shape == R.LIVE), kind.id
        assert ("Covers" in sentence) == (kind.shape == R.PERIOD), kind.id


def test_a_prepared_day_that_is_an_instant_and_not_a_day_is_not_named():
    """A datetime is an instant whose calendar day depends on the zone it is read in; only a bare IST date is named."""
    from datetime import datetime, timezone
    slot = R.slots_owed("monthly", 5, since=D("2026-09-20"), today=D("2026-10-05"))[0]
    sentence = R.slot_sentence("ar_ageing", slot, prepared_on=datetime(2026, 10, 7, 20, 0, tzinfo=timezone.utc))
    assert "the day it is prepared," in sentence and "7 Oct" not in sentence and "8 Oct" not in sentence


def test_a_missed_slot_is_written_down_with_the_date_it_fell_due_and_the_period():
    slot = R.slots_owed("monthly", 5, since=D("2026-08-20"), today=D("2026-09-05"))[0]
    sentence = R.missed_sentence(slot)
    assert "5 Sep 2026" in sentence and "August 2026" in sentence and sentence.startswith("Not prepared")


def test_the_screen_is_told_in_words_that_a_person_presses_send():
    assert "presses Send" in R.HOW_IT_WORKS and "Nothing is mailed by itself" in R.HOW_IT_WORKS
    assert "automatic" not in R.HOW_IT_WORKS.lower().replace("by itself", "")


# ═══ The module reads no clock and touches no I/O ═══════════════════════════════════════════════════════════════

CLOCKS = {"ist_today", "ist_now", "today", "now", "utcnow", "time", "monotonic", "perf_counter"}
IMPURE_ROOTS = ("services", "routers", "repositories", "jobs", "supabase", "httpx", "requests", "postgrest",
                "resend", "smtplib", "os", "subprocess", "socket", "pathlib", "logging")


def _tree():
    return ast.parse(MODULE.read_text(encoding="utf-8"))


def test_the_module_never_reads_the_clock_it_is_handed_the_day():
    called = {(n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", ""))
              for n in ast.walk(_tree()) if isinstance(n, ast.Call)}
    assert not called & CLOCKS, f"report_schedule calls the clock: {sorted(called & CLOCKS)}"


def test_the_module_imports_no_database_mail_or_other_io():
    roots = set()
    for node in ast.walk(_tree()):
        if isinstance(node, ast.Import):
            roots |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            roots.add((node.module or "").split(".")[0])
    assert not roots & set(IMPURE_ROOTS), sorted(roots & set(IMPURE_ROOTS))
    assert {"core", "datetime", "dataclasses"} <= roots   # the scan sees the imports it is meant to


def test_the_clock_guard_would_catch_a_clock_read():
    """The negative control for the guard above: the same scan over a module that does read the clock."""
    bad = ast.parse("from core.ist_clock import ist_today\ndef f():\n    return ist_today()\n")
    called = {n.func.id for n in ast.walk(bad) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert called & CLOCKS


# ═══ The same rules for any date at all (Hypothesis) ═════════════════════════════════════════════════════════════

DATES = st.dates(min_value=date(2000, 1, 1), max_value=date(2100, 12, 31))
FREQUENCIES = st.sampled_from(R.FREQUENCIES)
DAYS = st.integers(min_value=R.MIN_DAY, max_value=R.MAX_DAY)
SPAN = timedelta(days=1500)


@st.composite
def a_schedule(draw):
    """A frequency, a day, the day the schedule began and a today not far after it (so the owed list is bounded)."""
    frequency, day = draw(FREQUENCIES), draw(DAYS)
    since = draw(DATES)
    today = since + timedelta(days=draw(st.integers(min_value=-40, max_value=SPAN.days)))
    return frequency, day, since, today


@kernel()
@given(s=a_schedule())
def test_every_owed_slot_is_after_the_day_it_began_and_on_or_before_today_on_the_chosen_day(s):
    frequency, day, since, today = s
    owed = R.slots_owed(frequency, day, since=since, today=today)
    for slot in owed:
        assert since < slot.due_on <= today
        assert slot.due_on.day == day                      # 1 to 28 exists in every month: never clamped
        assert slot.period.end < slot.due_on               # a report covers a period that has ENDED
        assert (slot.due_on.year, slot.due_on.month) == (
            (slot.period.end.year + (slot.period.end.month == 12)), slot.period.end.month % 12 + 1)
    assert [x.due_on for x in owed] == sorted({x.due_on for x in owed})


@kernel()
@given(s=a_schedule())
def test_consecutive_slots_tile_the_calendar_with_no_gap_and_no_overlap(s):
    frequency, day, since, today = s
    owed = R.slots_owed(frequency, day, since=since, today=today)
    for earlier, later in zip(owed, owed[1:], strict=False):
        assert later.period.start == earlier.period.end + timedelta(days=1)
    for slot in owed:
        assert slot.period.start <= slot.period.end


@kernel()
@given(s=a_schedule())
def test_no_period_key_repeats_for_one_schedule(s):
    frequency, day, since, today = s
    keys = [x.period.key for x in R.slots_owed(frequency, day, since=since, today=today)]
    assert len(keys) == len(set(keys))


@kernel()
@given(s=a_schedule())
def test_the_first_slot_is_the_first_due_date_strictly_after_the_day_it_began(s):
    frequency, day, since, today = s
    owed = R.slots_owed(frequency, day, since=since, today=since + SPAN)
    assume(owed)
    first = R.next_slot(frequency, day, since=since, today=since)
    assert owed[0] == first and first.due_on > since
    # and nothing strictly after `since` falls before it
    assert all(x.due_on >= first.due_on for x in owed)


@kernel()
@given(s=a_schedule())
def test_the_next_slot_is_the_first_after_both_today_and_the_day_it_began(s):
    frequency, day, since, today = s
    nxt = R.next_slot(frequency, day, since=since, today=today)
    assert nxt.due_on > max(since, today)
    # Everything owed up to the next slot, except the slot itself, is what is owed today.
    owed_to_next = R.slots_owed(frequency, day, since=since, today=nxt.due_on)
    assert owed_to_next[-1] == nxt
    assert owed_to_next[:-1] == R.slots_owed(frequency, day, since=since, today=today)


@kernel()
@given(s=a_schedule(), data=st.data())
def test_a_plan_prepares_only_the_latest_owed_slot_and_misses_the_rest(s, data):
    frequency, day, since, today = s
    owed = R.slots_owed(frequency, day, since=since, today=today)
    keys = [x.period.key for x in owed]
    recorded = set(data.draw(st.lists(st.sampled_from(keys), unique=True))) if keys else set()
    p = R.plan(frequency, day, since=since, today=today, recorded=recorded)
    if not owed:
        assert (p.prepare, p.missed) == (None, ())
    else:
        latest = owed[-1]
        assert p.prepare == (None if latest.period.key in recorded else latest)
        assert list(p.missed) == [x for x in owed[:-1] if x.period.key not in recorded]
    handled = ({p.prepare.period.key} if p.prepare else set()) | {x.period.key for x in p.missed}
    assert not handled & recorded                       # nothing already recorded is prepared or missed again
    assert handled <= set(keys)                          # and nothing outside what is owed
    assert p.upcoming.due_on > max(since, today)


@kernel()
@given(s=a_schedule())
def test_a_frequency_covers_exactly_its_own_periods(s):
    frequency, day, since, today = s
    for slot in R.slots_owed(frequency, day, since=since, today=today):
        p = slot.period
        if frequency == "monthly":
            assert p.start.day == 1 and (p.end + timedelta(days=1)).day == 1 and p.start.month == p.end.month
        elif frequency == "quarterly":
            assert (p.start.isoformat(), p.end.isoformat()) in {
                (a, b) for fy in (R._fy_label(y) for y in range(p.start.year - 1, p.start.year + 1))
                for _, a, b in fy_quarters(fy)}
        else:
            assert (p.start.month, p.start.day, p.end.month, p.end.day) == (4, 1, 3, 31)
            assert p.end.year == p.start.year + 1


def test_the_three_key_shapes_never_collide_so_a_schedule_that_changes_frequency_keeps_its_history():
    """A month is 'YYYY-MM', a quarter 'YYYY-YY-Qn' and a year 'YYYY-YY'. The first and third could only be confused
    when a financial year's second half is a month number (FY 2000-01 is also 'January 2000'), which happens only
    for years starting 2000 to 2011 and 2100 to 2111: before GST and a century away. The run table is unique per
    schedule and key, so the range is not load-bearing, and it is stated rather than hidden."""
    years_range = range(2012, 2100)
    monthly = {R._month_period(y, m).key for y in years_range for m in range(1, 13)}
    years = {R._year_period(R._fy_label(y)).key for y in years_range}
    quarters = {p.key for y in years_range for p in R._quarter_periods(R._fy_label(y))}
    assert not (monthly & years) and not (monthly & quarters) and not (years & quarters)
    assert len(monthly) == 88 * 12 and len(quarters) == 88 * 4
    # and the boundary the comment names is real, so the claim is not vacuous
    assert R._year_period("2000-01").key == R._month_period(2000, 1).key
