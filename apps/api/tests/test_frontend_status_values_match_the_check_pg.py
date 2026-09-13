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

    AND WHERE IT CANNOT SEE AT ALL, IT SAYS SO. A file whose tables carry no
    `status` CHECK has an empty union, so it is skipped — meaning a file can
    leave KNOWN by losing its last measurable table instead of by being fixed,
    which is what moving a screen onto the API does. UNMEASURED records those,
    asserted in both directions, so a drop in coverage cannot read as progress.

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
    "app/client-portal/page.tsx": {"overdue", "posted"},
    "app/clients/[id]/accounting/page.tsx": {"failed"},
    "app/clients/[id]/lifecycle/page.tsx": {"done", "skipped"},
    # "resident" left this list on 2026-09-12, and it was never a report worth
    # having: line 1217 declares
    #     residential_status: "resident" | "non_resident" | null;
    # which is a TYPE ANNOTATION on a DIFFERENT FIELD — `status:` matched the
    # tail of `residential_status:`. Two heuristic misfires in one line. The
    # first is fixed in _WRITE below; the second is recorded as a limitation.
    # "active" and "archived" left this list on 2026-09-09, and the reason is
    # worth keeping: they were never a real report. They are
    # recurring_invoice_templates.status values, and the scanner attributed
    # them to a table whose CHECK does not allow them because _skip_args ran on
    # past the query they belong to — an apostrophe inside a comment in a
    # payload had desynchronised it (see _frontend_select_parser.blank_comments).
    # Blanking comments before the walk removed the false positive.
    "app/clients/[id]/sales/page.tsx": {"failed", "generated", "paused"},
    "app/mca/page.tsx": {"Filed", "Overdue", "Pending"},
    "app/payroll/declarations/page.tsx": {"rejected", "verified"},
    "app/payroll/reports/page.tsx": {"due-soon", "overdue"},
}

#: Files that READ a table and USE a status literal, but whose tables carry no
#: `status` CHECK — so this check has nothing to measure them against.
#:
#: WHY THIS LIST EXISTS, AND IT IS NOT A SECOND EXEMPTION. `_scan` skips a file
#: with an empty union, which means a file can LEAVE the KNOWN ratchet above by
#: going blind rather than by being fixed — and "the list can only shrink" then
#: stops being true. That is not hypothetical: it happened on 13-09-2026.
#: Replacing eleven hand-rolled copies of `getFirmId` with the shared cached one
#: removed the last `.from("users")` read from `app/gst/page.tsx` and
#: `app/income-tax/page.tsx`. `users.status` was the ONLY status CHECK either
#: file had ever been measured against — neither has anything to do with a
#: user's status — so both silently stopped reporting, and
#: test_no_known_entry_is_stale asked for their entries to be deleted as though
#: three real defects had been fixed.
#:
#: Recording them keeps the fact visible: these files use a status vocabulary
#: nothing checks. Growing this list is a REGRESSION in coverage even when it
#: comes from good work elsewhere, so it is asserted in both directions.
#:
#: FIVE OF THE SEVEN WERE ALREADY BLIND before that change and nobody knew,
#: which is the better argument for the list than the two that arrived with it.
#:
#: Every entry below was checked by hand against the table that really holds the
#: value, and all seven are correct today. That is the point: the check could
#: not have told anyone so, and cannot tell anyone when one stops being correct.
UNMEASURED: dict[str, set[str]] = {
    # recurring_journal_templates.status ('active'|'paused'|'archived') and
    # recurring_journal_runs.status ('generated'|'skipped'|'failed'), migration
    # 377. The screen reads both through GET /api/recurring-journals and touches
    # only chart_of_accounts directly, which has no status column.
    "app/accounting/recurring/page.tsx": {"active", "generated"},
    # recurring_purchase_bill_templates.status ('active'|'paused'|'archived')
    # and recurring_purchase_bill_runs.status ('generated'|'skipped'|'failed'),
    # migration 379 — the same shape as the recurring-journal screen above, and
    # for the same reason. The component reads both through
    # GET /api/recurring-purchase-bills and touches only `vendors` and
    # `service_catalogue` directly, to fill two dropdowns; neither has a status
    # column, so there is nothing here to measure against. Checked by hand
    # against migration 379's two CHECKs on 2026-09-13.
    "components/purchases/RecurringBills.tsx": {"active", "archived", "failed", "paused"},
    # mca_filings.status allows all three; the page reads mca_companies only.
    "app/clients/[id]/compliance/mca/page.tsx": {"filed", "in_progress", "not_started"},
    # compliance_tasks.status allows 'filed'; the page reads government_notices.
    "app/clients/[id]/compliance/page.tsx": {"filed"},
    # `GSTFiling.status` is DERIVED in the browser by computeOverdueStatus and
    # never written — compliance_calendar has no `status` column at all, and the
    # column the screen does write is `filing_status`, whose 'pending' is
    # reported here only through the documented `status:` left-boundary
    # limitation. Renaming the derived field is the real fix and is separate.
    "app/gst/page.tsx": {"Filed", "Overdue", "Pending", "pending"},
    # Same shape as the GST screen, lower-cased; compliance_tasks allows both.
    "app/income-tax/page.tsx": {"filed", "pending"},
    # client_sales_invoices.status and purchase_bills.status both allow 'draft'.
    # Each editor reads service_catalogue, which has no status column.
    "components/invoices/InvoiceEditor.tsx": {"draft"},
    "components/purchases/PurchaseBillEditor.tsx": {"draft"},
}

