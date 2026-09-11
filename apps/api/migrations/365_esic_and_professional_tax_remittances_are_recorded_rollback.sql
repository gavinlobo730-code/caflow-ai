-- Rollback for 365.
--
-- Drops the table outright. That is safe ONLY while nothing has been recorded
-- in it — which is the case until the first CA types a challan number — because
-- a statutory remittance record is evidence that money was paid, and there is
-- nowhere else in this schema that holds it. `epfo_ecr_filings` does not cover
-- ESI or PT; that is why 365 exists.
--
-- So: if this has to come off a database with rows in it, export
-- public.statutory_remittances first. The rows cannot be reconstructed from the
-- payroll run — the challan number, the date it was paid and the amount that
-- actually left the bank (which may carry ESI Act s.39(5) interest the run
-- never computed) exist only here.

BEGIN;

DROP INDEX IF EXISTS public.idx_statutory_remittances_client_month;
DROP INDEX IF EXISTS public.uq_statutory_remittance_live;
DROP TABLE IF EXISTS public.statutory_remittances;

COMMIT;
