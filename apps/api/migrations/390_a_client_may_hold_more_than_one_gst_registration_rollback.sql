-- Rollback for 390.
--
-- REFUSES while any additional registration exists, and refuses again if any
-- client holds two returns for one period — restoring `UNIQUE (client_id,
-- period)` would fail on those rows, and the failure would come after the table
-- had already gone.

BEGIN;

DO $$
DECLARE n INTEGER;
BEGIN
  IF to_regclass('public.client_gst_registrations') IS NOT NULL THEN
    EXECUTE 'SELECT count(*) FROM public.client_gst_registrations
              WHERE deleted_at IS NULL' INTO n;
    IF n > 0 THEN
      RAISE EXCEPTION
        'Refusing to roll back 390: % additional GST registration(s) exist. '
        'Their returns would lose the only column telling them apart.', n;
    END IF;
  END IF;

  SELECT count(*) INTO n FROM (
    SELECT client_id, period FROM public.gstr1_returns
     GROUP BY client_id, period HAVING count(*) > 1
    UNION ALL
    SELECT client_id, period FROM public.gstr3b_returns
     GROUP BY client_id, period HAVING count(*) > 1
  ) AS dupes;
  IF n > 0 THEN
    RAISE EXCEPTION
      'Refusing to roll back 390: % client/period pair(s) hold more than one '
      'return, which the old UNIQUE (client_id, period) cannot express.', n;
  END IF;
END $$;

DROP INDEX IF EXISTS public.uq_gstr1_return_per_registration;
DROP INDEX IF EXISTS public.uq_gstr3b_return_per_registration;

ALTER TABLE public.gstr1_returns
  ADD CONSTRAINT gstr1_returns_client_id_period_key UNIQUE (client_id, period);
ALTER TABLE public.gstr3b_returns
  ADD CONSTRAINT gstr3b_returns_client_id_period_key UNIQUE (client_id, period);

DROP TABLE IF EXISTS public.client_gst_registrations;

COMMIT;
