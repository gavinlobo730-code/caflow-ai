"""
Applying the migration set TWICE to one database must leave the same schema as
applying it once.

WHY THIS EXISTS, AND WHY IT IS NOT AN ABSTRACT PROPERTY
    psql runs each migration with ON_ERROR_STOP but WITHOUT
    --single-transaction, so a migration that fails partway still commits every
    statement before the failing one. A migration that can never apply is
    therefore not inert — it re-applies its partial effects on every run. And
    before this was fixed it DID run on every run: a failure never reaches its
    INSERT into schema_migrations, so nothing recorded that it had been tried.

    055_v131_hardening.sql is such a migration, and one of the statements before
    its failure is a CREATE OR REPLACE of prevent_posted_journal_modification()
    carrying the ORIGINAL body. Migration 213 later replaces it with one that
    permits exactly the is_reversed FALSE->TRUE flip reverse_entry() performs.

    So on the second run 055 re-ran, 213 was skipped as already applied, and the
    guard reverted — leaving a database where a posted journal entry CANNOT BE
    REVERSED. Reversal is the only sanctioned correction for a posted entry
    (CLAUDE.md), so the whole correction path was gone, silently, on any
    database the runner was pointed at more than once.

    Production escaped by accident: 055 is recorded there from the hand-applied
    era, so it is skipped before it can re-run. That is luck, not a design.

WHAT IS ASSERTED
    The symptom, not the bookkeeping. A second run must leave a posted entry
    still reversible. test_the_second_run_does_not_retry_a_known_failure covers
    the mechanism underneath it.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="re-runnability proof requires HARNESS_PG + psql",
)

FIRM = "f3060000-0000-0000-0000-000000000001"
CLIENT = "c3060000-0000-0000-0000-000000000001"


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-X", "-q", "-t", "-A", "-c", sql],
                          capture_output=True, text=True)


def _apply(dsn: str, *extra: str) -> dict:
    proc = subprocess.run(
        [sys.executable, str(RUNNER), "--dsn", dsn, "--with-compat", "--only-schema",
         "--continue-on-error", "--json", *extra],
        capture_output=True, text=True, cwd=str(API_ROOT),
    )
    return json.loads(proc.stdout)


def _apply_from(dsn: str, migrations_dir, *extra: str) -> dict:
    """Apply a migration set of the test's own, not the repository's.

    Writing a probe migration into apps/api/migrations would leak into any
    other test that builds a schema from that directory — and the template
    fixture several files share is built exactly once, from whatever is on disk
    at that moment. --migrations-dir keeps the probe out of everyone's way."""
    proc = subprocess.run(
        [sys.executable, str(RUNNER), "--dsn", dsn, "--only-schema",
         "--continue-on-error", "--json", "--migrations-dir", str(migrations_dir), *extra],
        capture_output=True, text=True, cwd=str(API_ROOT),
    )
    return json.loads(proc.stdout)


@pytest.fixture()
def fresh_db():
    admin = _ADMIN.strip()
    name = f"rerun_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}";').returncode != 0:
        pytest.skip("could not create a database")
    try:
        yield f"{admin} dbname={name}"
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _schema_fingerprint(dsn: str) -> dict[str, str]:
    """Every function body and trigger definition in `public`, by name.

    The bug this file exists for is a re-run silently REPLACING an object a
    later migration had corrected, so the property to assert is that a second
    run changes nothing — not that some particular guard permits some
    particular update. Asserting the contract of a guard would have to model
    that contract, and it has already moved twice (213 relaxed it for the
    is_reversed flip; 266 rewrote it again for editable journals). The
    fingerprint is indifferent to all of that and still catches the clobber.
    """
    r = _psql(dsn, """
        SELECT p.proname || '|' || md5(p.prosrc)
          FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
         WHERE n.nspname = 'public'
        UNION ALL
        SELECT 'trigger:' || t.tgname || '|' || md5(pg_get_triggerdef(t.oid))
          FROM pg_trigger t
          JOIN pg_class c ON c.oid = t.tgrelid
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'public' AND NOT t.tgisinternal
         ORDER BY 1;
    """)
    assert r.returncode == 0, r.stderr
    out: dict[str, str] = {}
    for line in r.stdout.splitlines():
        if "|" in line:
            name, digest = line.rsplit("|", 1)
            out[name.strip()] = digest.strip()
    return out


# ── The symptom ───────────────────────────────────────────────────────────────

