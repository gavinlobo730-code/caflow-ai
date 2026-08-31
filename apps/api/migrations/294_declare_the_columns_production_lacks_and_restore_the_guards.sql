-- ============================================================================
-- 294 — add the columns production is missing, then restore the RLS guards
--
-- WHY — FOUR FEATURES ARE BROKEN IN PRODUCTION RIGHT NOW
--
--     Migration 292 closed the columns production REQUIRES and the migrations
--     called optional. This is the mirror: columns the MIGRATIONS declare that
--     production does not have. tests/test_schema_matches_production_pg.py
--     reported them and deliberately did not assert on them, reasoning that
--     "none of them can reject an insert". That reasoning was wrong, and this
--     is what it cost:
--
--       * routers/year_end_adjustments.py:201 sets record["client_id"] and
--         inserts. year_end_adjustments has no client_id in production, so
--         every year-end adjustment creation fails there.
--
--       * routers/year_end_statements.py:149 inserts statement_data. The
--         column does not exist in production, so no financial-statement
--         version can be saved.
--
--       * routers/year_end_mappings.py:348-349 insert statement_type and
--         account_name into account_group_mappings. Neither exists there.
--
--       * services/gst_filing_record_service.build_filings_row sets firm_id,
--         and filings has no firm_id in production. This is the worst of the
--         four: it is the GENUINE post-filing path — the CA files on the
--         portal and records it here — and public.filings is what
--         journal_period_lock_reason reads (migrations 266 and 267). A
--         filings row that never gets written is a period that never locks,
--         so entries stay editable after the return covering them is filed.
--
--     All four are the same shape as form_26as_uploads.uploaded_by: the CI
--     template is built FROM the migrations, so every check here passes while
--     production rejects the write.
--
-- ADDING THE COLUMNS IS SAFE, AND THAT WAS CHECKED, NOT ASSUMED
--     Every affected table was counted in the live database first. All are
--     EMPTY except client_profiles (82 rows), whose four missing columns are
--     nullable or defaulted. The two columns declared NOT NULL with no default
--     — year_end_adjustments.client_id and
--     financial_statement_versions.statement_data — are on empty tables.
--
--     Even so, nothing here adds a column NOT NULL outright. Each is added
--     nullable and then tightened only if no NULL row exists, so an
--     environment this file has not seen fails no migration; it converges as
--     far as it safely can and leaves the rest visible to the drift check.
--     Migration 291 stalled by failing hard against a shape it did not expect.
--
--     clients_external is deliberately absent: it is a VIEW in production, so
--     its is_test is derived, not stored.
--
-- WHY THE POLICY LOOPS ARE RE-RUN, AND WHY THAT IS THE REAL FIX
--     Comparing RLS policies for the first time (scripts/db/guard_snapshot.py)
--     found 35 the migrations declare that production does not have. Eight are
--     RESTRICTIVE on tables production actually has — the assignment-scope and
--     internal-partner-only checks. A permissive policy GRANTS, so a missing
--     one only narrows access; a missing RESTRICTIVE one removes a check.
--     Without them a staff member reads clients they are not assigned to, and
--     a non-Partner reads the firm's own internal client records, on
--     client_health_scores, client_health_overrides, government_notices,
--     gstr2b_uploads, portal_messages and year_end_adjustments.
--
--     The cause is not that anyone deleted them. Migrations 074 and 084 build
--     these policies with ONE-SHOT loops over whatever tables carried a
--     client_id at the moment they ran. Production applies migrations
--     incrementally as they merge, so its timeline differs from the template's:
--     a table repaired later (169 fixed the health tables; 052's tables were
--     re-made after it) gains its client_id AFTER 074/084 have already run,
--     and never gets the policy. The template, applied from scratch, caught a
--     different set.
--
--     RE-RUNNING THE LOOPS WAS TRIED FIRST, AND IS WRONG. It looks like the
--     elegant fix — one idempotent pass, catches every table that has a
--     client_id now, keeps catching them. The real-Postgres suite rejected it
--     in six tests, and they were right:
--
--       * migration 262 deliberately SPLIT payroll_employees' and
--         payroll_runs' assignment_scope into per-command policies so an
--         employee can read their own payslip. Re-running 084 recreates the
--         FOR ALL version and blanks the employee portal again.
--       * client_portal_users HAS a client_id and deliberately has NO
--         assignment-scope policy: a portal user is not staff, and the check
--         would lock them out of their own record.
--
--     The loops are one-shot BY DESIGN, not by oversight. They are idempotent
--     in mechanism and not in intent — replaying them re-imposes a 2024 answer
--     over every later decision. So this file names the eight policies
--     explicitly, in 074's and 084's own wording, and CREATES ONLY WHAT IS
--     ABSENT: an existing policy of the same name is left exactly as it is,
--     whatever a later migration made of it.
--
--     Column changes come FIRST, so year_end_adjustments has the client_id its
--     policy references by the time that policy is created.
--
--     Nothing here removes or weakens a policy. Zero policies are RESTRICTIVE
--     in the migrations and PERMISSIVE in production — that was checked, and a
--     check silently becoming a grant has not happened anywhere.
-- ============================================================================

