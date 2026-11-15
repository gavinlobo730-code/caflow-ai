"""Every table a signed-in session can reach is observed by the role-by-table matrix, or is named on a list that only shrinks
(POST-A-008, its first part).

WHY THIS EXISTS
    The role-by-table matrix (`test_rls_role_by_table_matrix_pg.py`) tries every actor against every table the BROWSER reaches
    and holds the answer to a reviewed file. PostgREST answers for every table `authenticated` is granted, not only for the ones
    a screen reads: a person's own JWT and the anon key are all a hand-made request needs, and the API runs as the caller when
    USE_USER_JWT is on. Measured on 15-11-2026, a migration-built database grants a signed-in session 265 tables, the matrix
    observes 99 relations, and 193 tables sit outside it, 76 of them writable (the ledger balances, the ITC reversal register,
    GST challans and Form 26AS records among them). Nothing said which, and a table a new migration creates is granted to
    `authenticated` by the platform's default privileges, so the blind spot grew silently with every migration.

WHAT THIS HOLDS
    * `tests/fixtures/tables_a_signed_in_session_reaches_outside_the_matrix.txt` is EXACTLY the reachable tables the matrix does
      not observe, each marked `read` or `write` as the database grants it (a column grant counts): a new grant fails until the
      table is added to the matrix, the grant is taken away, or it is named here with the ceiling below raised; a table that
      leaves the blind spot is deleted from the list; and a table whose grant widens from read to write fails until the line is
      changed by hand, so a widened grant is a visible diff.
    * The list's size is held under a ceiling that only comes down (`CEILING`, and `WRITABLE_CEILING` for the writable part).
    * The format, without a database: one name and one kind a line, sorted, no duplicates, no table the matrix observes, and no
      `write` entry on the list of tables production takes every signed-in write from
      (`tables_the_signed_in_role_cannot_write.txt`), which would mean the migrations and production disagree.

WHAT IT DOES NOT DO
    It does not say what a reachable table ADMITS: the matrix observes that, and the assignment-scope ratchets
    (`test_every_client_table_is_assignment_scoped_or_says_why_pg.py`) hold the client tables' read scope. Reaching a table is
    not reading another tenant's rows. The list is what the next tranches work down, by adding a group of tables to the matrix or
    by moving its writers to the API's privileged client and taking the signed-in write away (the shape of migrations 549 to 551,
    583 and 593).

The database half runs only when HARNESS_PG is set + psql on PATH; the format half runs in the mock-mode job.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
LIST = API_ROOT / "tests" / "fixtures" / "tables_a_signed_in_session_reaches_outside_the_matrix.txt"
MATRIX = API_ROOT / "tests" / "fixtures" / "rls_expected_access.json"
CLOSED = API_ROOT / "tests" / "fixtures" / "tables_the_signed_in_role_cannot_write.txt"
_ADMIN = os.environ.get("HARNESS_PG")

#: Only ever lowered. Raising one is a decision a reviewer sees in the diff: a new table a signed-in session reaches that the matrix
#: does not observe.
CEILING = 193
WRITABLE_CEILING = 3

_REACHABLE = """
SELECT c.relname,
       has_table_privilege('authenticated', c.oid, 'INSERT,UPDATE,DELETE')
       OR EXISTS (SELECT 1 FROM pg_attribute a
                   WHERE a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
                     AND has_column_privilege('authenticated', c.oid, a.attnum, 'INSERT,UPDATE'))
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
   AND (has_table_privilege('authenticated', c.oid, 'SELECT,INSERT,UPDATE,DELETE')
        OR EXISTS (SELECT 1 FROM pg_attribute a
                    WHERE a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
                      AND has_column_privilege('authenticated', c.oid, a.attnum, 'SELECT,INSERT,UPDATE')))
 ORDER BY 1
