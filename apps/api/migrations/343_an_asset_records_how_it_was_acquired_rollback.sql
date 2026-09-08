-- Rollback for 343.
--
-- Dropping these columns loses which vendor an asset came from and whether its
-- tax was claimed as ITC — facts no journal line records, because the
-- acquisition entry only ever showed the net effect. Export
-- fixed_assets(id, acquisition_mode, vendor_id, purchase_bill_id, itc_eligible)
-- before running this if any asset has been created since 343 applied.

DROP INDEX IF EXISTS public.uq_fixed_assets_purchase_bill;
DROP INDEX IF EXISTS public.idx_fixed_assets_vendor;

ALTER TABLE public.fixed_assets
  DROP CONSTRAINT IF EXISTS fixed_assets_acquisition_mode_check;

ALTER TABLE public.fixed_assets
  DROP COLUMN IF EXISTS acquisition_mode,
  DROP COLUMN IF EXISTS vendor_id,
  DROP COLUMN IF EXISTS purchase_bill_id,
  DROP COLUMN IF EXISTS bank_account_id,
  DROP COLUMN IF EXISTS payment_mode,
  DROP COLUMN IF EXISTS igst_paise,
  DROP COLUMN IF EXISTS cgst_paise,
  DROP COLUMN IF EXISTS sgst_paise,
  DROP COLUMN IF EXISTS itc_eligible,
  DROP COLUMN IF EXISTS itc_blocked_reason;
