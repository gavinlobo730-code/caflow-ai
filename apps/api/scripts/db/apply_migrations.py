#!/usr/bin/env python3
"""
Ordered, idempotent migration runner for the PracticeSync schema.

Background
----------
The repository has 150+ hand-numbered SQL migrations in apps/api/migrations/ but
NO runner and NO tracking table — migrations were applied by hand in MCP/psql
sessions, which is the documented root cause of repo-vs-live schema drift
(see docs/audits/2026-07-02-executive-product-audit.md, findings F5/F20/R2.6).

This script gives the migration set a real runner:
  * discovers migrations in a deterministic order (numeric prefix, then filename,
    so duplicate-numbered files order stably);
  * records every applied file + its sha256 in a `schema_migrations` tracking
    table, so re-runs are idempotent (already-applied, unchanged files skip);
  * optionally injects a Supabase-compatibility bootstrap so the Supabase-only
    constructs (auth/storage schemas, anon/authenticated/service_role roles,
    auth.uid()/auth.jwt()) resolve on a plain PostgreSQL (local dev / CI);
  * classifies pure data-seed migrations so a schema-only run can skip them.

It shells out to `psql` (like the existing migration tests) rather than adding a
Python driver dependency, and applies each file with ON_ERROR_STOP=1 so a broken
migration fails loudly instead of half-applying.

Usage
-----
    python scripts/db/apply_migrations.py --dsn "postgresql://user@host:5432/db" \
        [--with-compat] [--only-schema] [--continue-on-error] [--dry-run] [--json]

If --dsn is omitted, psql's standard PG* environment variables are used.

Exit code is 0 only when every attempted migration applied (or was already
applied); non-zero if any failed (unless --continue-on-error, which still exits
non-zero but runs the whole set first so you get the full failure list).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"
COMPAT_BOOTSTRAP = MIGRATIONS_DIR / "_supabase_compat_bootstrap.sql"

# Pure data-seed migrations: they INSERT rows that depend on a seeded firm /
# auth user rather than defining schema. A schema-only run (--only-schema) skips
# them; they are still applied in a full run once prerequisites exist.
SEED_MIGRATIONS = {
    "011_seed_chart_of_accounts.sql",
    "040_seed_owner_user.sql",
}

_NUM_PREFIX = re.compile(r"^(\d+)_")


@dataclass
class Migration:
    path: Path
    number: int
    is_seed: bool

    @property
    def name(self) -> str:
        return self.path.name

    def checksum(self) -> str:
        return hashlib.sha256(self.path.read_bytes()).hexdigest()


@dataclass
class RunReport:
    applied: list[str] = field(default_factory=list)
    skipped_already: list[str] = field(default_factory=list)
    skipped_seed: list[str] = field(default_factory=list)
    # Files that failed on an EARLIER run at this same checksum and were not
    # attempted again. See run()'s "WHY A FAILURE IS REMEMBERED".
    skipped_failed_before: list[str] = field(default_factory=list)
    failed: list[dict] = field(default_factory=list)
    duplicate_numbers: dict[int, list[str]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.failed


def discover_migrations(migrations_dir: Path = MIGRATIONS_DIR) -> list[Migration]:
    """Return migrations in apply order: numeric prefix, then filename.

    Excludes rollbacks (*_rollback.sql) and helper files starting with '_'.
    Duplicate numeric prefixes are ordered by filename for stability (and
    reported separately so the hygiene problem stays visible).
    """
    out: list[Migration] = []
    for p in sorted(migrations_dir.glob("*.sql")):
        if p.name.startswith("_") or "rollback" in p.name:
            continue
        m = _NUM_PREFIX.match(p.name)
        if not m:
            continue
        out.append(Migration(path=p, number=int(m.group(1)), is_seed=p.name in SEED_MIGRATIONS))
    out.sort(key=lambda mig: (mig.number, mig.name))
    return out


def duplicate_numbers(migrations: list[Migration]) -> dict[int, list[str]]:
    by_num: dict[int, list[str]] = {}
    for mig in migrations:
        by_num.setdefault(mig.number, []).append(mig.name)
    return {n: names for n, names in by_num.items() if len(names) > 1}


def _psql(dsn: str | None, args: list[str], input_sql: str | None = None) -> subprocess.CompletedProcess:
    cmd = ["psql"]
    if dsn:
        cmd.append(dsn)
    cmd += ["-v", "ON_ERROR_STOP=1", "-X", "-q"]
    cmd += args
    return subprocess.run(
        cmd, input=input_sql, capture_output=True, text=True,
        env={**os.environ, "PGOPTIONS": "-c client_min_messages=warning"},
    )


def ensure_tracking_table(dsn: str | None) -> None:
    sql = """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        filename    text PRIMARY KEY,
        checksum    text NOT NULL,
        applied_at  timestamptz NOT NULL DEFAULT now()
    );
    CREATE TABLE IF NOT EXISTS schema_migration_failures (
        filename        text PRIMARY KEY,
        checksum        text NOT NULL,
        error           text,
        attempts        integer NOT NULL DEFAULT 1,
        first_failed_at timestamptz NOT NULL DEFAULT now(),
        last_failed_at  timestamptz NOT NULL DEFAULT now()
    );
    """
    r = _psql(dsn, ["-c", sql])
    if r.returncode != 0:
        raise RuntimeError(f"Failed to create tracking tables: {r.stderr.strip()}")


def failed_set(dsn: str | None) -> dict[str, str]:
    """filename -> checksum for migrations that failed on an earlier run.

    Keyed by checksum on purpose: EDITING a broken migration changes its
    checksum, which drops it out of this set and makes it run again. That is
    the intended way to retry one — fix it, or pass --retry-failed."""
    r = _psql(dsn, ["-tA", "-c", "SELECT filename, checksum FROM schema_migration_failures;"])
    if r.returncode != 0:
        return {}
    out: dict[str, str] = {}
    for line in r.stdout.splitlines():
        if "|" in line:
            fn, cs = line.split("|", 1)
            out[fn.strip()] = cs.strip()
    return out


def _record_failure(dsn: str | None, name: str, checksum: str, error: str) -> None:
    q = lambda v: "'" + str(v).replace("'", "''") + "'"          # noqa: E731
    _psql(dsn, ["-c", (
        "INSERT INTO schema_migration_failures(filename, checksum, error) "
        f"VALUES ({q(name)}, {q(checksum)}, {q(error[:2000])}) "
        "ON CONFLICT (filename) DO UPDATE SET checksum = EXCLUDED.checksum, "
        "error = EXCLUDED.error, attempts = schema_migration_failures.attempts + 1, "
        "last_failed_at = now();"
    )])


def _clear_failure(dsn: str | None, name: str) -> None:
    q = "'" + name.replace("'", "''") + "'"
    _psql(dsn, ["-c", f"DELETE FROM schema_migration_failures WHERE filename = {q};"])


def applied_set(dsn: str | None) -> dict[str, str]:
    r = _psql(dsn, ["-tA", "-c", "SELECT filename, checksum FROM schema_migrations;"])
    if r.returncode != 0:
        return {}
    out: dict[str, str] = {}
    for line in r.stdout.splitlines():
        if "|" in line:
            fn, cs = line.split("|", 1)
            out[fn.strip()] = cs.strip()
    return out


def apply_compat_bootstrap(dsn: str | None, dry_run: bool) -> None:
    if not COMPAT_BOOTSTRAP.exists():
        raise RuntimeError(f"Compat bootstrap not found: {COMPAT_BOOTSTRAP}")
    if dry_run:
        print(f"[dry-run] would apply compat bootstrap {COMPAT_BOOTSTRAP.name}", file=sys.stderr)
        return
    r = _psql(dsn, ["-f", str(COMPAT_BOOTSTRAP)])
    if r.returncode != 0:
        raise RuntimeError(f"Compat bootstrap failed: {r.stderr.strip()}")
    print(f"applied compat bootstrap {COMPAT_BOOTSTRAP.name}", file=sys.stderr)


def run(
    dsn: str | None,
    *,
    with_compat: bool = False,
    only_schema: bool = False,
    continue_on_error: bool = False,
    dry_run: bool = False,
    retry_failed: bool = False,
    migrations_dir: Path = MIGRATIONS_DIR,
) -> RunReport:
    """
    WHY A FAILURE IS REMEMBERED

    A migration that fails never reaches its INSERT into schema_migrations, so
    before this it was retried on every single run — forever, for a file that
    can never apply. That is not merely wasted work, because psql runs with
    ON_ERROR_STOP but WITHOUT --single-transaction: the statements BEFORE the
    failing one commit. A permanently-broken migration therefore re-applies its
    partial effects on every run, silently overwriting whatever later
    migrations did to the same objects.

    That is not hypothetical. 055_v131_hardening.sql fails partway and one of
    the statements before its failure is a CREATE OR REPLACE of
    prevent_posted_journal_modification() carrying the ORIGINAL body. Migration
    213 later replaces that function with one permitting exactly the
    is_reversed FALSE->TRUE flip that reverse_entry() must make. Run the set
    twice against one database and 055 re-runs while 213 is skipped as already
    applied — so the guard reverts and REVERSING A POSTED JOURNAL ENTRY becomes
    impossible, which is the only sanctioned correction there is.

    Production escaped it by accident: 055 is recorded there from the
    hand-applied era, so it is skipped before it can re-run. Any database the
    runner is pointed at more than once — a long-lived staging box — did not.

    So a failure is now recorded, and a file that failed at THIS checksum is
    not attempted again. First-run behaviour is unchanged: a fresh database
    still applies 055 partially and still reports it failed, exactly as the
    baseline in tests/test_migrations_apply.py expects.

    To retry one: fix it (the checksum changes, so it runs), or pass
    --retry-failed to attempt every remembered failure once more.

    DO NOT "FIX" THIS BY EDITING 055. Its checksum is what production matches
    on to skip it; change the file and it re-runs there on the next deploy and
    reverts the guard on the live database.
    """
    migrations = discover_migrations(migrations_dir)
    report = RunReport(duplicate_numbers=duplicate_numbers(migrations))

    if not dry_run:
        ensure_tracking_table(dsn)
    if with_compat:
        apply_compat_bootstrap(dsn, dry_run)

    done = {} if dry_run else applied_set(dsn)
    previously_failed = {} if (dry_run or retry_failed) else failed_set(dsn)

    for mig in migrations:
        if only_schema and mig.is_seed:
            report.skipped_seed.append(mig.name)
            continue
        checksum = mig.checksum()
        if done.get(mig.name) == checksum:
            report.skipped_already.append(mig.name)
            continue
        if previously_failed.get(mig.name) == checksum:
            report.skipped_failed_before.append(mig.name)
            print(f"skipping {mig.name} — it failed at this checksum on an earlier "
                  "run; edit it or pass --retry-failed", file=sys.stderr)
            continue
        if dry_run:
            report.applied.append(mig.name)
            continue

        # ONE psql per migration, not two.
        #
        # The migration and its schema_migrations row used to be separate psql
        # invocations. Each spawn costs a process, a TCP connection and an auth
        # handshake — measured at 54ms — and at 309 migrations that was 618 of
        # them: ~33 seconds of a 74-second schema build spent saying hello. The
        # SQL itself was never the slow part.
        #
        # ON_ERROR_STOP=1 is what makes combining them SAFE rather than merely
        # faster: psql stops at the first error, so a migration that fails can
        # never reach the INSERT that would mark it applied, and the exit code
        # is still non-zero. Same guarantee as before, one round trip.
        #
        # It also closes a real hole. The old INSERT's return code was never
        # checked, so a migration could apply while its tracking row silently
        # failed to write — leaving it to run again on the next pass.
        #
        # Fed on stdin rather than -f: no migration uses a psql meta-command
        # (\i, \copy — checked across all of them), so the two are equivalent,
        # and _first_error greps for "ERROR:" without caring about the filename.
        safe_name = mig.name.replace("'", "''")  # filenames are repo-controlled; escape defensively
        r = _psql(dsn, ["-f", "-"], input_sql=(
            mig.path.read_text(encoding="utf-8")
            + "\n\nINSERT INTO schema_migrations(filename, checksum) VALUES "
            + f"('{safe_name}', '{checksum}') "
            + "ON CONFLICT (filename) DO UPDATE SET checksum = EXCLUDED.checksum, applied_at = now();\n"
        ))
        if r.returncode != 0:
            err = _first_error(r.stderr)
            report.failed.append({"file": mig.name, "error": err})
            _record_failure(dsn, mig.name, checksum, err)
            if not continue_on_error:
                return report
            continue

        # Applied cleanly — drop any remembered failure so a fixed migration
        # leaves no trace that would confuse the next run.
        if mig.name in previously_failed:
            _clear_failure(dsn, mig.name)
        report.applied.append(mig.name)

    return report


def _first_error(stderr: str) -> str:
    for line in stderr.splitlines():
        if "ERROR:" in line:
            return line.strip()
    return (stderr.strip().splitlines() or ["unknown error"])[-1]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dsn", help="libpq connection string/URI. Falls back to PG* env vars.")
    ap.add_argument("--with-compat", action="store_true", help="Inject the Supabase-compat bootstrap first (for plain Postgres).")
    ap.add_argument("--only-schema", action="store_true", help="Skip pure data-seed migrations.")
    ap.add_argument("--continue-on-error", action="store_true", help="Attempt every migration; report all failures.")
    ap.add_argument("--dry-run", action="store_true", help="List what would be applied without touching the DB.")
    ap.add_argument("--json", action="store_true", help="Emit the run report as JSON.")
    ap.add_argument("--migrations-dir",
                    help="Apply from this directory instead of apps/api/migrations. For "
                         "tests that need a migration set of their own — writing a probe "
                         "file into the real directory would leak into any other test "
                         "that builds a schema from it.")
    ap.add_argument("--retry-failed", action="store_true",
                    help="Attempt migrations that failed on an earlier run at the same "
                         "checksum. Without this they are skipped — see run()'s docstring.")
    args = ap.parse_args(argv)

    report = run(
        args.dsn,
        with_compat=args.with_compat,
        only_schema=args.only_schema,
        continue_on_error=args.continue_on_error,
        dry_run=args.dry_run,
        retry_failed=args.retry_failed,
        migrations_dir=Path(args.migrations_dir) if args.migrations_dir else MIGRATIONS_DIR,
    )

    if args.json:
        print(json.dumps({
            "applied": report.applied,
            "skipped_already": report.skipped_already,
            "skipped_seed": report.skipped_seed,
            "skipped_failed_before": report.skipped_failed_before,
            "failed": report.failed,
            "duplicate_numbers": report.duplicate_numbers,
            "ok": report.ok,
        }, indent=2))
    else:
        print(f"applied={len(report.applied)} already={len(report.skipped_already)} "
              f"seed_skipped={len(report.skipped_seed)} "
              f"failed_before={len(report.skipped_failed_before)} "
              f"failed={len(report.failed)}")
        if report.duplicate_numbers:
            print(f"WARNING duplicate migration numbers: {report.duplicate_numbers}")
        for f in report.failed:
            print(f"  FAIL {f['file']}: {f['error']}")

    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
