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
migration stops at its first error, and -- unless the file is one of the few that
cannot run inside a transaction, see "ATOMICITY" below -- inside ONE transaction, so
a file that fails on its third statement leaves nothing behind.

ATOMICITY
    A migration runs in a single transaction (`psql --single-transaction`, with its
    schema_migrations row inside it), EXCEPT where wrapping would be wrong:

      * the file carries its own BEGIN/COMMIT (109 of the files do) -- a second
        BEGIN is a warning and its COMMIT would end OUR transaction early, so it
        is left to manage itself exactly as before;
      * it holds a statement PostgreSQL refuses inside a transaction block
        (CREATE INDEX CONCURRENTLY, VACUUM, ALTER TYPE ... ADD VALUE, ...);
      * it opts out with a `-- migration: no-transaction` line, for the case
        the scanner cannot see;
      * it is one of BASELINE_FAILURES, the ten files that already fail on a
        fresh database and whose partial effects the rest of the schema build
        (and every tests/test_*_pg.py) was written against. Wrapping them would
        roll those effects back and change the schema every later migration and
        test starts from, so they keep the legacy behaviour until each is fixed
        and leaves the set.

    Which of the four applied to a file is reported (`not_atomic` in --json), so
    "ran without a wrapper" is a thing a person can see rather than assume.

Usage
-----
    python scripts/db/apply_migrations.py --dsn "postgresql://user@host:5432/db" \
        [--with-compat] [--only-schema] [--continue-on-error] [--dry-run] [--json]

If --dsn is omitted, psql's standard PG* environment variables are used.

Exit code is 0 only when every attempted migration applied (or was already
applied) AND no failure is still remembered from an earlier run (see run()'s
"WHY A FAILURE IS REMEMBERED"); non-zero if any failed (unless --continue-on-error,
which still exits non-zero but runs the whole set first so you get the full failure
list). A remembered failure that BASELINE_FAILURES names is the one exception: those
ten are tolerated, explicitly, and the set may only shrink.
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

# THE TEN MIGRATIONS THAT ALREADY FAIL ON A FRESH DATABASE, named once, here.
#
# tests/test_migrations_apply.py holds the same set as EXPECTED_MIGRATION_FAILURES
# (with the reason beside each) and a mock-mode test asserts the two are EQUAL, so
# there is one list in two places that cannot drift apart. Both directions are
# ratcheted: a migration that starts failing and is not here fails the CI harness,
# and one here that now applies fails it too, which is what forces this set to shrink.
#
# THIS SET DOES TWO THINGS AND BOTH ARE DELIBERATE:
#   1. A remembered failure of one of these does not turn the pipeline red. In
#      production they are recorded as applied from the hand-applied era and never
#      reach the failure check at all; the exemption only matters for a database
#      built from scratch and run twice, where they would otherwise keep every
#      later run red for a defect that has been recorded and tolerated for months.
#   2. They keep the LEGACY partial-apply behaviour instead of being wrapped in a
#      transaction. Each of them commits what precedes its failing statement on a
#      fresh database, and the rest of the migration set and every real-Postgres
#      test was written against the schema that results. Rolling it back would move
#      the floor under all of them, with no way to run the harness here to find out
#      which. They leave this set the day they are fixed, not before.
#
# Do NOT add a name. A file that fails is a defect to fix; this list is the debt
# already on the books and it may only get shorter.
BASELINE_FAILURES: frozenset[str] = frozenset({
    "008_linter_fixes.sql",
    "045_assignment_rules.sql",
    "053_hardening.sql",
    "054_v13_payroll_assets_banking.sql",
    "055_v131_hardening.sql",
    "068_workflow_engine.sql",
    "070_ai_memory.sql",
    "071_rls_policies.sql",
    "095_grant_reconciliation.sql",
    "144_security_search_path_and_rls.sql",
})

