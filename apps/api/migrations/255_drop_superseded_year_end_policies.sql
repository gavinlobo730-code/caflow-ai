-- Migration 255: drop the superseded year-end RLS policies that only ever
-- existed in production.
--
-- WHY THIS EXISTS
-- The three year_end_* tables were created in production by a Studio migration
-- (`phase6_year_end_tables`), not by any file in this repository — that is the
-- gap migration 252 closed by finally defining them here. Production's copies
-- came with policies of their own:
--
--     CREATE POLICY yen_firm ON public.year_end_notes
--         FOR ALL USING (firm_id = get_my_firm_id());
--
-- and the same shape as `yeci_firm` / `yere_firm`.
--
-- These are NOT broken. A permissive FOR ALL policy with USING and no WITH
-- CHECK still constrains INSERT, because Postgres reuses the USING expression
-- as the WITH CHECK when none is supplied. Tenant isolation held throughout.
--
-- What they are is REDUNDANT, and redundant permissive policies are their own
-- hazard: RLS OR-s permissive policies together, so the effective rule is the
-- union. Leaving `yen_firm` (TO PUBLIC) alongside 252's `year_end_notes_isolation`
-- (TO authenticated) means the stricter of the two never actually binds — the
-- looser one keeps letting rows through. Anyone later tightening the _isolation
-- policy would change nothing and have no way to tell.
--
-- 252's own post-condition refuses to commit while a policy on these tables has
-- a NULL with_check in pg_policies, which is exactly how the legacy pair
-- registers. So this is also what lets 252 apply to production at all.
--
-- IDEMPOTENT AND A NO-OP EVERYWHERE ELSE. Nothing in this repository ever
-- created these policy names, so a database built by replaying migrations has
-- never had them. This matters only for production and for anything restored
-- from it.
--
-- HISTORY: 251-254 were applied to production by hand via the Supabase MCP
-- connection on 2026-08-03, because the `apply pending migrations — production`
-- CI job cannot run — the SUPABASE_DB_URL secret is unset, so that job has
-- failed on every push to main since it was added. The policy drops below were
-- part of that manual apply; this file exists so the repository records them
-- rather than leaving them as an undocumented hand edit. Setting the secret is
-- the real fix and is still outstanding.

BEGIN;

DROP POLICY IF EXISTS yen_firm  ON public.year_end_notes;
DROP POLICY IF EXISTS yeci_firm ON public.year_end_checklist_items;
DROP POLICY IF EXISTS yere_firm ON public.year_end_review_events;

-- ── Post-conditions ─────────────────────────────────────────────────────────
DO $verify$
BEGIN
    -- The superseded pair must be gone...
    IF EXISTS (SELECT 1 FROM pg_policies
                WHERE schemaname = 'public'
                  AND policyname IN ('yen_firm', 'yeci_firm', 'yere_firm')) THEN
        RAISE EXCEPTION 'Migration 255 failed: a superseded year-end policy survives.';
    END IF;

    -- ...and each table must still be covered, so this never leaves one open.
    -- (RLS with zero policies denies everything to `authenticated`, which would
    -- break the year-end pages rather than expose them — still wrong, and still
    -- worth refusing to commit over.)
    IF (SELECT count(*) FROM pg_policies
         WHERE schemaname = 'public'
           AND tablename IN ('year_end_notes','year_end_checklist_items',
                             'year_end_review_events')) <> 3 THEN
        RAISE EXCEPTION
            'Migration 255 failed: expected exactly one policy per year-end table.';
    END IF;
END
$verify$;

COMMIT;
