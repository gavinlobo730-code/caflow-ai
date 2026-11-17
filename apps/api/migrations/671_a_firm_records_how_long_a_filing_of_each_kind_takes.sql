-- 671 — a firm records how long one filing of each kind takes (POST-A-212).
--
-- THE GAP
--
-- Team Workload is the one capacity model (`services/capacity_risk_service`). A task carries its own whole-minute estimate (migration
-- 452); a compliance obligation that is worked as a task is counted once, as that task. An obligation that is NOT worked as a task
-- (most GSTR-1s, GSTR-3Bs and TDS statements) carried no estimate and nothing could hold one, so the forecast saw the work as dated
-- and weightless: every such filing was counted in "items without an estimate" and added no hours.
--
-- WHAT THIS ADDS
--
-- One table, `compliance_effort_estimates`: per firm and per obligation type (the calendar's own `compliance_type`, the word the
-- obligation already carries), how many whole minutes one filing of that kind takes in THIS practice. The figure is the firm's own
-- statement, never the product's: there is no default, no seed and no backfill, a type with no row has no estimate and is still
-- counted as an item without one, and nothing is averaged over it. Written by the API alone (`PUT /api/workload/obligation-estimates`,
-- `workload.write`): a signed-in session is given read only, so a row security policy is not the second lock on a write.
--
-- Whole minutes MORE than zero, like a task's. No statutory figure is held: how long a filing takes is practice effort and not a date,
-- a rate or a threshold.
--
-- Additive; no row is written here.

BEGIN;

SELECT set_config('lock_timeout', '15s', true);

CREATE TABLE IF NOT EXISTS public.compliance_effort_estimates (
  id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id           UUID        NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  compliance_type   TEXT        NOT NULL,
  estimated_minutes INTEGER     NOT NULL,
  updated_by        UUID        REFERENCES public.users(id) ON DELETE SET NULL,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT compliance_effort_estimates_one_per_type UNIQUE (firm_id, compliance_type),
  CONSTRAINT compliance_effort_estimates_minutes_are_positive CHECK (estimated_minutes > 0),
  CONSTRAINT compliance_effort_estimates_type_is_a_word CHECK (char_length(btrim(compliance_type)) BETWEEN 1 AND 60)
);

COMMENT ON TABLE public.compliance_effort_estimates IS
  'POST-A-212, migration 671. How long one filing of an obligation type takes in this practice, in whole minutes (> 0), stated by the '
  'firm and never defaulted. Read by services/capacity_risk_service for obligations not worked as a task. Written by the API only.';

ALTER TABLE public.compliance_effort_estimates ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "compliance_effort_estimates_firm_isolation" ON public.compliance_effort_estimates;
CREATE POLICY "compliance_effort_estimates_firm_isolation" ON public.compliance_effort_estimates
  FOR ALL TO authenticated
  USING (firm_id = (SELECT public.get_my_firm_id()))
  WITH CHECK (firm_id = (SELECT public.get_my_firm_id()));

REVOKE ALL ON public.compliance_effort_estimates FROM PUBLIC, anon, authenticated;
GRANT SELECT ON public.compliance_effort_estimates TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.compliance_effort_estimates TO service_role;

DO $$
BEGIN
    PERFORM public.guard_member_firm('public.compliance_effort_estimates');
END $$;

DO $$
DECLARE
    r text;
    verb text;
BEGIN
    FOREACH r IN ARRAY ARRAY['authenticated', 'anon'] LOOP
        FOREACH verb IN ARRAY ARRAY['INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER'] LOOP
            IF has_table_privilege(r, 'public.compliance_effort_estimates', verb) THEN
                RAISE EXCEPTION 'migration 671: % still holds % on compliance_effort_estimates', r, verb;
            END IF;
        END LOOP;
    END LOOP;
END $$;

COMMIT;
