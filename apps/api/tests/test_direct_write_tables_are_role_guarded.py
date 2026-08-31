"""
The backlog, kept honest: which tables the browser writes directly, and which of
those the database still lets any role write.

Some screens talk to PostgREST rather than the API. For those, rbac() never
runs, so the only role check that can happen is the one in RLS. Migration 260
added that check to the nine tables where an existing API rule could be copied
verbatim. The rest are still open — not because they are safe, but because
nobody has decided who may edit them, and a guess would silently lock someone
out of their job with no error message that explains why.

This test does two jobs:

  1. It stops the guarded nine from quietly regressing — if a frontend write
     appears against a table migration 260 covers, that is fine; if migration
     260 stops covering one, the list below no longer matches and it fails.
  2. It makes the remainder VISIBLE and COUNTED, so "we'll do the rest later"
     cannot decay into "we forgot". Adding a new direct-write table without a
     decision fails this test rather than passing unnoticed.

It is a source scan, not a database check — the live policies are proved in
test_role_write_policies_pg.py, which needs PostgreSQL. This one runs always.
"""
import re
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"
_MIG_DIR = Path(__file__).resolve().parents[1] / "migrations"
MIGRATION_SOURCES = [_MIG_DIR / "260_role_aware_write_policies.sql",
                     _MIG_DIR / "261_role_aware_write_policies_part2.sql",
                     _MIG_DIR / "296_employee_income_tax_declarations.sql",
                     _MIG_DIR / "297_let_an_employee_file_their_own_declaration.sql"]

# Covered by migration 260 — each mirrors a live rbac() guard on an endpoint
# that writes the same table.
GUARDED = {
    # migration 260 — mirrored an existing endpoint's rbac() guard
    "chart_of_accounts", "clients", "customers", "tasks", "documents",
    "fee_invoices", "fee_engagements", "mca_filings", "firms",
    # migration 261 — no endpoint existed; each rule argued in that file's header
    "attendance", "leave_balances", "compliance_calendar", "it_notices",
    "tax_audits", "tax_planning_records", "shared_reports", "scheduled_reports",
    "client_documents", "document_requests", "suppliers", "msme_payments",
    "client_timeline_events",
    # migrations 296 + 297 — the §192 declaration tables. Guarded differently
    # from everything above, and deliberately: staff need Manager (payroll:write),
    # but Rule 26C makes Form 12BB the EMPLOYEE's own statement, so 297 also
    # admits an employee to their own unverified declaration and nothing else.
    # The boundary is proved against real Postgres in
    # tests/test_297_employee_declaration_rls_pg.py — row scope, column scope
    # (an employee may declare an amount but never verify it) and time scope
    # (verified is final as far as the employee is concerned).
    "payroll_it_declarations", "payroll_it_declaration_items",
}

# Written from the browser and NOT yet role-guarded. An entry needs a product
# decision — "who may edit this?" — before a rule can be written, because no API
# endpoint exists whose rbac() guard could be copied.
#
# Empty: every table the browser writes now carries a role rule (260 + 261). The
# category stays because the NEXT unguarded direct write should land here, with
# the question it raises, rather than being waved through — which is exactly
# what test_no_unaccounted_direct_write_table_appears enforces.
AWAITING_DECISION: dict[str, str] = {}

# Direct writes that CANNOT succeed, so no role policy would add anything. Kept
# as a third category rather than lumped in above, because "already impossible"
# and "undecided" need different follow-up: these two are broken features to fix
# or delete, not permission questions to answer.
#
# Both were found by this scan and confirmed against the production database.
# Both original entries have since been fixed, so the set is empty. It stays
# because the third category is still the right home for a direct write that
# cannot land — an empty dict here is a statement that none currently exist, and
# test_no_unaccounted_direct_write_table_appears will demand a decision the
# moment one does.
#
#   * `users` — settings/page.tsx wrote full_name directly while migration 153
#     had revoked the grant, so saving a display name answered "permission
#     denied for table users". Replaced by PATCH /api/identity/me.
#   * `transactions` — lib/data/gst.ts updated gst_invoice_category on a table
#     migration 139 dropped. That whole path is gone; the GST screens now use
#     the API's from-books endpoints. Reads of the dropped table that remain
#     elsewhere are tracked in test_frontend_does_not_read_dropped_tables.py.
CANNOT_SUCCEED: dict[str, str] = {}

