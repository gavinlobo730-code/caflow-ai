"""
"All clients" means all clients THIS CALLER may read (ACC-17).

WHAT WAS WRONG
    Every reporting endpoint in routers/accounting.py treats `client_id=None` as
    "all clients", and for a Partner that is right: `_FIRMWIDE_ROLES` is
    `{Role.PARTNER}` (core/authz.py), so a Partner sees the whole practice by
    definition. For anyone else it was not. "accounting" read is
    `_AT_LEAST_EXECUTIVE`, so an Executive or a Manager assigned to three
    clients who omitted `client_id` received the consolidated trial balance,
    profit and loss, balance sheet, Schedule III and cash flow of EVERY client
    in the firm — turnover, salaries, loans, bank balances.

    It did not even need a hand-made request: `/accounting/schedule-iii` offers
    "All Clients" as an ordinary control and sends no `client_id` when it is
    chosen. The exposure is intra-firm only — `firm_id` was always applied —
    which is why this is a medium and not a tenancy breach.

    The router said so about itself: "Recorded, not fixed."

WHERE THE FIX LIVES, AND WHY THERE
    On the LEDGER SOURCE, which is built once per request from the caller's own
    scope, rather than threaded through the nine report methods. A source that
    holds the scope cannot be asked an unscoped question, and a fetch added
    later inherits the rule; the alternative makes forgetting it possible, which
    is how this became a finding in the first place.

WHAT THIS FILE ASSERTS
    The RULE, in three directions: the source narrows, the factory hands the
    scope over, and no reporting route builds an engine without one. Not a list
    of the seven endpoints — a list would pass the day an eighth is added.
"""
from __future__ import annotations

import ast
import inspect
import pathlib

import pytest

from domain.reporting import InMemoryLedgerSource
from domain.reporting.model import Account, JournalEntry, JournalLine

API = pathlib.Path(__file__).resolve().parent.parent

FIRM = "F1"
MINE_A, MINE_B, THEIRS = "C-mine-a", "C-mine-b", "C-theirs"


def _entry(eid: str, client_id: str, amount: int) -> JournalEntry:
    return JournalEntry(
        id=eid, entry_date="2026-06-15", client_id=client_id, firm_id=FIRM,
        entry_type="Journal",
        lines=[JournalLine("a1", amount, 0), JournalLine("a2", 0, amount)],
    )


ACCOUNTS = [
    Account(id="a1", code="1100", name="Trade Receivables", type="Asset", subtype="Receivable"),
    Account(id="a2", code="4000", name="Sales", type="Revenue", subtype="Sales"),
]
ENTRIES = [_entry("e1", MINE_A, 100), _entry("e2", MINE_B, 200), _entry("e3", THEIRS, 400)]


def _source(allowed):
    return InMemoryLedgerSource(accounts=ACCOUNTS, entries=ENTRIES,
                                allowed_client_ids=allowed)


# ── the source narrows ───────────────────────────────────────────────────────

def test_no_client_named_and_no_scope_is_the_whole_firm():
    """A Partner. `effective_client_ids` returns None for a firm-wide role, and
    None must keep meaning "no restriction" — otherwise this fix would take the
    consolidated view away from the one role entitled to it."""
    snap = _source(None).snapshot(FIRM, None, None, None)
    assert {e.id for e in snap.entries_in_range} == {"e1", "e2", "e3"}


def test_no_client_named_with_a_scope_is_that_scope():
    """The finding. An Executive assigned to two clients asks for "All Clients"
    and gets two, not three."""
    snap = _source({MINE_A, MINE_B}).snapshot(FIRM, None, None, None)
    assert {e.id for e in snap.entries_in_range} == {"e1", "e2"}


def test_a_named_client_is_unaffected_by_the_scope():
    """`assert_client_access` has already established the caller may read it, so
    naming a client answers about that client. The scope narrows the ABSENCE of
    a name, not a name."""
    snap = _source({MINE_A, MINE_B}).snapshot(FIRM, MINE_A, None, None)
    assert {e.id for e in snap.entries_in_range} == {"e1"}


def test_a_caller_assigned_nothing_sees_nothing():
    """An empty set is an answer, not a missing filter. Reading it as "no
    restriction" is the exact inversion this fix removes."""
    snap = _source(set()).snapshot(FIRM, None, None, None)
    assert snap.entries_in_range == []


