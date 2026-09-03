-- Migration 320: make client_profiles the table production actually has
--
-- WHAT IS WRONG
--
-- In a database built from these migrations, public.client_profiles has NINE
-- columns. In production it has TWENTY-NINE. The twenty missing ones are the
-- entire versioned profile that the memory pipeline computes and writes:
-- profile_version, is_current, last_computed_at, data_points_used, and every
-- behavioural, compliance and financial field.
--
-- public.client_profile_history does not exist in the migrations AT ALL.
--
-- So on the CI template, and on any new environment, the whole memory and
-- client-intelligence subsystem cannot run: every write from
-- repositories/memory_repository.upsert_profile fails with "column ... does not
-- exist", and its history snapshot has no table to go in.
--
-- HOW IT HAPPENED — the same silent no-op, a third time
--
-- Migration 059 creates client_profiles with nine columns and a
-- UNIQUE (firm_id, client_id). Migration 070 then creates it again, properly,
-- with all twenty-nine — but as CREATE TABLE IF NOT EXISTS, which finds 059's
-- table and does nothing. 070 goes on to reference a column that CREATE never
-- made and fails, which is why it sits in EXPECTED_MIGRATION_FAILURES with the
-- note "client_profiles CREATE IF NOT EXISTS no-ops (059) -> is_current
-- missing". Production has 070's shape because it applied there first.
--
-- That is the third instance of one pattern in this series: a guarded
-- statement that silently does nothing when the guard is already satisfied.
-- Migration 062's IF EXISTS skipped eight tables (317); 068's CREATE IF NOT
-- EXISTS lost workflow_steps.template_id; this is 070's.
--
-- WHY NO CHECK CAUGHT IT
--
-- test_schema_matches_production_pg.py asserts the two directions that reject
-- an insert in PRODUCTION. This is the mirror: columns production has and the
-- migrations lack, which its docstring calls informational because it "cannot
-- break an insert". That is true of production and false of everywhere else —
-- here it breaks every insert on a fresh database.
--
-- test_backend_columns_exist_pg.py should have seen the column names, and
-- cannot: upsert_profile builds its payload in a variable and calls
-- .insert(record), so all twenty names are "unreadable references" in that
-- check's own accounting.
--
-- WHAT THIS DOES
--
-- Adds the twenty columns and creates the history table, both copied from
-- production, so both are no-ops there. Then replaces the unique.
--
-- THE UNIQUE, WHICH IS THE PART THAT IS A DECISION
--
-- 059 declares UNIQUE (firm_id, client_id). Production does not have it and
-- CANNOT: upsert_profile VERSIONS profiles — it retires the current row
-- (is_current = false), inserts the next with profile_version + 1, and writes a
-- client_profile_history snapshot pointing at the retired one. Production holds
-- 100 rows across 6 client pairs, one per client per day since 18 August.
--
-- So the declaration was never right. What the code actually guarantees is
-- ONE CURRENT PROFILE per client, and that is what is declared here, as a
-- partial unique index. Verified against production before writing: 6 groups,
-- every one with exactly one is_current row, none with two, none with zero.
--
-- It is safe against the write path because the order is retire-then-insert
-- (memory_repository.py: UPDATE is_current = false, then INSERT), so the two
-- current rows never coexist. Written the other way round it would deadlock on
-- itself, which is worth knowing before anyone reorders it.
--
-- NOT decided here: that a profile recomputed daily keeps every version for
-- ever. Six clients have produced 100 rows in sixteen days. Whether that wants
-- a retention rule is a product question, recorded rather than answered.

