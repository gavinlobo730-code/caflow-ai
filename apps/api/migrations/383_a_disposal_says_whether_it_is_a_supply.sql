-- 383 — A fixed-asset disposal records its GST treatment (FA-08b).
--
-- WHAT WAS WRONG
--     `journal_for_asset_disposal` posted four lines — accumulated
--     depreciation cleared, the whole proceeds to bank, the asset out at cost,
--     and the gain or loss balancing — and NO tax line of any kind.
--     `DisposalIn` carried no field that could have driven one. A sale of a
--     capital asset is a supply, so the tax was never declared, never posted,
--     and the CA had to remember to raise a separate sales invoice with
--     nothing anywhere prompting them.
--
--     It is not merely "tax on the sale" either. CGST Act s.18(6) charges the
--     HIGHER of the input tax credit taken on the asset, reduced for the time
--     it was held, and the tax on the transaction value under s.15 — so an
--     asset sold cheap early in its life pays back credit rather than tax on
--     the price. Migration 343 already stores the credit side
--     (igst/cgst/sgst_paise, itc_eligible); what was missing was the disposal
--     side.
--
-- WHY THREE COLUMNS AND NOT ONE
--     `disposal_is_supply` is a fact about the TRANSACTION, not about the
--     rate. A scrapping for no consideration, a write-off, a transfer whose
--     treatment turns on Schedule I — the answer decides whether any tax is
--     charged at all, and no ledger holds the facts. It is NULLABLE WITH NO
--     DEFAULT on purpose: NULL means nobody has said, which the disposal
--     answer names as a gap. Defaulting it either way would decide a statutory
--     question by omission — the same shape as `vendors.msme_status` and
--     `fixed_assets.rule_43_use`.
--
--     `disposal_gst_rate_bps` is the rate on the OUTWARD supply, which is not
--     necessarily the rate the asset was bought at, and
--     `disposal_is_interstate` is which head it falls in. Both are STATED. An
--     asset bought locally and sold across a state border took CGST+SGST
--     credit and charges IGST, and nothing in the register could infer that.
--
-- THE PROCEEDS ARE TAX-INCLUSIVE. `disposal_value_paise` is what the buyer
-- paid, and `domain/gst/section_18_6` backs the tax out of it with the same
-- exact splitter a bank charge uses, so the disposal journal balances without
-- a rounding plug. Every row written before this migration has a NULL rate and
-- so is not split at all — which is what it was.
ALTER TABLE public.fixed_assets
  ADD COLUMN IF NOT EXISTS disposal_is_supply      BOOLEAN,
  ADD COLUMN IF NOT EXISTS disposal_gst_rate_bps   INTEGER,
  ADD COLUMN IF NOT EXISTS disposal_is_interstate  BOOLEAN NOT NULL DEFAULT false;

-- The same five rates domain/banking/charge_gst.ALLOWED_RATES_BPS accepts,
-- which is the set migrations 254 and 382 already use. A typo in a tax head
-- becomes a wrong GSTR-3B.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'public.fixed_assets'::regclass
      AND conname  = 'fixed_assets_disposal_gst_rate_bps_check'
  ) THEN
    ALTER TABLE public.fixed_assets
      ADD CONSTRAINT fixed_assets_disposal_gst_rate_bps_check
      CHECK (disposal_gst_rate_bps IS NULL
             OR disposal_gst_rate_bps IN (0, 500, 1200, 1800, 2800));
  END IF;
END $$;

COMMENT ON COLUMN public.fixed_assets.disposal_is_supply IS
  'Whether this disposal is a SUPPLY for GST. NULL = nobody has said, which '
  'the disposal answer names as a gap; there is deliberately no default, '
  'because a scrapping for no consideration and a sale are the same row shape '
  'and only the CA knows which this is. false = no output tax is charged and '
  'CGST Act s.18(6) is not reached.';

COMMENT ON COLUMN public.fixed_assets.disposal_gst_rate_bps IS
  'The GST rate on the OUTWARD supply, in basis points, as STATED by the CA — '
  'not inferred from the acquisition, which may have been at a different rate '
  'or under a different head. NULL means not stated, and the tax on the '
  'transaction value (limb (b) of CGST Act s.18(6)) is then refused rather '
  'than guessed. disposal_value_paise is TAX-INCLUSIVE and the tax is backed '
  'out of it.';

COMMENT ON COLUMN public.fixed_assets.disposal_is_interstate IS
  'false = CGST + SGST on the disposal, true = IGST. Meaningless where '
  'disposal_gst_rate_bps is NULL. An asset bought locally may be sold '
  'inter-state, so this is a fact about the SALE and not about the asset.';

-- The return reads the period's disposals that carry output tax.
CREATE INDEX IF NOT EXISTS idx_fixed_assets_disposal_gst
  ON public.fixed_assets (client_id, disposal_date)
  WHERE disposal_gst_rate_bps IS NOT NULL AND is_disposed = true;