def test_another_firm_is_still_out_of_reach():
    """The scope narrows WITHIN a firm; it does not replace the firm filter."""
    snap = _source(None).snapshot("F2", None, None, None)
    assert snap.entries_in_range == []


# ── the Supabase source narrows the same way ─────────────────────────────────

class _Q:
    def __init__(self, log):
        self.log = log

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self.log.append(("eq", col, val))
        return self

    def in_(self, col, vals):
        self.log.append(("in", col, tuple(vals)))
        return self


def test_the_supabase_source_filters_on_the_assigned_set():
    from domain.reporting.sources import SupabaseLedgerSource
    log: list = []
    src = SupabaseLedgerSource(db=None, allowed_client_ids={MINE_B, MINE_A})
    src._scope(_Q(log), None)
    assert log == [("in", "client_id", (MINE_A, MINE_B))], (
        "with no client named, the read must be confined to the assigned set"
    )


def test_the_supabase_source_leaves_an_unscoped_read_alone():
    from domain.reporting.sources import SupabaseLedgerSource
    log: list = []
    SupabaseLedgerSource(db=None, allowed_client_ids=None)._scope(_Q(log), None)
    assert log == [], "a firm-wide role must still get the whole firm"


def test_the_supabase_source_prefers_a_named_client():
    from domain.reporting.sources import SupabaseLedgerSource
    log: list = []
    SupabaseLedgerSource(db=None, allowed_client_ids={MINE_A})._scope(_Q(log), MINE_A)
    assert log == [("eq", "client_id", MINE_A)]


def test_an_empty_assigned_set_is_an_empty_filter_not_no_filter():
    from domain.reporting.sources import SupabaseLedgerSource
    log: list = []
    SupabaseLedgerSource(db=None, allowed_client_ids=set())._scope(_Q(log), None)
    assert log == [("in", "client_id", ())], (
        "an empty set must filter to nothing — treating it as unrestricted is "
        "the inversion the fix exists to remove"
    )


# ── the router hands the scope over, on every route ──────────────────────────

def _accounting_router_tree() -> ast.Module:
    return ast.parse((API / "routers" / "accounting.py").read_text())


def _is_route(fn: ast.AST) -> bool:
    return isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
        isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
        and isinstance(d.func.value, ast.Name) and d.func.value.id == "router"
        for d in fn.decorator_list
    )


def test_every_route_that_builds_a_reporting_engine_gives_it_the_caller():
    """The rule, not a list of the seven endpoints — a list passes the day an
    eighth is added. Any ROUTE that calls `_reporting_service` must pass the
    caller, because that is the only thing that carries the scope."""
    offenders = []
    for fn in ast.walk(_accounting_router_tree()):
        if not _is_route(fn):
            continue
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "_reporting_service"):
                named = [a.id for a in node.args if isinstance(a, ast.Name)]
                if "current_user" not in named:
                    offenders.append(fn.name)
    assert not offenders, (
        "these routes build a reporting engine with no caller, so an omitted "
        "client_id reads the whole firm:\n  " + "\n  ".join(sorted(set(offenders)))
    )


def test_the_factory_asks_authz_for_the_scope_rather_than_deciding_it():
    """One definition of "which clients may this user read", in core.authz.
    A second answer here would drift from `/journals` and `/ledger-span`, which
    is the inconsistency ACC-17 records."""
    from routers import accounting
    src = inspect.getsource(accounting._reporting_service)
    assert "effective_client_ids(current_user)" in src


def test_the_source_is_given_the_scope_on_both_paths():
    """Supabase and mock alike. The mock one enforces nothing in practice —
    `effective_client_ids` returns None without a database — but a shape that
    differs between the two is where the next divergence starts."""
    from routers import accounting
    src = inspect.getsource(accounting._reporting_service)
    assert "SupabaseLedgerSource(get_supabase(), allowed)" in src
    assert "mock_ledger_source(allowed)" in src


def test_the_router_no_longer_says_it_is_unfixed():
    """The comment in get_ledger was the finding's own evidence."""
    from routers import accounting
    assert "Recorded, not fixed" not in inspect.getsource(accounting.get_ledger)
