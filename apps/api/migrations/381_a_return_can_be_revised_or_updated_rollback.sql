-- Rollback for 381_a_return_can_be_revised_or_updated.sql.
--
-- ⚠️ NOT SYMMETRIC, AND IT CANNOT BE. Restoring migration 319's
-- `UNIQUE (firm_id, client_id, financial_year, itr_form)` fails outright if any
-- client has a revised or updated return recorded — which is the whole point of
-- 381. So the restore is attempted and, where it cannot be made, SAYS SO with
-- the count rather than leaving the table looking rolled back when it is not.
--
-- Drop the columns first: doing so removes the rows' only reason to collide.

DROP INDEX IF EXISTS public.idx_itr_filings_original;
DROP INDEX IF EXISTS public.uq_itr_filings_one_original;

ALTER TABLE public.itr_filings
  DROP CONSTRAINT IF EXISTS itr_filings_return_type_check,
  DROP CONSTRAINT IF EXISTS itr_filings_original_is_not_self_check;

ALTER TABLE public.itr_filings
  DROP COLUMN IF EXISTS original_filing_date,
  DROP COLUMN IF EXISTS original_acknowledgement_number,
  DROP COLUMN IF EXISTS original_filing_id,
  DROP COLUMN IF EXISTS return_type;

DO $$
DECLARE
  dupes integer;
BEGIN
  IF EXISTS (SELECT 1 FROM pg_constraint
             WHERE conrelid = 'public.itr_filings'::regclass
               AND conname = 'itr_filings_firm_id_client_id_financial_year_itr_form_key') THEN
    RETURN;
  END IF;
  SELECT count(*) INTO dupes FROM (
    SELECT 1 FROM public.itr_filings
     GROUP BY firm_id, client_id, financial_year, itr_form
    HAVING count(*) > 1
  ) d;
  IF dupes > 0 THEN
    RAISE WARNING
      'itr_filings: % (client, year, form) groups hold more than one return, '
      'so migration 319''s UNIQUE cannot be restored. The rows are intact and '
      'the columns are dropped; decide which return to keep before restoring '
      'the constraint by hand.', dupes;
    RETURN;
  END IF;
  ALTER TABLE public.itr_filings
    ADD CONSTRAINT itr_filings_firm_id_client_id_financial_year_itr_form_key
    UNIQUE (firm_id, client_id, financial_year, itr_form);
END $$;
