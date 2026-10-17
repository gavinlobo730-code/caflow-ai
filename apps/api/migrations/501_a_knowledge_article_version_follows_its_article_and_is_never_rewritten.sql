-- Migration 501: a knowledge-base version is visible only to someone who can see its article, is written only by the
-- tier that may write the article, and is never rewritten or deleted by a signed-in session
-- (ledger POST-A-009, from the Batch 6 design review).
--
-- WHAT WAS WRONG
--   `knowledge_article_versions` is where the CONTENT of a knowledge-base article lives (`knowledge_articles` holds only the
--   title, the scope and the pointer to the current version). Migration 073 gave it ONE policy, `firm_id = get_my_firm_id()`,
--   and granted `authenticated` SELECT, INSERT, UPDATE and DELETE. Migrations 079 and 483 put the rules that matter on the
--   ARTICLE table only: a client-scoped article is visible to a Manager and a Partner and to staff assigned to its client
--   (079), an article of the firm's own practice-client is Partner-only (079), and writing an article takes the
--   `knowledge:write` tier, Manager and above (483). None of that reached the version rows, so a signed-in session with its
--   own JWT (which is how the API itself reads them: `services/knowledge_service` is on `db_provider.request_db`) could
--   read the text of an article it cannot see, an unassigned Executive or a Reviewer could read client-scoped and
--   internal-practice article text straight over PostgREST, and ANY member of the firm could UPDATE or DELETE a history row,
--   so the "immutable history, restore writes a new version" promise lived in the API only.
--
-- WHAT THIS DOES
--   1. PRIVILEGE (the first lock). `authenticated` keeps SELECT and INSERT and loses everything else: the API only ever
--      INSERTs a version (create, edit, restore) and reads them, and nothing in `apps/web` names the table. `anon` and PUBLIC
--      lose everything. `service_role` is not touched. Foreign-key cascades from the article (and from the client and the
--      firm above it) are not a privilege of the caller and still remove the versions with their article.
--   2. VISIBILITY (the second lock). A RESTRICTIVE policy, for every command, requires that the parent article is visible to
--      the caller: the subquery on `knowledge_articles` runs under that table's own policies, so the assignment scope (079),
--      the internal-practice Partner-only rule (079) and the firm rule all apply to the versions without being copied, and a
--      later change to who may see an article moves the versions with it.
--   3. WRITE TIER. A RESTRICTIVE INSERT policy requires `my_permission('knowledge', 'write', 'Manager')`, the same call the
--      article policies of migration 483 make, so a per-person grant or denial in the access grid is honoured in both places.
--   A closing check fails the migration, and so the deploy, if `authenticated` still holds an effective privilege other than
--   SELECT and INSERT, `anon` holds any, the API lost one, or either policy is missing.
--
-- WHAT IT LEAVES ALONE, AND SAYS SO
--   * No row, column, function or article policy changes. No backfill. (Production held no article and no version on
--     17-10-2026, so no existing row changes who can see it.)
--   * SELECT is still every assigned member's, as for the article itself; this migration does not decide the open question
--     of whether a Manager should be firm-wide in the knowledge base (079 says so; this follows whatever it becomes).
--   * It is not in the access matrix (`tests/test_rls_role_by_table_matrix_pg.py`): that matrix is the tables the BROWSER
--     reaches, and the browser does not reach this one. `tests/test_501_..._pg.py` is its proof.
--   * `client_instructions` (the other Batch 6 table) is not touched.
--
-- Idempotent. Reversible: 501_..._rollback.sql grants UPDATE and DELETE back and drops the two policies, which RE-OPENS
-- the holes.

REVOKE ALL ON public.knowledge_article_versions FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT ON public.knowledge_article_versions TO authenticated;

DROP POLICY IF EXISTS "knowledge_article_versions_article_visible" ON public.knowledge_article_versions;
CREATE POLICY "knowledge_article_versions_article_visible" ON public.knowledge_article_versions
  AS RESTRICTIVE FOR ALL TO authenticated
  USING (EXISTS (SELECT 1 FROM public.knowledge_articles a WHERE a.id = knowledge_article_versions.article_id))
  WITH CHECK (EXISTS (SELECT 1 FROM public.knowledge_articles a WHERE a.id = knowledge_article_versions.article_id));

DROP POLICY IF EXISTS "knowledge_article_versions_role_insert" ON public.knowledge_article_versions;
CREATE POLICY "knowledge_article_versions_role_insert" ON public.knowledge_article_versions
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('knowledge', 'write', 'Manager'));

DO $$
DECLARE
  r text;
  verb text;
BEGIN
  -- The EFFECTIVE privilege (has_table_privilege and has_any_column_privilege see PUBLIC, membership and column grants).
  FOREACH verb IN ARRAY ARRAY['UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER'] LOOP
    IF has_table_privilege('authenticated', 'public.knowledge_article_versions', verb) THEN
      RAISE EXCEPTION 'migration 501: authenticated still holds % on knowledge_article_versions', verb;
    END IF;
  END LOOP;
  IF has_any_column_privilege('authenticated', 'public.knowledge_article_versions', 'UPDATE') THEN
    RAISE EXCEPTION 'migration 501: authenticated still holds a column-level UPDATE on knowledge_article_versions';
  END IF;
  FOREACH verb IN ARRAY ARRAY['SELECT', 'INSERT'] LOOP
    IF NOT has_table_privilege('authenticated', 'public.knowledge_article_versions', verb) THEN
      RAISE EXCEPTION 'migration 501: authenticated lost % on knowledge_article_versions, which the API needs', verb;
    END IF;
  END LOOP;
  FOREACH verb IN ARRAY ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE'] LOOP
    IF has_table_privilege('anon', 'public.knowledge_article_versions', verb) THEN
      RAISE EXCEPTION 'migration 501: anon still holds % on knowledge_article_versions', verb;
    END IF;
  END LOOP;
  FOREACH r IN ARRAY ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE'] LOOP
    IF NOT has_table_privilege('service_role', 'public.knowledge_article_versions', r) THEN
      RAISE EXCEPTION 'migration 501: the API (service_role) lost % on knowledge_article_versions', r;
    END IF;
  END LOOP;
  IF (SELECT count(*) FROM pg_policies
       WHERE schemaname = 'public' AND tablename = 'knowledge_article_versions' AND permissive = 'RESTRICTIVE'
         AND policyname IN ('knowledge_article_versions_article_visible', 'knowledge_article_versions_role_insert')) <> 2 THEN
    RAISE EXCEPTION 'migration 501: the two restrictive policies on knowledge_article_versions are not both in place';
  END IF;
  IF NOT (SELECT relrowsecurity FROM pg_class WHERE oid = 'public.knowledge_article_versions'::regclass) THEN
    RAISE EXCEPTION 'migration 501: row security is off on knowledge_article_versions';
  END IF;
END $$;
