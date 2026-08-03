-- Migration 252: create the objects that live code queries but production never got.
--
-- Companion to docs/audits/2026-08-02-migration-ledger-drift-audit.md, which
-- verified — object by object against the live catalog, not by filename — that
-- 12 of 93 unaccounted repository migrations never reached this database, and
-- that seven of the missing objects are queried by routers with no fallback.
-- Those endpoints have been failing in production while passing CI, because the
-- real-Postgres CI job replays the repository and therefore builds the schema
-- the repository DESCRIBES rather than the one production HAS.
--
-- This migration repairs the four that are purely missing schema. The other
-- three (year-end notes / checklist / reviews) needed no schema at all: the
-- tables exist under the names a divergent Studio migration gave them, so the
-- routers were repointed at `year_end_notes`, `year_end_checklist_items` and
-- `year_end_review_events` instead of creating a second, duplicate set.
--
-- ── What this creates, and where each definition comes from ─────────────────
--   government_notices     migration 052 + the three columns from 158
--   gstr2b_uploads         migration 052
--   firm_hsn_rate_history  migration 181 (verbatim — it was already correct)
--   reminders.firm_id      migration 008
--   clients.is_test        migration 042
--
-- Every statement is IF NOT EXISTS / idempotent, so this is a no-op anywhere the
-- originals did land.
--
-- ── One deliberate deviation from the originals ─────────────────────────────
-- 052 wrote its policies as:
--
--     CREATE POLICY "firm_isolation" ON public.government_notices
--         USING (firm_id = get_my_firm_id());
--
-- That has two problems this migration does NOT reproduce:
--
--   1. No explicit WITH CHECK. This is NOT a tenant-isolation hole — Postgres
--      reuses the USING expression as the WITH CHECK when none is given, so
--      firm_id = get_my_firm_id() is still enforced on INSERT. (An earlier
--      version of this comment claimed otherwise; it was wrong about Postgres
--      semantics.) Writing it explicitly is still worth doing: it states the
--      write rule at the point someone reads the policy, rather than leaving it
--      to a fallback, and it stops a later `FOR SELECT`-style narrowing from
--      silently changing what INSERT allows.
--   2. No TO clause, so the policy binds to PUBLIC rather than `authenticated`.
--
-- Both are fixed here, matching the convention migrations 093 and 181 settled
-- on. Recreating a known-broken policy just because it is what the original file
-- said would be the wrong kind of faithful.

BEGIN;

