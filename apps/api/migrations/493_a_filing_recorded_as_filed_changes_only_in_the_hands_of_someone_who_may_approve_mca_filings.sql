-- Migration 493 — an MCA filing recorded as filed changes only in the hands of someone who may approve MCA filings
-- (found by the 14-10-2026 audit of the browser's direct writes; ledger POST-A-225).
--
-- THE HOLE
--   `mca_filings` takes its writes from anyone with `mca:write` (Executive and above: migration 488). The API reserves
--   RECORDING A FILING AS FILED to `mca:approve` (Manager and above) with the CA's explicit confirmation
--   (PATCH /api/mca-workspace/filings/{id}/status), but a row policy cannot see a transition, so with their own sign-in
--   an Executive could write `status = 'filed'` with an SRN and a date straight into the table, create a row already
--   filed, reopen a filed one, rewrite its SRN or delete it. The MCA screen did exactly that (three places, one of which
--   supplied TODAY as the date it was filed), and the screen now goes through the route (same change). A statutory
--   filing recorded as done by someone the route would refuse is a false statement to the partner who relies on the
--   tracker and, through the risk views, to the client.
--
-- WHAT THIS DOES (RESTRICTIVE, so it ANDs with the firm, assignment and `mca:write` rules and can only narrow)
--   With `my_permission('mca', 'approve', 'Manager')` (so the per-person grid counts here as it does in `can_user` at the
--   route):
--     INSERT   a row may be created `filed` only by someone who may approve
--     UPDATE   a row that is CURRENTLY `filed` may be changed only by someone who may approve, and any row may be given
--              the status `filed` only by them. An Executive still creates, edits and progresses an unfiled filing.
--     DELETE   a filed filing is deleted only by someone who may approve
--
-- WHAT IT LEAVES ALONE, AND SAYS SO
--   * The service role and a connection with no JWT are not `authenticated` and are untouched.
--   * It does not decide which transitions are valid (a Manager can still reopen a filed filing through the route).
--   * No function, grant, table or row changes. No backfill.
--
-- Idempotent: DROP POLICY IF EXISTS before each CREATE, and the closing check fails the migration (and so the deploy) if
-- any policy is missing or not RESTRICTIVE. Reversible: 493_..._rollback.sql drops them again, which RE-OPENS the hole.

DROP POLICY IF EXISTS "mca_filings_state_tier_insert" ON public.mca_filings;
CREATE POLICY "mca_filings_state_tier_insert" ON public.mca_filings
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (COALESCE(status, 'not_started') <> 'filed'
              OR public.my_permission('mca', 'approve', 'Manager'));

DROP POLICY IF EXISTS "mca_filings_state_tier_update" ON public.mca_filings;
CREATE POLICY "mca_filings_state_tier_update" ON public.mca_filings
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (COALESCE(status, 'not_started') <> 'filed'
         OR public.my_permission('mca', 'approve', 'Manager'))
  WITH CHECK (COALESCE(status, 'not_started') <> 'filed'
              OR public.my_permission('mca', 'approve', 'Manager'));

DROP POLICY IF EXISTS "mca_filings_state_tier_delete" ON public.mca_filings;
CREATE POLICY "mca_filings_state_tier_delete" ON public.mca_filings
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (COALESCE(status, 'not_started') <> 'filed'
         OR public.my_permission('mca', 'approve', 'Manager'));

-- ── the closing check: all three policies exist and every one is RESTRICTIVE ─────────────────────
DO $$
DECLARE
  n int;
BEGIN
  SELECT count(*) INTO n
    FROM pg_policies
   WHERE schemaname = 'public'
     AND permissive = 'RESTRICTIVE'
     AND policyname IN ('mca_filings_state_tier_insert', 'mca_filings_state_tier_update', 'mca_filings_state_tier_delete');
  IF n <> 3 THEN
    RAISE EXCEPTION 'migration 493: expected 3 restrictive policies, found %', n;
  END IF;
END $$;
