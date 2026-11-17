-- Rollback of migration 715. Drops the record of past bulk GSTR-2B drops; the reconciliations themselves (gstr2a_records, gstr2b_uploads)
-- are untouched. The API keeps working: a drop is reconciled as before and its answer says it was not recorded.
BEGIN;
DROP TABLE IF EXISTS public.gstr2b_bulk_drop_files;
DROP TABLE IF EXISTS public.gstr2b_bulk_drops;
COMMIT;
