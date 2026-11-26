"""
The three frontend schema guards, asked of the committed files, so a frontend-only pull request is checked too (POST-A-038).

WHAT WAS LEFT
    `test_frontend_columns_exist_pg.py`, `test_frontend_status_values_match_the_check_pg.py` and
    `test_frontend_never_writes_an_auth_id_into_a_users_fk_pg.py` read a migration-built Postgres (about 600 migrations), so they
    skip in the `browser contract` job, and that is the only job a pull request touching nothing but `apps/web` runs. A screen that
    named a column the schema lacks, wrote a status its CHECK refuses or put a sign-in id into a key to users was caught only when
    the same pull request also touched `apps/api`. `.github/workflows/backend-ci.yml` named it as the job's one residual.

WHAT THIS DOES
    The same three questions, with the SAME scanners (imported from the three modules, never copied: `_offenders` and `_bad` with
    `scan_filters` and `scan_writes`, `_scan`, and `auth_id_writes`) and the same exemptions (`INTENTIONAL`, `UNFIXED`, `KNOWN`),
    answered from `tests/_schema_from_files.py` instead of a database. It imports those modules, so
    `scripts/ci/tests_reading_the_browser.py` puts it in the browser-contract job; the last test here holds that.

WHAT IT CAN SEE, AND WHAT IT CANNOT
    * A COLUMN fails here when it is in NEITHER the production snapshot (`tests/fixtures/production_schema_*.json`, the newest; the
      file name says 2026-09-03 and its `.meta.json` says it was captured through migration 557) NOR a database the migrations
      build, as `tests/_schema_from_files.py` replays them. So a column a migration added after the snapshot passes, and a name
      nobody ever declared (or one a migration dropped before the snapshot) fails. What it cannot see: a column a migration
      dropped or renamed away AFTER the snapshot (the snapshot still has it), and a wrong column of a view, because a view is read
      generously as every word of its definition.
    * A STATUS is measured, for the tables that still have a CHECK on `status`, against every value any migration's CHECK on it
      has EVER allowed, so a CHECK a later migration narrowed still allows the old value here. The guards snapshot
      (`production_guards_*.json`) cannot help: it keeps a hash of each CHECK and never its values. `KNOWN` is subtracted as in
      the real guard; the two ratchets that need the exact vocabulary (a KNOWN entry gone stale, a file going blind) stay with the
      real guard only, because a wider vocabulary would answer them wrongly.
    * A KEY TO USERS is read by replaying the migrations (an added key, a dropped constraint, a dropped column or table, a renamed
      column or table). The guards snapshot keeps a foreign key's name and never what it references, so it cannot answer this.
    * Nothing built at run time (`EXECUTE format(...)`, apart from migration 319's shape), nothing only production has, and
      nothing a migration declares after a statement that fails on a fresh database.

    `test_the_schema_read_from_the_committed_files_agrees_with_a_migration_built_database_pg.py` is what makes this safe to run:
    in the real-Postgres job it holds every column the real guard sees to be known here, the tables with a status CHECK to be the
    same set with every real value allowed here, and the keys to users to be the same set, so a migration the reader misreads
    fails THAT test on its own pull request instead of making this one cry wolf. The real guards stay the authority wherever
    Postgres runs; this one can only be weaker than them, never stricter (one edge: a screen reading a relation no migration
    creates is checked here against the snapshot, where the real column guard leaves it to `test_frontend_tables_exist.py`).
"""
from __future__ import annotations

import sys
from pathlib import Path

from tests import _schema_from_files as files
from tests import production_types
from tests.test_frontend_columns_exist_pg import (
    FIXED_HERE, INTENTIONAL, UNFIXED, WEB, _bad, _offenders, scan, scan_filters, scan_writes,
)
from tests.test_frontend_never_writes_an_auth_id_into_a_users_fk_pg import auth_id_writes
from tests.test_frontend_status_values_match_the_check_pg import KNOWN, _scan

API = Path(__file__).resolve().parents[1]


def _schema() -> set[str]:
    return set(files.known_columns())


# ── enough to be meaningful ──────────────────────────────────────────────────────────────────────────────────────────────

