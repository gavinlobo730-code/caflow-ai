"""
Migration 252 + the year-end repoint — the seven broken paths, on real PostgreSQL.

Background
----------
docs/audits/2026-08-02-migration-ledger-drift-audit.md verified against the live
catalog that seven objects queried by routers do not exist in production. Four
were purely missing schema (migration 252 creates them). Three were the year-end
tables, which DO exist under the names a divergent Studio migration gave them —
so the routers were repointed at `year_end_notes`, `year_end_checklist_items`
and `year_end_review_events` rather than creating a duplicate set.

These tests run the EXACT insert payloads the fixed routers build, against a
database freshly built by replaying every migration. That is the check that was
missing: mock-mode tests pass whatever the schema is, so an insert against a
non-existent table only ever failed for a real user.

Runs only when HARNESS_PG is set + psql on PATH (same gate as the other
real-Postgres tests); skips in the mock-mode CI job. The `migrations` CI job
runs it against its Postgres service.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid

import pytest

_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or not shutil.which("psql"),
    reason="needs HARNESS_PG and psql on PATH",
)

FIRM = "aaaaaaaa-0000-0000-0000-000000000001"
CLIENT = "aaaaaaaa-0000-0000-0000-000000000002"
ENG = "aaaaaaaa-0000-0000-0000-000000000003"
USER = "aaaaaaaa-0000-0000-0000-000000000004"
HSN = "aaaaaaaa-0000-0000-0000-000000000005"


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql],
        capture_output=True, text=True,
    )


def _scalar(dsn: str, sql: str) -> str:
    r = subprocess.run(
        ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.fixture()
def migrated_db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"r252_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F', 'f@t.in');
            -- Migration 315 makes year_end_review_events.actor_id a real FK to
            -- users(id), so the actor has to exist before an event can name it.
            INSERT INTO users (id, firm_id, full_name, email, role)
            VALUES ('{USER}', '{FIRM}', 'U', 'u@t.in', 'Partner');
            INSERT INTO clients (id, firm_id, client_name, entity_type)
            VALUES ('{CLIENT}', '{FIRM}', 'C', 'Private Limited');
            INSERT INTO year_end_engagements
              (id, firm_id, client_id, financial_year, fy_start, fy_end, status, created_by)
            VALUES ('{ENG}', '{FIRM}', '{CLIENT}', '2025-26',
                    DATE '2025-04-01', DATE '2026-03-31', 'draft', '{USER}');
            INSERT INTO firm_hsn_library (id, firm_id, hsn_code, description, hsn_type)
            VALUES ('{HSN}', '{FIRM}', '9983', 'Professional services', 'services');
        """)
        assert seed.returncode == 0, f"seed failed: {seed.stderr}"
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


# ══════════════════════════════════════════════════════════════════════════════
# The four objects migration 252 creates
# ══════════════════════════════════════════════════════════════════════════════

def test_government_notice_insert_matches_the_router_payload(migrated_db):
    """routers/document_intelligence_v2.py:168 — every key it sends."""
    r = _psql(migrated_db, f"""
        INSERT INTO government_notices
          (id, firm_id, client_id, notice_type, authority, reference_no, issue_date,
           response_due_date, description, source_document_url, extracted_data,
           status, ca_approved, task_id, created_at, updated_at)
        VALUES (gen_random_uuid(), '{FIRM}', '{CLIENT}', 'gst_scrutiny', 'GSTN',
                'REF/1', DATE '2026-04-01', DATE '2026-05-01', 'ASMT-10',
                'https://x/y.pdf', '{{"a":1}}'::jsonb, 'open', false, NULL, now(), now());
    """)
    assert r.returncode == 0, r.stderr


def test_notice_defaults_to_not_ca_approved(migrated_db):
    """CLAUDE.md: nothing statutory acts without an explicit CA confirmation."""
    _psql(migrated_db, f"""
        INSERT INTO government_notices (firm_id, client_id, notice_type, authority)
        VALUES ('{FIRM}', '{CLIENT}', 'income_tax', 'Income Tax Dept');
    """)
    assert _scalar(migrated_db, "SELECT bool_and(NOT ca_approved) FROM government_notices;") == "t"


