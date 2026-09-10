"""
Migration 361 — both period-lock SQL functions must equal their Python twins.

WHY THERE ARE TWO OF THEM AT ALL
    `period_lock_reason` is a SQL function, and mock mode and the in-memory
    test sources have no SQL functions. CLAUDE.md's rule for a rule that has to
    exist in SQL is: MOVE it, and where a Python one must survive for mock mode
    and local dev, pin the two with a parity test that runs every scenario
    through both. `period_lock_service.reason_from_tables` is that Python one,
    and this file is that test. Adding the second implementation WITHOUT this
    file is the thing CLAUDE.md names as not to be done.

    It matters more here than for a report, because this function is what
    REFUSES a posting. If the twin says "open" where the SQL says "closed", the
    difference is a journal entry inside a filed period — and it appears only in
    the environment nobody runs the tests in.

WHAT IS COMPARED
    The whole answer, not a summary: the SQL returns a SENTENCE, and the
    sentence is what a CA is shown, so the two must produce it character for
    character. That is deliberately strict — it catches a reworded branch, a
    date formatted differently ('DD Mon YYYY' vs %d %b %Y), and an FY label
    computed differently (lpad((y+1) % 100) vs str(y+1)[2:]), each of which is
    a real divergence a boolean comparison would hide.

WHAT EACH SCENARIO ALSO ASSERTS
    Parity alone is satisfied by two implementations that are wrong in the same
    way, so every scenario also carries what it EXPECTS — the branch that must
    fire. The three-branch precedence (firm year, then client year-end, then
    filed return) is the point of migration 361 and is asserted directly.

BOTH ENTRY POINTS, BECAUSE THE SPLIT IS THE DESIGN
    Migration 361 has two functions, not one: `period_closure_reason` answers
    the two DELIBERATE closures — the firm's locked year and this client's
    finalised year-end — and `period_lock_reason` calls it and adds the filed
    return. The posting KERNEL asks the first and only the first, because a
    filed GSTR-1 freezes the supplies it reported rather than the whole ledger,
    and refusing every June posting from 11 July would stop routine
    bookkeeping. So every scenario runs through FOUR implementations — two SQL,
    two Python — and each carries both expected answers.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from services import period_lock_service

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="SQL/Python parity proof requires HARNESS_PG + psql",
)

FIRM = "f3610000-0000-0000-0000-000000000001"
CLIENT = "c3610000-0000-0000-0000-000000000001"
OTHER_CLIENT = "c3610000-0000-0000-0000-000000000002"


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql],
                          capture_output=True, text=True)


def _scalar(dsn: str, sql: str) -> str | None:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    out = r.stdout.rstrip("\n")
    # -tA prints an SQL NULL as the empty string, and this function's "open"
    # answer IS NULL. Nothing it returns is ever empty-but-not-null.
    return out or None


@pytest.fixture()
def dsn(pg_template):
    admin = _ADMIN.strip()
    name = f"e361_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    d = f"{admin} dbname={name}"
    try:
        seed = _psql(d, f"""
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F', 'f@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type)
            VALUES ('{CLIENT}', '{FIRM}', 'C', 'Proprietorship'),
                   ('{OTHER_CLIENT}', '{FIRM}', 'D', 'Proprietorship');
        """)
        assert seed.returncode == 0, seed.stderr
        yield d
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


# ── The scenarios ────────────────────────────────────────────────────────────
#
# Each is (name, firm_locked_fys, client_year_locks, filings, date, expect).
#   client_year_locks : [(client_id, financial_year)]
#   filings           : [(client_id, filing_type, start, end, filed_date, deleted)]
#   expect            : None for open, else the exact sentence period_lock_reason
#                       and reason_from_tables must return.
#
# What `period_closure_reason` must return is DERIVED rather than declared —
# `_closure_expected` below — because the relationship is the design: the two
# functions differ in exactly one branch, so a scenario whose only reason is a
# filed return is open to the closure question and closed to the lock question,
# and every other scenario answers identically on both. Declaring it a second
# time would let the two drift in the table itself.
#
# The expected sentences are written out in full rather than matched loosely,
# because the sentence is the product: it names the remedy, and a CA sent to
# the portal to amend a return when all they had to do was reopen a year has
# been told the wrong thing by software that was technically correct.

_FIRM_LOCK = ("Financial year 2026-27 is locked. Unlock it, or post a reversal "
              "in an open year.")
_CLIENT_LOCK = ("FY 2026-27 is closed for this client — its year-end has been "
                "finalised. Reopen the year before posting to it.")
_FILED = ("GSTR-1 covering this date was filed on 11 Jul 2026. Correct it with "
          "a reversal and an amendment in the next return.")

SCENARIOS = [
    ("nothing is locked", [], [], [], "2026-06-15", None),

    # ── Branch 1: the firm's own switch ──────────────────────────────────────
    ("the firm locked the year", ["2026-27"], [], [], "2026-06-15", _FIRM_LOCK),
    ("a different year is locked", ["2025-26"], [], [], "2026-06-15", None),
    ("1 April is the first day of the locked year", ["2026-27"], [], [],
     "2026-04-01", _FIRM_LOCK),
    ("31 March is the last day of the locked year", ["2026-27"], [], [],
     "2027-03-31", _FIRM_LOCK),
    ("1 April the following year is outside it", ["2026-27"], [], [],
     "2027-04-01", None),
    ("31 March the same calendar year is the year before", ["2026-27"], [], [],
     "2026-03-31", None),

    # ── Branch 2: this client's finalised year (what 361 adds) ───────────────
    ("this client's year-end is finalised", [], [(CLIENT, "2026-27")], [],
     "2026-06-15", _CLIENT_LOCK),
    ("another client's year-end is not this client's", [],
     [(OTHER_CLIENT, "2026-27")], [], "2026-06-15", None),
    ("a different year finalised for this client", [], [(CLIENT, "2025-26")], [],
     "2026-06-15", None),

    # ── Branch 3: a filed return ─────────────────────────────────────────────
    ("a filed GSTR-1 covers the date", [], [],
     [(CLIENT, "GSTR-1", "2026-06-01", "2026-06-30", "2026-07-11", False)],
     "2026-06-15", _FILED),
    ("the first day of the filed period is covered", [], [],
     [(CLIENT, "GSTR-1", "2026-06-01", "2026-06-30", "2026-07-11", False)],
     "2026-06-01", _FILED),
    ("the last day of the filed period is covered", [], [],
     [(CLIENT, "GSTR-1", "2026-06-01", "2026-06-30", "2026-07-11", False)],
     "2026-06-30", _FILED),
    ("the day before the filed period is not", [], [],
     [(CLIENT, "GSTR-1", "2026-06-01", "2026-06-30", "2026-07-11", False)],
     "2026-05-31", None),
    ("a return prepared but NOT filed locks nothing", [], [],
     [(CLIENT, "GSTR-1", "2026-06-01", "2026-06-30", None, False)],
     "2026-06-15", None),
    ("a deleted filing locks nothing", [], [],
     [(CLIENT, "GSTR-1", "2026-06-01", "2026-06-30", "2026-07-11", True)],
     "2026-06-15", None),
    ("another client's filing locks nothing", [], [],
     [(OTHER_CLIENT, "GSTR-1", "2026-06-01", "2026-06-30", "2026-07-11", False)],
     "2026-06-15", None),
    ("two filings cover it — the EARLIER filed date is named", [], [],
     [(CLIENT, "GSTR-3B", "2026-06-01", "2026-06-30", "2026-07-20", False),
      (CLIENT, "GSTR-1", "2026-06-01", "2026-06-30", "2026-07-11", False)],
     "2026-06-15", _FILED),

    # ── The precedence, which is the order of the REMEDIES ───────────────────
    ("firm lock outranks the client's year-end", ["2026-27"],
     [(CLIENT, "2026-27")], [], "2026-06-15", _FIRM_LOCK),
    ("firm lock outranks a filed return", ["2026-27"], [],
     [(CLIENT, "GSTR-1", "2026-06-01", "2026-06-30", "2026-07-11", False)],
     "2026-06-15", _FIRM_LOCK),
    ("the client's year-end outranks a filed return", [], [(CLIENT, "2026-27")],
     [(CLIENT, "GSTR-1", "2026-06-01", "2026-06-30", "2026-07-11", False)],
     "2026-06-15", _CLIENT_LOCK),
    ("all three at once still names the most reopenable", ["2026-27"],
     [(CLIENT, "2026-27")],
     [(CLIENT, "GSTR-1", "2026-06-01", "2026-06-30", "2026-07-11", False)],
     "2026-06-15", _FIRM_LOCK),

    # ── The FY label, computed two different ways ────────────────────────────
    # SQL: lpad(((y + 1) % 100)::text, 2, '0');  Python: str(y + 1)[2:].
    # They agree everywhere, and the century rollover is where a reader doubts
    # it — 2099-00, not 2099-100 and not 2099-0.
    ("the century rollover produces the same label", ["2099-00"], [], [],
     "2099-06-15",
     "Financial year 2099-00 is locked. Unlock it, or post a reversal in an open year."),
    ("a single-digit year end is zero padded", ["2005-06"], [], [],
     "2005-06-15",
     "Financial year 2005-06 is locked. Unlock it, or post a reversal in an open year."),

    # ── A date whose filed_date needs the month abbreviated ──────────────────
    # to_char(..., 'DD Mon YYYY') against strftime("%d %b %Y"): both must give
    # "05 Sep 2026", zero-padded day and three-letter month.
    ("the filed date is formatted identically", [], [],
     [(CLIENT, "GSTR-3B", "2026-08-01", "2026-08-31", "2026-09-05", False)],
     "2026-08-20",
     "GSTR-3B covering this date was filed on 05 Sep 2026. Correct it with a "
     "reversal and an amendment in the next return."),
]


# ── The Python side's source ─────────────────────────────────────────────────

class _Q:
    def __init__(self, rows):
        self._rows = rows
        self._eq: list[tuple[str, object]] = []
        self._limit = None

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self._eq.append((col, val))
        return self

    def limit(self, n):
        self._limit = n
        return self

    def execute(self):
        rows = [r for r in self._rows if all(r.get(c) == v for c, v in self._eq)]
        if self._limit is not None:
            rows = rows[: self._limit]
        return type("R", (), {"data": rows})()


class _Src:
    """The in-memory shape `reason_from_tables` is written against — no .rpc,
    because having one is what routes a caller to the SQL instead."""

    def __init__(self, tables):
        self._t = tables

    def table(self, name):
        return _Q(self._t.get(name, []))


def _python_source(locked_fys, client_locks, filings) -> _Src:
    return _Src({
        "firms": [{"id": FIRM, "locked_financial_years": list(locked_fys)}],
        "client_year_locks": [
            {"id": str(uuid.uuid4()), "firm_id": FIRM, "client_id": cid,
             "financial_year": fy}
            for cid, fy in client_locks
        ],
        "filings": [
            {"filing_type": ft, "filed_date": filed, "period_start": ps,
             "period_end": pe, "deleted_at": "2026-01-01T00:00:00Z" if deleted else None,
             "client_id": cid}
            for cid, ft, ps, pe, filed, deleted in filings
        ],
    })


def _seed_sql(dsn_: str, locked_fys, client_locks, filings) -> None:
    arr = ("ARRAY[" + ", ".join(f"'{fy}'" for fy in locked_fys) + "]::text[]"
           if locked_fys else "'{}'::text[]")
    stmts = [
        "DELETE FROM client_year_locks;",
        "DELETE FROM filings;",
        f"UPDATE firms SET locked_financial_years = {arr} WHERE id = '{FIRM}';",
    ]
    for cid, fy in client_locks:
        stmts.append("INSERT INTO client_year_locks (firm_id, client_id, financial_year) "
                     f"VALUES ('{FIRM}', '{cid}', '{fy}');")
    for cid, ft, ps, pe, filed, deleted in filings:
        stmts.append(
            "INSERT INTO filings (client_id, filing_type, period_start, period_end, "
            "filed_date, deleted_at) VALUES "
            f"('{cid}', '{ft}', '{ps}', '{pe}', "
            f"{'NULL' if filed is None else chr(39) + filed + chr(39)}, "
            f"{'NOW()' if deleted else 'NULL'});")
    r = _psql(dsn_, "\n".join(stmts))
    assert r.returncode == 0, r.stderr


def _closure_expected(expect):
    """A filed return is not a closure. Everything else answers the same."""
    return None if (expect and "was filed on" in expect) else expect


@pytest.mark.parametrize(
    "name,locked_fys,client_locks,filings,date,expect",
    SCENARIOS, ids=[s[0] for s in SCENARIOS],
)
def test_the_sql_and_the_twin_give_the_same_answer(
        dsn, name, locked_fys, client_locks, filings, date, expect):
    _seed_sql(dsn, locked_fys, client_locks, filings)
    src = _python_source(locked_fys, client_locks, filings)

    from_sql = _scalar(
        dsn, f"SELECT public.period_lock_reason('{FIRM}'::uuid, '{CLIENT}'::uuid, '{date}'::date)")
    from_python = period_lock_service.reason_from_tables(src, FIRM, CLIENT, date)

    assert from_sql == expect, f"the SQL function is wrong for: {name}"
    assert from_python == expect, f"the Python twin is wrong for: {name}"
    assert from_sql == from_python


@pytest.mark.parametrize(
    "name,locked_fys,client_locks,filings,date,expect",
    SCENARIOS, ids=[s[0] for s in SCENARIOS],
)
def test_the_closure_question_agrees_too_and_ignores_a_filed_return(
        dsn, name, locked_fys, client_locks, filings, date, expect):
    """The function the posting KERNEL asks, over the same scenarios.

    Two claims at once: the SQL and the twin agree, and neither treats a filed
    return as a closure. The second is what keeps June's receipts postable on
    15 July after GSTR-1 went on the 11th — and the reason it is asserted here,
    scenario by scenario, rather than once: a branch added to the wrong function
    would pass a single spot-check and fail the calendar."""
    _seed_sql(dsn, locked_fys, client_locks, filings)
    src = _python_source(locked_fys, client_locks, filings)
    expected = _closure_expected(expect)

    from_sql = _scalar(
        dsn, f"SELECT public.period_closure_reason('{FIRM}'::uuid, '{CLIENT}'::uuid, '{date}'::date)")
    from_python = period_lock_service._closure_from_tables(src, FIRM, CLIENT, date)

    assert from_sql == expected, f"the SQL closure function is wrong for: {name}"
    assert from_python == expected, f"the Python closure twin is wrong for: {name}"
    assert from_sql == from_python


def test_the_lock_is_the_closure_plus_the_filed_return_and_nothing_else(dsn):
    """Stated as a relationship rather than as two tables of numbers.

    Wherever a closure applies, `period_lock_reason` returns exactly what
    `period_closure_reason` returns — the SAME sentence, not a similar one —
    because 361 has the second CALL the first rather than restate it."""
    for name, locked_fys, client_locks, filings, date, expect in SCENARIOS:
        closure = _closure_expected(expect)
        if closure is None:
            continue
        _seed_sql(dsn, locked_fys, client_locks, filings)
        lock = _scalar(dsn, f"SELECT public.period_lock_reason('{FIRM}'::uuid, '{CLIENT}'::uuid, '{date}'::date)")
        clos = _scalar(dsn, f"SELECT public.period_closure_reason('{FIRM}'::uuid, '{CLIENT}'::uuid, '{date}'::date)")
        assert lock == clos == closure, f"the two diverged on: {name}"


def test_an_unreadable_date_is_the_same_nothing_on_both_sides(dsn):
    """NULL in, NULL out — the function is asked about a date and given none.

    This is NOT the kernel's behaviour for an unparseable date: `_create_journal`
    refuses it outright (ACC-27), because a date the lock cannot read is a date
    the lock cannot be checked against. That refusal lives above this function;
    what this pins is that both halves agree there is nothing here to answer.
    """
    _seed_sql(dsn, ["2026-27"], [], [])
    assert _scalar(dsn, f"SELECT public.period_lock_reason('{FIRM}'::uuid, '{CLIENT}'::uuid, NULL)") is None
    assert period_lock_service.reason_from_tables(_python_source(["2026-27"], [], []),
                                                  FIRM, CLIENT, None) is None
    assert period_lock_service.reason_from_tables(_python_source(["2026-27"], [], []),
                                                  FIRM, CLIENT, "not-a-date") is None


def test_the_wrapper_short_circuits_on_a_missing_client_and_the_sql_does_not(dsn):
    """A DELIBERATE difference, recorded so it is not read as drift.

    `period_lock_reason(firm, NULL, date)` still answers the FIRM's own year
    lock — the branch does not need a client. `lock_reason` returns None before
    calling anything when the client_id is missing, because a caller without one
    is a draft or a bulk path that has no client to check, and the firm's year
    is separately enforced by `period_validation_service.validate_posting_date`
    on every one of those paths.

    The parity claim is about the RULE — `reason_from_tables` against the SQL —
    not about the wrapper's argument handling, and this test is what says so.
    """
    _seed_sql(dsn, ["2026-27"], [], [])
    assert _scalar(dsn, f"SELECT public.period_lock_reason('{FIRM}'::uuid, NULL, '2026-06-15'::date)") == _FIRM_LOCK
    assert period_lock_service.lock_reason(
        _python_source(["2026-27"], [], []), FIRM, None, "2026-06-15") is None


def test_a_source_that_cannot_be_read_is_not_a_source_saying_open():
    """Fail-closed, on the twin as well as the SQL path.

    The twin reads three tables. If any read raises, the answer is UNVERIFIABLE
    — not None. This is the property that makes the mock-mode branch safe to
    take at all: `lock_reason` routes to the twin on the ABSENCE of `.rpc`, and
    a source that has `.rpc` and raises still fails closed.
    """
    class _Broken:
        def table(self, _name):
            raise RuntimeError("connection reset")

    assert period_lock_service.reason_from_tables(
        _Broken(), FIRM, CLIENT, "2026-06-15") == period_lock_service.UNVERIFIABLE
    assert period_lock_service._closure_from_tables(
        _Broken(), FIRM, CLIENT, "2026-06-15") == period_lock_service.UNVERIFIABLE


def test_the_cache_never_remembers_a_closed_period(dsn):
    """The bulk-import memo caches the OPEN answer only.

    A CSV import asks this question once per row; the memo turns 2,000
    Singapore-to-Mumbai round trips into one per distinct (client, date). It
    must never make a refusal cheaper to forget: nothing is stored for a period
    that turned out to be closed, so every row in it is refused through a real
    read, and UNVERIFIABLE — a failure to ask, not an answer — is never stored
    at all.
    """
    open_src = _python_source([], [], [])
    closed_src = _python_source(["2026-27"], [], [])

    cache: dict = {}
    assert period_lock_service.lock_reason(open_src, FIRM, CLIENT, "2026-06-15", cache) is None
    assert cache, "an open period should be remembered"

    closure_cache: dict = {}
    assert period_lock_service.closure_reason(open_src, FIRM, CLIENT, "2026-06-15", closure_cache) is None
    assert closure_cache, "the closure question caches on the same terms"

    closed_cache: dict = {}
    assert period_lock_service.lock_reason(closed_src, FIRM, CLIENT, "2026-06-15", closed_cache) == _FIRM_LOCK
    assert closed_cache == {}, "a closed period must never be remembered"

    class _Broken:
        def table(self, _name):
            raise RuntimeError("connection reset")

    broken_cache: dict = {}
    assert period_lock_service.lock_reason(
        _Broken(), FIRM, CLIENT, "2026-06-15", broken_cache) == period_lock_service.UNVERIFIABLE
    assert broken_cache == {}, "an unverifiable answer must never be remembered"
