-- PracticeSync AI — Migration 079 ROLLBACK (Knowledge Base assignment-gated RLS)
-- Drops only the objects added by 079, reverting to firm-scoped RLS (073).
-- Idempotent.

DROP POLICY IF EXISTS "knowledge_articles_assignment" ON knowledge_articles;
DROP POLICY IF EXISTS "knowledge_articles_internal_partner_only" ON knowledge_articles;
DROP POLICY IF EXISTS "client_instructions_assignment" ON client_instructions;
DROP FUNCTION IF EXISTS get_my_user_id();
