"""
Shared pytest fixtures.

Production now defaults REPORTING_PASSBOOK_MODE to "on" — the reporting passbook
(account_period_balances) is backfilled, trigger-maintained, and verified
paise-identical to the raw ledger, so accrual reports serve from it by default
(with automatic fall-back to the legacy engine on any error).

Tests, however, run against in-memory / fake-DB doubles that have no
account_period_balances rows, so they must exercise the LEGACY engine unless a
test opts into the passbook explicitly. This autouse fixture forces the mode to
"off" for every test; the passbook tests (test_passbook_read_path) call
monkeypatch.setenv(...) inside the test body, which runs after this fixture and
therefore overrides it.
"""
import pytest


@pytest.fixture(autouse=True)
def _passbook_off_by_default(monkeypatch):
    monkeypatch.setenv("REPORTING_PASSBOOK_MODE", "off")


@pytest.fixture
def dev_header_auth(monkeypatch):
    """Opt in to the documented dev/test auth mode: X-User-Role / X-Firm-Id /
    X-User-Id headers stand in for a Supabase JWT.

    core.auth.get_current_user only honours those headers when SUPABASE_URL is
    unset AND APP_ENV=development — the second condition is what stops a
    production deployment from being spoofed by anyone who can set a header.
    That gate is correct and is deliberately NOT relaxed; tests that want the
    dev mode ask for it here, per module.

    Deliberately a fixture rather than an autouse/global setting, because
    APP_ENV=development is not auth-only: year_end_exports.py swallows a
    Storage upload failure instead of raising 500 under it. Turning it on for
    the whole suite would silently move every export test onto that path.

    Most test modules here don't need this at all — they override
    app.dependency_overrides[get_current_user] instead, which is the dominant
    convention (38 of the 43 TestClient modules). This fixture exists for the
    handful written against the header mode, where the point of the test is to
    vary the CALLER'S ROLE per request (partner vs manager vs executive) and a
    header is the natural way to say that.
    """
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("SUPABASE_URL", raising=False)


# ── Real-Postgres harness: build the migrated schema ONCE per session ────────
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

_API_ROOT = Path(__file__).resolve().parents[1]
_RUNNER = _API_ROOT / "scripts" / "db" / "apply_migrations.py"
_HARNESS_PG = os.environ.get("HARNESS_PG")


def _tpl_psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql],
        capture_output=True, text=True,
    )


class PgTemplate:
    """Handle on the session's pre-migrated template database.

    `name`   — database to clone with CREATE DATABASE ... TEMPLATE
    `failed` — set of migration filenames that failed to apply, from the single
               runner invocation; the per-file drift assertions read this.
    """

    __slots__ = ("name", "failed", "report")

    def __init__(self, name: str, failed: set, report: dict):
        self.name = name
        self.failed = failed
        self.report = report


@pytest.fixture(scope="session")
def pg_template():
    """Apply the full migration set exactly once, into a template database.

    Every tests/test_*_pg.py fixture used to CREATE DATABASE and then replay the
    whole migration set (~250 files) for EVERY test — ~25s of setup each, and at
    109 such tests that is ~40 minutes of CI spent rebuilding the same schema.
    Postgres copies a database at the file level (CREATE DATABASE ... TEMPLATE)
    in about a second, so the migrations are applied once here and each test
    clones the result.

    Isolation is UNCHANGED: every test still gets its own brand-new database
    that no other test can see or touch. Only how it is populated changed — and
    because the clone is a byte copy of a freshly-migrated database, what each
    test starts from is identical to what it started from before.
    """
    if not _HARNESS_PG or shutil.which("psql") is None or not _RUNNER.exists():
        pytest.skip("real-Postgres harness requires HARNESS_PG + psql")

    admin = _HARNESS_PG.strip()
    admin_dsn = f"{admin} dbname=postgres"
    name = f"caflow_tpl_{uuid.uuid4().hex[:12]}"

    if _tpl_psql(admin_dsn, f'CREATE DATABASE "{name}";').returncode != 0:
        pytest.skip("could not create the template database")

    try:
        proc = subprocess.run(
            [sys.executable, str(_RUNNER), "--dsn", f"{admin} dbname={name}",
             "--with-compat", "--only-schema", "--continue-on-error", "--json"],
            capture_output=True, text=True, cwd=str(_API_ROOT),
        )
        report = json.loads(proc.stdout)
        yield PgTemplate(name, {f["file"] for f in report["failed"]}, report)
    finally:
        # FORCE: the runner's connection is closed by now, but a failed test can
        # leave a stray session attached, and a template with any connection
        # cannot be dropped.
        _tpl_psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')
