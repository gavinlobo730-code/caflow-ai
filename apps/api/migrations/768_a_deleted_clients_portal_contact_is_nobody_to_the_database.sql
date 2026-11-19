-- Migration 768: a deleted client's portal contact is nobody's contact to the database either (ledger POST-A-503).
--
-- WHAT WAS WRONG
-- POST-A-447 stopped a deleted client's portal contact signing in to the API: the one door every client-portal route
-- resolves its principal through now drops a client whose `deleted_at` is set (services/portal_access_service.py). The
-- policies a signed-in contact meets through the database's own web interface were not touched. Ten policies on four
-- tables (client_documents, document_requests, portal_messages, shared_reports) read the contact's membership with an
-- inline subquery (client_portal_users with status = 'active', or the legacy clients.portal_user_id link) and never looked at
-- the client's `deleted_at`, and my_portal_client_ids() (migration 440 to 443), which every other portal branch of every
-- policy is built on, did the same. So a contact of a deleted client who still held a valid session could read the client's
-- portal messages and fee invoices and what hangs from them, and write portal messages and payment links, with the public key
-- and their own token, without going through the API. (Shared reports, documents and document requests were never reachable
-- that way by a contact: shared_reports by its restrictive assignment-scope policy, which has no portal branch, and the other
-- two since migration 551 took the signed-in role's privileges. Their ten policies are brought in line regardless, so the rule
-- is one rule and the next table that regains a portal branch cannot forget the deletion.)
--
-- WHAT THIS DOES, AND WHAT IT DELIBERATELY DOES NOT
-- 1. my_portal_client_ids() answers only for a client that is not deleted, in both of its branches (the contact table and
--    the legacy link). Same function (name, SETOF uuid, SECURITY DEFINER, search path, grants), derived from migration 443,
--    the last that declares it (440 to 442 declare the identical body); only the two `deleted_at IS NULL` tests are new.
--    Everything built on it (the portal branches of 440 to 443: the fee scope link, the customer, invoice and document
--    helpers, the payment links, the receipts, the notes) follows, with no policy of its own touched.
-- 2. A new function, my_portal_contact_client_ids(), is the contact-table branch alone, for the same reason the first is
--    SECURITY DEFINER: a subquery on `clients` inside a policy runs under the caller's own row security. The five
--    `portal_contact_*` policies ask it instead of reading client_portal_users themselves.
-- 3. The five `portal_client_*` policies (the legacy single-contact link) keep their inline subquery and gain the client's
--    `deleted_at IS NULL`. They are NOT pointed at the function: that would give a legacy-link contact a read the policy,
--    as written, does not give them today, and a migration that tightens must not also widen.
-- All ten are altered IN PLACE (ALTER POLICY keeps the name, the command, the role and its permissive kind).
-- tests/test_768_*_pg.py holds a rule over the whole catalogue: no policy in `public` reads the contact table directly, and
-- every one that names the legacy link also tests the client's deletion.
-- An ARCHIVED client is deliberately untouched, as at the API door: archiving is the practice putting a client aside, and
-- the portal keeps working for it (the decision recorded with POST-A-447).
--
-- No table is created, altered or written. Reversible: 768_..._rollback.sql restores 443's function body, drops the new
-- function and puts the ten policies' own expressions back. Applied with the API already deployed: nothing in the API
-- calls these.

BEGIN;

CREATE OR REPLACE FUNCTION public.my_portal_client_ids()
RETURNS SETOF uuid
LANGUAGE sql
STABLE SECURITY DEFINER
SET search_path TO 'public', 'pg_catalog'
AS $$
  SELECT cpu.client_id FROM public.client_portal_users cpu
    JOIN public.clients c ON c.id = cpu.client_id AND c.deleted_at IS NULL
   WHERE cpu.auth_user_id = auth.uid() AND cpu.status = 'active'
  UNION
  SELECT id FROM public.clients
   WHERE portal_user_id = auth.uid() AND deleted_at IS NULL
$$;

REVOKE EXECUTE ON FUNCTION public.my_portal_client_ids() FROM PUBLIC, anon;
GRANT  EXECUTE ON FUNCTION public.my_portal_client_ids() TO authenticated;

CREATE OR REPLACE FUNCTION public.my_portal_contact_client_ids()
RETURNS SETOF uuid
LANGUAGE sql
STABLE SECURITY DEFINER
SET search_path TO 'public', 'pg_catalog'
AS $$
  SELECT cpu.client_id FROM public.client_portal_users cpu
    JOIN public.clients c ON c.id = cpu.client_id AND c.deleted_at IS NULL
   WHERE cpu.auth_user_id = auth.uid() AND cpu.status = 'active'
$$;

COMMENT ON FUNCTION public.my_portal_contact_client_ids() IS
  'The clients the caller is an ACTIVE portal contact of through client_portal_users, not deleted. The contact-table branch of '
  'my_portal_client_ids(), for the five portal_contact_* policies. Migration 768.';

REVOKE EXECUTE ON FUNCTION public.my_portal_contact_client_ids() FROM PUBLIC, anon;
GRANT  EXECUTE ON FUNCTION public.my_portal_contact_client_ids() TO authenticated;

ALTER POLICY portal_client_sees_own_documents ON public.client_documents
  USING (client_id IN ( SELECT clients.id FROM public.clients WHERE ((clients.portal_user_id = ( SELECT auth.uid() AS uid)) AND (clients.deleted_at IS NULL))));

ALTER POLICY portal_client_fulfills_own_requests ON public.document_requests
  USING (client_id IN ( SELECT clients.id FROM public.clients WHERE ((clients.portal_user_id = ( SELECT auth.uid() AS uid)) AND (clients.deleted_at IS NULL))));

ALTER POLICY portal_client_sees_own_requests ON public.document_requests
  USING (client_id IN ( SELECT clients.id FROM public.clients WHERE ((clients.portal_user_id = ( SELECT auth.uid() AS uid)) AND (clients.deleted_at IS NULL))));

ALTER POLICY portal_client_messages ON public.portal_messages
  USING (client_id IN ( SELECT clients.id FROM public.clients WHERE ((clients.portal_user_id = ( SELECT auth.uid() AS uid)) AND (clients.deleted_at IS NULL))));

ALTER POLICY portal_client_sees_own_shared_reports ON public.shared_reports
  USING (client_id IN ( SELECT clients.id FROM public.clients WHERE ((clients.portal_user_id = ( SELECT auth.uid() AS uid)) AND (clients.deleted_at IS NULL))));

ALTER POLICY portal_contact_sees_own_documents ON public.client_documents
  USING (client_id IN (SELECT public.my_portal_contact_client_ids()));

ALTER POLICY portal_contact_fulfills_own_requests ON public.document_requests
  USING (client_id IN (SELECT public.my_portal_contact_client_ids()));

ALTER POLICY portal_contact_sees_own_requests ON public.document_requests
  USING (client_id IN (SELECT public.my_portal_contact_client_ids()));

ALTER POLICY portal_contact_messages ON public.portal_messages
  USING (client_id IN (SELECT public.my_portal_contact_client_ids()))
  WITH CHECK (client_id IN (SELECT public.my_portal_contact_client_ids()));

ALTER POLICY portal_contact_sees_own_shared_reports ON public.shared_reports
  USING (client_id IN (SELECT public.my_portal_contact_client_ids()));

COMMIT;
