-- 163 — Harden client_portal_users RLS/grants (roadmap R3.0, surfaced by the
-- R2.5 regression review).
--
-- Migration 109's client_portal_users_own_firm policy is FOR ALL, scoped only
-- by firm_id: USING/WITH CHECK (firm_id = get_my_firm_id()). Combined with the
-- table-level GRANT INSERT/UPDATE/DELETE TO authenticated, ANY authenticated
-- firm staff member (any role, not just Partner) can directly INSERT/UPDATE/
-- DELETE a client_portal_users row for their own firm from the browser --
-- bypassing services/portal_access_service.py's invite_contact() entirely
-- (its token/TTL/audit trail, single-use accept flow, etc.). Not a
-- cross-tenant confidentiality leak (staff already have equivalent CA-side
-- access to the same client's data) but a real audit-integrity gap: a staff
-- member could self-activate an arbitrary contact, or read another contact's
-- plaintext invite_token (a bearer secret) via the same broad SELECT grant.
--
-- Every legitimate mutation already goes exclusively through
-- portal_access_service.py's service-role client (get_service_supabase(),
-- never the user-JWT client), which bypasses RLS/grants entirely regardless
-- of this fix -- confirmed by inspection: invite_contact/resend_invite/
-- deactivate_contact/accept_portal_invite (the _bind() helper) cover every
-- column this table has other than id/created_at. A repo-wide check also
-- confirms apps/web has zero direct `.from("client_portal_users")` calls --
-- every frontend interaction goes through the backend REST API
-- (api.portal.*). So, unlike the users-table fix in migration 153, there is
-- no legitimate frontend self-service feature to preserve here (no column-
-- level UPDATE grant needed) -- making this table SELECT-only for
-- `authenticated` is a clean win with no feature to carve out.
REVOKE INSERT, UPDATE, DELETE ON public.client_portal_users FROM authenticated;

DROP POLICY IF EXISTS "client_portal_users_own_firm" ON public.client_portal_users;

-- A firm staff member may still read every portal-contact row for their own
-- firm (needed by the CA-side "manage contacts" UI) -- but never write one
-- directly. client_portal_users_self (SELECT-only, auth_user_id = auth.uid())
-- is untouched -- already correct, and relied on by sibling OR-combined
-- policies on client_documents/document_requests/portal_messages/shared_reports
-- (all SELECT-only subqueries against this table, never mutations).
CREATE POLICY "client_portal_users_own_firm" ON public.client_portal_users
  FOR SELECT TO authenticated
  USING (firm_id = get_my_firm_id());