-- ── 1. The twenty columns 070 never managed to add ──────────────────────────
ALTER TABLE public.client_profiles
  ADD COLUMN IF NOT EXISTS profile_version            integer NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS doc_upload_reliability     numeric(5,2) DEFAULT 0,
  ADD COLUMN IF NOT EXISTS portal_engagement          numeric(5,2) DEFAULT 0,
  ADD COLUMN IF NOT EXISTS avg_response_time_days     numeric(6,2),
  ADD COLUMN IF NOT EXISTS preferred_contact          text DEFAULT 'email',
  ADD COLUMN IF NOT EXISTS avg_gst_delay_days         numeric(6,2),
  ADD COLUMN IF NOT EXISTS avg_tds_delay_days         numeric(6,2),
  ADD COLUMN IF NOT EXISTS missed_deadline_count      integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS notice_count               integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS compliance_score           numeric(5,2) DEFAULT 75,
  ADD COLUMN IF NOT EXISTS seasonal_revenue_peak      text,
  ADD COLUMN IF NOT EXISTS cash_flow_risk_months      jsonb DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS avg_debtor_days            numeric(6,2),
  ADD COLUMN IF NOT EXISTS recurring_issues           jsonb DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS avg_year_end_duration_days integer,
  ADD COLUMN IF NOT EXISTS common_provisions          jsonb DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS common_auditor_requests    jsonb DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS last_computed_at           timestamptz NOT NULL DEFAULT now(),
  ADD COLUMN IF NOT EXISTS data_points_used           integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS is_current                 boolean NOT NULL DEFAULT true;

-- 059 left created_at/updated_at nullable; 070 declares both NOT NULL and that
-- is what production has. Both carry DEFAULT now(), so nothing can have written
-- a NULL — the tightening is declaration only. Guarded on there being none, so
-- an environment that somehow holds one fails loudly instead of silently
-- skipping (this file exists because of a statement that silently skipped).
DO $mig$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM public.client_profiles WHERE created_at IS NULL) THEN
    ALTER TABLE public.client_profiles ALTER COLUMN created_at SET NOT NULL;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM public.client_profiles WHERE updated_at IS NULL) THEN
    ALTER TABLE public.client_profiles ALTER COLUMN updated_at SET NOT NULL;
  END IF;
END $mig$;

-- ── 2. The history table, which the migrations never created ────────────────
CREATE TABLE IF NOT EXISTS public.client_profile_history (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id         uuid NOT NULL,
  client_id       uuid NOT NULL,
  profile_id      uuid NOT NULL,
  profile_version integer NOT NULL,
  snapshot        jsonb NOT NULL DEFAULT '{}'::jsonb,
  computed_at     timestamptz NOT NULL DEFAULT now()
);

DO $mig$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname = 'client_profile_history_profile_id_fkey'
                   AND conrelid = 'public.client_profile_history'::regclass) THEN
    ALTER TABLE public.client_profile_history
      ADD CONSTRAINT client_profile_history_profile_id_fkey
      FOREIGN KEY (profile_id) REFERENCES public.client_profiles(id) ON DELETE CASCADE;
  END IF;
END $mig$;

-- Grants and row-level security exactly as production has them. Without these a
-- fresh deployment would have the table and no way to reach it — and, worse,
-- reach it with no isolation, which is what migration 317 had to repair for
-- eight other tables.
GRANT SELECT, INSERT, UPDATE, DELETE ON public.client_profile_history TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.client_profile_history TO service_role;
ALTER TABLE public.client_profile_history ENABLE ROW LEVEL SECURITY;

DO $mig$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policy
                 WHERE polname = 'client_profile_history_firm_isolation'
                   AND polrelid = 'public.client_profile_history'::regclass) THEN
    CREATE POLICY client_profile_history_firm_isolation
      ON public.client_profile_history FOR ALL
      USING (firm_id = get_my_firm_id())
      WITH CHECK (firm_id = get_my_firm_id());
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policy
                 WHERE polname = 'client_profile_history_assignment_scope'
                   AND polrelid = 'public.client_profile_history'::regclass) THEN
    CREATE POLICY client_profile_history_assignment_scope
      ON public.client_profile_history AS RESTRICTIVE FOR ALL
      USING (can_access_client((client_id)::text))
      WITH CHECK (can_access_client((client_id)::text));
  END IF;
END $mig$;

-- ── 3. Replace a unique the data can never satisfy with the one it can ──────
ALTER TABLE public.client_profiles
  DROP CONSTRAINT IF EXISTS client_profiles_firm_id_client_id_key;

CREATE UNIQUE INDEX IF NOT EXISTS client_profiles_one_current_per_client
  ON public.client_profiles (firm_id, client_id) WHERE is_current;
