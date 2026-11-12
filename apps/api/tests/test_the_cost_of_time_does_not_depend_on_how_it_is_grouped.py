"""The cost of time, and the minutes it is made of, do not depend on how the entries are grouped (POST-B-321).

`domain/practice/profitability.fold_effort` prices each ENTRY at its member's cost rate, floored once per entry, so the
client view, the engagement view and the member view of the same entries add to the same total, and no minute is lost
or counted twice between "priced" and "unpriced". A rule that priced a GROUP (the floor of a sum) would fail this.

It is its own module, importing `tests/_property.py` before Hypothesis, for that helper's rule: where `CI` is set a
missing Hypothesis is an ERROR and not a silent skip, and a skip here must not take the rule's example tests with it.
"""
from __future__ import annotations

from tests._property import kernel  # noqa: I001  (first: it skips or fails by the CI rule)

from hypothesis import given, strategies as st

from domain.practice import profitability as rule

_USERS = ["u1", "u2", "u3", None]
_entries = st.lists(st.fixed_dictionaries({
    "user_id": st.sampled_from(_USERS),
    "client_id": st.sampled_from(["A", "B", None]),
    "engagement_id": st.sampled_from(["e1", "e2", None]),
    "duration_minutes": st.one_of(st.none(), st.integers(0, 2_000)),
    "is_billable": st.booleans(),
}), max_size=40)
_rates = st.fixed_dictionaries({"u1": st.one_of(st.none(), st.integers(0, 10 ** 7)),
                                "u2": st.one_of(st.none(), st.integers(0, 10 ** 7))})


@kernel()
@given(entries=_entries, raw=_rates)
def test_the_cost_and_the_minutes_are_the_same_however_the_entries_are_grouped(entries, raw):
    """Floored once per ENTRY, so the client view, the engagement view and the member view of the same entries add to the
    same total, and no minute is lost or counted twice between 'priced' and 'unpriced'."""
    rates = rule.clean_cost_rates(raw)
    totals_by = []
    for key in ("client_id", "engagement_id", "user_id"):
        groups = rule.fold_effort(entries, rates, key).values()
        totals_by.append((sum(g.cost_paise for g in groups), sum(g.minutes for g in groups),
                          sum(g.unrated_minutes for g in groups)))
    assert totals_by[0] == totals_by[1] == totals_by[2]
    assert totals_by[0][1] == sum((e["duration_minutes"] or 0) for e in entries)
    assert totals_by[0][2] <= totals_by[0][1]
    # and the figure itself is the sum of each entry's own FLOOR, worked out here from the entries and nothing of the rule's
    expected = sum(((e["duration_minutes"] or 0) * rates[e["user_id"]]) // 60
                   for e in entries if rates.get(e["user_id"]) is not None)
    assert totals_by[0][0] == expected
