-- Rollback of migration 567: drop the per-filing record of what each return used of a brought-forward loss.
-- The two totals (`utilized_amount_paise`, `remaining_amount_paise`) stay as the filings left them; only the breakdown by filing and year
-- goes, so after this a computation offers `remaining` for every year again.

BEGIN;

ALTER TABLE public.brought_forward_losses
    DROP CONSTRAINT IF EXISTS brought_forward_losses_entries_within_utilized;
ALTER TABLE public.brought_forward_losses
    DROP CONSTRAINT IF EXISTS brought_forward_losses_utilisations_is_an_object;
ALTER TABLE public.brought_forward_losses
    DROP COLUMN IF EXISTS utilisations;
DROP FUNCTION IF EXISTS public.brought_forward_loss_entries_total(JSONB);

COMMIT;
