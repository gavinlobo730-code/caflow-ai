-- Migration 483 — four tables get, in the database, the role tier and the client scope the API already gives them
-- (security_privacy-34, found by the role-by-table access matrix; ledger POST-B-006, POST-B-025, POST-B-026).
--
-- THE HOLES (each reproduced by tests/test_rls_role_by_table_matrix_pg.py before this migration)
--
--   1. `vendors` and `knowledge_articles` have a firm policy and an assignment scope and NO role tier, so an
--      Executive assigned to a client could insert, update and delete that client's vendors, and an Executive
--      or Reviewer could write knowledge articles, straight over PostgREST with their own JWT. The API refuses
--      every one of those: POST/PATCH /api/vendors take `client:write` (Manager and above), DELETE takes
--      `client:delete` (Partner), and the knowledge routes take `knowledge:write` (Manager and above).
--
--   2. `cross_client_matches` names TWO clients (client_id_a, client_id_b) and the PAN, GSTIN or e-mail that
--      links them, and its one policy is `firm_id = get_my_firm_id()`. Every member of the firm could read, and
--      write, every match, including ones that disclose a client they are not assigned to. The API narrows the
--      list to matches where BOTH clients are in the caller's reach (`routers/relationships._match_visible`:
--      "not either: seeing it with only one end authorised still discloses the other end") and takes
--      `client:write` for detect and review.
--
--   3. `year_end_notes` and `year_end_review_events` carry `engagement_id` and no `client_id`, so migration 084's
--      assignment scope never reached them: every member read and wrote the notes and the review trail of every
--      client's year-end engagement, and an unassigned Executive or a Reviewer could rewrite them. The API takes
--      `year_end:write` (Executive and above) for the notes and the review events.
--
-- WHAT THIS DOES
--   All new policies are RESTRICTIVE, so they AND with the existing firm-isolation and assignment-scope rules
--   and can only narrow, never widen. Role is asked through `my_permission(resource, action, minimum_role)`,
--   the function the route's `rbac()` resolves through, so a per-person grant or denial in the access grid
--   (migrations 403/415) is honoured in both places. `get_my_user_id()` and `get_my_role()` answer NULL for a
--   suspended or signed-out member (468), so they have no tier.
--
--   vendors               INSERT, UPDATE  my_permission('client', 'write', 'Manager')
--                         DELETE          my_permission('client', 'delete', 'Partner')   (the API's own tier)
--   knowledge_articles    INSERT, UPDATE, DELETE  my_permission('knowledge', 'write', 'Manager')
--                         (the API has no delete route; a delete takes the write tier, as in 260/261)
--   cross_client_matches  ALL: can_access_client(client_id_a) AND can_access_client(client_id_b)
--                         INSERT, UPDATE, DELETE  my_permission('client', 'write', 'Manager')
--   year_end_notes,       ALL: the parent engagement is in the caller's reach
--   year_end_review_events  (EXISTS year_end_engagements e, e.id = engagement_id AND can_access_client(e.client_id))
--                         INSERT, UPDATE, DELETE  my_permission('year_end', 'write', 'Executive')
--
-- WHAT IT LEAVES ALONE, AND SAYS SO
--   * SELECT stays as it was on `vendors` and `knowledge_articles` (all assigned staff read them), and below
--     Executive on the year-end children: who may READ year-end data below Executive is undocumented in
--     core/permissions and the access matrix records the observed value without claiming it is right.
--   * The internal practice client's Partner-only policies on `vendors` and `knowledge_articles` are untouched.
--   * No function, grant, table or row changes. No backfill: a note, match or vendor already written stays.
--   * The fee tables (`fee_engagements`, `fee_invoices`, `fee_receipts`) are NOT in this migration. Making their
--     reads Partner-only changes what the Fee Receivables screen and the firm analytics endpoint show to a
--     Manager (a silent zero where an unknown belongs), so that change ships with those two consumers.
--
-- Idempotent: DROP POLICY IF EXISTS before each CREATE, and the closing check fails the migration (and so the
-- deploy) if any policy is missing. Reversible:
-- 483_the_role_tiers_and_client_scopes_the_api_gives_four_more_tables_reach_the_database_rollback.sql
-- drops them again, which RE-OPENS the holes.

-- ── vendors ──────────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "vendors_role_insert" ON public.vendors;
CREATE POLICY "vendors_role_insert" ON public.vendors
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('client', 'write', 'Manager'));

DROP POLICY IF EXISTS "vendors_role_update" ON public.vendors;
CREATE POLICY "vendors_role_update" ON public.vendors
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('client', 'write', 'Manager'))
  WITH CHECK (public.my_permission('client', 'write', 'Manager'));

DROP POLICY IF EXISTS "vendors_role_delete" ON public.vendors;
CREATE POLICY "vendors_role_delete" ON public.vendors
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('client', 'delete', 'Partner'));

-- ── knowledge_articles ───────────────────────────────────────────────────────
DROP POLICY IF EXISTS "knowledge_articles_role_insert" ON public.knowledge_articles;
CREATE POLICY "knowledge_articles_role_insert" ON public.knowledge_articles
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('knowledge', 'write', 'Manager'));

DROP POLICY IF EXISTS "knowledge_articles_role_update" ON public.knowledge_articles;
CREATE POLICY "knowledge_articles_role_update" ON public.knowledge_articles
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('knowledge', 'write', 'Manager'))
  WITH CHECK (public.my_permission('knowledge', 'write', 'Manager'));

