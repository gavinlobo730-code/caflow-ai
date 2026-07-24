-- Task #232: WDV depreciation was recomputed from the asset's CURRENT
-- (already-reduced) accumulated_depreciation_paise on EVERY monthly
-- posting, instead of a FIXED annual figure computed once per financial
-- year from that year's OPENING WDV — systematically under-depreciating
-- (~6.6% understated in year one, compounding in later years).
--
-- These columns cache the opening-of-financial-year accumulated
-- depreciation an asset's remaining monthly postings in that FY should
-- keep dividing by 12 (via annual/12), reset only when the first
-- depreciation period of a NEW financial year is posted for that asset.
-- See routers/fixed_assets.py's _annual_depreciation_for_period.
ALTER TABLE public.fixed_assets
  ADD COLUMN IF NOT EXISTS depreciation_fy TEXT,
  ADD COLUMN IF NOT EXISTS depreciation_fy_start_accum_paise BIGINT;
