"""A recurring task is generated once per INDIAN day, not once per UTC day.

── THE DEFECT ───────────────────────────────────────────────────────────────
`recurring_task_service._is_already_generated_today` compared two dates in different
zones:

    last_gen_date = datetime.fromisoformat(last_generated...).date()   # UTC
    today = ist_today()                                                # IST
    return last_gen_date == today

`last_generated_at` is a `timestamptz`, so it comes back from PostgREST in UTC
and `.date()` is the UTC calendar date. `ist_today()` is the Indian one. From
**18:30 to 24:00 UTC** — which is **00:00 to 05:30 IST the next day** — those
are different days, so the check answered "not generated today" about a config
generated minutes earlier and the sweep generated the task A SECOND TIME.

A duplicate recurring task is not cosmetic: these are the firm's compliance
obligations. Two "Monthly GST Filing" tasks for one month is two assignees, two
reminders, and a filing that looks outstanding after it has been done.

── WHY THIS TEST EXISTS BESIDE THE ONE THAT ALREADY FAILED ─────────────────
`test_recurring_tasks.py::test_idempotency_skips_if_generated_today` builds its
stamp with `datetime.now(timezone.utc)` and its date with `date.today()`, so it
reproduces the bug ONLY when the suite happens to run inside that 5½-hour
window. It was green in CI at 23:21 UTC and red at 23:35 UTC on the same commit
— a test that finds a real defect one sixth of the time reports "no defect" the
other five.

This one FREEZES both sides, so it fails on the old code at any hour.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest

from services import recurring_task_service as svc

# 23:35 UTC on 23 September is 05:05 IST on the 24th. The stamp's UTC date and
# its Indian date are different days, which is the whole defect.
STAMP_UTC = datetime(2026, 9, 23, 23, 35, tzinfo=timezone.utc)
IST_DAY = date(2026, 9, 24)


@pytest.mark.parametrize(
    "stamp",
    [
        STAMP_UTC.isoformat(),                                # +00:00
        STAMP_UTC.isoformat().replace("+00:00", "Z"),         # Z, as Postgres emits
        STAMP_UTC.replace(tzinfo=None).isoformat(),           # naive, read as UTC
    ],
)
def test_a_stamp_from_late_utc_counts_as_todays_indian_day(stamp: str):
    with patch.object(svc, "ist_today", return_value=IST_DAY):
        assert svc._is_already_generated_today({"last_generated_at": stamp}) is True, (
            "a task generated at 05:05 IST was reported as NOT generated today, "
            "so the sweep would generate it again on the same Indian day"
        )


def test_a_stamp_from_the_previous_indian_day_still_counts_as_yesterday():
    """The fix must not make the check answer True for everything.

    22:00 UTC on the 22nd is 03:30 IST on the 23rd — a different Indian day from
    the 24th — so this has to stay False. Without it the test above passes on a
    `return True`, which is the shape a guard has to rule out about itself.
    """
    stamp = datetime(2026, 9, 22, 22, 0, tzinfo=timezone.utc).isoformat()
    with patch.object(svc, "ist_today", return_value=IST_DAY):
        assert svc._is_already_generated_today({"last_generated_at": stamp}) is False


def test_a_stamp_inside_the_same_utc_day_is_unaffected():
    """The ordinary case, which is most of the day and must not move.

    07:00 UTC on the 24th is 12:30 IST on the 24th: both zones agree, and this
    passed before the fix as well. Pinned so a later change cannot buy the edge
    case by breaking the common one.
    """
    stamp = datetime(2026, 9, 24, 7, 0, tzinfo=timezone.utc).isoformat()
    with patch.object(svc, "ist_today", return_value=IST_DAY):
        assert svc._is_already_generated_today({"last_generated_at": stamp}) is True


def test_no_stamp_is_not_generated_today():
    assert svc._is_already_generated_today({}) is False
    assert svc._is_already_generated_today({"last_generated_at": None}) is False


def test_an_unparseable_stamp_does_not_crash_the_sweep():
    """It answers False — generate again — rather than raising.

    That is the pre-existing behaviour and it is the safe direction here: the
    sweep runs unattended over every firm, and one unreadable row must not stop
    every other firm's tasks being generated. A duplicate is visible and
    fixable; a sweep that died silently at row 40 is neither.
    """
    assert svc._is_already_generated_today({"last_generated_at": "not a timestamp"}) is False
