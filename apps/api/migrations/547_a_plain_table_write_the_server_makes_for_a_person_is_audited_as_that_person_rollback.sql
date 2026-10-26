-- Rollback of migration 547: public.carried_audit_actor() goes back to migration 545's definition (the setting alone). A write the
-- server makes for a person is audited by nobody again, as before 547; nothing reads the request header any more.
-- The probe function is dropped too. ORDER: roll back the code that sends the header (and any revoke migration that relies on it) FIRST. Without them a plain table write
-- the API makes with its privileged client would leave the edit log empty.

CREATE OR REPLACE FUNCTION public.carried_audit_actor()
RETURNS uuid
LANGUAGE plpgsql
STABLE
SECURITY INVOKER
SET search_path = pg_catalog
AS $fn$
DECLARE
    v_setting text := nullif(current_setting('app.audit_actor', true), '');
BEGIN
    IF v_setting IS NULL THEN
        RETURN NULL;
    END IF;
    BEGIN
        RETURN v_setting::uuid;
    EXCEPTION WHEN others THEN
        RETURN NULL;
    END;
END;
$fn$;

REVOKE ALL ON FUNCTION public.carried_audit_actor() FROM PUBLIC, anon, authenticated;

DROP FUNCTION IF EXISTS public.audit_actor_probe();
