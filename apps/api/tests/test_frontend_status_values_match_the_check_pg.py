"""
A status a screen writes or compares must be one the CHECK constraint allows.

WHY THIS EXISTS
    tests/test_frontend_columns_exist_pg.py checks that the COLUMNS a screen
    names exist. It cannot see the VALUES, and a status vocabulary drifts the
    same way a column name does — silently, and in both directions:

      * WRITTEN: the database refuses the row. On the API path the refusal is
        usually swallowed into an HTTP 200 carrying {success: false}; over
        PostgREST it is an error object the caller often does not read. Either
        way the screen closes its panel and reloads an unchanged list.
      * COMPARED: nothing matches, so a counter reads 0 and a badge renders with
        no class. Nothing errors. Nothing is logged.

    Both shipped, in the same module. app/tds/page.tsx declared
    `status: "Pending" | "Filed" | "Overdue"` for tds_returns, whose CHECK
    stores 'pending','prepared','ca_approved','filed','revised' — so the three
    counters on the Returns tab were permanently 0/0/0 (TDS-15). And the client
    TDS screen sent certificate_type "Form 16A" where migration 037 accepts
    '16A', so every certificate draft was rejected outright (TDS-04).

HOW IT DECIDES, AND WHERE IT IS DELIBERATELY BLUNT
    Per FILE: the tables it reads via .from("t"), the union of the values every
    CHECK on a `status` column of those tables allows, and every `.status ===`
    comparison and `status: "…"` literal in the file. It reports a value only
    when NO table the file reads allows it.

    That union is imprecise on purpose. A file reading six tables gets a
    generous allowance, and a `status` on a client-computed object (a derived
    "due-soon", a local UI state) is not a database value at all and can be
    flagged wrongly. A precise version would need to resolve which table each
    object came from, which needs type inference this cannot do.

    Blunt in the SAFE direction: it under-reports rather than over-reports on
    the tables, and everything it does report is at least a vocabulary a reader
    of that file would have to check by hand. KNOWN below carries what it
    currently finds so the number can only fall.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode CI job.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
WEB = API_ROOT.parents[1] / "apps" / "web"
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists() or not WEB.exists(),
    reason="frontend status-vocabulary check requires HARNESS_PG + psql + apps/web",
)

# Files this check currently reports, with the values it reports, recorded on
# 2026-09-09 against the state of the tree at that date.
#
# NOT TRIAGED, and the entry says so rather than pretending otherwise. Each
# belongs to its own module's phase in docs/audits/2026-09-08c-the-phase-plan.md
# — the TDS screens were fixed in Phase 3 because Phase 3 is the TDS phase, and
# fixing eleven files across GST, MCA, sales, payroll and lifecycle inside it
# would be the scope creep that plan exists to prevent.
#
# ONE OF THEM IS CONFIRMED REAL and is called out because it is the same defect
# as TDS-04, not a heuristic's guess: app/mca/page.tsx UPDATEs mca_filings with
# status "Filed" while that table's CHECK accepts 'filed'. The row is rejected
# by the database, so marking an ROC filing as filed does nothing.
#
# A ratchet, not an exemption: test_no_known_entry_is_stale fails the moment a
# file stops reporting, so this list can only shrink.
KNOWN: dict[str, set[str]] = {
    "app/accounting/recurring/page.tsx": {"Active", "Paused", "posted"},
    "app/client-portal/page.tsx": {"overdue", "posted"},
    "app/clients/[id]/accounting/page.tsx": {"failed"},
    "app/clients/[id]/lifecycle/page.tsx": {"done", "skipped"},
    "app/clients/[id]/purchases/page.tsx": {"resident"},
    # "active" and "archived" left this list on 2026-09-09, and the reason is
    # worth keeping: they were never a real report. They are
    # recurring_invoice_templates.status values, and the scanner attributed
    # them to a table whose CHECK does not allow them because _skip_args ran on
    # past the query they belong to — an apostrophe inside a comment in a
    # payload had desynchronised it (see _frontend_select_parser.blank_comments).
    # Blanking comments before the walk removed the false positive.
    "app/clients/[id]/sales/page.tsx": {"failed", "generated", "paused"},
    "app/gst/page.tsx": {"Filed", "Overdue", "Pending", "pending"},
    "app/income-tax/page.tsx": {"filed", "pending"},
    "app/mca/page.tsx": {"Filed", "Overdue", "Pending"},
    "app/payroll/declarations/page.tsx": {"rejected", "verified"},
    "app/payroll/reports/page.tsx": {"due-soon", "overdue"},
}

_SKIP_DIRS = {"node_modules", ".next", "out", ".vercel"}
_FROM = re.compile(r'\.from\("([a-z_0-9]+)"\)')
_COMPARE = re.compile(r'\.status\s*(?:===|!==)\s*"([^"]+)"')
_WRITE = re.compile(r'status:\s*"([^"]+)"')


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-tA",
                           "-F", "\t", "-c", sql], capture_output=True, text=True)


def _blank(text: str) -> str:
    return re.sub(r"[^\n]", " ", text)


def _strip_comments(src: str) -> str:
    """Comments blanked, line numbers preserved.

    Required, not tidy: the note left where each wrong value used to be quotes
    the wrong value, so a scan that read comments would report the
    documentation of its own fix. `//` is only a comment when not preceded by a
    colon, so `https://` inside a string survives."""
    src = re.sub(r"/\*[\s\S]*?\*/", lambda m: _blank(m.group(0)), src)
    return re.sub(r'(^|[^:])//[^\n]*',
                  lambda m: m.group(1) + _blank(m.group(0)[len(m.group(1)):]), src)


@pytest.fixture(scope="module")
def allowed_status(pg_template):
    """(table, 'status') → the values its CHECK accepts, from the real schema."""
    admin = _ADMIN.strip()
    name = f"statusvocab_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        r = _psql(dsn, """
            SELECT c.relname, pg_get_constraintdef(con.oid)
              FROM pg_constraint con
              JOIN pg_class c ON c.oid = con.conrelid
              JOIN pg_namespace n ON n.oid = c.relnamespace
              JOIN unnest(con.conkey) k(attnum) ON true
              JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = k.attnum
             WHERE n.nspname = 'public' AND con.contype = 'c'
               AND array_length(con.conkey, 1) = 1 AND a.attname = 'status';
        """)
        assert r.returncode == 0, r.stderr
        out: dict[str, set[str]] = {}
        for line in r.stdout.strip().splitlines():
            if "\t" not in line:
                continue
            table, defn = line.split("\t", 1)
            values = set(re.findall(r"'([^']*)'::text", defn))
            if values:
                out.setdefault(table, set()).update(values)
        assert out, "no status CHECK constraints found — the fixture is broken"
        yield out
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _reports(allowed: dict[str, set[str]]) -> dict[str, set[str]]:
    """relpath → the status values that file uses and no table it reads allows."""
    found: dict[str, set[str]] = {}
    for path in sorted(WEB.rglob("*.ts*")):
        parts = set(path.relative_to(WEB).parts)
        if parts & _SKIP_DIRS or path.name.endswith(".test.ts"):
            continue
        src = _strip_comments(path.read_text(encoding="utf-8", errors="ignore"))
        tables = set(_FROM.findall(src))
        if not tables:
            continue                      # not a database screen; its status is its own
        union: set[str] = set()
        for t in tables:
            union |= allowed.get(t, set())
        if not union:
            continue                      # no CHECK to measure against
        used = {m.group(1) for m in _COMPARE.finditer(src)}
        used |= {m.group(1) for m in _WRITE.finditer(src)}
        outside = used - union
        if outside:
            found[str(path.relative_to(WEB))] = outside
    return found


def test_no_new_screen_uses_a_status_the_check_forbids(allowed_status):
    reports = _reports(allowed_status)
    new = {f: sorted(v - KNOWN.get(f, set())) for f, v in reports.items()}
    new = {f: v for f, v in new.items() if v}
    assert not new, (
        "these screens use a status value no table they read allows — written, "
        "the database refuses the row; compared, nothing ever matches:\n  "
        + "\n  ".join(f"{f}: {', '.join(v)}" for f, v in sorted(new.items()))
        + "\n\nUse the CHECK's own value. If the field is computed in the "
          "browser and is not a database status at all, rename it so it does "
          "not read as one."
    )


def test_the_tds_screens_are_clean(allowed_status):
    """Phase 3's own result, pinned. These are the two files TDS-15 and TDS-04
    were about, and they must never re-enter KNOWN."""
    reports = _reports(allowed_status)
    for f in ("app/tds/page.tsx", "app/clients/[id]/compliance/tds/page.tsx"):
        assert f not in reports, (
            f"{f} is using a status value the CHECK forbids again: "
            f"{sorted(reports[f])}")
        assert f not in KNOWN, f"{f} must not be given an exemption"


def test_no_known_entry_is_stale(allowed_status):
    """A ratchet only ratchets if a fixed file has to leave it."""
    reports = _reports(allowed_status)
    stale = sorted(f for f in KNOWN if f not in reports)
    assert not stale, (
        "these files no longer report — delete their KNOWN entries so the list "
        f"keeps shrinking: {stale}")
    narrowed = {f: sorted(KNOWN[f] - reports.get(f, set()))
                for f in KNOWN if KNOWN[f] - reports.get(f, set())}
    assert not narrowed, (
        "these KNOWN values are no longer used — remove them individually, so "
        f"a partial fix is recorded rather than lost: {narrowed}")


def test_the_scan_still_sees_the_files_it_is_meant_to_police(allowed_status):
    """A scanner that silently stops matching keeps passing while checking
    nothing. Assert it still reads a real population."""
    screens = [p for p in WEB.rglob("*.ts*")
               if not (set(p.relative_to(WEB).parts) & _SKIP_DIRS)
               and '.from("' in p.read_text(encoding="utf-8", errors="ignore")]
    assert len(screens) >= 50, (
        f"only {len(screens)} files read a table — the scan has stopped matching")
