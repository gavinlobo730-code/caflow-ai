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


@pytest.fixture(autouse=True)
def _practice_mail_is_on_for_the_suite(monkeypatch):
    """Production leaves PRACTICE_MAIL_ENABLED unset, which is OFF. The mail tests
    exercise the mail itself, so they run with it on; the tests of the switch
    delete the variable inside the test body, which runs after this fixture."""
    monkeypatch.setenv("PRACTICE_MAIL_ENABLED", "true")


@pytest.fixture(autouse=True)
def _the_public_rate_windows_are_fresh_for_every_test():
    """The per-address windows on the routes that need no login (middleware/public_rate_limit, ops-30) are
    process-wide, and every TestClient request comes from the same address. Without this a test that spends
    a bucket would starve whichever test happens to use it next, in a worker that ran both."""
    from middleware import public_rate_limit
    public_rate_limit.reset()
    yield
    public_rate_limit.reset()


@pytest.fixture(autouse=True)
def _the_year_lock_pin_attempt_windows_are_fresh_for_every_test():
    """The attempts counted against the year-lock PIN (services/year_lock_service, POST-A-004) are process-wide:
    a test that spends them on purpose would otherwise leave a worker's next test refused with a 429."""
    from services import year_lock_service
    year_lock_service.reset_pin_attempts()
    yield
    year_lock_service.reset_pin_attempts()


@pytest.fixture(autouse=True)
def _no_schema_drift_watch_outlives_its_test():
    """The schema-drift re-check (core/schema_guard.start_drift_watch, ops-19) is a
    daemon thread that asks the database again every two minutes. Under test it only
    starts where SUPABASE_URL is set, but some modules set that for their own
    purposes, and a thread left running would go on mutating the verdict /health
    reads in whichever test happens to be running two minutes later."""
    yield
    from core import schema_guard
    schema_guard.stop_drift_watch(timeout=1.0)


# ── a monkeypatch of a METHOD on an instance must not leave the instance holding the method (POST-A-034) ──────────
#
# `monkeypatch.setattr(instance, "method", stub)` records the old value with `getattr`, which for a method the INSTANCE only
# inherits is the bound method, and puts it back with `setattr`: the instance ends the test holding an attribute of its own that
# shadows the class's, for the rest of the process. A later test that patches the same method on the CLASS (the only way to reach
# every instance a router builds for itself) is then ignored by that instance. CI runs `pytest -n auto --dist loadfile`, where which
# files share a worker is not chosen, and a run that spread the tests one by one (`--dist load`, the order-dependence hunt of
# POST-A-034) found it: `test_a_year_of_depreciation_is_one_request` patched `fa._journal_svc.journal_for_depreciation`, and two
# tests that patch `Phase2JournalService.journal_for_depreciation` then failed with "DID NOT RAISE" on whichever worker had run it.
# So an instance patch of an inherited attribute is undone with `delattr`, which is what the author meant by "put it back".
import pytest as _pytest_for_the_undo
try:                                               # pytest 8 and later keep the sentinel here
    from _pytest.compat import NOTSET as _notset
except ImportError:                                # pragma: no cover - an older pytest
    from _pytest.monkeypatch import notset as _notset

_real_monkeypatch_setattr = _pytest_for_the_undo.MonkeyPatch.setattr


def _setattr_that_undoes_an_inherited_attribute_by_deleting_it(self, target, name, value=_notset, raising=True):
    inherited_only = (
        value is not _notset
        and not isinstance(target, (str, type))
        and not hasattr(target, "__path__") and type(target).__name__ != "module"
        and isinstance(name, str)
        and name not in getattr(target, "__dict__", {})
        and hasattr(type(target), name)
    )
    _real_monkeypatch_setattr(self, target, name, value, raising)
    if inherited_only and self._setattr and self._setattr[-1][0] is target and self._setattr[-1][1] == name:
        self._setattr[-1] = (target, name, _notset)


_pytest_for_the_undo.MonkeyPatch.setattr = _setattr_that_undoes_an_inherited_attribute_by_deleting_it


# The modules whose module-level singleton a test module reloads away. `importlib.reload` re-runs the module in the
# SAME module object, so `phase2_journal_service = Phase2JournalService()` builds a NEW instance: a test module that
# imported the old one at collection keeps it, while application code that imports it inside a function at call time
# gets the new one, and a monkeypatch on the first never reaches the second.
_RELOADED_SINGLETONS = {
    "services.phase2_journal_service": "phase2_journal_service",
    "services.period_validation_service": "period_validation_service",
    "services.timeline_service": "timeline_service",
}
_original_singletons: dict = {}


@pytest.fixture(autouse=True)
def _a_reloaded_service_module_leaves_the_same_singleton_behind():
    """Four test modules (test_phase2_journal_key_resolution, test_phase2_stabilization,
    test_the_employer_contribution_is_its_own_expense_head, the compensation-cess one) reload the journal service to
    force it out of mock mode, and reload it again at the end to restore `_USE_MOCK`. The second reload restores the
    FLAG and not the OBJECT, so every module that ran after one of them and had patched the singleton it imported at
    collection (test_batch3_1_hardening patches `journal_for_sales_invoice`) saw its patch ignored.

    Serially that never showed, because the alphabetical order puts those modules after the ones they break. It showed
    the day the suite ran in parallel (`-n auto --dist loadfile`, engineering-21), where which modules share a worker
    changes from run to run. A required check that fails on the grouping is not a check, so the first test of a
    process records each singleton and every later test starts with that same object back. The reload itself is left
    alone: its tests need it, and what they need is the module, not a new singleton for everybody else."""
    import importlib

    for module_name, attr in _RELOADED_SINGLETONS.items():
        module = importlib.import_module(module_name)
        if module_name not in _original_singletons:
            _original_singletons[module_name] = getattr(module, attr)
        elif getattr(module, attr) is not _original_singletons[module_name]:
            setattr(module, attr, _original_singletons[module_name])
    yield


