-- Migration 521: a fixed deposit says whether its maturity amount is the deposit receipt's figure or an estimate (POST-A-134).
--
-- public.fixed_deposits.maturity_amount_paise (migration 026) is NOT NULL, and the only writer is the register screen, which
-- computed it in the browser as annual compounding (P x (1 + r/100)^(days/365)) and stored it as though it were the bank's. Banks
-- usually compound a cumulative deposit quarterly and a payout deposit does not compound at all, so the stored figure can differ
-- from the receipt, and the register and the risk register ("FD Maturing Soon") both showed it as the amount maturing.
--
-- maturity_amount_is_estimate is true when the figure is the product's estimate and false when the CA typed the amount printed
-- on the deposit receipt (the document of record). It defaults to TRUE, which is the truthful value for every row written before
-- this column: none was ever typed. READ FROM PRODUCTION on 18-10-2026: public.fixed_deposits holds 0 rows, so the default
-- relabels nothing that exists.
--
-- Additive and idempotent. ADD COLUMN with a constant default is a metadata change, not a table rewrite. The rollback drops the
-- column, after which the register cannot say which of its figures are estimates.

ALTER TABLE IF EXISTS public.fixed_deposits
    ADD COLUMN IF NOT EXISTS maturity_amount_is_estimate BOOLEAN NOT NULL DEFAULT true;

DO $$
BEGIN
    IF to_regclass('public.fixed_deposits') IS NOT NULL THEN
        COMMENT ON COLUMN public.fixed_deposits.maturity_amount_is_estimate IS
            'true: maturity_amount_paise is the product''s estimate (annual compounding); false: the CA typed the amount on the deposit receipt. Migration 521.';
    END IF;
END $$;
