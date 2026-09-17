"""
Two functions named `fy_quarters`, and only one of them decides.

WHAT WAS WRONG
    `core.ist_clock.fy_quarters` derives the four windows of an Indian
    financial year from `fy_bounds`, and its own docstring says why:

        Derived from `fy_bounds` rather than restating April, so a change to
        what a financial year IS cannot leave the quarters describing the old
        one.

    `services.compliance_obligation_service.fy_quarters` — same name, different
    module — restated them as literals: `(start, 4, start, 6)` and three more.
    Both happened to agree, which is exactly what makes this the dangerous
    shape rather than a harmless one: nothing would have failed on the day they
    stopped agreeing, and the second one is what decides which GSTR-1 and
    GSTR-3B deadlines a QRMP client sees in their compliance calendar.

    This repository already records the trap under a different pair —
    `parseQuantity` against `quantityFromInput` — as *"two functions with one
    name in one directory is how the wrong one gets called."* Here they are in
    two directories, which is worse, because a grep for the name finds both and
    neither says it is the copy.

    Found while verifying GST-11's return-period work, which reads the
    `ist_clock` one and was careful to add no third.

THE RULE, NOT A SPELLING OF IT
    The guard below does NOT assert that the service's source contains a
    particular call — a spelling, which breaks on a refactor that does not
    break the rule, and which this file's history shows being fixed four times
    over. It asserts the PROPERTY: for every financial year it is asked about,
    the two functions describe the same twelve months in the same order. A
    literal table reintroduced anywhere fails the moment it disagrees, and
    agrees harmlessly until then — which is the honest limit of what a test can
    say here, and is why the derivation itself is the real fix.

WHY THE DUPLICATE IS NOT DELETED
    The two answer in different SHAPES on purpose. `_gst_obligations` wants
    year and month NUMBERS, to hand to `compliance_engine`'s due-date
    functions; `ist_clock` answers in ISO dates because its other callers
    window a report with them. One definition of WHICH months a quarter is,
    two presentations of it, is the right end state — not one function
    contorted to serve both.
"""
from __future__ import annotations

import pytest

from core.ist_clock import fy_quarters as clock_quarters
from services.compliance_obligation_service import fy_quarters as gst_quarters

# Years either side of the ones in live use, so a table pinned to "this year"
# fails rather than passing by coincidence.
YEARS = ["2017-18", "2019-20", "2023-24", "2024-25", "2025-26", "2026-27", "2030-31"]


@pytest.mark.parametrize("fy", YEARS)
def test_both_describe_the_same_four_quarters(fy):
    """The property. Not "the service calls the clock" — that is a spelling."""
    from_clock = [
        (int(s[:4]), int(s[5:7]), int(e[:4]), int(e[5:7]))
        for _label, s, e in clock_quarters(fy)
    ]
    assert gst_quarters(fy) == from_clock


@pytest.mark.parametrize("fy", YEARS)
def test_the_quarters_are_april_to_march_and_cover_every_month(fy):
    """An Indian FY runs 1 April to 31 March, so Q1 opens in April, Q4 closes
    in March of the NEXT calendar year, and the twelve months are contiguous
    with no gap and no overlap. Asserted on the service's own output, because
    that is the one a client's deadlines are built from."""
    qs = gst_quarters(fy)
    assert len(qs) == 4
    assert qs[0][1] == 4, "Q1 opens in April"
    assert qs[-1][3] == 3, "Q4 closes in March"
    assert qs[-1][2] == qs[0][0] + 1, "Q4 is in the following calendar year"

    months = []
    for sy, sm, ey, em in qs:
        y, m = sy, sm
        while (y, m) <= (ey, em):
            months.append((y, m))
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    assert len(months) == 12, "twelve months"
    assert len(set(months)) == 12, "no month counted twice"
    for earlier, later in zip(months, months[1:]):
        step = (later[0] - earlier[0]) * 12 + (later[1] - earlier[1])
        assert step == 1, f"a gap between {earlier} and {later}"


def test_a_leap_february_does_not_move_q4():
    """Q4 ends in March whatever February did. Stated because the quarters are
    month-aligned by construction and a day-counting rewrite would not be."""
    assert gst_quarters("2023-24")[-1] == (2024, 1, 2024, 3)   # 2024 is a leap year
    assert gst_quarters("2024-25")[-1] == (2025, 1, 2025, 3)


def test_the_service_answers_in_month_numbers_and_the_clock_in_dates():
    """The shapes are deliberately different — that is why both exist. If this
    ever fails, one of them has been contorted to serve the other's callers and
    the duplicate should be deleted instead."""
    assert all(isinstance(x, int) for q in gst_quarters("2025-26") for x in q)
    assert all(isinstance(x, str) for q in clock_quarters("2025-26") for x in q)
