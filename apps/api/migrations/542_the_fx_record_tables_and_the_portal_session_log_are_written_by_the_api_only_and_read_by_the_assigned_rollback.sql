-- Rollback of migration 542: gives the signed-in role back the privileges migrations 149, 156 and 194 granted (SELECT, INSERT, UPDATE and
-- DELETE) on the two FX record tables and the portal session log, and drops the six policies, so the firm policy is the only rule
-- again. THIS RE-OPENS the forgery of an FX adjustment, a revaluation run and a portal session by any member of the firm over PostgREST.
-- The policies and the grants are changed inside one block, after a lock on the three tables taken without queueing (retried for up to 15 seconds).
SELECT set_config('lock_timeout', '15s', true);

DO $apply$
DECLARE
  v_try integer := 0;
BEGIN
  LOOP
    BEGIN
      LOCK TABLE public.fx_adjustments, public.fx_revaluations, public.client_portal_sessions IN ACCESS EXCLUSIVE MODE NOWAIT;
      EXIT;
    EXCEPTION WHEN lock_not_available THEN
      v_try := v_try + 1;
      IF v_try >= 30 THEN
        RAISE EXCEPTION 'rollback of migration 542: could not lock the three FX and portal tables in 15 seconds; run it again';
      END IF;
      PERFORM pg_sleep(0.5);
    END;
  END LOOP;

  DROP POLICY IF EXISTS "fx_adjustments_assignment_scope" ON public.fx_adjustments;
  DROP POLICY IF EXISTS "fx_adjustments_internal_partner_only" ON public.fx_adjustments;
  GRANT SELECT, INSERT, UPDATE, DELETE ON public.fx_adjustments TO authenticated;

  DROP POLICY IF EXISTS "fx_revaluations_assignment_scope" ON public.fx_revaluations;
  DROP POLICY IF EXISTS "fx_revaluations_internal_partner_only" ON public.fx_revaluations;
  GRANT SELECT, INSERT, UPDATE, DELETE ON public.fx_revaluations TO authenticated;

  DROP POLICY IF EXISTS "client_portal_sessions_assignment_scope" ON public.client_portal_sessions;
  DROP POLICY IF EXISTS "client_portal_sessions_internal_partner_only" ON public.client_portal_sessions;
  GRANT SELECT, INSERT, UPDATE, DELETE ON public.client_portal_sessions TO authenticated;
END $apply$;