# A line comment that opts one migration out of the wrapper, for the case the
# scanner below cannot see (a DO block that COMMITs, a procedure call). Write the
# reason after it. Never retrofit it into an EXISTING file: a migration's
# checksum is what production matches on, and editing one re-runs it there.
NO_TRANSACTION_MARKER = re.compile(r"^[ \t]*--[ \t]*migration:[ \t]*no-transaction\b", re.I | re.M)


def strip_sql(sql: str) -> str:
    """The SQL with everything that is not a statement taken out.

    Comments are removed (`--`, and `/* */` which Postgres lets nest), and the
    CONTENT of single-quoted strings (E'..' backslash escapes included),
    double-quoted identifiers and dollar-quoted bodies is blanked. What is left
    is what the server would parse as statements, which is the only text a
    question like "does this file begin a transaction" may be asked of: a
    plpgsql function body is full of `BEGIN ... END;` that is not transaction
    control, and a grep for the word finds every one of them.
    """
    out: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        c = sql[i]
        if c == "-" and sql.startswith("--", i):
            j = sql.find("\n", i)
            i = n if j == -1 else j
            continue
        if c == "/" and sql.startswith("/*", i):
            i = _skip_block_comment(sql, i)
            out.append(" ")
            continue
        if c == "'":
            i = _skip_single_quoted(sql, i)
            out.append("''")
            continue
        if c == '"':
            i = _skip_double_quoted(sql, i)
            out.append('""')
            continue
        if c == "$":
            after = _skip_dollar_quoted(sql, i)
            if after is not None:
                i = after
                out.append("$$")
                continue
        out.append(c)
        i += 1
    return "".join(out)


# The four scanners below each take the text and the index of an opening delimiter and answer the index just
# past the construct, so `strip_sql` stays a dispatcher a reader can hold in their head (the lint ratchet caps a
# function's complexity, and a lexer folded into one loop is how this one reached nineteen).

def _skip_block_comment(sql: str, i: int) -> int:
    """Past a `/* ... */`, which Postgres lets nest."""
    n = len(sql)
    depth, i = 1, i + 2
    while i < n and depth:
        if sql.startswith("/*", i):
            depth, i = depth + 1, i + 2
        elif sql.startswith("*/", i):
            depth, i = depth - 1, i + 2
        else:
            i += 1
    return i


def _skip_single_quoted(sql: str, i: int) -> int:
    """Past a single-quoted string; an `E'..'` string also honours backslash escapes."""
    n = len(sql)
    before = sql[i - 1] if i else " "
    before2 = sql[i - 2] if i > 1 else " "
    backslash_escapes = before in "eE" and not (before2.isalnum() or before2 == "_")
    i += 1
    while i < n:
        if backslash_escapes and sql[i] == "\\":
            i += 2
            continue
        if sql[i] == "'":
            if sql.startswith("''", i):
                i += 2
                continue
            break
        i += 1
    return i + 1


def _skip_double_quoted(sql: str, i: int) -> int:
    """Past a double-quoted identifier."""
    n = len(sql)
    i += 1
    while i < n:
        if sql[i] == '"':
            if sql.startswith('""', i):
                i += 2
                continue
            break
        i += 1
    return i + 1


def _skip_dollar_quoted(sql: str, i: int) -> "int | None":
    """Past a dollar-quoted body, or None where this `$` does not open one (a `$1` parameter, or a `$`
    inside a word)."""
    prev = sql[i - 1] if i else " "
    if prev.isalnum() or prev in "_$":
        return None
    m = _DOLLAR_TAG.match(sql, i)
    if not m:
        return None
    tag = m.group(0)
    end = sql.find(tag, m.end())
    return len(sql) if end == -1 else end + len(tag)


# `$tag$`, where the tag may not start with a digit (`$1` is a parameter, not a quote).
_DOLLAR_TAG = re.compile(r"\$(?:[A-Za-z_\u0080-\U0010ffff][A-Za-z_0-9\u0080-\U0010ffff]*)?\$")

# A statement that is transaction control. END is COMMIT's synonym.
_OWN_TRANSACTION = re.compile(
    r"^(BEGIN|START\s+TRANSACTION|COMMIT|END|ROLLBACK|ABORT|PREPARE\s+TRANSACTION)\b", re.I)

