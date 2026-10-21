"""The engagement-letter number is ONE sequence for the firm and is read with every letter in view (migration 529).

WHAT WAS WRONG
    `_next_engagement_no` takes the newest letter of the firm and adds one, and the table has a unique index on
    (firm_id, engagement_number). It read as the CALLER. While the database let a Manager read every letter of the firm that
    was right; once `engagements` carries the assignment scope (migration 529) the newest letter a Manager can see is the
    newest of THEIR clients' letters, the next number is one another client's letter already holds, the insert fails on the
    index (a 422 carrying the raw database text), and it fails again on every retry because the Manager's own latest never
    passes the hidden numbers. Found by the independent read of every reader of `engagements` before the scope was written:
    with letters 0001 (the Manager's client), 0002 (a lead's) and 0003 (another Manager's client, the newest), the Manager's
    next number was 0004 before the scope and 0003 after it.

WHAT THIS HOLDS
    * the number is read with the privileged client when there is one, so it sees every letter, and falls back to the
      caller's own client only where there is no other (mock mode, a test double);
    * the create route asks for the number through that function and never passes the caller's client straight in, so the
      next author cannot put the caller's client back without this failing;
    * the arithmetic itself is unchanged: the newest letter's last group plus one, in the year of today.

Runs in the mock-mode job: no database is needed.
"""
from __future__ import annotations

import ast
import inspect

import routers.engagement_letters as el


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def execute(self):
        class _R:
            pass
        r = _R()
        r.data = self._rows
        return r


class _Db:
    """Answers `table("engagements")...execute()` with the letters it was given, newest first."""

    def __init__(self, numbers):
        self._numbers = numbers

    def table(self, name):
        assert name == "engagements"
        return _Rows([{"engagement_number": n} for n in self._numbers[:1]])


def test_the_number_is_read_with_the_privileged_client_when_there_is_one(monkeypatch):
    visible_to_the_caller = _Db(["EL-2026-0002"])
    every_letter = _Db(["EL-2026-0003", "EL-2026-0002", "EL-2026-0001"])
    monkeypatch.setattr(el.db_provider, "service_db_or_none", lambda: every_letter)
    assert el._numbering_db(visible_to_the_caller) is every_letter
    year = el.ist_today().year
    assert el._next_engagement_no(el._numbering_db(visible_to_the_caller), "f1") == f"EL-{year}-0004", (
        "the next number must follow the newest letter of the FIRM, not the newest the caller can see")


def test_the_callers_own_client_is_the_fallback_where_there_is_no_other(monkeypatch):
    mine = _Db(["EL-2026-0007"])
    monkeypatch.setattr(el.db_provider, "service_db_or_none", lambda: None)
    assert el._numbering_db(mine) is mine
    assert el._next_engagement_no(el._numbering_db(mine), "f1") == f"EL-{el.ist_today().year}-0008"


def test_mock_mode_has_no_client_to_read_with(monkeypatch):
    monkeypatch.setattr(el.db_provider, "service_db_or_none", lambda: _Db(["EL-2026-0009"]))
    assert el._numbering_db(None) is None, "mock mode must stay on the in-memory sequence, not reach for a database"


def test_the_create_route_asks_for_the_number_through_that_function():
    """Written as a rule over the route's source rather than a call to it: the route needs a lead, a template, a client and
    a database to run, and what must not come back is the one-word edit that hands the caller's client straight in."""
    tree = ast.parse(inspect.getsource(el.create_engagement))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "_next_engagement_no"]
    assert len(calls) == 1, "create_engagement should ask for the number exactly once"
    first = calls[0].args[0]
    assert isinstance(first, ast.Call) and isinstance(first.func, ast.Name) and first.func.id == "_numbering_db", (
        "the number must be read with _numbering_db(db), not with the caller's own client: the caller sees only the "
        "letters of the clients they are assigned to, and the sequence is the firm's")


def test_no_other_caller_of_the_allocator_hands_it_the_callers_client():
    """The allocator has one production caller today. A second one must read the same way."""
    source = inspect.getsource(el)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_next_engagement_no"):
            arg = node.args[0]
            assert isinstance(arg, ast.Call) and getattr(arg.func, "id", "") == "_numbering_db", ast.dump(arg)