def test_gstr2b_upload_insert_matches_the_router_payload(migrated_db):
    """routers/gst_workspace.py:510 — every key it sends."""
    r = _psql(migrated_db, f"""
        INSERT INTO gstr2b_uploads
          (id, firm_id, client_id, period, file_url, raw_data,
           reconciliation_result, status, created_by, uploaded_at)
        VALUES (gen_random_uuid(), '{FIRM}', '{CLIENT}', '042026', 'https://x/2b.json',
                '{{"docs":[]}}'::jsonb, '{{"matched_count":0}}'::jsonb,
                'reconciled', '{USER}', now());
    """)
    assert r.returncode == 0, r.stderr


def test_firm_hsn_rate_history_insert_and_constraints(migrated_db):
    ok = _psql(migrated_db, f"""
        INSERT INTO firm_hsn_rate_history
          (firm_id, firm_hsn_library_id, gst_rate_pct, supply_type, effective_from, notes)
        VALUES ('{FIRM}', '{HSN}', 18.00, 'taxable', DATE '2025-04-01', 'Notification 09/2025-CTR');
    """)
    assert ok.returncode == 0, ok.stderr
    # A rate outside 0–100 must be refused.
    bad = _psql(migrated_db, f"""
        INSERT INTO firm_hsn_rate_history
          (firm_id, firm_hsn_library_id, gst_rate_pct, effective_from)
        VALUES ('{FIRM}', '{HSN}', 150.00, DATE '2025-04-01');
    """)
    assert bad.returncode != 0
    # effective_to before effective_from must be refused.
    backwards = _psql(migrated_db, f"""
        INSERT INTO firm_hsn_rate_history
          (firm_id, firm_hsn_library_id, gst_rate_pct, effective_from, effective_to)
        VALUES ('{FIRM}', '{HSN}', 18.00, DATE '2025-04-01', DATE '2025-01-01');
    """)
    assert backwards.returncode != 0


def test_reminders_accepts_firm_id(migrated_db):
    """routers/reminders.py:28 filters on it and :45 inserts it — GET and POST
    /api/reminders both failed outright without this column."""
    r = _psql(migrated_db, f"""
        INSERT INTO reminders (firm_id, client_id, reminder_type, scheduled_for, status)
        VALUES ('{FIRM}', '{CLIENT}', 'email', now(), 'pending');
    """)
    assert r.returncode == 0, r.stderr
    assert _scalar(migrated_db, f"SELECT count(*) FROM reminders WHERE firm_id = '{FIRM}';") == "1"


def test_clients_is_test_defaults_false(migrated_db):
    """client_repository.find_all adds .eq('is_test', False) when include_test=False."""
    assert _scalar(migrated_db, f"SELECT is_test FROM clients WHERE id = '{CLIENT}';") == "f"
    r = _psql(migrated_db, "SELECT count(*) FROM clients WHERE is_test = false;")
    assert r.returncode == 0, r.stderr


# ── tenant isolation on the new tables ──────────────────────────────────────

def test_new_tables_isolate_on_write_not_just_read(migrated_db):
    """052's original policies had USING but no WITH CHECK, so any authenticated
    user could INSERT a row carrying another firm's id. 252 does not reproduce
    that. Asserted structurally: a policy missing either half is the bug."""
    bad = _scalar(migrated_db, """
        SELECT count(*) FROM pg_policies
         WHERE schemaname='public'
           AND tablename IN ('government_notices','gstr2b_uploads','firm_hsn_rate_history')
           AND (qual IS NULL OR with_check IS NULL);
    """)
    assert bad == "0", "an RLS policy on a new table is missing USING or WITH CHECK"


def test_new_tables_have_rls_enabled(migrated_db):
    for t in ("government_notices", "gstr2b_uploads", "firm_hsn_rate_history"):
        on = _scalar(migrated_db, f"""
            SELECT c.relrowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
             WHERE n.nspname='public' AND c.relname='{t}';
        """)
        assert on == "t", f"{t} has RLS disabled"


# ══════════════════════════════════════════════════════════════════════════════
# The three year-end tables the routers were repointed at
# ══════════════════════════════════════════════════════════════════════════════

