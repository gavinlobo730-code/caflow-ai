-- PracticeSync AI — Migration 079: Knowledge Base assignment-gated RLS (Batch 6)
-- Amendment v1.1 (Phase 10B). Additive, idempotent. NO new tables (the KB tables
-- were created in 073). Refines the firm-scoped RLS to assignment-gating:
--   * Partner/Manager  -> firm-wide.
--   * Executive/Reviewer -> only their assigned clients (user_client_assignments).
--   * Internal practice client KB -> Partner-only (G1).
-- Backend uses the service-role key (RLS bypassed) so the API/repository layer is
-- the PRIMARY control; these RESTRICTIVE policies are defense-in-depth.

-- Resolve the caller's internal users.id (for assignment checks).
CREATE OR REPLACE FUNCTION get_my_user_id()
RETURNS uuid AS $$
  SELECT id FROM users WHERE auth_user_id = auth.uid() LIMIT 1;
$$ LANGUAGE sql SECURITY DEFINER STABLE;

-- ── knowledge_articles: assignment-gate client-scoped rows ───────────────────
DROP POLICY IF EXISTS "knowledge_articles_assignment" ON knowledge_articles;
CREATE POLICY "knowledge_articles_assignment" ON knowledge_articles
  AS RESTRICTIVE FOR ALL
  USING (
    get_my_role() IN ('Partner','Manager')
    OR client_id IS NULL                                   -- firm/department scope: all staff
    OR EXISTS (SELECT 1 FROM user_client_assignments a
               WHERE a.user_id = get_my_user_id() AND a.client_id = knowledge_articles.client_id)
  )
  WITH CHECK (
    get_my_role() IN ('Partner','Manager')
    OR client_id IS NULL
    OR EXISTS (SELECT 1 FROM user_client_assignments a
               WHERE a.user_id = get_my_user_id() AND a.client_id = knowledge_articles.client_id)
  );

-- ── knowledge_articles: internal practice client -> Partner-only (G1) ────────
-- client_id::text on both sides for the same type-safety reason documented in
-- migration 074. knowledge_articles.client_id is uuid (cast is a no-op here);
-- applied for cross-migration consistency.
DROP POLICY IF EXISTS "knowledge_articles_internal_partner_only" ON knowledge_articles;
CREATE POLICY "knowledge_articles_internal_partner_only" ON knowledge_articles
  AS RESTRICTIVE FOR ALL
  USING (get_my_role() = 'Partner' OR client_id::text IS DISTINCT FROM my_internal_client_id()::text)
  WITH CHECK (get_my_role() = 'Partner' OR client_id::text IS DISTINCT FROM my_internal_client_id()::text);

-- ── client_instructions: assignment-gate (always client-scoped) ──────────────
-- (internal-client partner-only already added for client_instructions in 074)
DROP POLICY IF EXISTS "client_instructions_assignment" ON client_instructions;
CREATE POLICY "client_instructions_assignment" ON client_instructions
  AS RESTRICTIVE FOR ALL
  USING (
    get_my_role() IN ('Partner','Manager')
    OR EXISTS (SELECT 1 FROM user_client_assignments a
               WHERE a.user_id = get_my_user_id() AND a.client_id = client_instructions.client_id)
  )
  WITH CHECK (
    get_my_role() IN ('Partner','Manager')
    OR EXISTS (SELECT 1 FROM user_client_assignments a
               WHERE a.user_id = get_my_user_id() AND a.client_id = client_instructions.client_id)
  );
