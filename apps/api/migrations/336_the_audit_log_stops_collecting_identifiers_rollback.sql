-- Rollback for migration 336: restore migration 111's audit_capture verbatim,
-- so snapshots carry every column again, and drop the redactor.
--
-- Note what a rollback CANNOT do: rows written while 336 was in force keep
-- their "[redacted]" markers. audit_log blocks UPDATE and DELETE, so the
-- original values are not recoverable — they were never written. That is the
-- point of the migration, and it is the reason to be deliberate about applying
-- it rather than the reason not to.
BEGIN;

CREATE OR REPLACE FUNCTION public.audit_capture()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_actor  uuid := auth.uid();
  v_email  text;
  v_firm   uuid;
  v_entity text;
  v_etype  text;
  v_action text;
  v_old    jsonb;
  v_new    jsonb;
BEGIN
  IF v_actor IS NULL THEN
    RETURN NULL;
  END IF;

  IF (TG_OP = 'INSERT') THEN
    v_action := 'create'; v_new := to_jsonb(NEW);
  ELSIF (TG_OP = 'UPDATE') THEN
    v_action := 'update'; v_new := to_jsonb(NEW); v_old := to_jsonb(OLD);
  ELSE
    v_action := 'delete'; v_old := to_jsonb(OLD);
  END IF;

  v_firm := nullif(coalesce(v_new->>'firm_id', v_old->>'firm_id'), '')::uuid;
  IF v_firm IS NULL THEN
    RETURN NULL;
  END IF;

  v_entity := coalesce(v_new->>'id', v_old->>'id');

  v_etype := CASE TG_TABLE_NAME
    WHEN 'chart_of_accounts'   THEN 'account'
    WHEN 'accounts'            THEN 'account'
    WHEN 'compliance_calendar' THEN 'compliance'
    ELSE CASE
      WHEN TG_TABLE_NAME LIKE '%ies' THEN left(TG_TABLE_NAME, length(TG_TABLE_NAME) - 3) || 'y'
      WHEN TG_TABLE_NAME LIKE '%s'   THEN left(TG_TABLE_NAME, length(TG_TABLE_NAME) - 1)
      ELSE TG_TABLE_NAME
    END
  END;

  SELECT u.email INTO v_email FROM public.users u WHERE u.auth_user_id = v_actor LIMIT 1;

  INSERT INTO public.audit_log
    (firm_id, actor_id, actor_email, entity_type, entity_id, action, old_data, new_data, metadata)
  VALUES
    (v_firm, v_actor, v_email, v_etype, v_entity, v_action, v_old, v_new,
     jsonb_build_object('source', 'db_trigger', 'table', TG_TABLE_NAME));

  RETURN NULL;
EXCEPTION WHEN OTHERS THEN
  RETURN NULL;
END;
$$;

DROP FUNCTION IF EXISTS public.audit_redact(jsonb);

COMMIT;
