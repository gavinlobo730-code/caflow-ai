-- Rollback of migration 543: drops the cached-stock trigger and the stock-history delete trigger with their functions, and gives activity_logs, ai_evidence and ai_signals back the
-- four privileges the signed-in role held on them (anon's TRUNCATE, REFERENCES and TRIGGER, which production's platform defaults had
-- given, stay revoked, as in the rollback of migration 538). THIS RE-OPENS: a member assigned to a client can again set an item's cached stock figures over PostgREST,
-- and the signed-in role again holds every write verb on three tables nobody uses.
SELECT set_config('lock_timeout', '15s', true);

DO $apply$
DECLARE
  v_try integer := 0;
BEGIN
  LOOP
    BEGIN
      LOCK TABLE public.service_catalogue IN ACCESS EXCLUSIVE MODE NOWAIT;
      EXIT;
    EXCEPTION WHEN lock_not_available THEN
      v_try := v_try + 1;
      IF v_try >= 30 THEN
        RAISE EXCEPTION 'rollback of migration 543: could not lock public.service_catalogue in 15 seconds; run it again';
      END IF;
      PERFORM pg_sleep(0.5);
    END;
  END LOOP;

  DROP TRIGGER IF EXISTS an_items_cached_stock_is_not_edited_from_a_signed_in_session ON public.service_catalogue;
  DROP TRIGGER IF EXISTS an_item_with_stock_history_is_not_deleted_from_a_signed_in_session ON public.service_catalogue;
END $apply$;

DROP FUNCTION IF EXISTS public.refuse_a_signed_in_edit_of_the_items_cached_stock();
DROP FUNCTION IF EXISTS public.refuse_a_signed_in_delete_of_an_item_with_stock_history();

DO $$
DECLARE
  t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['activity_logs', 'ai_evidence', 'ai_signals'] LOOP
    IF to_regclass('public.' || t) IS NOT NULL THEN
      EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON public.%I TO authenticated', t);
    END IF;
  END LOOP;
END $$;
