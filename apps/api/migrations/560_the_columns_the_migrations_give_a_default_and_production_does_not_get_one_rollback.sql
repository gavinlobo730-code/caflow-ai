-- Rollback of migration 560: removes the nine defaults it gave. The two it changed to production's values
-- (tally_migration_jobs.is_dry_run and form_26as_reconciliations.status) are left as they are: on production they are
-- what was already there.
ALTER TABLE public.brought_forward_losses
    ALTER COLUMN original_amount_paise DROP DEFAULT,
    ALTER COLUMN remaining_amount_paise DROP DEFAULT;
ALTER TABLE public.eway_bill_records
    ALTER COLUMN dispatch_from DROP DEFAULT,
    ALTER COLUMN goods_description DROP DEFAULT,
    ALTER COLUMN ship_to DROP DEFAULT,
    ALTER COLUMN taxable_value_paise DROP DEFAULT;
ALTER TABLE public.itr_filing_versions ALTER COLUMN json_payload DROP DEFAULT;
ALTER TABLE public.tax_deduction_claims ALTER COLUMN claimed_amount_paise DROP DEFAULT;
ALTER TABLE public.tax_disallowances ALTER COLUMN amount_paise DROP DEFAULT;