def test_year_end_notes_accepts_the_repointed_payload(migrated_db):
    """routers/year_end_notes.py generate_notes — with `note_number` dropped,
    since year_end_notes has no such column (it belonged to the never-applied
    notes_to_accounts schema)."""
    r = _psql(migrated_db, f"""
        INSERT INTO year_end_notes
          (id, engagement_id, firm_id, note_type, sequence_no, title, content,
           note_data, is_locked, is_auto_generated, created_by, created_at, updated_at)
        VALUES (gen_random_uuid(), '{ENG}', '{FIRM}', 'fixed_assets', 1,
                'Property, Plant and Equipment', 'text', '{{"gross":0}}'::jsonb,
                false, true, '{USER}', now(), now());
    """)
    assert r.returncode == 0, r.stderr
    assert _scalar(migrated_db, "SELECT count(*) FROM year_end_notes;") == "1"


def test_year_end_notes_rejects_the_stale_column(migrated_db):
    """Proves the payload fix was necessary, not cosmetic: sending note_number
    is exactly what PostgREST would have rejected."""
    r = _psql(migrated_db, f"""
        INSERT INTO year_end_notes
          (engagement_id, firm_id, note_type, sequence_no, title, note_number, created_by)
        VALUES ('{ENG}', '{FIRM}', 'loans', 2, 'Borrowings', 2, '{USER}');
    """)
    assert r.returncode != 0 and "note_number" in r.stderr


def test_year_end_checklist_items_accepts_the_repointed_payload(migrated_db):
    """routers/year_end_checklist.py auto-initialisation — all 13 keys."""
    r = _psql(migrated_db, f"""
        INSERT INTO year_end_checklist_items
          (id, engagement_id, firm_id, category, item_code, item_label, sequence_no,
           status, notes, completed_by, completed_at, created_at, updated_at)
        VALUES (gen_random_uuid(), '{ENG}', '{FIRM}', 'bank', 'BANK_RECON',
                'Bank reconciliation complete', 1, 'pending', NULL, NULL, NULL, now(), now());
    """)
    assert r.returncode == 0, r.stderr


def test_year_end_review_events_accepts_every_event_the_router_emits(migrated_db):
    """All four event_type values in routers/year_end_reviews.py must satisfy the
    table's CHECK, and `reviewed_by` must NOT be sent — the column doesn't exist."""
    for ev in ("submitted_for_review", "approved", "revision_requested",
               "final_approved_and_locked"):
        r = _psql(migrated_db, f"""
            INSERT INTO year_end_review_events
              (id, engagement_id, firm_id, event_type, comment, actor_id, created_at)
            VALUES (gen_random_uuid(), '{ENG}', '{FIRM}', '{ev}', 'c', '{USER}', now());
        """)
        assert r.returncode == 0, f"{ev} rejected: {r.stderr}"
    assert _scalar(migrated_db, "SELECT count(*) FROM year_end_review_events;") == "4"


def test_year_end_review_events_rejects_the_stale_column(migrated_db):
    r = _psql(migrated_db, f"""
        INSERT INTO year_end_review_events
          (engagement_id, firm_id, event_type, actor_id, reviewed_by)
        VALUES ('{ENG}', '{FIRM}', 'approved', '{USER}', '{USER}');
    """)
    assert r.returncode != 0 and "reviewed_by" in r.stderr


def test_the_repointed_tables_exist_in_a_replayed_database(migrated_db):
    """The point of defining them in migration 252.

    Production got these from a Studio migration the repository never had, so
    before 252 a replayed database (CI, any fresh environment) lacked them
    entirely — the repointed routers would have worked in production and broken
    everywhere else. This asserts the repository now describes what production
    runs.
    """
    for t in ("year_end_notes", "year_end_checklist_items", "year_end_review_events"):
        assert _scalar(migrated_db, f"SELECT to_regclass('public.{t}') IS NOT NULL;") == "t", (
            f"{t} missing — the repointed routers would break outside production"
        )


def test_067s_tables_are_no_longer_referenced_by_any_router():
    """067's names still get created by a replay (the file is still in the repo,
    as history), but nothing may query them any more — that is what the repoint
    means. Source-level check, so it holds regardless of database."""
    import pathlib
    api_root = pathlib.Path(__file__).resolve().parents[1]
    offenders = []
    for path in (api_root / "routers").rglob("*.py"):
        text = path.read_text()
        for stale in ("notes_to_accounts", "year_end_checklists", "year_end_reviews"):
            if f'table("{stale}")' in text or f"table('{stale}')" in text:
                offenders.append(f"{path.name} -> {stale}")
    assert not offenders, "routers still query 067's never-applied tables: " + ", ".join(offenders)
