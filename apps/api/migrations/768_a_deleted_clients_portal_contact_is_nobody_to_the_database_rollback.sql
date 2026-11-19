-- Rollback of migration 768: restores migration 443's my_portal_client_ids() (no test of the client's deletion), puts the
-- ten policies' own inline expressions back and drops the contact-table function the five portal_contact_* policies asked.

BEGIN;

ALTER POLICY portal_client_sees_own_documents ON public.client_documents
  USING (client_id IN ( SELECT clients.id FROM public.clients WHERE (clients.portal_user_id = ( SELECT auth.uid() AS uid))));

ALTER POLICY portal_client_fulfills_own_requests ON public.document_requests
  USING (client_id IN ( SELECT clients.id FROM public.clients WHERE (clients.portal_user_id = ( SELECT auth.uid() AS uid))));

ALTER POLICY portal_client_sees_own_requests ON public.document_requests
  USING (client_id IN ( SELECT clients.id FROM public.clients WHERE (clients.portal_user_id = ( SELECT auth.uid() AS uid))));

ALTER POLICY portal_client_messages ON public.portal_messages
  USING (client_id IN ( SELECT clients.id FROM public.clients WHERE (clients.portal_user_id = ( SELECT auth.uid() AS uid))));

ALTER POLICY portal_client_sees_own_shared_reports ON public.shared_reports
  USING (client_id IN ( SELECT clients.id FROM public.clients WHERE (clients.portal_user_id = ( SELECT auth.uid() AS uid))));

ALTER POLICY portal_contact_sees_own_documents ON public.client_documents
  USING (client_id IN ( SELECT client_portal_users.client_id FROM public.client_portal_users WHERE ((client_portal_users.auth_user_id = ( SELECT auth.uid() AS uid)) AND (client_portal_users.status = 'active'::text))));

ALTER POLICY portal_contact_fulfills_own_requests ON public.document_requests
  USING (client_id IN ( SELECT client_portal_users.client_id FROM public.client_portal_users WHERE ((client_portal_users.auth_user_id = ( SELECT auth.uid() AS uid)) AND (client_portal_users.status = 'active'::text))));

ALTER POLICY portal_contact_sees_own_requests ON public.document_requests
  USING (client_id IN ( SELECT client_portal_users.client_id FROM public.client_portal_users WHERE ((client_portal_users.auth_user_id = ( SELECT auth.uid() AS uid)) AND (client_portal_users.status = 'active'::text))));

ALTER POLICY portal_contact_messages ON public.portal_messages
  USING (client_id IN ( SELECT client_portal_users.client_id FROM public.client_portal_users WHERE ((client_portal_users.auth_user_id = ( SELECT auth.uid() AS uid)) AND (client_portal_users.status = 'active'::text))))
  WITH CHECK (client_id IN ( SELECT client_portal_users.client_id FROM public.client_portal_users WHERE ((client_portal_users.auth_user_id = ( SELECT auth.uid() AS uid)) AND (client_portal_users.status = 'active'::text))));

ALTER POLICY portal_contact_sees_own_shared_reports ON public.shared_reports
  USING (client_id IN ( SELECT client_portal_users.client_id FROM public.client_portal_users WHERE ((client_portal_users.auth_user_id = ( SELECT auth.uid() AS uid)) AND (client_portal_users.status = 'active'::text))));

DROP FUNCTION IF EXISTS public.my_portal_contact_client_ids();

CREATE OR REPLACE FUNCTION public.my_portal_client_ids()
RETURNS SETOF uuid
LANGUAGE sql
STABLE SECURITY DEFINER
SET search_path TO 'public', 'pg_catalog'
AS $$
  SELECT client_id FROM public.client_portal_users
   WHERE auth_user_id = auth.uid() AND status = 'active'
  UNION
  SELECT id FROM public.clients
   WHERE portal_user_id = auth.uid()
$$;

REVOKE EXECUTE ON FUNCTION public.my_portal_client_ids() FROM PUBLIC, anon;
GRANT  EXECUTE ON FUNCTION public.my_portal_client_ids() TO authenticated;

COMMIT;
