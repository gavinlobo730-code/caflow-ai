-- Rollback for 389.
--
-- REFUSES while any Bill of Entry exists. Each one carries a credit claimed on
-- a filed or fileable GSTR-3B Table 4(A)(1) and, where posted, a journal entry
-- that cannot be deleted (migration 251). Dropping the table would leave the
-- return's largest ITC line with nothing behind it.
--
-- The 'Customs Duty' account is NOT removed either: a firm may have posted to
-- it, and a chart_of_accounts row with journal lines against it cannot go.

BEGIN;

DO $$
DECLARE n INTEGER;
BEGIN
  IF to_regclass('public.bills_of_entry') IS NOT NULL THEN
    EXECUTE 'SELECT count(*) FROM public.bills_of_entry' INTO n;
    IF n > 0 THEN
      RAISE EXCEPTION
        'Refusing to roll back 389: % bill(s) of entry exist. Each carries '
        'import IGST declared on GSTR-3B Table 4(A)(1), and a posted one has a '
        'journal entry behind it. Soft-delete them through the API first.', n;
    END IF;
  END IF;
END $$;

DROP TABLE IF EXISTS public.bills_of_entry;

COMMIT;
