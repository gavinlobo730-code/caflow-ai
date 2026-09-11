"""D1 — the MCA annual deadlines come from each company's own AGM date.

WHAT WAS WRONG

apps/web/app/calendar/page.tsx built fourteen deadlines in the browser, and the
MCA ones were wrong twice over:

  * it assumed an AGM on 30 SEPTEMBER FOR EVERY CLIENT; and
  * it then counted the offsets inclusively, so AOC-4 showed 29 October where
    Companies Act s.137 gives 30, and MGT-7 showed 28 November where s.92
    gives 29.

A day early is merely wrong. The invented AGM is the serious one: it is wrong
for every company whose meeting was not on 30 September, and a CA reading a
firm-wide calendar had no way to tell a computed row from an assumed one.

mca_companies.last_agm_date has held the real date since migration 038 — whose
own comment reads "AGM date drives AOC-4/MGT-7 deadline". The browser copy never
read it.

THE REFUSAL THAT MATTERS

A company with no AGM date recorded is NAMED, not defaulted. 30 September is a
plausible guess, and a plausible guess on a statutory deadline is how a filing
is missed.
"""
from __future__ import annotations

from datetime import date

import pytest

from services.compliance_engine import MCA_AGM_OFFSET_DAYS, mca_due_date


# ── the arithmetic the browser got wrong ─────────────────────────────────────

@pytest.mark.parametrize("form,expected", [
    ("ADT-1", date(2026, 10, 15)),   # s.139, AGM + 15
    ("AOC-4", date(2026, 10, 30)),   # s.137, AGM + 30 — the browser said 29 Oct
    ("MGT-7", date(2026, 11, 29)),   # s.92,  AGM + 60 — the browser said 28 Nov
])
def test_an_agm_on_30_september_gives_these_dates(form, expected):
    assert mca_due_date(date(2026, 9, 30), form) == expected


@pytest.mark.parametrize("form,wrong", [("AOC-4", date(2026, 10, 29)),
                                        ("MGT-7", date(2026, 11, 28))])
def test_the_offset_is_not_counted_inclusively(form, wrong):
    """The browser counted the AGM day itself, landing a day early on both."""
    assert mca_due_date(date(2026, 9, 30), form) != wrong


def test_the_offsets_are_the_ones_the_act_gives():
    assert MCA_AGM_OFFSET_DAYS == {"ADT-1": 15, "AOC-4": 30, "MGT-7": 60}


# ── and it moves with the AGM, which is the whole point ──────────────────────

@pytest.mark.parametrize("agm,aoc4", [
    (date(2026, 9, 30), date(2026, 10, 30)),
    (date(2026, 8, 14), date(2026, 9, 13)),    # an earlier AGM
    (date(2026, 12, 31), date(2027, 1, 30)),   # extended, and across a year end
    (date(2028, 2, 28), date(2028, 3, 29)),    # a leap year February
])
def test_aoc4_follows_the_company_s_own_agm(agm, aoc4):
    assert mca_due_date(agm, "AOC-4") == aoc4


def test_a_month_end_agm_does_not_land_on_a_month_end():
    """Day arithmetic, not month arithmetic — s.137 says thirty DAYS.

    31 October + 30 days is 30 November, not 30 November because November is
    short. Pinned because "AGM month end + 1 month" is the plausible wrong rule.
    """
    assert mca_due_date(date(2026, 10, 31), "AOC-4") == date(2026, 11, 30)
    assert mca_due_date(date(2026, 1, 31), "AOC-4") == date(2026, 3, 2)


# ── the endpoint's contract ──────────────────────────────────────────────────

def test_the_firmwide_endpoint_names_a_company_with_no_agm_rather_than_defaulting():
    """The refusal, asserted on the handler's source.

    It short-circuits without a database in mock mode, and the failure worth
    guarding is somebody later replacing the gap with a sensible-looking
    default — which is precisely the bug this replaced.
    """
    import inspect

    from routers import mca_workspace

    src = inspect.getsource(mca_workspace.mca_calendar_firmwide)
    assert "without_agm_date" in src
    assert "30 September" not in src.split('"""')[2], (
        "no default AGM may appear in the body — a plausible guess on a "
        "statutory deadline is how a filing is missed")


def test_the_firmwide_endpoint_is_scoped_to_the_caller_s_clients():
    import inspect

    from routers import mca_workspace

    src = inspect.getsource(mca_workspace.mca_calendar_firmwide)
    assert "effective_client_ids" in src, '"all clients" is right only for a Partner'
    assert "if not allowed:" in src, (
        "an EMPTY set means no clients, never no filter")
