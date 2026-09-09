"""
Every INSERT the backend writes must supply every column the table REQUIRES.

WHAT THIS CATCHES THAT NOTHING ELSE DID
    tests/test_backend_columns_exist_pg.py checks the columns a write NAMES.
    Its own docstring says what it does not check: "a NOT NULL column a write
    forgot". That is the other half of the same failure, and it is worse,
    because the first half fails loudly at PostgREST parse time while this half
    fails at INSERT time — inside a `try: … except Exception` that turns it
    into an HTTP 200 carrying {success: false} which the caller does not read.

    It had shipped. routers/tds_workspace.py::create_return never supplied
    tds_returns.quarter_end (DATE NOT NULL, no default, migration 037), so
    "Prepare a Return" could not create a return on any real database — while
    every mock-mode test passed, because a dict store has no NOT NULL. That is
    the shape: the test suite is structurally blind to this class, so the check
    has to be against a real schema.

WHY THE PARSER HAD TO FOLLOW A VARIABLE
    The dominant idiom in apps/api is

        record = {...}
        if condition:
            record["extra"] = x
        db.table("t").insert(record).execute()

    A scanner that reads only `insert({...})` written inline cannot see any of
    those — including create_return, the very site this exists for. So
    _backend_query_parser.insert_payloads follows exactly one step: a name
    bound to a dict literal once in its own function, plus `name["key"] = …`
    additions in that same function. Anything less certain is counted as
    unreadable rather than guessed at, because a payload read WRONGLY would
    report a column missing that is in fact supplied — a false alarm is how a
    ratchet gets deleted.

WHAT IS DELIBERATELY NOT CHECKED
    * UPDATE. A partial update is the normal thing; "this update omits a
      required column" is not a defect. INSERT and UPSERT both create a row
      when none matches, so both must satisfy NOT NULL.
    * A column with ANY default, an identity column, or a generated column —
      the database supplies those, which is what a default is for.
    * A table the local template does not have. The CI template is built with
      --continue-on-error, so the migrations on test_migrations_apply.py's
      baseline never run and their tables are absent locally while present in
      production. Reporting those would call one bug two; missing TABLES are
      test_backend_tables_exist's job.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode CI job.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _backend_query_parser import insert_payloads  # noqa: E402

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="required-column check requires HARNESS_PG + psql",
)

# Inserts that omit a required column and are RIGHT to. Empty, and that is the
# finding: every site the check flagged on its first run was a real defect.
#
# A legitimate entry would be a column a BEFORE INSERT trigger fills — the
# database supplies it, but pg_attribute cannot say so. Spell out which trigger,
# so the entry can be re-checked when that trigger changes.
ALLOWED: dict[str, str] = {}

# Payloads insert_payloads could not read: built by a comprehension, spread from
# a **kwargs dict, or passed in as a parameter. Budgeted so the blind spot has a
# number on it and cannot quietly grow — it may shrink freely, and raising it is
# a deliberate act visible in a diff.
UNREADABLE_BUDGET = 125


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-tA",
                           "-F", "\t", "-c", sql], capture_output=True, text=True)


@pytest.fixture(scope="module")
def schema(pg_template):
    """(required columns per table, every table) read off the real schema.

    Required means NOT NULL with NO default of any kind — not an identity
    column, not a generated one. Those three are exactly the cases where the
    database fills the value in and an omitting INSERT still succeeds.
    """
    admin = _ADMIN.strip()
    name = f"reqcol_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        r = _psql(dsn, """
            SELECT c.relname, a.attname
              FROM pg_attribute a
              JOIN pg_class c ON c.oid = a.attrelid
              JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'public' AND c.relkind = 'r'
               AND a.attnum > 0 AND NOT a.attisdropped
               AND a.attnotnull AND NOT a.atthasdef
               AND a.attidentity = '' AND a.attgenerated = '';
        """)
        assert r.returncode == 0, r.stderr
        required: dict[str, set[str]] = {}
        for line in r.stdout.strip().splitlines():
            if not line.strip():
                continue
            table, col = line.split("\t")
            required.setdefault(table, set()).add(col)

        t = _psql(dsn, "SELECT c.relname FROM pg_class c JOIN pg_namespace n "
                       "ON n.oid = c.relnamespace WHERE n.nspname='public' "
                       "AND c.relkind='r';")
        assert t.returncode == 0, t.stderr
        tables = {ln.strip() for ln in t.stdout.splitlines() if ln.strip()}
        assert tables, "no tables in the template — the fixture is broken"
        yield required, tables
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _offenders(schema):
    required, tables = schema
    found, _ = insert_payloads(API_ROOT)
    out = []
    for path, lineno, relation, keys in found:
        if relation not in tables:
            continue                      # test_backend_tables_exist's job
        for col in sorted(required.get(relation, set()) - keys):
            if f"{relation}.{col}" in ALLOWED:
                continue
            out.append((path, lineno, relation, col))
    return out


def test_no_insert_omits_a_column_the_table_requires(schema):
    offenders = _offenders(schema)
    assert not offenders, (
        "these INSERTs omit a NOT NULL column that has no default, so they "
        "raise against the real database and — where the call sits in a broad "
        "except — return an HTTP 200 saying success: false:\n  "
        + "\n  ".join(f"{p}:{ln}  {rel}.{col}" for p, ln, rel, col in offenders)
        + "\n\nSupply the column, give it a DEFAULT in a migration, or add it "
          "to ALLOWED naming the trigger that fills it."
    )


def test_the_check_can_actually_see_a_payload_built_in_a_variable(schema):
    """The scanner's own blind spot, pinned.

    An earlier draft read only `insert({...})` written inline at the call site.
    Against this codebase that reads almost nothing — and specifically not
    routers/tds_workspace.py::create_return, the site this whole file exists
    for, whose payload is a `record` variable. A version of this check that
    cannot follow one assignment passes on the bug it was written to catch.
    """
    found, _ = insert_payloads(API_ROOT)
    by_site = {(p, rel): keys for p, _ln, rel, keys in found}
    ret = by_site.get(("routers/tds_workspace.py", "tds_returns"))
    assert ret is not None, (
        "create_return's payload is no longer readable — if it moved, re-point "
        "this test at another variable-built insert rather than deleting it")
    # Two keys that prove the two halves of the follow, and NEITHER is the
    # column the fix added — a pin on quarter_end here would just restate the
    # test above and would fail for the wrong reason if the fix regressed.
    assert "due_date" in ret, (
        "the dict literal bound to `record` was not read — the scanner is "
        "matching something else")
    assert "fvu_json" in ret, (
        "`record[\"fvu_json\"] = …` was not read. A payload amended after it "
        "is bound is the normal shape here, and a scanner that stops at the "
        "literal under-reads every one of them — which reports columns as "
        "missing that are supplied.")


def test_unreadable_payloads_stay_within_budget():
    """A parser that silently stops matching keeps passing while checking
    nothing. The count is the alarm."""
    _found, unreadable = insert_payloads(API_ROOT)
    assert unreadable <= UNREADABLE_BUDGET, (
        f"{unreadable} insert payloads cannot be read (budget "
        f"{UNREADABLE_BUDGET}). Write the payload inline, or bind it to a "
        "local dict literal, rather than raising this."
    )


def test_every_allowed_entry_still_omits_the_column_it_claims(schema):
    """A ratchet only ratchets if a fixed entry has to leave it. An allowance
    for a column now supplied is a stale exemption hiding the next one."""
    required, tables = schema
    found, _ = insert_payloads(API_ROOT)
    still_missing = {
        f"{rel}.{col}"
        for _p, _ln, rel, keys in found if rel in tables
        for col in required.get(rel, set()) - keys
    }
    stale = sorted(set(ALLOWED) - still_missing)
    assert not stale, f"ALLOWED entries no longer omitted — delete them: {stale}"
