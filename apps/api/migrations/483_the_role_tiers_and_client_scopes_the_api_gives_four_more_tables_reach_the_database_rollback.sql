-- Rollback for migration 483: the 18 restrictive policies it added are dropped.
--
-- Rolling back RE-OPENS the holes 483 closes: an Executive can write vendors and knowledge articles over
-- PostgREST, every member of the firm can read and write every cross-client match (including those naming a
-- client they cannot see), and every member can read and write the notes and review trail of every client's
-- year-end engagement. Nothing else changes; no row is touched.

DROP POLICY IF EXISTS "vendors_role_insert" ON public.vendors;
DROP POLICY IF EXISTS "vendors_role_update" ON public.vendors;
DROP POLICY IF EXISTS "vendors_role_delete" ON public.vendors;

DROP POLICY IF EXISTS "knowledge_articles_role_insert" ON public.knowledge_articles;
DROP POLICY IF EXISTS "knowledge_articles_role_update" ON public.knowledge_articles;
DROP POLICY IF EXISTS "knowledge_articles_role_delete" ON public.knowledge_articles;

DROP POLICY IF EXISTS "cross_client_matches_both_clients_in_reach" ON public.cross_client_matches;
DROP POLICY IF EXISTS "cross_client_matches_role_insert" ON public.cross_client_matches;
DROP POLICY IF EXISTS "cross_client_matches_role_update" ON public.cross_client_matches;
DROP POLICY IF EXISTS "cross_client_matches_role_delete" ON public.cross_client_matches;

DROP POLICY IF EXISTS "year_end_notes_engagement_in_reach" ON public.year_end_notes;
DROP POLICY IF EXISTS "year_end_notes_role_insert" ON public.year_end_notes;
DROP POLICY IF EXISTS "year_end_notes_role_update" ON public.year_end_notes;
DROP POLICY IF EXISTS "year_end_notes_role_delete" ON public.year_end_notes;

DROP POLICY IF EXISTS "year_end_review_events_engagement_in_reach" ON public.year_end_review_events;
DROP POLICY IF EXISTS "year_end_review_events_role_insert" ON public.year_end_review_events;
DROP POLICY IF EXISTS "year_end_review_events_role_update" ON public.year_end_review_events;
DROP POLICY IF EXISTS "year_end_review_events_role_delete" ON public.year_end_review_events;
