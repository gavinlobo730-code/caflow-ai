"""POST-A-280 (the health readers) — the client health score and its factors count a late obligation by the ONE rule, not by the date alone.

WHAT WAS WRONG
    `domain/practice/compliance_overdue` is the rule (not settled, and either moved to "Overdue" by hand or due strictly before the CA's day), and
    every other backend reader asks it. Two readers in `routers/health.py` still asked the database for `due_date < today`: the compliance-health
    dimension and the factor list behind it. They differ from the rule only for an obligation somebody moved to "Overdue" with a date ahead or none,
    which the rest of the product counts as late and these scored as nothing.

WHAT THIS PINS
    SCORE    -25 for each unsettled obligation the rule calls late: by its date, and by a hand-set "Overdue" with a date ahead;
             nothing for one due today, a settled one, or one that was soft-deleted (a GST frequency
             change retires the stale monthly rows that way, and every list-based reader leaves them out);
    FACTORS  the same obligations, five at most, each named, and dated only when it has a date;
    NOT THE ITR OVER SIX MONTHS  that override is "more than six months past its date" and a hand-set word cannot say how long, so it stays on the date.
"""
from __future__ import annotations

import inspect
from datetime import date

import pytest

import routers.health as health
from tests.e2e_harness import FakeDB

FIRM, CLIENT = "FIRM-H", "CLI-H"
TODAY = date(2026, 10, 20)


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setattr(health, "ist_today", lambda: TODAY)
    return FakeDB()


def _rec(db, status, due, label=None, deleted_at=None):
    db.seed("compliance_records", {"firm_id": FIRM, "client_id": CLIENT, "status": status, "due_date": due, "compliance_type": "GSTR-3B",
                                   "period_label": label, "deleted_at": deleted_at})


def _score(db) -> int:
    return health._dim_compliance_health_db(db, CLIENT, FIRM)


def _labels(db) -> list[str]:
    return [f["label"] for f in health._dimension_detail_db(db, CLIENT, FIRM, "compliance_health")]


def test_the_score_deducts_for_each_late_obligation_by_the_one_rule(db):
    _rec(db, "Not Started", "2026-10-19")        # late by its date
    _rec(db, "Overdue", "2026-12-31")            # moved to Overdue by hand, date ahead
    _rec(db, "Overdue", "2027-03-31")            # moved to Overdue by hand, a different date ahead
    assert _score(db) == 100 - 3 * 25


def test_nothing_is_deducted_for_what_is_not_late(db):
    _rec(db, "Not Started", "2026-10-20")        # due today: not late until the day is out
    _rec(db, "In Progress", "2026-12-31")        # open, not late
    _rec(db, "Ready To File", "2026-11-30")
    _rec(db, "Filed", "2026-01-01")              # settled, however old
    _rec(db, "Completed", "2026-01-01")
    assert _score(db) == 100


def test_a_soft_deleted_obligation_costs_nothing_and_is_not_named(db):
    _rec(db, "Not Started", "2026-09-01", "Retired monthly row", deleted_at="2026-10-01T00:00:00+00:00")
    _rec(db, "Not Started", "2026-09-02", "Live late row")
    assert _score(db) == 75
    assert _labels(db) == ["Live late row overdue since 2026-09-02"]


def test_another_clients_late_obligation_costs_this_client_nothing(db):
    db.seed("compliance_records", {"firm_id": FIRM, "client_id": "OTHER", "status": "Overdue", "due_date": "2026-12-31", "compliance_type": "GSTR-3B"})
    _rec(db, "Not Started", "2026-10-19")
    assert _score(db) == 75


def test_the_factor_list_names_the_same_obligations_five_at_most(db):
    for n in range(4):
        _rec(db, "Not Started", f"2026-09-0{n + 1}", f"Late {n}")
    _rec(db, "Overdue", "2026-12-31", "Hand-set ahead")
    _rec(db, "Overdue", "2027-03-31", "Hand-set later")
    _rec(db, "Not Started", "2026-10-20", "Due today")
    named = [x for x in _labels(db) if "overdue" in x]
    assert len(named) == 5, named
    assert not any("Due today" in x for x in named)


def test_the_factor_list_holds_every_late_obligation_when_there_are_few(db):
    _rec(db, "Not Started", "2026-10-01", "Late")
    _rec(db, "Overdue", "2026-12-31", "Hand-set ahead")
    _rec(db, "Overdue", "2027-03-31", "Hand-set later")
    _rec(db, "Not Started", "2026-10-20", "Due today")
    assert sorted(_labels(db)) == sorted(["Late overdue since 2026-10-01", "Hand-set ahead overdue since 2026-12-31",
                                          "Hand-set later overdue since 2027-03-31"])


def test_the_itr_override_keeps_asking_the_date_because_six_months_is_a_length(db):
    src = inspect.getsource(health._detect_hard_override_db)
    assert 'six_months_ago' in src and '.lt("due_date", six_months_ago)' in src


def test_neither_reader_filters_on_the_date_in_the_query():
    for fn in (health._dim_compliance_health_db, health._dimension_detail_db):
        src = inspect.getsource(fn)
        compliance = src.split('"compliance_records"')[1].split("government_notices")[0].split("tasks")[0]
        assert "overdue_records(" in src, fn.__name__
        assert '.lt("due_date"' not in compliance, f"{fn.__name__} filters on the date again"