def test_the_committed_files_describe_enough_of_the_schema_to_check_against():
    """Vacuity guards, one per answer: a reader that silently stopped matching would make every test below pass while checking
    nothing. The floors sit under what the files held on 16-11-2026 (5,350 columns, 91 tables with a status CHECK, 132 keys to
    users)."""
    assert len(files.snapshot_columns()) >= 5000, "the production snapshot did not load"
    assert len(files.migration_columns()) >= 5000, "the migrations replayed into almost nothing — the reader broke"
    assert len(files.status_values()) >= 85, "too few status CHECKs read out of the migrations"
    assert sum(len(c) for c in files.users_keys().values()) >= 125, "too few keys to users read out of the migrations"
    found, _ = scan(WEB)
    assert len(found) >= 800 and len(scan_filters(WEB)) >= 400, "the frontend scan found too little to be meaningful"


# ── columns ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_no_frontend_select_names_a_column_that_neither_the_snapshot_nor_a_migration_has():
    new = {k: v for k, v in _offenders(_schema()).items() if k not in INTENTIONAL}
    assert not new, (
        "these selects name columns that are in neither the production snapshot nor any migration. PostgREST rejects the "
        "ENTIRE select on one bad column, so the page's load() fails:\n  "
        + "\n  ".join(f"{col}  ({', '.join(sorted(f))})" for col, f in sorted(new.items())))


def test_no_filter_or_write_names_a_column_that_neither_the_snapshot_nor_a_migration_has():
    schema = _schema()
    for kind, refs in (("FILTER", scan_filters(WEB)), ("WRITE", scan_writes(WEB))):
        new = {k: v for k, v in _bad(refs, schema).items() if k not in UNFIXED}
        assert not new, (
            f"these {kind} arguments name columns that are in neither the production snapshot nor any migration:\n  "
            + "\n  ".join(f"{c}  ({', '.join(sorted(f))})" for c, f in sorted(new.items())))


def test_a_name_nobody_declared_is_caught_and_one_only_a_later_migration_declares_is_not():
    """Not blind, in both directions, on the real files. The pinned regressions of the real guard are names nothing ever
    declared, so this reading must still refuse them; and a column a migration added after the snapshot was taken must pass."""
    schema = _schema()
    for col in FIXED_HERE:
        table, name = col.split(".", 1)
        assert col not in schema, f"{col} is known to the committed files, so this guard could not catch it coming back"
        assert _bad([("app/probe.tsx", table, name)], schema) == {col: {"app/probe.tsx"}}
    assert _bad([("app/probe.tsx", "tds_challans", "journal_entry_idd")], schema), "a typo of a real column was not caught"

    later = [f"{t}.{c}" for t, c in production_types.ADDED_AFTER_THE_SNAPSHOT]
    assert later, "production_types names no column added after the snapshot; pick another probe for this direction"
    for col in later:
        assert col not in files.snapshot_columns(), f"{col} is in the snapshot now: delete its ADDED_AFTER_THE_SNAPSHOT entry"
        assert col in schema, f"{col} was added by a migration after the snapshot and this reading does not know it"


# ── status values ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_no_new_screen_uses_a_status_no_migration_ever_allowed_on_the_tables_it_reads():
    reports, _blind = _scan(files.status_values())
    new = {f: sorted(v - KNOWN.get(f, set())) for f, v in reports.items()}
    new = {f: v for f, v in new.items() if v}
    assert not new, (
        "these screens use a status value that no CHECK in any migration has allowed on a table they read — written, the "
        "database refuses the row; compared, nothing ever matches:\n  "
        + "\n  ".join(f"{f}: {', '.join(v)}" for f, v in sorted(new.items())))


# ── keys to users ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_no_frontend_write_puts_an_auth_id_in_a_key_the_migrations_leave_to_users():
    offenders = auth_id_writes(files.users_keys())
    assert not offenders, (
        "these frontend writes put a Supabase AUTH id into a column the migrations key to public.users(id), the INTERNAL "
        "id; every such write is refused by the key:\n  " + "\n  ".join(offenders))


def test_the_auth_id_scan_still_fires_on_a_key_it_is_given():
    """The scan is the real guard's, so it is enough to show it answers to the pairs it is handed: the frontend writes
    `it_notices` from the browser, and a key on any column of that payload makes the scan look at it."""
    from tests.test_frontend_never_writes_an_auth_id_into_a_users_fk_pg import _payloads
    seen = {t for p in WEB.rglob("*.tsx") if "node_modules" not in p.parts for t, _, _ in _payloads(p.read_text("utf-8"))}
    assert "it_notices" in seen, "the write this probe stands on is no longer matched by the scan"


