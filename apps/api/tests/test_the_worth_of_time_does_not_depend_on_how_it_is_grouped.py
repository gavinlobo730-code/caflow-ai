"""The worth of billable time, and the minutes it is made of, do not depend on how the entries are grouped (POST-A-426).

`domain/practice/realization.fold_worth` prices each ENTRY from its own rate, floored once per entry, so the engagement view,
the client view and the member view of the same entries add to the same total, and no minute is lost or counted twice between
"priced" and "unpriced". A rule that priced a GROUP (the floor of a sum) would fail this. And the worth a screen shows is the
one `time_rate.entry_group` gives the same entry on the unbilled-work screen: they are one reading of what an hour is worth.

It is its own module, importing `tests/_property.py` before Hypothesis, for that helper's rule: where `CI` is set a missing
Hypothesis is an ERROR and not a silent skip, and a skip here must not take the rule's example tests with it.
"""
from __future__ import annotations

from tests._property import kernel  # noqa: I001  (first: it skips or fails by the CI rule)

from hypothesis import given, strategies as st

from domain.billing import time_rate
from domain.practice import realization as rule

_rate = st.one_of(st.none(), st.integers(0, 10 ** 7))
_entries = st.lists(st.fixed_dictionaries({
    "client_id": st.sampled_from(["A", "B", None]),
    "engagement_id": st.sampled_from(["e1", "e2", None]),
    "duration_minutes": st.one_of(st.none(), st.integers(0, 2_000)),
    "is_billable": st.booleans(),
    "billable_rate_paise": _rate,
    "hourly_rate_paise": _rate,
}), max_size=40)


def _expected_value(e: dict) -> int:
    rate = time_rate.entry_rate(e)
    return ((e["duration_minutes"] or 0) * rate) // 60 if rate is not None else 0


@kernel()
@given(entries=_entries)
def test_the_worth_and_the_minutes_are_the_same_however_the_entries_are_grouped(entries):
    totals_by = []
    for key in ("engagement_id", "client_id"):
        groups = rule.fold_worth(entries, key).values()
        totals_by.append((sum(g.value_paise for g in groups), sum(g.billable_minutes for g in groups),
                          sum(g.unpriced_minutes for g in groups)))
    assert totals_by[0] == totals_by[1]
    billable = [e for e in entries if e["is_billable"] and (e["duration_minutes"] or 0) > 0]
    assert totals_by[0][1] == sum(e["duration_minutes"] for e in billable)
    assert totals_by[0][2] <= totals_by[0][1]
    # the figure itself is the sum of each entry's own FLOOR, worked out here from the entries and nothing of the rule's
    assert totals_by[0][0] == sum(_expected_value(e) for e in billable if time_rate.entry_rate(e) is not None)
    assert totals_by[0][2] == sum(e["duration_minutes"] for e in billable if time_rate.entry_rate(e) is None)


@kernel()
@given(entries=_entries)
def test_adding_the_groups_gives_the_firm_and_a_known_worth_is_one_with_nothing_unpriced(entries):
    groups = rule.fold_worth(entries, "engagement_id")
    firm = rule.firm({}, groups)
    inside = [w for k, w in groups.items() if k is not None]
    assert firm.worth.billable_minutes == sum(w.billable_minutes for w in inside)
    assert firm.worth.value_paise == sum(w.value_paise for w in inside)
    assert firm.worth.value_is_known == (firm.worth.billable_minutes > 0 and all(w.unpriced_minutes == 0 for w in inside))


@kernel()
@given(entries=_entries, revenue=st.integers(0, 10 ** 9))
def test_a_realization_is_given_only_where_every_billable_minute_is_priced(entries, revenue):
    for worth in rule.fold_worth(entries, "engagement_id").values():
        rate = rule.realization_rate(revenue, worth)
        if worth.unpriced_minutes > 0 or worth.value_paise <= 0:
            assert rate is None
        else:
            assert rate == round(revenue / worth.value_paise, 2)


@kernel()
@given(entries=_entries)
def test_realization_and_the_unbilled_work_screen_price_the_same_hour_the_same(entries):
    """One function says what an hour is worth: an unbilled entry's value on its screen is the worth realization gives it."""
    for e in entries:
        grouped = time_rate.entry_group({**e, "task_id": None, "billed_invoice_id": None})
        worth = rule.fold_worth([e], "engagement_id")
        if grouped is None:
            assert not worth or sum(w.billable_minutes for w in worth.values()) == 0
            continue
        total = sum(w.value_paise for w in worth.values())
        assert total == grouped["value_paise"]
        assert sum(w.unpriced_minutes for w in worth.values()) == (0 if grouped["priced"] else grouped["minutes"])