DROP POLICY IF EXISTS "knowledge_articles_role_delete" ON public.knowledge_articles;
CREATE POLICY "knowledge_articles_role_delete" ON public.knowledge_articles
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('knowledge', 'write', 'Manager'));

-- ── cross_client_matches: both ends in reach, then the write tier ────────────
DROP POLICY IF EXISTS "cross_client_matches_both_clients_in_reach" ON public.cross_client_matches;
CREATE POLICY "cross_client_matches_both_clients_in_reach" ON public.cross_client_matches
  AS RESTRICTIVE FOR ALL TO authenticated
  USING (
    public.can_access_client(client_id_a::text)
    AND public.can_access_client(client_id_b::text)
  )
  WITH CHECK (
    public.can_access_client(client_id_a::text)
    AND public.can_access_client(client_id_b::text)
  );

DROP POLICY IF EXISTS "cross_client_matches_role_insert" ON public.cross_client_matches;
CREATE POLICY "cross_client_matches_role_insert" ON public.cross_client_matches
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('client', 'write', 'Manager'));

DROP POLICY IF EXISTS "cross_client_matches_role_update" ON public.cross_client_matches;
CREATE POLICY "cross_client_matches_role_update" ON public.cross_client_matches
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('client', 'write', 'Manager'))
  WITH CHECK (public.my_permission('client', 'write', 'Manager'));

DROP POLICY IF EXISTS "cross_client_matches_role_delete" ON public.cross_client_matches;
CREATE POLICY "cross_client_matches_role_delete" ON public.cross_client_matches
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('client', 'write', 'Manager'));

-- ── year_end_notes and year_end_review_events: the engagement's client, then the write tier ──
DROP POLICY IF EXISTS "year_end_notes_engagement_in_reach" ON public.year_end_notes;
CREATE POLICY "year_end_notes_engagement_in_reach" ON public.year_end_notes
  AS RESTRICTIVE FOR ALL TO authenticated
  USING (EXISTS (
    SELECT 1 FROM public.year_end_engagements e
     WHERE e.id = year_end_notes.engagement_id
       AND public.can_access_client(e.client_id::text)))
  WITH CHECK (EXISTS (
    SELECT 1 FROM public.year_end_engagements e
     WHERE e.id = year_end_notes.engagement_id
       AND public.can_access_client(e.client_id::text)));

DROP POLICY IF EXISTS "year_end_notes_role_insert" ON public.year_end_notes;
CREATE POLICY "year_end_notes_role_insert" ON public.year_end_notes
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('year_end', 'write', 'Executive'));

DROP POLICY IF EXISTS "year_end_notes_role_update" ON public.year_end_notes;
CREATE POLICY "year_end_notes_role_update" ON public.year_end_notes
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('year_end', 'write', 'Executive'))
  WITH CHECK (public.my_permission('year_end', 'write', 'Executive'));

DROP POLICY IF EXISTS "year_end_notes_role_delete" ON public.year_end_notes;
CREATE POLICY "year_end_notes_role_delete" ON public.year_end_notes
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('year_end', 'write', 'Executive'));

DROP POLICY IF EXISTS "year_end_review_events_engagement_in_reach" ON public.year_end_review_events;
CREATE POLICY "year_end_review_events_engagement_in_reach" ON public.year_end_review_events
  AS RESTRICTIVE FOR ALL TO authenticated
  USING (EXISTS (
    SELECT 1 FROM public.year_end_engagements e
     WHERE e.id = year_end_review_events.engagement_id
       AND public.can_access_client(e.client_id::text)))
  WITH CHECK (EXISTS (
    SELECT 1 FROM public.year_end_engagements e
     WHERE e.id = year_end_review_events.engagement_id
       AND public.can_access_client(e.client_id::text)));

DROP POLICY IF EXISTS "year_end_review_events_role_insert" ON public.year_end_review_events;
CREATE POLICY "year_end_review_events_role_insert" ON public.year_end_review_events
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('year_end', 'write', 'Executive'));

DROP POLICY IF EXISTS "year_end_review_events_role_update" ON public.year_end_review_events;
CREATE POLICY "year_end_review_events_role_update" ON public.year_end_review_events
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('year_end', 'write', 'Executive'))
  WITH CHECK (public.my_permission('year_end', 'write', 'Executive'));

DROP POLICY IF EXISTS "year_end_review_events_role_delete" ON public.year_end_review_events;
CREATE POLICY "year_end_review_events_role_delete" ON public.year_end_review_events
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('year_end', 'write', 'Executive'));

-- ── the closing check: all 18 policies exist and every one is RESTRICTIVE ─────
DO $$
DECLARE
  n int;
BEGIN
  SELECT count(*) INTO n
    FROM pg_policies
   WHERE schemaname = 'public'
     AND permissive = 'RESTRICTIVE'
     AND policyname IN (
       'vendors_role_insert', 'vendors_role_update', 'vendors_role_delete',
       'knowledge_articles_role_insert', 'knowledge_articles_role_update', 'knowledge_articles_role_delete',
       'cross_client_matches_both_clients_in_reach', 'cross_client_matches_role_insert',
       'cross_client_matches_role_update', 'cross_client_matches_role_delete',
       'year_end_notes_engagement_in_reach', 'year_end_notes_role_insert',
       'year_end_notes_role_update', 'year_end_notes_role_delete',
       'year_end_review_events_engagement_in_reach', 'year_end_review_events_role_insert',
       'year_end_review_events_role_update', 'year_end_review_events_role_delete');
  IF n <> 18 THEN
    RAISE EXCEPTION 'migration 483: expected 18 restrictive policies, found %', n;
  END IF;
END $$;