-- ── 1. government_notices (052) ─────────────────────────────────────────────
-- AI-extracted statutory notices. Read/written by routers/document_intelligence_v2.py.
CREATE TABLE IF NOT EXISTS public.government_notices (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id             UUID        NOT NULL,
    client_id           UUID        NOT NULL,
    notice_type         TEXT        NOT NULL,   -- gst_scrutiny | income_tax | mca_show_cause | …
    authority           TEXT        NOT NULL,   -- GSTN | Income Tax Dept | MCA21 | …
    reference_no        TEXT,
    issue_date          DATE,
    response_due_date   DATE,
    description         TEXT,
    source_document_url TEXT,
    extracted_data      JSONB,
    status              TEXT        NOT NULL DEFAULT 'open',
    task_id             UUID,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Migration 158's columns. A notice is a statutory document — nothing acts on it
-- until a CA has approved it (CLAUDE.md: never auto-submit, always require an
-- explicit confirmation).
ALTER TABLE public.government_notices
  ADD COLUMN IF NOT EXISTS ca_approved    BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS ca_approved_by UUID,
  ADD COLUMN IF NOT EXISTS ca_approved_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_government_notices_firm_client
    ON public.government_notices (firm_id, client_id);
CREATE INDEX IF NOT EXISTS idx_government_notices_due
    ON public.government_notices (response_due_date) WHERE status <> 'closed';

ALTER TABLE public.government_notices ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "firm_isolation" ON public.government_notices;
DROP POLICY IF EXISTS government_notices_isolation ON public.government_notices;
CREATE POLICY government_notices_isolation ON public.government_notices
    FOR ALL TO authenticated
    USING (firm_id = public.get_my_firm_id())
    WITH CHECK (firm_id = public.get_my_firm_id());
GRANT SELECT, INSERT, UPDATE, DELETE ON public.government_notices TO authenticated;
GRANT ALL                            ON public.government_notices TO service_role;

-- ── 2. gstr2b_uploads (052) ─────────────────────────────────────────────────
-- CGST Act s.38 — the auto-drafted inward-supplies statement, plus the stored
-- result of reconciling it against the books. Written by routers/gst_workspace.py.
CREATE TABLE IF NOT EXISTS public.gstr2b_uploads (
    id                    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id               UUID        NOT NULL,
    client_id             UUID        NOT NULL,
    period                TEXT        NOT NULL,   -- MMYYYY, e.g. '042026'
    uploaded_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    file_url              TEXT,
    raw_data              JSONB,
    reconciliation_result JSONB,
    status                TEXT        NOT NULL DEFAULT 'uploaded',
    created_by            UUID
);

CREATE INDEX IF NOT EXISTS idx_gstr2b_uploads_firm_client_period
    ON public.gstr2b_uploads (firm_id, client_id, period);

ALTER TABLE public.gstr2b_uploads ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "firm_isolation" ON public.gstr2b_uploads;
DROP POLICY IF EXISTS gstr2b_uploads_isolation ON public.gstr2b_uploads;
CREATE POLICY gstr2b_uploads_isolation ON public.gstr2b_uploads
    FOR ALL TO authenticated
    USING (firm_id = public.get_my_firm_id())
    WITH CHECK (firm_id = public.get_my_firm_id());
GRANT SELECT, INSERT, UPDATE, DELETE ON public.gstr2b_uploads TO authenticated;
GRANT ALL                            ON public.gstr2b_uploads TO service_role;

-- ── 3. firm_hsn_rate_history (181, verbatim) ────────────────────────────────
-- CA-entered GST rate history per HSN. Rates are entered, never computed.
CREATE TABLE IF NOT EXISTS public.firm_hsn_rate_history (
    id                    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id               UUID        NOT NULL,
    firm_hsn_library_id   UUID        NOT NULL
        REFERENCES public.firm_hsn_library(id) ON DELETE CASCADE,
    gst_rate_pct          NUMERIC(5,2) NOT NULL,
    cess_rate_pct         NUMERIC(5,2),
    cess_specific_paise_per_unit BIGINT,
    supply_type           TEXT        NOT NULL DEFAULT 'taxable'
        CHECK (supply_type IN ('taxable', 'exempt', 'nil', 'non_gst')),
    effective_from        DATE        NOT NULL,
    effective_to          DATE,
    notes                 TEXT,
    created_by            UUID,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT firm_hsn_rate_history_rate_range
        CHECK (gst_rate_pct >= 0 AND gst_rate_pct <= 100),
    CONSTRAINT firm_hsn_rate_history_cess_range
        CHECK (cess_rate_pct IS NULL OR (cess_rate_pct >= 0 AND cess_rate_pct <= 100)),
    CONSTRAINT firm_hsn_rate_history_cess_specific_nonneg
        CHECK (cess_specific_paise_per_unit IS NULL OR cess_specific_paise_per_unit >= 0),
    CONSTRAINT firm_hsn_rate_history_date_order
        CHECK (effective_to IS NULL OR effective_to >= effective_from)
);

CREATE INDEX IF NOT EXISTS idx_firm_hsn_rate_history_lookup
    ON public.firm_hsn_rate_history (firm_hsn_library_id, effective_from DESC);

ALTER TABLE public.firm_hsn_rate_history ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS firm_hsn_rate_history_isolation ON public.firm_hsn_rate_history;
CREATE POLICY firm_hsn_rate_history_isolation ON public.firm_hsn_rate_history
    FOR ALL TO authenticated
    USING (firm_id = public.get_my_firm_id())
    WITH CHECK (firm_id = public.get_my_firm_id());
GRANT SELECT, INSERT, UPDATE ON public.firm_hsn_rate_history TO authenticated;
GRANT ALL                    ON public.firm_hsn_rate_history TO service_role;

-- ── 4. reminders.firm_id (008) ──────────────────────────────────────────────
-- routers/reminders.py passes firm_id into find_all unconditionally and inserts
-- it on create, so GET and POST /api/reminders have both been failing outright.
ALTER TABLE public.reminders
  ADD COLUMN IF NOT EXISTS firm_id UUID REFERENCES public.firms(id);

-- Backfill from the owning client where possible. A no-op on this database
-- (reminders is empty), but correct anywhere the table already holds rows.
UPDATE public.reminders r
   SET firm_id = c.firm_id
  FROM public.clients c
 WHERE r.client_id = c.id
   AND r.firm_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_reminders_firm_id ON public.reminders (firm_id);

-- ── 5. The year-end tables production actually has ──────────────────────────
--
-- These are NOT new. They exist in production, created by a Studio migration
-- recorded as `phase6_year_end_tables`, and the routers have now been repointed
-- at them. What was missing is the repository's KNOWLEDGE of them: no file here
-- ever defined them, so a database built by replaying migrations (CI, and every
-- fresh environment) would not have them and the repointed routers would break
-- there while working in production. Defining them closes that gap — repository
-- and production finally describe the same schema.
--
-- Shape copied from the live catalog, column for column, so this is a strict
-- no-op in production.
--
-- HISTORY WORTH KNOWING: migration 155 hit this same fork and chose the other
-- branch — it fixed the CODE to use 067's names (year_end_checklists,
-- notes_to_accounts, year_end_reviews) and repaired their columns. Neither 067
-- nor 155 ever reached production, so that decision only ever existed in the
-- repository while production ran the other naming. Going the other way now is
-- the cheaper reconciliation: production's tables hold real engagements, and
-- renaming live tables to match a file nobody applied would be the riskier half
-- of the trade. 067's tables are consequently dead in fresh environments;
-- dropping them is a separate cleanup, not something to do in a repair.