# ── the reader itself ────────────────────────────────────────────────────────────────────────────────────────────────────

def _read(*sql: str) -> files._Replay:
    replay = files._Replay()
    for text in sql:
        for stmt in files.statements(text):
            replay.read(stmt)
    return replay


def test_a_status_check_is_read_from_a_column_a_constraint_and_a_replaced_constraint_and_its_values_keep_their_case():
    r = _read("""
        CREATE TABLE public.t (id uuid, status text NOT NULL DEFAULT 'Draft' CHECK (status IN ('Draft', 'Filed')),
                               filing_status text CHECK (filing_status IN ('not_a_status')));
        -- a comment saying CHECK (status IN ('commented'))
        ALTER TABLE t DROP CONSTRAINT t_status_check, ADD CONSTRAINT t_status_check
            CHECK (status = ANY (ARRAY['Draft'::text, 'it''s'::text]));
        CREATE TABLE gone (status text CONSTRAINT gone_status_ok CHECK (status IN ('a')));
        ALTER TABLE gone DROP CONSTRAINT IF EXISTS gone_status_ok;
        CREATE TABLE dropped (status text CHECK (status IN ('b')));
        DROP TABLE IF EXISTS dropped CASCADE;
    """)
    assert files.status_values(r) == {"t": {"Draft", "Filed", "it's"}}, (
        "a narrowed CHECK still allows its old values, a comment allows nothing, and a table whose CHECK (or whose table) "
        "was dropped has nothing to be measured against, as in the real guard")


def test_a_key_to_users_is_replayed_through_its_add_drop_and_renames():
    r = _read("""
        CREATE TABLE t (id uuid, made_by uuid REFERENCES public.users(id), seen_by uuid REFERENCES auth.users(id));
        ALTER TABLE t ADD COLUMN IF NOT EXISTS checked_by uuid, ADD CONSTRAINT t_checker FOREIGN KEY (checked_by) REFERENCES users(id);
        ALTER TABLE t RENAME COLUMN made_by TO created_by;
        ALTER TABLE t DROP CONSTRAINT t_checker;
        CREATE TABLE IF NOT EXISTS t (id uuid, other_by uuid REFERENCES users(id));
        ALTER TABLE t RENAME TO u;
        DO $$ BEGIN ALTER TABLE u ADD COLUMN approved_by uuid REFERENCES users(id); END $$;
    """)
    keys = {c for cols in files.users_keys(r).values() for c in cols}
    assert r.keys.get("u") and "t" not in r.keys
    assert keys == {"created_by", "approved_by"}, (
        "auth.users is not users; a dropped constraint is gone; a CREATE TABLE IF NOT EXISTS on a table that is there adds nothing")
    assert r.live["u"] == {"id", "created_by", "seen_by", "checked_by", "approved_by"}, (
        "a renamed column is gone, and a CREATE TABLE IF NOT EXISTS on a table that is there adds no column")


def test_migration_319s_constraints_declared_as_data_are_read():
    r = _read("""
        CREATE TABLE x (id uuid, created_by uuid, status text);
        DO $mig$ DECLARE spec record; BEGIN FOR spec IN SELECT * FROM (VALUES
          ($d$x$d$, $d$x_created_by_fkey$d$, $d$FOREIGN KEY (created_by) REFERENCES users(id)$d$),
          ($d$x$d$, $d$x_status_check$d$, $d$CHECK ((status = ANY (ARRAY['draft'::text, 'filed'::text])))$d$),
          ($d$absent$d$, $d$absent_created_by_fkey$d$, $d$FOREIGN KEY (created_by) REFERENCES users(id)$d$)
        ) AS v(tbl, con, def) LOOP EXECUTE format('ALTER TABLE public.%I ADD CONSTRAINT %I %s', spec.tbl, spec.con, spec.def);
        END LOOP; END $mig$;
    """)
    assert r.keys == {"x": {"x_created_by_fkey": "created_by"}}, "a row for a table that is not there adds nothing"
    assert files.status_values(r) == {"x": {"draft", "filed"}}


# ── it runs where it is needed ───────────────────────────────────────────────────────────────────────────────────────────

def test_the_browser_contract_job_runs_this_module():
    sys.path.insert(0, str(API / "scripts" / "ci"))
    import tests_reading_the_browser as selector
    names = {p.name for p in selector.modules_reading_the_browser()}
    assert Path(__file__).name in names, "the browser-contract job would not run this, which is the whole point of it"