"""


def _listed() -> dict[str, str]:
    out: dict[str, str] = {}
    for ln in LIST.read_text(encoding="utf-8").splitlines():
        if not ln.strip() or ln.startswith("#"):
            continue
        name, kind = ln.split("\t")
        out[name] = kind
    return out


def _matrix_tables() -> set[str]:
    return set(json.loads(MATRIX.read_text(encoding="utf-8"))["tables"])


def _closed() -> set[str]:
    return {ln.strip() for ln in CLOSED.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")}


# ── the file, without a database ───────────────────────────────────────────────────────────────────────────────────

def test_the_list_is_one_table_and_one_kind_a_line_sorted_and_unique():
    lines = [ln for ln in LIST.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]
    names = [ln.split("\t")[0] for ln in lines]
    assert all(len(ln.split("\t")) == 2 and ln.split("\t")[1] in ("read", "write") for ln in lines), \
        "a line is a table name, a tab and `read` or `write`"
    assert names == sorted(names) and len(set(names)) == len(names), "sorted, no duplicates"


def test_the_list_stays_under_its_ceilings():
    listed = _listed()
    assert len(listed) <= CEILING, f"{len(listed)} tables outside the matrix; the ceiling is {CEILING} and is only lowered"
    writable = sum(1 for k in listed.values() if k == "write")
    assert writable <= WRITABLE_CEILING, f"{writable} writable tables outside the matrix; the ceiling is {WRITABLE_CEILING}"


def test_no_table_the_matrix_observes_is_on_the_list():
    assert set(_listed()) & _matrix_tables() == set()


def test_no_table_production_closes_to_signed_in_writes_is_listed_as_writable():
    assert {t for t, k in _listed().items() if k == "write"} & _closed() == set()


def test_a_ceiling_that_was_lowered_is_not_left_above_the_list():
    """A ceiling higher than the list leaves room for a table to join unseen, so the two are equal."""
    listed = _listed()
    assert CEILING == len(listed) and WRITABLE_CEILING == sum(1 for k in listed.values() if k == "write"), \
        "lower the ceilings to the list's size in the change that shrinks it"


# ── the database ───────────────────────────────────────────────────────────────────────────────────────────────────

_needs_pg = pytest.mark.skipif(not _ADMIN or shutil.which("psql") is None, reason="requires HARNESS_PG + psql")


@pytest.fixture()
def dsn(pg_template):
    admin = _ADMIN.strip()
    name = f"reach_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    made = subprocess.run(["psql", admin_dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c",
                           f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";'], capture_output=True, text=True)
    if made.returncode != 0:
        pytest.skip("could not create throwaway db")
    try:
        yield f"{admin} dbname={name}"
    finally:
        subprocess.run(["psql", admin_dsn, "-X", "-q", "-c", f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);'],
                       capture_output=True, text=True)


def _reachable(dsn: str) -> dict[str, str]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-tA", "-c", _REACHABLE], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    out = {}
    for ln in r.stdout.strip().splitlines():
        name, writable = ln.split("|")
        out[name] = "write" if writable == "t" else "read"
    return out


@_needs_pg
def test_the_list_is_exactly_what_the_matrix_does_not_observe(dsn):
    reach = _reachable(dsn)
    assert len(reach) > 100, "the probe found almost nothing reachable: it is not measuring what it says"
    outside = {t: k for t, k in reach.items() if t not in _matrix_tables()}
    listed = _listed()
    new = sorted(set(outside) - set(listed))
    gone = sorted(set(listed) - set(outside))
    widened = sorted(t for t in set(outside) & set(listed) if outside[t] == "write" and listed[t] == "read")
    narrowed = sorted(t for t in set(outside) & set(listed) if outside[t] == "read" and listed[t] == "write")
    assert not new, (f"a signed-in session reaches {new}, which the matrix does not observe: add each to the matrix, take its grant "
                     f"away, or name it in {LIST.name} and raise the ceiling")
    assert not gone, f"{gone} left the blind spot (now in the matrix, or no longer reachable): delete them from {LIST.name}"
    assert not widened, f"{widened} gained a write: change each line to `write` and raise WRITABLE_CEILING, in the change that grants it"
    assert not narrowed, f"{narrowed} lost every write: change each line to `read` and lower WRITABLE_CEILING"


@_needs_pg
def test_the_probe_sees_a_column_grant_and_a_table_grant(dsn):
    """The negative control: a table reachable only through a column grant, and one through a write alone, are both seen."""
    subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c",
                    "CREATE TABLE public.zz_probe_col (id int, secret text); REVOKE ALL ON public.zz_probe_col FROM PUBLIC, anon, authenticated;"
                    "GRANT SELECT (id) ON public.zz_probe_col TO authenticated;"
                    "CREATE TABLE public.zz_probe_write (id int); REVOKE ALL ON public.zz_probe_write FROM PUBLIC, anon, authenticated;"
                    "GRANT UPDATE (id) ON public.zz_probe_write TO authenticated;"
                    "CREATE TABLE public.zz_probe_none (id int); REVOKE ALL ON public.zz_probe_none FROM PUBLIC, anon, authenticated;"],
                   check=True, capture_output=True, text=True)
    reach = _reachable(dsn)
    assert reach.get("zz_probe_col") == "read" and reach.get("zz_probe_write") == "write" and "zz_probe_none" not in reach