_CHAIN = re.compile(r'\.from\("([a-z_]+)"\)((?:[^;]|\n){0,400}?)(?=\.from\("|;|\Z)', re.S)
_WRITE = re.compile(r'\.\s*(insert|upsert|update|delete)\s*\(')


def _direct_write_tables() -> dict[str, set[str]]:
    """table -> the frontend files that write it via PostgREST."""
    found: dict[str, set[str]] = {}
    for path in WEB.rglob("*.ts*"):
        if set(path.parts) & {"node_modules", ".next", "out", ".vercel"}:
            continue
        try:
            src = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for table, tail in _CHAIN.findall(src):
            if _WRITE.search(tail):
                found.setdefault(table, set()).add(path.relative_to(WEB).as_posix())
    return found


pytestmark = pytest.mark.skipif(not WEB.is_dir(), reason="frontend not in this checkout")


def test_the_scan_finds_direct_writes_at_all():
    """Vacuity guard — if the PostgREST call shape changes, every assertion
    below would iterate an empty set and pass."""
    found = _direct_write_tables()

    assert len(found) >= 15, (
        f"only {len(found)} direct-write tables found; the .from(...).insert() "
        "pattern this scan depends on has probably changed"
    )


def test_no_unaccounted_direct_write_table_appears():
    """A direct write to a table in neither set is a new hole nobody decided on.

    Fix it by guarding the table in a migration (move it to GUARDED), or by
    recording the open question in AWAITING_DECISION — but not by ignoring it.
    """
    unaccounted = sorted(set(_direct_write_tables())
                         - GUARDED - set(AWAITING_DECISION) - set(CANNOT_SUCCEED))

    assert not unaccounted, (
        "these tables are written straight from the browser and no role rule "
        "covers them:\n  "
        + "\n  ".join(f"{t}  ({', '.join(sorted(_direct_write_tables()[t])[:2])})"
                      for t in unaccounted)
        + "\n\nGuard the table in a migration, add it to AWAITING_DECISION with "
          "the question that needs answering, or to CANNOT_SUCCEED if the write "
          "can never land anyway."
    )


def test_guarded_tables_are_actually_in_the_migration():
    """GUARDED is a claim about the migrations. Hold it to the files, so removing
    a table from one cannot leave this test asserting protection that no longer
    exists.

    The table may be named in a loop's array (260/261 build their policies that
    way) or spelled out in a CREATE POLICY (296/297 do, because the employee
    branch differs per table). Either counts; what must not pass is a table
    named in NEITHER.
    """
    src = "\n".join(m.read_text(encoding="utf-8") for m in MIGRATION_SOURCES)

    for table in sorted(GUARDED):
        in_loop_array = re.search(rf"[\[,]\s*'{table}'\s*[,\]]", src)
        in_named_policy = re.search(
            rf"CREATE POLICY[^;]*?AS RESTRICTIVE[^;]*?ON public\.{table}\b", src,
            re.IGNORECASE | re.DOTALL)
        in_named_policy_alt = re.search(
            rf"ON public\.{table}\s+AS RESTRICTIVE", src, re.IGNORECASE)
        assert in_loop_array or in_named_policy or in_named_policy_alt, (
            f"{table} is listed as guarded but no migration covers it"
        )


def test_the_three_sets_do_not_overlap():
    """A table belongs in exactly one category; an overlap would hide a resolved
    question or claim a false one."""
    assert not (GUARDED & set(AWAITING_DECISION))
    assert not (GUARDED & set(CANNOT_SUCCEED))
    assert not (set(AWAITING_DECISION) & set(CANNOT_SUCCEED))


def test_every_open_table_carries_the_question_that_blocks_it():
    """An entry with no reason is a TODO, and TODOs are how a backlog stops
    being actionable. Each needs the actual decision spelled out."""
    for table, why in {**AWAITING_DECISION, **CANNOT_SUCCEED}.items():
        assert len(why) > 25, f"{table}: say what needs deciding, not just that it does"
