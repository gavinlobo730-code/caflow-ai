-- Rollback for migration 484: the portal-contact policy is dropped and production's firm-wide audit-log read
-- policy is put back exactly as it stood on 14-10-2026 (permissive SELECT TO authenticated, firm only).
--
-- Rolling back RE-OPENS both holes: every member of the firm reads the whole firm's audit log, and every member
-- reads every client's portal contacts and invite tokens.

DROP POLICY IF EXISTS "client_portal_users_staff_in_reach" ON public.client_portal_users;

DROP POLICY IF EXISTS "audit_log_own_firm" ON public.audit_log;
CREATE POLICY "audit_log_own_firm" ON public.audit_log
  FOR SELECT TO authenticated
  USING (firm_id = public.get_my_firm_id());