# What PostgreSQL refuses, or quietly changes the meaning of, inside a transaction
# block. (pattern, True if it is matched against each STATEMENT's start and False
# if it is looked for anywhere in the code, reason).
_NOT_WRAPPABLE = (
    (re.compile(r"\bCONCURRENTLY\b", re.I), False,
     "it uses CONCURRENTLY, which cannot run inside a transaction block"),
    (re.compile(r"^(VACUUM|CLUSTER|CREATE\s+DATABASE|DROP\s+DATABASE|CREATE\s+TABLESPACE|"
                r"DROP\s+TABLESPACE|ALTER\s+SYSTEM|REINDEX\s+(DATABASE|SYSTEM))\b", re.I), True,
     "it runs a statement PostgreSQL refuses inside a transaction block"),
    (re.compile(r"^ALTER\s+TYPE\b.*?\bADD\s+VALUE\b", re.I | re.S), True,
     "ALTER TYPE ... ADD VALUE: the new value cannot be used until the transaction ends"),
)

# A SQL-standard function body (PostgreSQL 14+). Its `;`-separated statements end
# in a bare END, which is not transaction control; the scanner does not try to tell
# the two apart and the file is left unwrapped, with that reason.
_BEGIN_ATOMIC = re.compile(r"\bBEGIN\s+ATOMIC\b", re.I)


@dataclass(frozen=True)
class TransactionPlan:
    """Whether the runner wraps a file in one transaction, and if not, why not."""
    wrap: bool
    reason: str = ""


