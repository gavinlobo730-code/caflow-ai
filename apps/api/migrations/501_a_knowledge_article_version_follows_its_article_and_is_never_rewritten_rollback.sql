-- Rollback of migration 501: drops the two restrictive policies and gives `authenticated` UPDATE and DELETE back on the
-- knowledge-base version history, as migration 073 granted them. It does NOT restore the platform-default TRUNCATE,
-- REFERENCES and TRIGGER privileges, nor anything for `anon`: no migration ever granted them.
-- THIS RE-OPENS THE HOLES: any member of the firm can again read the text of an article they cannot see and rewrite or
-- delete a history row directly over the database.
DROP POLICY IF EXISTS "knowledge_article_versions_article_visible" ON public.knowledge_article_versions;
DROP POLICY IF EXISTS "knowledge_article_versions_role_insert" ON public.knowledge_article_versions;
GRANT UPDATE, DELETE ON public.knowledge_article_versions TO authenticated;