-- ── 1. the columns ──────────────────────────────────────────────────────────
ALTER TABLE public.account_group_mappings       ADD COLUMN IF NOT EXISTS account_name          text;
ALTER TABLE public.account_group_mappings       ADD COLUMN IF NOT EXISTS is_active             boolean DEFAULT true;
ALTER TABLE public.account_group_mappings       ADD COLUMN IF NOT EXISTS sequence_no           integer DEFAULT 0;
ALTER TABLE public.account_group_mappings       ADD COLUMN IF NOT EXISTS statement_type        text;
ALTER TABLE public.account_group_mappings       ADD COLUMN IF NOT EXISTS sub_line              text;
ALTER TABLE public.automation_executions        ADD COLUMN IF NOT EXISTS firm_id               uuid;
ALTER TABLE public.client_profiles              ADD COLUMN IF NOT EXISTS last_updated_at       timestamptz DEFAULT now();
ALTER TABLE public.client_profiles              ADD COLUMN IF NOT EXISTS profile_data          jsonb DEFAULT '{}'::jsonb;
ALTER TABLE public.client_profiles              ADD COLUMN IF NOT EXISTS segment               text;
ALTER TABLE public.client_profiles              ADD COLUMN IF NOT EXISTS tags                  text[] DEFAULT '{}'::text[];
ALTER TABLE public.filings                      ADD COLUMN IF NOT EXISTS firm_id               uuid;
ALTER TABLE public.financial_statement_versions ADD COLUMN IF NOT EXISTS change_reason         text;
ALTER TABLE public.financial_statement_versions ADD COLUMN IF NOT EXISTS statement_data        jsonb;
ALTER TABLE public.firm_profiles                ADD COLUMN IF NOT EXISTS last_updated_at       timestamptz DEFAULT now();
ALTER TABLE public.firm_profiles                ADD COLUMN IF NOT EXISTS profile_data          jsonb DEFAULT '{}'::jsonb;
ALTER TABLE public.firm_profiles                ADD COLUMN IF NOT EXISTS settings              jsonb DEFAULT '{}'::jsonb;
ALTER TABLE public.permission_grants            ADD COLUMN IF NOT EXISTS firm_id               uuid;
ALTER TABLE public.workflow_steps               ADD COLUMN IF NOT EXISTS default_assignee_role text;
ALTER TABLE public.workflow_steps               ADD COLUMN IF NOT EXISTS estimated_hours       numeric;
ALTER TABLE public.workflow_steps               ADD COLUMN IF NOT EXISTS required              boolean DEFAULT true;
ALTER TABLE public.workflow_steps               ADD COLUMN IF NOT EXISTS step_description      text;
ALTER TABLE public.workflow_steps               ADD COLUMN IF NOT EXISTS step_name             text;
ALTER TABLE public.workflow_steps               ADD COLUMN IF NOT EXISTS workflow_id           uuid;
ALTER TABLE public.year_end_adjustments         ADD COLUMN IF NOT EXISTS client_id             uuid;
ALTER TABLE public.year_end_adjustments         ADD COLUMN IF NOT EXISTS reviewed_at           timestamptz;
ALTER TABLE public.year_end_adjustments         ADD COLUMN IF NOT EXISTS reviewed_by           uuid;
ALTER TABLE public.year_end_engagements         ADD COLUMN IF NOT EXISTS prepared_at           timestamptz;
ALTER TABLE public.year_end_engagements         ADD COLUMN IF NOT EXISTS prepared_by           uuid;
ALTER TABLE public.year_end_engagements         ADD COLUMN IF NOT EXISTS reviewed_at           timestamptz;
ALTER TABLE public.year_end_engagements         ADD COLUMN IF NOT EXISTS reviewed_by           uuid;
ALTER TABLE public.year_end_exports             ADD COLUMN IF NOT EXISTS version_id            uuid;

