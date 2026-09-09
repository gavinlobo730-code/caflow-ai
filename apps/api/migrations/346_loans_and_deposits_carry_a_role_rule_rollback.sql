-- Rollback for 346. Leaves the firm and assignment policies in place; only the
-- role rules go, which is the state where a Reviewer can write a loan again.
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['loans','fixed_deposits'] LOOP
    IF to_regclass('public.' || quote_ident(t)) IS NULL THEN CONTINUE; END IF;
    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_role_insert', t);
    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_role_update', t);
    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_role_delete', t);
  END LOOP;
END $$;