def test_a_second_run_changes_no_function_or_trigger(fresh_db):
    """The whole bug, stated as the property it violates.

    Before this fix, running the set twice left prevent_posted_journal_update
    and prevent_posted_journal_modification carrying migration 055's bodies
    instead of the ones later migrations installed — because 055 fails partway,
    was never recorded, re-ran, and its pre-failure CREATE OR REPLACE committed
    over them. Reversing a posted journal entry became impossible, which is the
    only sanctioned correction there is.
    """
    first = _apply(fresh_db)
    assert first["applied"], "nothing applied on the first run"
    before = _schema_fingerprint(fresh_db)
    assert before, "no functions found — the schema did not build"

    _apply(fresh_db)                      # the second run is the whole point
    after = _schema_fingerprint(fresh_db)

    changed = sorted(k for k in before if k in after and before[k] != after[k])
    vanished = sorted(set(before) - set(after))
    assert not changed and not vanished, (
        "a second migration run rewrote objects the first run had settled — a "
        "permanently-failing migration re-applied its partial effects over a "
        f"later fix.\n  rewritten: {changed}\n  vanished: {vanished}")


def test_the_journal_guards_specifically_survive_a_second_run(fresh_db):
    """The named casualty, kept as a regression anchor beside the general
    property — these two are what 055 re-creates, and reversal is what breaks."""
    guards = ("prevent_posted_journal_update", "prevent_posted_journal_modification")
    _apply(fresh_db)
    before = _schema_fingerprint(fresh_db)
    _apply(fresh_db)
    after = _schema_fingerprint(fresh_db)
    for g in guards:
        assert g in before, f"{g} is not in the built schema at all"
        assert after.get(g) == before[g], (
            f"{g} was rewritten by the second run — migration 055's body is back, "
            "and a posted journal entry can no longer be reversed")


# ── The mechanism ─────────────────────────────────────────────────────────────

def test_the_second_run_does_not_retry_a_known_failure(fresh_db):
    first = _apply(fresh_db)
    failed = {f["file"] for f in first["failed"]}
    assert failed, "expected the known baseline failures on a fresh database"

    second = _apply(fresh_db)
    assert not second["failed"], (
        "the second run retried migrations that already failed at the same "
        f"checksum: {[f['file'] for f in second['failed']]}")
    assert failed <= set(second["skipped_failed_before"]), (
        "every migration that failed on the first run should have been skipped "
        "on the second")


def test_the_first_run_is_unchanged(fresh_db):
    """The baseline in test_migrations_apply.py is asserted against a FIRST run,
    and remembering failures must not alter it."""
    first = _apply(fresh_db)
    assert not first["skipped_failed_before"], (
        "a fresh database has no remembered failures, so nothing may be skipped "
        "for that reason on the first run")
    assert first["failed"], "the known baseline failures should still be reported"


def test_retry_failed_attempts_them_again(fresh_db):
    """The escape hatch has to work, or a genuinely transient failure would be
    remembered forever."""
    _apply(fresh_db)
    retried = _apply(fresh_db, "--retry-failed")
    assert retried["failed"], "--retry-failed should have attempted them again"
    assert not retried["skipped_failed_before"]


def test_editing_a_broken_migration_makes_it_run_again(fresh_db, tmp_path):
    """Keyed by checksum, so the normal way to retry one is to fix the file.

    Run against a migration set of the test's own — touching a real historical
    migration is exactly what must not be done, because 055's checksum is what
    production matches on to skip it. Change that file and it re-runs there on
    the next deploy and reverts the journal guard on the live database.
    """
    probe_dir = tmp_path / "migrations"
    probe_dir.mkdir()
    probe = probe_dir / "001_probe.sql"
    probe.write_text("SELECT 1 FROM a_table_that_does_not_exist;\n")

    first = _apply_from(fresh_db, probe_dir)
    assert probe.name in {f["file"] for f in first["failed"]}

    second = _apply_from(fresh_db, probe_dir)
    assert probe.name in second["skipped_failed_before"]
    assert not second["failed"]

    probe.write_text("CREATE TABLE IF NOT EXISTS public.rerun_probe (id int);\n")
    third = _apply_from(fresh_db, probe_dir)
    assert probe.name in third["applied"], (
        "a repaired migration must run again — its checksum changed")

    fourth = _apply_from(fresh_db, probe_dir)
    assert probe.name in fourth["skipped_already"]
    assert probe.name not in fourth["skipped_failed_before"], (
        "a migration that later succeeded should leave no remembered failure")