CREATE TABLE IF NOT EXISTS public.year_end_notes (
    id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    engagement_id     UUID        NOT NULL REFERENCES public.year_end_engagements(id) ON DELETE CASCADE,
    firm_id           UUID        NOT NULL,
    note_type         TEXT        NOT NULL,
    sequence_no       INTEGER     NOT NULL DEFAULT 0,
    title             TEXT        NOT NULL,
    content           TEXT,
    note_data         JSONB,
    is_locked         BOOLEAN     NOT NULL DEFAULT false,
    is_auto_generated BOOLEAN     NOT NULL DEFAULT false,
    locked_by         UUID,
    locked_at         TIMESTAMPTZ,
    created_by        UUID        NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.year_end_checklist_items (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    engagement_id UUID        NOT NULL REFERENCES public.year_end_engagements(id) ON DELETE CASCADE,
    firm_id       UUID        NOT NULL,
    category      TEXT        NOT NULL,
    item_code     TEXT        NOT NULL,
    item_label    TEXT        NOT NULL,
    sequence_no   INTEGER     NOT NULL DEFAULT 0,
    status        TEXT        NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'in_progress', 'complete', 'not_applicable')),
    notes         TEXT,
    completed_by  UUID,
    completed_at  TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.year_end_review_events (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    engagement_id UUID        NOT NULL REFERENCES public.year_end_engagements(id) ON DELETE CASCADE,
    firm_id       UUID        NOT NULL,
    event_type    TEXT        NOT NULL
        CHECK (event_type IN ('submitted_for_review', 'approved',
                              'revision_requested', 'final_approved_and_locked')),
    comment       TEXT,
    actor_id      UUID        NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_year_end_notes_engagement
    ON public.year_end_notes (engagement_id, sequence_no);
CREATE INDEX IF NOT EXISTS idx_year_end_checklist_items_engagement
    ON public.year_end_checklist_items (engagement_id, sequence_no);
CREATE INDEX IF NOT EXISTS idx_year_end_review_events_engagement
    ON public.year_end_review_events (engagement_id, created_at DESC);

DO $ye_rls$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['year_end_notes','year_end_checklist_items','year_end_review_events'] LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_isolation', t);
        EXECUTE format(
            'CREATE POLICY %I ON public.%I FOR ALL TO authenticated '
            'USING (firm_id = public.get_my_firm_id()) '
            'WITH CHECK (firm_id = public.get_my_firm_id())', t || '_isolation', t);
        EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON public.%I TO authenticated', t);
        EXECUTE format('GRANT ALL ON public.%I TO service_role', t);
    END LOOP;
END
$ye_rls$;

-- ── 6. clients.is_test (042) ────────────────────────────────────────────────
-- Latent rather than live: include_test defaults to True in both the repository
-- and the router, so only an explicit ?include_test=false hit the missing column.
ALTER TABLE public.clients
  ADD COLUMN IF NOT EXISTS is_test BOOLEAN NOT NULL DEFAULT false;

-- ── Post-conditions ─────────────────────────────────────────────────────────
-- Assert the exact objects the audit found missing, so a partial apply cannot
-- commit and quietly leave an endpoint broken.
DO $verify$
DECLARE missing text[] := ARRAY[]::text[];
BEGIN
    IF to_regclass('public.government_notices')    IS NULL THEN missing := missing || 'government_notices'; END IF;
    IF to_regclass('public.gstr2b_uploads')        IS NULL THEN missing := missing || 'gstr2b_uploads'; END IF;
    IF to_regclass('public.firm_hsn_rate_history') IS NULL THEN missing := missing || 'firm_hsn_rate_history'; END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_schema='public' AND table_name='government_notices'
                      AND column_name='ca_approved') THEN
        missing := missing || 'government_notices.ca_approved';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_schema='public' AND table_name='reminders'
                      AND column_name='firm_id') THEN
        missing := missing || 'reminders.firm_id';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_schema='public' AND table_name='clients'
                      AND column_name='is_test') THEN
        missing := missing || 'clients.is_test';
    END IF;

    IF array_length(missing, 1) > 0 THEN
        RAISE EXCEPTION 'Migration 252 failed: still missing %', array_to_string(missing, ', ');
    END IF;

    -- Every new table must isolate by firm on BOTH read and write. A policy
    -- without WITH CHECK would let one firm insert rows into another's data —
    -- exactly the defect in 052's original policies.
    IF EXISTS (
        SELECT 1 FROM pg_policies
         WHERE schemaname = 'public'
           AND tablename IN ('government_notices','gstr2b_uploads','firm_hsn_rate_history',
                             'year_end_notes','year_end_checklist_items','year_end_review_events')
           AND (qual IS NULL OR with_check IS NULL)
    ) THEN
        RAISE EXCEPTION
            'Migration 252 failed: a new table has an RLS policy missing USING or WITH CHECK.';
    END IF;

    -- The three the routers were repointed at must exist, or those endpoints
    -- work in production and break everywhere else.
    IF to_regclass('public.year_end_notes')           IS NULL
       OR to_regclass('public.year_end_checklist_items') IS NULL
       OR to_regclass('public.year_end_review_events')   IS NULL THEN
        RAISE EXCEPTION
            'Migration 252 failed: a year-end table the routers target is missing.';
    END IF;
END
$verify$;

COMMIT;
