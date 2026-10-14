-- Migration 491 — an approved or filed GST return changes only in the hands of someone who may approve GST returns
-- (security_privacy-34 family, found by an independent audit of the browser's direct writes; ledger POST-A-223 and
-- POST-A-224).
--
-- THE HOLE
--   `gstr1_returns` and `gstr3b_returns` take their writes from anyone who holds `gst:compute` (Executive and above:
--   migration 488). The API reserves APPROVING a return and RECORDING IT AS FILED to `gst:approve` (Manager and above:
--   PATCH /gstr1/{id}/status and /gstr3b/{id}/status), and refuses to delete a filed one. A row policy cannot see a
--   TRANSITION, but it can see the status a row has and the status it is given, so with their own sign-in an Executive
--   could, over PostgREST:
--     * set a return to `ca_approved`, or to `submitted` with an ARN (a filed record with no `filings` row behind it, so
--       no period lock), and name any user as the approver;
--     * reopen an approved or filed return to `draft`;
--     * rewrite the payload of an approved return, or DELETE a filed one (the API refuses both).
--   The web screens did exactly the first (approveGSTR1 / approveGSTR3B wrote the approval themselves) and, on every
--   ordinary Build or Compute click, the second. Both now go through the API (same change), which leaves the database
--   the backstop for a request that is not the screen's.
--
-- WHAT THIS DOES (RESTRICTIVE, so it ANDs with the firm, assignment and `gst:compute` rules and can only narrow)
--   For both tables, with the pair the route asks, `my_permission('gst', 'approve', 'Manager')` (so the per-person
--   grid counts here as it does in `can_user` at the route):
--     INSERT   the new row's status may be ca_approved or submitted only for someone who may approve
--     UPDATE   a row that is CURRENTLY ca_approved or submitted may be changed only by someone who may approve, and
--              may be GIVEN either status only by them. An Executive still prepares drafts and validated returns, and
--              still revises their own draft; an approved return is the approver's to reopen.
--     DELETE   a submitted return is deleted by NOBODY signed in (the route refuses it for every role: it carries the
--              ARN and the `filings` row that locks the period), and an approved one only by someone who may approve.
--
-- WHAT THIS CHANGES FOR A PERSON
--   An Executive who rebuilds a return a Manager has already approved is now refused (it would void the Manager's
--   approval without the Manager). The route answers in words ("only someone who may approve GST returns can change,
--   reopen, recompute or delete it") before the database has to; the screen shows the sentence. A Manager the Partner has
--   blocked from `gst:approve` in the access grid is treated as an Executive here, as they are at the route.
--
-- WHAT IT LEAVES ALONE, AND SAYS SO
--   * The service role and a connection with no JWT (the backend's own jobs, the migration runner) are not
--     `authenticated` and are untouched.
--   * It does not make the transitions themselves valid: a Manager can still move a submitted return back to draft
--     through the status route. That is the route's rule, not a row-policy question, and it is not changed here.
--   * Other return kinds share these two tables (`return_type` gstr9, gstr9c, iff, and so on) and follow the same rule.
--   * No function, grant, table or row changes. No backfill.
--
-- Idempotent: DROP POLICY IF EXISTS before each CREATE, and the closing check fails the migration (and so the deploy)
-- if any policy is missing or not RESTRICTIVE. Reversible: 491_..._rollback.sql drops them again, which RE-OPENS the hole.

-- ── gstr1_returns ────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "gstr1_returns_state_tier_insert" ON public.gstr1_returns;
CREATE POLICY "gstr1_returns_state_tier_insert" ON public.gstr1_returns
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (COALESCE(status, 'draft') NOT IN ('ca_approved', 'submitted')
              OR public.my_permission('gst', 'approve', 'Manager'));

DROP POLICY IF EXISTS "gstr1_returns_state_tier_update" ON public.gstr1_returns;
CREATE POLICY "gstr1_returns_state_tier_update" ON public.gstr1_returns
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (COALESCE(status, 'draft') NOT IN ('ca_approved', 'submitted')
         OR public.my_permission('gst', 'approve', 'Manager'))
  WITH CHECK (COALESCE(status, 'draft') NOT IN ('ca_approved', 'submitted')
              OR public.my_permission('gst', 'approve', 'Manager'));

DROP POLICY IF EXISTS "gstr1_returns_state_tier_delete" ON public.gstr1_returns;
CREATE POLICY "gstr1_returns_state_tier_delete" ON public.gstr1_returns
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (COALESCE(status, 'draft') <> 'submitted'
         AND (COALESCE(status, 'draft') <> 'ca_approved'
              OR public.my_permission('gst', 'approve', 'Manager')));

-- ── gstr3b_returns ───────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "gstr3b_returns_state_tier_insert" ON public.gstr3b_returns;
CREATE POLICY "gstr3b_returns_state_tier_insert" ON public.gstr3b_returns
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (COALESCE(status, 'draft') NOT IN ('ca_approved', 'submitted')
              OR public.my_permission('gst', 'approve', 'Manager'));

DROP POLICY IF EXISTS "gstr3b_returns_state_tier_update" ON public.gstr3b_returns;
CREATE POLICY "gstr3b_returns_state_tier_update" ON public.gstr3b_returns
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (COALESCE(status, 'draft') NOT IN ('ca_approved', 'submitted')
         OR public.my_permission('gst', 'approve', 'Manager'))
  WITH CHECK (COALESCE(status, 'draft') NOT IN ('ca_approved', 'submitted')
              OR public.my_permission('gst', 'approve', 'Manager'));

DROP POLICY IF EXISTS "gstr3b_returns_state_tier_delete" ON public.gstr3b_returns;
CREATE POLICY "gstr3b_returns_state_tier_delete" ON public.gstr3b_returns
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (COALESCE(status, 'draft') <> 'submitted'
         AND (COALESCE(status, 'draft') <> 'ca_approved'
              OR public.my_permission('gst', 'approve', 'Manager')));

-- ── the closing check: all six policies exist and every one is RESTRICTIVE ───────────────────────
DO $$
DECLARE
  n int;
BEGIN
  SELECT count(*) INTO n
    FROM pg_policies
   WHERE schemaname = 'public'
     AND permissive = 'RESTRICTIVE'
     AND policyname IN (
       'gstr1_returns_state_tier_insert', 'gstr1_returns_state_tier_update', 'gstr1_returns_state_tier_delete',
       'gstr3b_returns_state_tier_insert', 'gstr3b_returns_state_tier_update', 'gstr3b_returns_state_tier_delete');
  IF n <> 6 THEN
    RAISE EXCEPTION 'migration 491: expected 6 restrictive policies, found %', n;
  END IF;
END $$;