@pytest.fixture(autouse=True)
def _ai_rate_limit_windows_start_empty():
    """The limiter's windows are process-wide. Without this, the dozen tests that
    upload an invoice for the same firm id would exhaust the extraction bucket
    and the next one would get a 429 for a reason nothing in it is about."""
    from middleware import rate_limit
    rate_limit.reset()
    yield
    rate_limit.reset()


@pytest.fixture(autouse=True)
def _sentry_breadcrumbs_do_not_cross_from_one_test_to_the_next():
    """A breadcrumb recorded in one test is on the event of a later one.

    Breadcrumbs live on the SDK's scopes, which belong to the process and not to a client, and `sentry_sdk.init()` (the way the suites
    switch the client off again) does not empty them. Once any test has left default integrations switched on, a later `subprocess` or
    `logging` call adds a breadcrumb, and the next event another test captures carries it. Found in CI on 29-10-2026: the browser-rule
    test that runs `node` with a PAN on its command line left a breadcrumb, and `test_no_stack_frame_carries_its_local_variables`, which
    holds that the PAN is nowhere in its event, failed when the two landed on one worker. Passing alone, and in most groupings, is what
    made it a flake and not a failure; the scopes are emptied around every test so the grouping stops mattering.
    """
    import sentry_sdk

    def empty():
        for scope in (sentry_sdk.get_global_scope(), sentry_sdk.get_isolation_scope(), sentry_sdk.get_current_scope()):
            scope.clear_breadcrumbs()

    empty()
    yield
    empty()


@pytest.fixture(autouse=True)
def ai_usage_events(monkeypatch):
    """The AI gateway's pauses and usage rows, kept out of the suite.

    A retry backs off by sleeping and every model attempt writes a usage row; in
    a test the first would make a failing-provider fake cost seconds and the
    second would try the database whenever a module sets SUPABASE_URL. So the
    pauses are RECORDED instead of waited out (`ai_usage_events.sleeps`) and the
    rows are COLLECTED instead of written (the fixture is the list of
    `UsageEvent`s). A test of the policy itself reads both.
    """
    from domain.ai import gateway

    class _Events(list):
        sleeps: list

    events = _Events()
    events.sleeps = []

    async def _sleep_async(seconds):
        events.sleeps.append(seconds)

    monkeypatch.setattr(gateway, "sleep_async", _sleep_async)
    monkeypatch.setattr(gateway, "sleep_sync", lambda seconds: events.sleeps.append(seconds))
    gateway.set_sink(events.append)
    # What the gateway has SEEN a provider do is process-wide memory (ai-06); without
    # this a test that made a call would leave `/health` saying "ok" for the next.
    gateway.reset_health()
    # No firm has a monthly allowance unless a test gives it one: the gate must not go
    # to a database in the dozens of tests that set SUPABASE_URL, and its per-firm cache
    # is process-wide.
    from domain.ai import budget, budget_gate
    budget_gate.reset()
    budget_gate.set_fetcher(lambda firm_id, month: (budget.Limits(), budget.Used()))
    yield events
    gateway.set_sink(None)
    gateway.reset_health()
    budget_gate.set_fetcher(None)
    budget_gate.reset()


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


#: The cluster-wide roles `migrations/_supabase_compat_bootstrap.sql` stubs. A role belongs to the CLUSTER and not to a database, so
#: when the real-Postgres suite runs on several workers at once (`-n`), every worker's template build runs the bootstrap against one
#: fresh cluster at the same moment and two of them can both find a role missing and both create it. They are created here, once,
#: under a lock, before any worker builds its template; the bootstrap then finds them and does nothing. The statements are the
#: bootstrap's own (`tests/test_the_cluster_roles_are_created_before_the_workers_build_their_templates.py` holds the two together).
_ROLES_SQL = """
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
    CREATE ROLE anon NOLOGIN NOINHERIT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
    CREATE ROLE authenticated NOLOGIN NOINHERIT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
    CREATE ROLE service_role NOLOGIN NOINHERIT BYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticator') THEN
    CREATE ROLE authenticator NOINHERIT LOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'supabase_storage_admin') THEN
    CREATE ROLE supabase_storage_admin NOLOGIN NOINHERIT;
  END IF;
END
$$;
GRANT anon, authenticated, service_role TO authenticator;
"""


def _ensure_cluster_roles(admin_dsn: str) -> None:
    """Create the cluster-wide roles once, under a file lock shared by every worker of this machine. A failure is not raised: the
    bootstrap in the template build creates the same roles and reports its own error if they cannot be had."""
    import fcntl
    import hashlib
    import tempfile
    key = hashlib.sha1(admin_dsn.encode()).hexdigest()[:12]
    with open(Path(tempfile.gettempdir()) / f"caflow_pg_roles_{key}.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            _tpl_psql(admin_dsn, _ROLES_SQL)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


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

    _ensure_cluster_roles(admin_dsn)
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
