-- Migration 318: two status vocabularies where the code and production disagree
--
-- Both were found by the guard comparison added in 316, which is the first
-- thing in this repository able to see a CHECK constraint that exists in
-- production and in no migration. Both are LIVE production failures: the
-- shipped code writes a value the live database refuses, and in each case the
-- refusal is swallowed rather than surfaced.
--
-- ── 1. gst_sync_jobs: production refuses the status the code emits ──────────
--
-- domain/gst/portal_service.py:179 sets status = 'partial_failure' when some
-- snapshots of a portal sync succeeded and others failed. That value was added
-- deliberately, with its own comment ("A per-snap_type fetch failure must not
-- be silently swallowed into a blanket completed"), its own display branch in
-- routers/gst_portal.py:103, and three tests pinning it.
--
-- Production's CHECK was created with the table in Supabase Studio BEFORE that
-- status existed, and admits only pending/running/completed/error. So the
-- UPDATE at portal_service.py:189 has been rejected in production ever since.
-- The consequence is worse than a lost status: the raise lands in the except at
-- :191, which overwrites status with 'error' and stores the Postgres constraint
-- text as error_message, then re-raises — so the CA sees HTTP 500 and a raw
-- database error, completed_at is never set, snapshots_created stays 0, and the
-- timeline entry is never written, even though the snapshots WERE saved.
--
-- The constraint is what is wrong here, not the code, so this widens it. That
-- makes this migration a REAL DDL change in production, not a no-op — the only
-- one in this file.
--
-- No test caught it because tests/test_r239_gst_computation_gaps.py runs the
-- path against an in-memory FakeDB. tests/test_status_vocabularies_pg.py now
-- asserts, against real Postgres, that every status either module writes is
-- accepted.
--
-- ── 2. tally_migration_jobs: the DEFAULT drifted ────────────────────────────
--
-- migrations/156_missing_tables_f5.sql:435 declares status NOT NULL DEFAULT
-- 'pending'; production's default is 'uploaded'. create_migration_job
-- (domain/tally/migration_service.py:145) omits status entirely and lets the
-- default decide, so the two databases disagree about what a new job's status
-- is — and 'pending' is not among the ten values production's CHECK admits.
--
-- That matters now: declaring production's CHECK in the repository (the next
-- migration in this series) would make every job creation fail locally until
-- the default agrees. Converging it here keeps the two changes separable.
--
-- Note that no check in this repository compares DEFAULTS —
-- test_schema_matches_production_pg.py asserts presence, nullability and type
-- only — so this drift was invisible from both sides.
--
-- The matching code fix ('failed' -> 'error' in _run_import_detached, which
-- production has been refusing and the inner except was swallowing, leaving a
-- crashed import stuck at 'importing' for ever) is in the same commit.

-- ── 1. Widen the gst_sync_jobs status vocabulary ────────────────────────────
-- Declared here as well as widened, so a replayed database and production end
-- up with the identical constraint rather than production carrying one the
-- repository has never described.
ALTER TABLE public.gst_sync_jobs DROP CONSTRAINT IF EXISTS gst_sync_jobs_status_check;
ALTER TABLE public.gst_sync_jobs ADD CONSTRAINT gst_sync_jobs_status_check
  CHECK (status IN ('pending', 'running', 'completed', 'partial_failure', 'error'));

-- ── 2. Converge the tally_migration_jobs status default ─────────────────────
-- A no-op in production, which already defaults to 'uploaded'.
ALTER TABLE public.tally_migration_jobs ALTER COLUMN status SET DEFAULT 'uploaded';

-- ── 3. Declare the two tally vocabularies production already enforces ───────
-- Neither is in any migration, which is why the 'failed' write above could be
-- refused in production and pass every check here. Both are copied verbatim
-- from production, so both are no-ops there; locally they start enforcing what
-- production has always enforced, which is what makes
-- tests/test_status_vocabularies_pg.py able to see the bug at all.
--
-- Declared here rather than with the other 60 production-only constraints
-- because the fix above is not verifiable without them.
ALTER TABLE public.tally_migration_jobs DROP CONSTRAINT IF EXISTS tally_migration_jobs_status_check;
ALTER TABLE public.tally_migration_jobs ADD CONSTRAINT tally_migration_jobs_status_check
  CHECK (status IN ('uploaded', 'parsing', 'parsed', 'mapping', 'validating',
                    'previewing', 'importing', 'completed', 'rolled_back', 'error'));

ALTER TABLE public.tally_migration_items DROP CONSTRAINT IF EXISTS tally_migration_items_status_check;
ALTER TABLE public.tally_migration_items ADD CONSTRAINT tally_migration_items_status_check
  CHECK (status IN ('pending', 'mapped', 'validated', 'imported', 'failed', 'skipped'));