def transaction_plan(name: str, sql: str) -> TransactionPlan:
    """Decide how one migration is run. See the module docstring's ATOMICITY.

    The order is the order of cost-of-being-wrong: a baseline file first (its
    partial effects are load-bearing), then the explicit opt-out, then the
    file's own transaction control, then the statements that cannot be wrapped.
    """
    if name in BASELINE_FAILURES:
        return TransactionPlan(False, "a baseline failure keeps its legacy partial-apply behaviour")
    if NO_TRANSACTION_MARKER.search(sql):
        return TransactionPlan(False, "it opts out with `-- migration: no-transaction`")
    code = strip_sql(sql)
    # First, because the END that closes a BEGIN ATOMIC body would otherwise be
    # read as a COMMIT and the file given the wrong reason.
    if _BEGIN_ATOMIC.search(code):
        return TransactionPlan(False, "it has a BEGIN ATOMIC body, which this scanner does not split safely")
    statements = [stmt.strip() for stmt in code.split(";")]
    if any(_OWN_TRANSACTION.match(stmt) for stmt in statements):
        return TransactionPlan(False, "it carries its own transaction control (BEGIN/COMMIT)")
    for pattern, per_statement, why in _NOT_WRAPPABLE:
        hit = (any(pattern.match(stmt) for stmt in statements) if per_statement
               else pattern.search(code))
        if hit:
            return TransactionPlan(False, why)
    return TransactionPlan(True)


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
    # Migrations this run APPLIED without a wrapping transaction, and the reason.
    # An applied file that is not here ran atomically.
    not_atomic: dict[str, str] = field(default_factory=dict)

    @property
    def unresolved_failures(self) -> list[str]:
        """Remembered failures somebody has not dealt with: every one that
        BASELINE_FAILURES does not name. The baseline is the tolerated debt, and
        it is the only thing that is."""
        return [n for n in self.skipped_failed_before if n not in BASELINE_FAILURES]

    @property
    def ok(self) -> bool:
        # A failure remembered from an EARLIER run is still a failure. "Not
        # retried blindly" is right, and it used to mean "not reported" as well:
        # after one red run the next push skipped the broken file, applied what
        # it could and exited 0, with the change still unapplied in production.
        return not self.failed and not self.unresolved_failures


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

    A REMEMBERED FAILURE KEEPS THE RUN RED, AND THAT IS THE OTHER HALF

    "Not attempted again" used to mean "not reported again". The first push after
    a failure exited non-zero; the NEXT push skipped the broken file with one line
    on stderr, applied whatever else was pending and exited 0, so a pipeline that
    had been red for the one commit that mattered went green with that change
    still unapplied in production. `RunReport.ok` now counts a remembered failure
    unless BASELINE_FAILURES names it, so the pipeline stays red until somebody
    fixes the file or retries it. The run still CONTINUES past the remembered
    file (it applies what is pending, as before): stopping would hold every later
    migration hostage to one broken file, which is a different and larger
    decision than reporting it.

    AND THE FIRST HALF OF THE SAME PARAGRAPH IS NOW TRUE OF NOTHING NEW. Written
    when psql ran WITHOUT --single-transaction, so the statements before a
    failing one committed; a file that fails now rolls back whole (see the module
    docstring's ATOMICITY), which is what makes "remembered, not retried" safe on
    the live database: the broken file left nothing behind to be re-applied. The
    legacy behaviour survives for BASELINE_FAILURES alone, by design.
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
                  "run; edit it or pass --retry-failed"
                  + ("" if mig.name in BASELINE_FAILURES else
                     ". Until then this run FAILS: a change that is not applied is not "
                     "a green pipeline"), file=sys.stderr)
            continue
        if dry_run:
            report.applied.append(mig.name)
            # A dry run says how each file WOULD run, so an author sees that a
            # new migration is going to be wrapped (or why it is not) before merge.
            dry_plan = transaction_plan(mig.name, mig.path.read_text(encoding="utf-8"))
            if not dry_plan.wrap:
                report.not_atomic[mig.name] = dry_plan.reason
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
        #
        # ATOMIC UNLESS THERE IS A REASON NOT TO BE (see transaction_plan). Without
        # --single-transaction a file that fails on its third statement has already
        # COMMITTED the first two, so a half-applied change to the live database
        # stays there and — because a failure is remembered and not retried — stays
        # there for good. Inside one transaction the file's statements and its
        # schema_migrations row stand or fall together.
        sql = mig.path.read_text(encoding="utf-8")
        plan = transaction_plan(mig.name, sql)
        safe_name = mig.name.replace("'", "''")  # filenames are repo-controlled; escape defensively
        r = _psql(dsn, ["-f", "-"] + (["--single-transaction"] if plan.wrap else []), input_sql=(
            sql
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
        if not plan.wrap:
            report.not_atomic[mig.name] = plan.reason

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
            "unresolved_failures": report.unresolved_failures,
            "failed": report.failed,
            "duplicate_numbers": report.duplicate_numbers,
            "not_atomic": report.not_atomic,
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
        for name in report.unresolved_failures:
            print(f"  FAILED EARLIER, STILL UNAPPLIED {name}")

    annotate(report)
    return 0 if report.ok else 1


def annotate(report: RunReport, stream=None) -> None:
    """One GitHub error annotation per failure and per remembered failure.

    The job log of a run that exits 1 says so in a red line at the bottom; an
    annotation puts the FILE NAME on the run's summary page, where the person
    who has to act looks first. Written to STDERR on purpose: stdout is the
    --json document, and the real-Postgres harness parses it from a process that
    inherits GITHUB_ACTIONS, so a workflow command on stdout would make that
    JSON unreadable. Only under Actions; elsewhere the text report is the story.
    """
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    stream = stream or sys.stderr
    for f in report.failed:
        print("::error title=Migration failed::"
              + _annotation_text(f"{f['file']}: {f['error']}"), file=stream)
    for name in report.unresolved_failures:
        print("::error title=Migration failed earlier and is still unapplied::"
              + _annotation_text(
                  f"{name} failed on an earlier run at this checksum and has not been retried. "
                  "Fix it (a new checksum runs again) or re-run with --retry-failed; "
                  "see docs/deploy-migrations.md"), file=stream)


def _annotation_text(text: str) -> str:
    """A workflow command ends at the newline, and % and CR are its escapes."""
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")[:500]


if __name__ == "__main__":
    raise SystemExit(main())