_SKIP_DIRS = {"node_modules", ".next", "out", ".vercel"}
_FROM = re.compile(r'\.from\("([a-z_0-9]+)"\)')
_COMPARE = re.compile(r'\.status\s*(?:===|!==)\s*"([^"]+)"')
#: `status: "submitted"` in an OBJECT LITERAL — a value the browser sends.
#:
#: THE NEGATIVE LOOKAHEAD IS THE WHOLE OF IT, AND IT MATTERS. Without it this
#: also matches a TypeScript TYPE ANNOTATION:
#:
#:     status: "deposited" | "matched" | "unmatched";
#:
#: which is a DECLARATION of what a column holds, not a write of anything. In
#: TypeScript an object-literal property can be terminated by neither `;` nor
#: `|`, so a closing quote followed by either is a type position, never a value
#: position.
#:
#: 36 such annotations exist across apps/web against 53 real writes, and every
#: one of them was being counted. They passed only because the file declaring a
#: table's shape usually also READS that table, so the value was in the allowed
#: union anyway — a coincidence, not a check. `lib/data/tds.ts` is where it
#: stopped being one on 12-09-2026: `RecordedChallan` accurately declares
#: `tds_challans`' three CHECK values, and deleting that file's browser-side
#: `.from("tds_challans")` read (the one that fed the TDS-29 assembly) left the
#: annotation with no table to be measured against. The type is right, the
#: deletion is right, and the guard was reading a declaration as a write.
#:
#: What this deliberately still catches: every `status: "x",`, `status: "x" }`
#: and `status: "x")` — the shapes that actually cross the wire.
#:
#: ⚠️ KNOWN LIMITATION, LEFT ALONE ON PURPOSE. There is no left boundary, so
#: `status:` also matches the tail of `filing_status:`, `match_status:` and
#: `import_status:` — six files today — and their values are then measured
#: against the CHECK on a column called `status`, which is not the column they
#: write. They pass by coincidence: `filed`, `pending` and `matched` happen to
#: appear in some `status` CHECK in the union.
#:
#: A left boundary alone would be WORSE than the current state: it would stop
#: measuring those six against anything at all, when what they need is to be
#: measured against their OWN column's CHECK. Doing that properly means the
#: fixture keying every `*_status` column, not just `status`, and `_reports`
#: pairing each write with the right one. That is a real improvement and a
#: separate change; naming it here beats a half-fix that reads like a fix.
_WRITE = re.compile(r'status:\s*"([^"]+)"(?!\s*[;|])')


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


def _scan(allowed: dict[str, set[str]]) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """(reports, unmeasured).

    reports    — relpath → status values that file uses and no table it reads allows.
    unmeasured — relpath → status values in a file that DOES read a table but
                 whose tables carry no `status` CHECK, so there is nothing to
                 measure against. See test_no_file_becomes_unmeasurable_quietly.
    """
    found: dict[str, set[str]] = {}
    blind: dict[str, set[str]] = {}
    for path in sorted(WEB.rglob("*.ts*")):
        parts = set(path.relative_to(WEB).parts)
        if parts & _SKIP_DIRS or path.name.endswith(".test.ts"):
            continue
        src = _strip_comments(path.read_text(encoding="utf-8", errors="ignore"))
        tables = set(_FROM.findall(src))
        if not tables:
            continue                      # not a database screen; its status is its own
        used = {m.group(1) for m in _COMPARE.finditer(src)}
        used |= {m.group(1) for m in _WRITE.finditer(src)}
        union: set[str] = set()
        for t in tables:
            union |= allowed.get(t, set())
        if not union:
            if used:
                blind[str(path.relative_to(WEB))] = used
            continue                      # no CHECK to measure against
        outside = used - union
        if outside:
            found[str(path.relative_to(WEB))] = outside
    return found, blind


def _reports(allowed: dict[str, set[str]]) -> dict[str, set[str]]:
    return _scan(allowed)[0]


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


def test_no_file_becomes_unmeasurable_quietly(allowed_status):
    """Leaving KNOWN by going blind is not the same as being fixed.

    A file whose tables carry no `status` CHECK is skipped by `_scan`, so it
    reports nothing however wrong its values are. Deleting a table read — which
    is what moving a screen onto the API does — can therefore look exactly like
    a fix. Assert the blind set both ways: nothing new may join it, and an entry
    that stops being blind must leave.
    """
    _, blind = _scan(allowed_status)
    joined = {f: sorted(v) for f, v in blind.items() if f not in UNMEASURED}
    assert not joined, (
        "these files read a table, use a status value, and have no CHECK to be "
        "measured against — coverage went DOWN:\n  "
        + "\n  ".join(f"{f}: {', '.join(v)}" for f, v in sorted(joined.items()))
        + "\n\nEither give the value a table this check can see, or rename the "
          "field if it is computed in the browser and is not a database status. "
          "Recording it in UNMEASURED is the last resort and needs a reason."
    )
    left = sorted(f for f in UNMEASURED if f not in blind)
    assert not left, (
        f"these files are measurable again — delete their UNMEASURED entries: {left}")


def test_the_scan_still_sees_the_files_it_is_meant_to_police(allowed_status):
    """A scanner that silently stops matching keeps passing while checking
    nothing. Assert it still reads a real population."""
    screens = [p for p in WEB.rglob("*.ts*")
               if not (set(p.relative_to(WEB).parts) & _SKIP_DIRS)
               and '.from("' in p.read_text(encoding="utf-8", errors="ignore")]
    assert len(screens) >= 50, (
        f"only {len(screens)} files read a table — the scan has stopped matching")
