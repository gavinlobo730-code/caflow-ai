-- Rollback for 345. Drops the role rules and leaves the firm-scoped policies
-- from 014/037 in place — which is the state TDS-11 describes, so this should
-- only ever be run to unblock a migration failure, never as a fix.
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['tds_deductions','tds_returns','tds_challans','tds_certificates'] LOOP
    IF to_regclass('public.' || quote_ident(t)) IS NULL THEN CONTINUE; END IF;
    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_role_insert', t);
    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_role_update', t);
    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_role_delete', t);
  END LOOP;
END $$;
