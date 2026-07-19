-- Migration 233: MCA Workspace schema-drift fixes.
--
-- routers/mca_workspace.py has, since it was written, referenced columns and
-- CHECK-constraint values on mca_companies/mca_directors/mca_filings that no
-- migration ever created — every create_company/create_director/create_filing
-- call fails against a real Postgres instance (masked behind a generic
-- api_response(False, "Unable to complete MCA operation") try/except), and
-- both GET /companies/{id} and GET /filings?company_id= 500 on their
-- .eq("company_id", ...) filter since the column doesn't exist on either
-- mca_directors or mca_filings. This migration adds the missing columns and
-- widens the two CHECK constraints the router/frontend already assume are
-- wider than what migration 038 actually created.

-- 1. mca_directors/mca_filings need a company_id link — mca_companies
--    already supports multiple companies per client (UNIQUE(client_id, cin)),
--    and both the request models (CreateDirectorRequest.company_id,
--    CreateFilingRequest.company_id) and GET /companies/{id} (which joins
--    directors by company_id) assume this column exists. Nullable: the
--    current frontend doesn't populate it, so existing client-scoped
--    directors/filings are unaffected.
ALTER TABLE public.mca_directors
    ADD COLUMN IF NOT EXISTS company_id UUID REFERENCES public.mca_companies(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_mca_directors_company ON public.mca_directors (company_id);

ALTER TABLE public.mca_filings
    ADD COLUMN IF NOT EXISTS company_id UUID REFERENCES public.mca_companies(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_mca_filings_company ON public.mca_filings (company_id);

-- 2. mca_filings.category — routers/mca_workspace.py's create_filing computes
--    "annual" vs "event" from form_type and the frontend filters the list by
--    it (FilingsTab.load: all.filter(f => f.category === category)); no
--    migration ever added the column, so every filing silently vanished from
--    both the Annual and Event tabs.
ALTER TABLE public.mca_filings
    ADD COLUMN IF NOT EXISTS category TEXT CHECK (category IN ('annual', 'event'));

-- 3. mca_filings.acknowledgement_url — proof-of-filing reference the
--    complete-filing flow (Companies Act §92/137/139/165, CA-confirmed only)
--    already persists.
ALTER TABLE public.mca_filings
    ADD COLUMN IF NOT EXISTS acknowledgement_url TEXT;

-- 4. mca_filings.status — the router/frontend's filing lifecycle is
--    not_started -> in_progress -> filed (FilingsTab hard-codes all three
--    plus "overdue"), but migration 038's CHECK only allowed
--    ('pending','filed','overdue','in_progress','not_applicable'), so
--    create_filing's default status="not_started" violated the constraint on
--    every insert. Purely additive — existing 'pending'/'not_applicable' rows
--    (if any) remain valid.
ALTER TABLE public.mca_filings DROP CONSTRAINT IF EXISTS mca_filings_status_check;
ALTER TABLE public.mca_filings
    ADD CONSTRAINT mca_filings_status_check
    CHECK (status IN ('pending', 'not_started', 'filed', 'overdue', 'in_progress', 'not_applicable'));

-- 5. mca_directors.kyc_status — the frontend's "Mark KYC Active" button
--    (DirectorsTab.updateKYC) sends kyc_status="active", but migration 038's
--    CHECK only allowed ('pending','filed','overdue','deactivated'), so that
--    action always failed the constraint. Purely additive.
ALTER TABLE public.mca_directors DROP CONSTRAINT IF EXISTS mca_directors_kyc_status_check;
ALTER TABLE public.mca_directors
    ADD CONSTRAINT mca_directors_kyc_status_check
    CHECK (kyc_status IN ('pending', 'filed', 'overdue', 'deactivated', 'active'));
