-- Rollback for 084_assignment_scoped_rls.sql
-- Drops every *_assignment_scope policy added by the dynamic loop, the clients
-- and notifications policies, and the helper. Firm isolation (*_own_firm) and G1
-- (*_internal_partner_only) policies are left intact.

DO $$
DECLARE p record;
BEGIN
  FOR p IN
    SELECT schemaname, tablename, policyname
    FROM pg_policies
    WHERE schemaname = 'public' AND policyname LIKE '%\_assignment\_scope'
  LOOP
    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', p.policyname, p.tablename);
  END LOOP;
END $$;

DROP POLICY IF EXISTS "clients_assignment_scope" ON public.clients;
DROP POLICY IF EXISTS "notifications_recipient_scope" ON public.notifications;
DROP FUNCTION IF EXISTS public.can_access_client(text);