-- ── 2. the two that are declared NOT NULL, tightened only where it is safe ──
DO $do$
DECLARE
  target RECORD;
  nulls  BIGINT;
BEGIN
  FOR target IN
    SELECT * FROM (VALUES
      ('year_end_adjustments',         'client_id'),
      ('financial_statement_versions', 'statement_data'),
      ('account_group_mappings',       'is_active'),
      ('account_group_mappings',       'sequence_no'),
      ('workflow_steps',               'required')
    ) AS t(tbl, col)
  LOOP
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema='public' AND table_name=target.tbl
                     AND column_name=target.col AND is_nullable='YES') THEN
      CONTINUE;                      -- absent, or already NOT NULL
    END IF;
    EXECUTE format('SELECT count(*) FROM public.%I WHERE %I IS NULL',
                   target.tbl, target.col) INTO nulls;
    IF nulls > 0 THEN
      RAISE NOTICE 'left %.% nullable: % existing NULL row(s) to resolve first',
        target.tbl, target.col, nulls;
      CONTINUE;
    END IF;
    EXECUTE format('ALTER TABLE public.%I ALTER COLUMN %I SET NOT NULL',
                   target.tbl, target.col);
    RAISE NOTICE 'set %.% NOT NULL', target.tbl, target.col;
  END LOOP;
END
$do$;

-- ── 3. the eight RESTRICTIVE policies production is missing ────────────────
-- Created only where absent. Never dropped, never rewritten: if one already
-- exists here under a shape a later migration chose, that shape wins.
DO $do$
DECLARE
  target RECORD;
BEGIN
  FOR target IN
    SELECT * FROM (VALUES
      ('client_health_overrides',  'assignment_scope'),
      ('client_health_scores',     'assignment_scope'),
      ('government_notices',       'assignment_scope'),
      ('government_notices',       'internal_partner_only'),
      ('gstr2b_uploads',           'assignment_scope'),
      ('gstr2b_uploads',           'internal_partner_only'),
      ('portal_messages',          'assignment_scope'),
      ('year_end_adjustments',     'assignment_scope')
    ) AS t(tbl, kind)
  LOOP
    -- The table must exist and carry the column the policy reads. Where an
    -- earlier migration never applied, skip rather than fail the whole file.
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema='public' AND table_name=target.tbl
                     AND column_name='client_id') THEN
      RAISE NOTICE 'skipped %.%: no client_id column', target.tbl, target.kind;
      CONTINUE;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_policies
               WHERE schemaname='public' AND tablename=target.tbl
                 AND policyname = target.tbl || '_' || target.kind) THEN
      CONTINUE;                       -- already there; leave it alone
    END IF;

    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', target.tbl);

    IF target.kind = 'assignment_scope' THEN
      -- migration 084's wording
      EXECUTE format(
        'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR ALL '
        || 'USING (public.can_access_client(client_id::text)) '
        || 'WITH CHECK (public.can_access_client(client_id::text))',
        target.tbl || '_assignment_scope', target.tbl);
    ELSE
      -- migration 074's wording
      EXECUTE format(
        'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR ALL '
        || 'USING (get_my_role() = ''Partner'' OR client_id::text IS DISTINCT FROM my_internal_client_id()::text) '
        || 'WITH CHECK (get_my_role() = ''Partner'' OR client_id::text IS DISTINCT FROM my_internal_client_id()::text)',
        target.tbl || '_internal_partner_only', target.tbl);
    END IF;

    RAISE NOTICE 'created RESTRICTIVE policy %_%', target.tbl, target.kind;
  END LOOP;
END
$do$;
