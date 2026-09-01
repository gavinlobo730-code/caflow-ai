"""
Every column the BACKEND names must exist, checked against a real schema.

WHY THIS EXISTS
    A run of production 500s and silent no-ops turned out to be one bug
    repeated: application code naming columns no migration ever created.
    PostgREST rejects those at PARSE time (42703) — before a row is considered
    — and most call sites sit inside `try: … except Exception: pass`, so the
    failures were total AND invisible. Whole features had never worked once:
    the health engine's AI-risk dimension scored a flat 100 for every client,
    two hard overrides could never fire, no portal message had ever been sent,
    and no partner had ever been notified of a tax notice.

    core/schema_guard.py cannot catch this class. It parses MIGRATIONS for
    ADD COLUMN and checks the database has them, which finds "a migration was
    never applied". These columns were never in a migration at all; they were
    invented in code. Opposite direction, and nothing checked it.

    tests/test_frontend_columns_exist_pg.py checks that direction for apps/web.
    This is its counterpart for apps/api, and it exists because a one-off sweep
    is not a check: the sweep that found the first batch missed
    document_requests.document_name in routers/health.py — the SECOND instance
    of a bug it had just fixed twenty lines above — and read only .eq()-style
    filters, so it passed relationships.py clean while it filtered on
    section_186_flagged, a column that did not exist.

THE --continue-on-error PROBLEM, AND WHY IT DOES NOT MAKE THIS CRY WOLF
    The CI template is built with --continue-on-error, so the migrations on
    test_migrations_apply.EXPECTED_MIGRATION_FAILURES never run and their
    columns are absent LOCALLY while present in production. 070_ai_memory.sql
    alone accounts for five. Reporting those would be a false alarm on the
    first run, which is how a check like this gets deleted.

    Two guards, both derived rather than hand-listed, so neither becomes a hole
    someone has to remember to close:

      * a relation absent from the template is skipped — that is
        test_backend_tables_exist's job, and reporting it here would call one
        bug two.
      * a column DECLARED BY a baseline-failure migration is skipped. When that
        migration is repaired and drops off the baseline, its columns become
        checkable again automatically.

WHAT IT STILL DOES NOT CHECK
    A column that is MISSING — this finds names that do not exist, not a
    NOT NULL column a write forgot. And anything whose table or column name
    arrives as a variable or an f-string, which is counted and budgeted below
    rather than ignored.

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
from _backend_query_parser import scan, unverifiable_columns  # noqa: E402
from test_migrations_apply import EXPECTED_MIGRATION_FAILURES  # noqa: E402

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
MIGRATIONS = API_ROOT / "migrations"
_ADMIN = os.environ.get("HARNESS_PG")

_NEEDS_PG = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="backend column check requires HARNESS_PG + psql",
)

# Columns that DID NOT EXIST and were fixed in this change, kept as named
# regression pins. Each made PostgREST reject the whole statement.
FIXED_HERE: dict[str, str] = {
    # routers/lifecycle.py invented a generic entity_id/entity_type/metadata
    # shape across six inserts. The table has had the specific columns all
    # along. Every insert sat in `except Exception: pass`, so no lifecycle
    # event has ever been recorded for a lead stage change.
    "client_lifecycle_events.entity_id": "lead_id / client_id",
    "client_lifecycle_events.entity_type": "(none — lead_id vs client_id says which)",
    "client_lifecycle_events.metadata": "from_stage + to_stage",
    # Both of these failed AFTER their GL journal had already posted, leaving
    # the ledger and the document disagreeing.
    "client_sales_invoices.cancelled_at": "(none — status='cancelled' + updated_at)",
    "credit_notes.issued_at": "(none — status='issued' + updated_at)",
    # The second instance of a bug fixed twenty lines above it.
    "document_requests.document_name": "title",
}

# Offenders NOT fixed, because fixing one needs a decision rather than a
# rename. A ratchet, not an exemption: test_no_unfixed_entry_is_stale fails
# once one is fixed, so the list can only shrink.
#
# Empty, and that is the point — every phantom this check found on its first
# run was a rename or a deletion with an obvious right answer.
UNFIXED: dict[str, str] = {}

# References the parser cannot resolve: a table or column arriving as a
# variable, an f-string, or a **spread. Budgeted so the blind spot has a number
# on it. Set just above the current value — it may shrink freely, and growing
# it is a deliberate act that shows up in a diff.
#
# 430 -> 431: gst_return_service._gl_gst_movements gained
#   .or_(f"client_id.eq.{client_id},client_id.is.null")
# so that the GSTR-3B ledger reconciliation can see FIRM-WIDE GST control
# accounts (client_id NULL) and not just client-scoped ones — without it the
# reconciliation resolved no accounts at all and compared the books against a
# ledger of zero. The clause interpolates a runtime id, so it cannot be a
# string literal and the parser cannot read it; bank_posting_service and
# phase2_journal_service carry the identical idiom and are already inside this
# budget. The COLUMN it names, client_id, is verified elsewhere in the same
# file's select list, so nothing became unchecked that was checked before.
# 431 -> 432: itc_register_service._gst_input_credit_on gained the same
#   .or_(f"client_id.eq.{client_id},client_id.is.null")
# for the same reason — a chart built by coa_seed_service holds the GST Input
# account FIRM-WIDE with client_id NULL, and the register has to find it to
# check a reversal against the ledger movement on its own journal.
#
# The new module added THREE unreadable references and two were removed rather
# than budgeted: its inserts were .insert(row) with the dict built in a
# variable, which hides every column name from this scanner. Both are now
# written inline with literal keys, so the twelve columns they write are
# checked against the real schema. Only the or_ interpolation is genuinely
# unreadable, and it names client_id, which the same file's select lists
# verify.
# 432 -> 433: routers/accounting.list_accounts gained the SAME
#   .or_(f"client_id.eq.{client_id},client_id.is.null")
# a third time, and for the third time for the same reason — a chart seeded by
# seed_firm_coa holds its accounts FIRM-WIDE with client_id NULL (migration
# 057), so an endpoint serving a client's chart has to return those too or it
# shows an empty chart for every client of a normally-seeded firm. Only the
# interpolated client_id is unreadable; the same query's select list names
# client_id literally, so the column itself is still checked.
MAX_UNREADABLE = 433


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-tA", "-c", sql],
        capture_output=True, text=True)


@pytest.fixture(scope="module")
def schema(pg_template):
    """{'table.column'} for every relation in public, from a real migrated db."""
    admin = _ADMIN.strip()
    dbname = f"bcols_{uuid.uuid4().hex[:12]}"
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
    found, _ = scan(API_ROOT)
    relations = {s.split(".", 1)[0] for s in schema}
    unverifiable = unverifiable_columns(MIGRATIONS, EXPECTED_MIGRATION_FAILURES)
    bad: dict[str, set[str]] = {}
    for path, rel, col in found:
        ref = f"{rel}.{col}"
        if rel not in relations:
            continue          # unknown RELATION — a different check's job
        if ref in unverifiable:
            continue          # the migration that creates it fails locally
        if ref not in schema:
            bad.setdefault(ref, set()).add(str(Path(path).relative_to(API_ROOT)))
    return bad


# ── Vacuity guards ───────────────────────────────────────────────────────────

@_NEEDS_PG
def test_the_scan_finds_enough_to_be_meaningful(schema):
    """A parser that silently stopped matching would make every assertion below
    pass while checking nothing — the most likely way this file rots, because
    it would look exactly like a clean bill of health."""
    found, _ = scan(API_ROOT)
    assert len(found) >= 4000, f"only {len(found)} column refs found — parser likely broke"
    assert len(schema) >= 3000, f"only {len(schema)} columns in schema — migrations likely failed"


@_NEEDS_PG
def test_the_unverifiable_set_is_derived_and_not_swallowing_everything(schema):
    """The baseline-failure exclusion is the one place this check gives ground.
    It must stay small, and it must actually be derived — an empty set would
    mean the derivation broke and the first CI run would cry wolf."""
    unverifiable = unverifiable_columns(MIGRATIONS, EXPECTED_MIGRATION_FAILURES)
    assert unverifiable, "derived nothing — the migration parser likely broke"
    assert len(unverifiable) < len(schema) * 0.15, (
        f"{len(unverifiable)} columns excluded against {len(schema)} known — "
        "the exclusion has grown into a blind spot"
    )
    # The five that made this necessary, all from 070_ai_memory.sql.
    for ref in ("client_profiles.is_current", "client_profiles.profile_version",
                "client_profiles.compliance_score", "firm_profiles.is_current",
                "firm_profiles.last_computed_at"):
        assert ref in unverifiable, f"{ref} should be excluded but is not"


# ── The check itself ─────────────────────────────────────────────────────────

@_NEEDS_PG
def test_no_backend_query_names_a_column_that_does_not_exist(schema):
    bad = _offenders(schema)
    unexpected = {k: v for k, v in bad.items() if k not in UNFIXED}
    assert not unexpected, "backend queries name columns that do not exist:\n" + "\n".join(
        f"  {ref:48} {', '.join(sorted(paths))}" for ref, paths in sorted(unexpected.items())
    )


@_NEEDS_PG
def test_the_columns_fixed_here_stay_fixed(schema):
    """Named pins. A generic 'no phantoms' assertion would go green again if
    someone reintroduced one AND added it to UNFIXED; these would not."""
    for ref in FIXED_HERE:
        rel, col = ref.split(".", 1)
        assert ref not in schema, (
            f"{ref} now EXISTS — it was fixed by renaming the query. If a "
            f"migration has since added it, remove it from FIXED_HERE."
        )
    bad = _offenders(schema)
    regressed = sorted(set(FIXED_HERE) & set(bad))
    assert not regressed, f"these were fixed and have come back: {regressed}"


@_NEEDS_PG
def test_no_unfixed_entry_is_stale(schema):
    """UNFIXED may only shrink. An entry that no longer offends must be deleted,
    or the list slowly becomes a place bugs go to be forgotten."""
    bad = _offenders(schema)
    stale = sorted(set(UNFIXED) - set(bad))
    assert not stale, f"UNFIXED entries no longer offend — delete them: {stale}"


def test_every_unfixed_entry_says_which_column_is_real():
    """Reading the list must tell you what to do about each entry."""
    for ref, note in UNFIXED.items():
        assert note.strip(), f"{ref} has no explanation"


def test_the_parser_reads_the_shapes_that_hid_real_bugs():
    """Source-only, so it runs in the mock-mode job too — the shapes below are
    exactly the ones a naive parser misses, and a regression here would make
    the pg checks above quietly weaker rather than fail."""
    from _backend_query_parser import split_or_clause, split_select

    # The or_() miss: section_186_flagged was invisible to an .eq()-only sweep.
    assert split_or_clause("section_185_flagged.eq.true,section_186_flagged.eq.true") == [
        "section_185_flagged", "section_186_flagged"]
    # A comma inside in.(…) does not start a new clause.
    assert split_or_clause("status.in.(a,b),kind.eq.x") == ["status", "kind"]
    # Nested boolean groups name columns, not "and".
    assert split_or_clause("and(a.eq.1,b.eq.2)") == ["a", "b"]

    cols, embeds = split_select("id, alias:real_col, lines(amount), *")
    assert cols == ["id", "real_col"]
    assert embeds == 1, "an embedded resource is a relation, not a column"


@_NEEDS_PG
def test_unreadable_references_stay_within_budget():
    """The blind spot, with a number on it."""
    _, unreadable = scan(API_ROOT)
    assert unreadable <= MAX_UNREADABLE, (
        f"{unreadable} unreadable column references, budget {MAX_UNREADABLE}. "
        "Dynamic table/column names are invisible to this check — if this grew "
        "deliberately, raise the budget in the same commit and say why."
    )
