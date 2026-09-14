-- Rollback for 397.
--
-- REFUSES while any project has been CAPITALISED. That project's accumulated
-- cost is now a fixed_assets row and a posted journal (migration 251 makes it
-- immutable), and these tables are the only record of what the asset was built
-- from and over what period — which is exactly what the Schedule III ageing
-- and completion schedules are derived from for the years it was in progress.
--
-- The 'Capital Work-in-Progress' account is NOT removed: a firm may have
-- posted to it, and a chart_of_accounts row with journal lines against it
-- cannot go.
BEGIN;

DO $$
DECLARE n INTEGER;
BEGIN
  SELECT count(*) INTO n FROM public.capital_work_in_progress
   WHERE status = 'capitalised';
  IF n > 0 THEN
    RAISE EXCEPTION
      'Refusing to roll back 397: % projects have been capitalised. Their cost '
      'is in a fixed_assets row and in a posted journal this rollback cannot '
      'undo, and these tables are the only record of what those assets were '
      'built from.', n;
  END IF;
END $$;

DROP TABLE IF EXISTS public.cwip_additions;
DROP TABLE IF EXISTS public.capital_work_in_progress;

COMMIT;
