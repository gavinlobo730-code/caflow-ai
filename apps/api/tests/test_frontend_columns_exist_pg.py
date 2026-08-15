"""
Every column the frontend selects must exist, checked against a real schema.

WHY THIS EXISTS
    test_frontend_tables_exist.py checks the name in `.from("x")`. It never
    looked inside `.select(...)`, and that is where the same class of bug was
    still living. /portal/employee asked for:

        payroll_employees:  bank_account_number, ifsc_code
                            (real columns: bank_account_no, bank_ifsc)
        leave_balances:     leave_type, total_days, used_days
                            (real shape: one row per employee-year holding
                             casual_/sick_/earned_leave_balance)

    PostgREST rejects the WHOLE select when one column is unknown, so this was
    not a missing field in a corner of the page — the employee record never
    loaded at all, and the leave tab could not load for anyone, staff included.
    It looked like an RLS problem, and the RLS problem (migration 262) was real
    and separate, which is exactly how one bug hides behind another.

    tsc cannot catch it: `.select("id, ifsc_code")` is a string.

WHY IT USES A REAL DATABASE
    The sibling test replays migrations with regexes, which is good enough for
    relation names. Columns are not: they arrive via CREATE TABLE, ALTER TABLE
    ADD/DROP/RENAME COLUMN and view definitions spread over 250 files, and a
    regex model of that would be wrong often enough to be ignored — the failure
    mode that gets a test deleted. Applying the migrations and reading
    information_schema is exact, and the harness for it already exists.

WHAT IT CHECKS
    Three places a column name is written, all failing the same way:

        .select("a, b")          read    — PostgREST rejects the whole select
        .eq("a", …) .order("a")  filter  — rejects the request
        .insert({ a: … })        write   — rejects the write

    Filters and writes were added after /reports/cash-flow was found filtering
    `.in("filing_type", …)` on compliance_calendar (the column is
    compliance_type) — a third bad name on a query this file had already
    flagged for two others, invisible to a select-only checker and found only
    by reading the code. Widening it turned up 13 more across five pages.

WHAT IT STILL DOES NOT CHECK
    A column that is MISSING. This finds names that do not exist; it cannot
    find a NOT NULL column a write forgot — /clients/documents omitted
    client_documents.file_name, so that upload could not have worked even with
    every name corrected. Comparing write payloads against NOT NULL columns is
    the obvious next widening.

    Also unread: `.match({…})`, and any query whose table or column arrives as
    a variable or template literal.

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
from _frontend_select_parser import (  # noqa: E402
    scan, scan_filters, scan_writes, unreadable_selects,
)

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
WEB = API_ROOT.parents[1] / "apps" / "web"
_ADMIN = os.environ.get("HARNESS_PG")

# Applied per-test rather than as a module-level `pytestmark`, so that the one
# check in this file which reads only source code is not silently skipped
# everywhere Postgres is absent — that would make the check that catches an
# invisible select itself invisible.
_NEEDS_PG = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists() or not WEB.is_dir(),
    reason="frontend column check requires HARNESS_PG + psql + apps/web",
)

# Selects that name a non-existent column ON PURPOSE. Not debt — each is a
# deliberate probe, and "fixing" it would break the thing it protects.
#
# Keep this list tiny and make each entry earn its place: it is a hole in the
# check, so an accidental typo added here stops being caught.
INTENTIONAL: dict[str, str] = {
    # Empty, and that is the point. The one entry this list ever held —
    # chart_of_accounts.opening_balance_dr_paise, the trial-balance import's
    # capability probe — is gone because the wizard no longer needs a probe:
    # it posts a real opening journal through /api/accounting/trial-balance/import
    # instead of writing to a column that was never going to exist.
    #
    # Adding anything here is a hole in the check below. An entry must be a
    # query that MEANS to fail, never a typo someone did not want to fix.
}

# Filter/write offenders NOT fixed yet, because fixing them needs a decision
# rather than a rename. A ratchet, not an exemption: test_no_unfixed_entry_is_stale
# fails once one is fixed, so the list can only shrink.
#
# Empty. It held the whole /tds cluster — seven wrong column names, an insert of
# client_id: null into a NOT NULL column, and an `fy` with nowhere to go. All
# three are resolved: migration 263 adds tds_deductions.financial_year (which
# repositories/tds_repository.py had always filtered by), the page now has a
# client picker, and the names are corrected.
UNFIXED: dict[str, str] = {}

# Columns that DID NOT EXIST and were fixed in this change, kept as a named
# regression pin. Every one made PostgREST reject the entire select, so the
# query 400'd and took the page's load() with it.
FIXED_HERE: dict[str, str] = {
    "ai_insights.type": "insight_type",
    "client_documents.label": "description",
    "client_documents.storage_path": "file_path",
    "client_documents.file_size_bytes": "file_size",
    "loans.next_emi_date": "disbursement_date + maturity_date",
    "compliance_calendar.tax_amount_paise": "(no equivalent — leg removed)",
    # Found in production, not by this file: the client Overview page rendered
    # "Couldn't load this client's overview" and the console showed a 400 on
    # /rest/v1/tasks. `task_type` has never existed in any migration. The select
    # was the app's only template literal, which this parser could not read, and
    # the "unreadable select" budget it landed in was set to 120 against an
    # actual value of 73 — so it counted the miss and passed anyway.
    "tasks.task_type": "(no equivalent — the concept does not exist on tasks)",
}


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-tA", "-c", sql],
                          capture_output=True, text=True)


@pytest.fixture(scope="module")
def schema(pg_template):
    """{'table.column'} for every relation in public, from a real migrated db."""
    admin = _ADMIN.strip()
    dbname = f"cols_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        r = _psql(dsn, "SELECT table_name||'.'||column_name FROM information_schema.columns "
                       "WHERE table_schema='public';")
        assert r.returncode == 0, r.stderr
        yield set(r.stdout.split())
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def _offenders(schema: set[str]) -> dict[str, set[str]]:
    found, _ = scan(WEB)
    relations = {s.split(".", 1)[0] for s in schema}
    bad: dict[str, set[str]] = {}
    for path, rel, col in found:
        # Unknown RELATIONS are test_frontend_tables_exist.py's job; checking
        # them here too would report one bug as two.
        if rel in relations and f"{rel}.{col}" not in schema:
            bad.setdefault(f"{rel}.{col}", set()).add(path)
    return bad


@_NEEDS_PG
def test_the_scan_finds_enough_to_be_meaningful(schema):
    """Vacuity guard. A parser that silently stops matching would make every
    assertion below pass while checking nothing — the most likely way this file
    rots, because it would look like a clean bill of health."""
    found, unparsed = scan(WEB)
    assert len(found) >= 800, f"only {len(found)} select columns found — parser likely broke"
    assert len(schema) >= 2000, f"only {len(schema)} columns in schema — migrations likely failed"
    # `unparsed` counts every .from() with no readable select, and MOST of those
    # are inserts/updates/deletes that have no select at all (70 of 73 when this
    # was written). So it is a weak tripwire, and it was set weaker still: the
    # bound used to be 120 against an actual value of 73, which is to say it
    # could not fail. It caught nothing when lib/data/tasks.ts moved its select
    # to a template literal naming `task_type` — a column that has never existed
    # — and shipped a 400 that blanked the client Overview page.
    #
    # Kept only as a coarse "did the parser stop working" signal, now bounded
    # near the real value. The sharp check is the next test.
    assert unparsed <= 80, f"{unparsed} .from() calls had an unreadable select"


@pytest.mark.skipif(not WEB.is_dir(), reason="needs apps/web")
def test_every_select_the_frontend_writes_can_actually_be_read():
    """The check that would have caught `tasks.task_type`.

    Deliberately NOT under this module's HARNESS_PG skip: it reads source, not a
    database. Inheriting that skip would make the one check that catches an
    invisible select itself invisible in every environment without Postgres —
    the same shape of failure it exists to prevent.

    A `.select(...)` this parser cannot read is a column list nobody is
    verifying — it passes every assertion in this file by being invisible to
    them. There is no acceptable number of those but zero, so unlike the count
    above this has no budget to hide in.

    If a legitimately dynamic select ever appears (`.select(cols)` where cols is
    built at runtime), the answer is to make the column list static or to check
    it another way — not to raise a threshold."""
    unreadable = unreadable_selects(WEB)
    lines = [f"{f}:{line}  {snippet}" for f, line, snippet in unreadable]
    assert not unreadable, (
        "these .select() calls name columns this checker cannot read, so none of "
        "them are being verified against the schema:\n  " + "\n  ".join(lines)
    )


@_NEEDS_PG
def test_no_frontend_select_names_a_column_that_does_not_exist(schema):
    new = {k: v for k, v in _offenders(schema).items() if k not in INTENTIONAL}
    lines = [f"{col}  ({', '.join(sorted(files))})" for col, files in sorted(new.items())]
    assert not new, (
        "these selects name columns that do not exist. PostgREST rejects the "
        "ENTIRE select on one bad column, so the query fails at runtime and "
        "takes the page's load() with it:\n  "
        + "\n  ".join(lines)
        + "\n\nFix the name. Only add to INTENTIONAL if the query is a probe "
          "that MEANS to fail — every entry there is a hole in this check."
    )


@_NEEDS_PG
def test_the_columns_fixed_here_stay_fixed(schema):
    """Names the specific regressions, so a revert reports itself instead of
    arriving as an anonymous line in the list above."""
    for col, real in FIXED_HERE.items():
        assert col not in schema, (
            f"{col} now exists in the schema — this pin assumed it did not. "
            f"If a migration added it, delete the entry; do not weaken the test.")
    found, _ = scan(WEB)
    selected = {f"{rel}.{col}" for _, rel, col in found}
    still_wrong = sorted(set(FIXED_HERE) & selected)
    assert not still_wrong, (
        "these column names came back into the frontend: "
        + ", ".join(f"{c} (should be {FIXED_HERE[c]})" for c in still_wrong))


@_NEEDS_PG
def test_both_client_documents_pages_use_the_real_columns(schema):
    """client_documents has TWO consumers, and the first pass at this fix
    reported only one of them — the offender map printed a single file per
    column. Both are pinned so a partial fix cannot look complete."""
    for col in ("client_documents.description", "client_documents.file_path",
                "client_documents.file_size"):
        assert col in schema

    found, _ = scan(WEB)
    pages = {"app/client-portal/page.tsx", "app/clients/[id]/documents/page.tsx"}
    for page in pages:
        cols = {c for f, rel, c in found if f == page and rel == "client_documents"}
        assert cols, f"{page} no longer selects client_documents — update this test"
        for c in cols:
            assert f"client_documents.{c}" in schema, f"{page} selects bogus {c}"


@_NEEDS_PG
def test_the_employee_portal_columns_are_right(schema):
    """Pins the specific fix, so a revert names itself instead of arriving as
    one line in a generic list."""
    for col in ("payroll_employees.bank_account_no", "payroll_employees.bank_ifsc",
                "leave_balances.casual_leave_balance", "leave_balances.sick_leave_balance",
                "leave_balances.earned_leave_balance"):
        assert col in schema, f"{col} should exist — the portal now selects it"
    for gone in ("payroll_employees.bank_account_number", "payroll_employees.ifsc_code",
                 "leave_balances.leave_type", "leave_balances.total_days",
                 "leave_balances.used_days"):
        assert gone not in schema, (
            f"{gone} now exists — the portal fix assumed it did not; recheck it")

    found, _ = scan(WEB)
    portal = {(rel, col) for path, rel, col in found if path == "app/portal/employee/page.tsx"}
    assert portal, "no selects parsed from the employee portal page"
    for rel, col in sorted(portal):
        assert f"{rel}.{col}" in schema, f"employee portal still selects {rel}.{col}"


@_NEEDS_PG
def test_no_intentional_entry_is_stale(schema):
    """An exemption for a query that now resolves is a hole: the name can come
    back into use later and skip the check entirely."""
    stale = sorted(set(INTENTIONAL) - set(_offenders(schema)))
    assert not stale, (
        "these are exempted as deliberate probes but the column now resolves — "
        f"delete them from INTENTIONAL: {stale}")


@_NEEDS_PG
def test_every_intentional_entry_says_which_page_and_why():
    for col, why in INTENTIONAL.items():
        assert "app/" in why, f"{col}: name the page"
        assert len(why) > 120, (
            f"{col}: an exemption is a hole in this check — explain why the "
            f"query means to fail, or fix the name instead")


# ── filters and writes ──────────────────────────────────────────────────────

def _bad(refs, schema: set[str]) -> dict[str, set[str]]:
    relations = {s.split(".", 1)[0] for s in schema}
    out: dict[str, set[str]] = {}
    for path, rel, col in refs:
        if rel in relations and f"{rel}.{col}" not in schema:
            out.setdefault(f"{rel}.{col}", set()).add(path)
    return out


@_NEEDS_PG
def test_the_filter_and_write_scans_find_enough_to_be_meaningful(schema):
    """Vacuity guards, one per scan. The filter walk once matched only its first
    chain step (a stray \\A anchored it to the start of the whole file) and so
    found NOTHING while reporting a clean result — exactly the failure a floor
    like this catches."""
    assert len(scan_filters(WEB)) >= 400, "filter scan found too little — parser likely broke"
    assert len(scan_writes(WEB)) >= 200, "write scan found too little — parser likely broke"


@_NEEDS_PG
def test_no_filter_names_a_column_that_does_not_exist(schema):
    new = {k: v for k, v in _bad(scan_filters(WEB), schema).items() if k not in UNFIXED}
    assert not new, (
        "these FILTER arguments name columns that do not exist, so the request "
        "is rejected and the page's load() fails:\n  "
        + "\n  ".join(f"{c}  ({', '.join(sorted(f))})" for c, f in sorted(new.items()))
    )


@_NEEDS_PG
def test_no_write_payload_names_a_column_that_does_not_exist(schema):
    new = {k: v for k, v in _bad(scan_writes(WEB), schema).items() if k not in UNFIXED}
    assert not new, (
        "these INSERT/UPDATE payload keys name columns that do not exist, so the "
        "WRITE fails and nothing is saved:\n  "
        + "\n  ".join(f"{c}  ({', '.join(sorted(f))})" for c, f in sorted(new.items()))
    )


@_NEEDS_PG
def test_no_unfixed_entry_is_stale(schema):
    """Makes UNFIXED a ratchet. Fix one and this tells you to delete its line,
    so the list can only shrink and cannot become a silent permanent exemption."""
    seen = set(_bad(scan_filters(WEB), schema)) | set(_bad(scan_writes(WEB), schema))
    stale = sorted(set(UNFIXED) - seen)
    assert not stale, f"these are listed as unfixed but no longer appear — delete them: {stale}"


@_NEEDS_PG
def test_every_unfixed_entry_names_its_real_column_or_says_there_is_none():
    for col, real in UNFIXED.items():
        assert real, f"{col}: say what the real column is"
