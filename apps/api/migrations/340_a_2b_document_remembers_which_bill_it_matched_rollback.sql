-- Rollback for migration 340: drop the reconciliation columns from
-- gstr2a_records.
--
-- WHAT THIS LOSES is every recorded match, every itcavl flag off the portal,
-- and the ability to say from the Purchases tab whether a bill appears in 2B.
-- The table reverts to what it was: a shape nothing writes to. Run this only
-- to unblock something 340 broke.
--
-- Idempotent, and safe to re-run.

DROP INDEX IF EXISTS public.uq_gstr2a_records_document;
DROP INDEX IF EXISTS public.idx_gstr2a_records_bill;
DROP INDEX IF EXISTS public.idx_gstr2a_records_client_period;

ALTER TABLE public.gstr2a_records
  DROP CONSTRAINT IF EXISTS gstr2a_records_match_status_check;

ALTER TABLE public.gstr2a_records
  DROP COLUMN IF EXISTS purchase_bill_id,
  DROP COLUMN IF EXISTS match_status,
  DROP COLUMN IF EXISTS match_difference_paise,
  DROP COLUMN IF EXISTS itc_available,
  DROP COLUMN IF EXISTS itc_unavailable_reason_code,
  DROP COLUMN IF EXISTS itc_unavailable_reason,
  DROP COLUMN IF EXISTS document_type,
  DROP COLUMN IF EXISTS section,
  DROP COLUMN IF EXISTS cess_paise,
  DROP COLUMN IF EXISTS invoice_value_paise,
  DROP COLUMN IF EXISTS supplier_trade_name,
  DROP COLUMN IF EXISTS supplier_filed_on,
  DROP COLUMN IF EXISTS is_amendment,
  DROP COLUMN IF EXISTS amends_document_number,
  DROP COLUMN IF EXISTS reconciled_at,
  DROP COLUMN IF EXISTS updated_at;
