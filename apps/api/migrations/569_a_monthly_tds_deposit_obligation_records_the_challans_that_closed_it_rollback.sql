-- Rollback of migration 569: forget which challans closed each monthly TDS deposit obligation. The obligations stay as they were
-- (filed, with their date and serial); only the record of the challans goes, so a retraction names every filed month of the quarter
-- again and the closer can close a reopened month again on the same challans.

BEGIN;

ALTER TABLE public.compliance_records DROP CONSTRAINT IF EXISTS compliance_records_closing_tds_challan_ids_is_array;
ALTER TABLE public.compliance_records DROP COLUMN IF EXISTS closing_tds_challan_ids;

COMMIT;
