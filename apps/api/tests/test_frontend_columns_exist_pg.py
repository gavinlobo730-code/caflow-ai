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

WHAT IT DOES NOT CHECK
    Only `.select()`. Column names inside `.eq()`, `.order()`, `.in()` and
    friends are not verified. That gap is real and has already bitten once:
    /reports/cash-flow filtered `.in("filing_type", ...)` on compliance_calendar,
    where the column is compliance_type — a third bad name on a query this file
    had already flagged for two others, found only by reading the code. It is
    left deliberately, because those calls take dotted and computed forms that
    need a different parser and half a check that works beats none. Widening it
    is the obvious next change, and would have caught that one.

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
from _frontend_select_parser import scan  # noqa: E402

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
WEB = API_ROOT.parents[1] / "apps" / "web"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists() or not WEB.is_dir(),
    reason="frontend column check requires HARNESS_PG + psql + apps/web",
)

# Selects that name a non-existent column ON PURPOSE. Not debt — each is a
# deliberate probe, and "fixing" it would break the thing it protects.
#
# Keep this list tiny and make each entry earn its place: it is a hole in the
# check, so an accidental typo added here stops being caught.
INTENTIONAL: dict[str, str] = {
    "chart_of_accounts.opening_balance_dr_paise":
        "app/accounting/trial-balance-import/page.tsx:46 — a CAPABILITY PROBE, "
        "not a bug. The page deliberately selects this column and reads the "
        "error to decide whether the Trial Balance Import wizard can run at "
        "all ('C4: gate the entire wizard on whether the required schema "
        "exists, rather than letting every row's write silently fail'). The "
        "column genuinely does not exist, so the wizard correctly shows its "
        "unavailable banner. Making this query succeed is the job of a "
        "migration adding opening_balance_dr_paise/_cr_paise, not of a rename.",
}

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


def test_the_scan_finds_enough_to_be_meaningful(schema):
    """Vacuity guard. A parser that silently stops matching would make every
    assertion below pass while checking nothing — the most likely way this file
    rots, because it would look like a clean bill of health."""
    found, unparsed = scan(WEB)
    assert len(found) >= 500, f"only {len(found)} select columns found — parser likely broke"
    assert len(schema) >= 2000, f"only {len(schema)} columns in schema — migrations likely failed"
    # Template-literal and variable selects cannot be read; that is expected and
    # bounded. A jump means the codebase moved to a form this cannot see.
    assert unparsed <= 120, f"{unparsed} .from() calls had an unreadable select"


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


def test_no_intentional_entry_is_stale(schema):
    """An exemption for a query that now resolves is a hole: the name can come
    back into use later and skip the check entirely."""
    stale = sorted(set(INTENTIONAL) - set(_offenders(schema)))
    assert not stale, (
        "these are exempted as deliberate probes but the column now resolves — "
        f"delete them from INTENTIONAL: {stale}")


def test_every_intentional_entry_says_which_page_and_why():
    for col, why in INTENTIONAL.items():
        assert "app/" in why, f"{col}: name the page"
        assert len(why) > 120, (
            f"{col}: an exemption is a hole in this check — explain why the "
            f"query means to fail, or fix the name instead")
