-- ═══════════════════════════════════════════════════════════════════════════
-- 402 — public.capital_gains: whether the security was LISTED, and the
--       31-01-2018 fair market value the s.112A grandfathered cost rests on
--       (IT-28, and the second half of IT-19).
--
-- WHAT WAS WRONG, AND BOTH HALVES WERE LIVE ON A SCREEN
--
--   1. s.2(42A)'s proviso gives a SECURITY LISTED in a recognised stock
--      exchange in India a TWELVE-month holding period where an unlisted
--      asset needs twenty-four. The register's `asset_type` vocabulary is
--      equity_shares / mutual_funds / property / bonds / other, and 'bonds'
--      cannot say which: a debenture is the same kind of asset listed or not.
--      So `long_term_threshold_months` gave every bond twenty-four months and
--      a LISTED bond held seventeen was classified SHORT-TERM and charged at
--      a 30% slab estimate where s.112 charges 12.5% — and the wrong
--      classification was persisted into `gain_type` and `tax_rate_percent`.
--
--   2. s.55(2)(ac) deems the cost of a s.112A asset ACQUIRED BEFORE
--      01-02-2018 to be the HIGHER of the actual cost and the LOWER of the
--      31-01-2018 fair market value and the full value of the consideration.
--      The engine computed gain = sale - cost and applied s.112A to it, so on
--      every pre-2018 equity holding the gain was over-stated by the whole of
--      the appreciation up to 31-01-2018 — on shares bought in 2012 that is
--      usually most of it.
--
-- WHY TWO COLUMNS AND NOT A DERIVATION
--     Neither fact is in any ledger and neither can be computed from the
--     others. Whether a bond is listed is a fact about the instrument;
--     the 31-01-2018 fair market value is a fact about one scrip on one day
--     (the Explanation to the clause makes it the highest quoted price, or
--     the net asset value for an unlisted unit). Both are the shape
--     `transferred_asset_nature` took in migration 385 and
--     `fixed_assets.rule_43_use` took in 372: NULLABLE, NO DEFAULT, NO
--     BACKFILL, refused and NAMED by the domain module rather than guessed.
--
--     Guessing is unsafe in both directions and the directions are not
--     symmetrical, which is why the engine does not simply pick the cautious
--     one silently:
--
--       listed = true guessed  -> a real short-term gain is charged at 12.5%,
--                                 the s.112A annual exemption opens, and the
--                                 s.54/54EC/54F family (which gates on
--                                 is_long_term) can exempt a gain those
--                                 sections do not reach. A shortfall, with
--                                 s.234B interest running.
--       listed = false assumed -> more tax than is due, on a screen a CA
--                                 reads before filing. This is what the
--                                 engine does, AND IT SAYS SO.
--
--       fmv defaulted to cost  -> the whole pre-2018 appreciation taxed.
--       fmv defaulted to sale  -> a nil gain on a real one.
--       fmv absent             -> the actual cost stands, which is limb (i)'s
--                                 own floor, so the gain is the LARGEST the
--                                 section can give and the gap says so.
--
-- WHY THE FAIR MARKET VALUE IS STORED WHERE `indexed_cost_paise` IS NOT
--     IT-29 leaves `indexed_cost_paise` NULL when the Cost Inflation Index was
--     a fallback, because a DERIVED figure taken from an unnotified year is
--     wrong the moment the notification lands and nothing recomputes a stored
--     row. This is the opposite kind of value: the fair market value on
--     31 January 2018 is a fixed historical fact that never moves. It is an
--     INPUT, like `purchase_cost_paise` beside it, and storing it is what
--     makes the entry complete. The deemed cost it produces is NOT stored —
--     that is derived on every read, for migration 278's reason.
--
-- THE FIGURE IS THE WHOLE HOLDING'S, NOT A PER-SHARE PRICE
--     `capital_gains` has no quantity column, and `purchase_cost_paise` and
--     `sale_value_paise` are both totals for what was transferred. A per-share
--     price here would not be comparable with either limb it is ranked
--     against. The column comment says so, because it is the one way to put a
--     hundredfold error into this row.
--
-- NO NEW POLICIES AND NO NEW GRANTS
--     `public.capital_gains` predates migration 084, so it already carries
--     that migration's RESTRICTIVE `capital_gains_assignment_scope` policy —
--     084's one-shot DO loop has never run again, which is why a table
--     created SINCE has to declare one inline (see 385), and why a table
--     created BEFORE must not have a second one written over it here. RLS is
--     already enabled and migration 164 already left the browser read-only on
--     this table. Adding columns changes none of that.
-- ═══════════════════════════════════════════════════════════════════════════

ALTER TABLE public.capital_gains
  ADD COLUMN IF NOT EXISTS is_listed_security BOOLEAN;

ALTER TABLE public.capital_gains
  ADD COLUMN IF NOT EXISTS fmv_31_01_2018_paise BIGINT;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
     WHERE conrelid = 'public.capital_gains'::regclass
       AND conname = 'capital_gains_fmv_31_01_2018_paise_check'
  ) THEN
    ALTER TABLE public.capital_gains
      ADD CONSTRAINT capital_gains_fmv_31_01_2018_paise_check
      CHECK (fmv_31_01_2018_paise IS NULL OR fmv_31_01_2018_paise >= 0);
  END IF;
END $$;

COMMENT ON COLUMN public.capital_gains.is_listed_security IS
  'Whether the transferred security was listed in a recognised stock exchange '
  'in India. The proviso to IT Act s.2(42A) gives such a security (other than '
  'a unit) a 12-month holding period against 24 for everything else, and '
  'asset_type cannot carry it — a debenture is the same kind of asset either '
  'way. NULL means NOT RECORDED: domain/income_tax/capital_gains_engine.py '
  'then takes the UNLISTED period, which over-states the tax, and NAMES the '
  'gap rather than guessing. A notified zero coupon bond (s.2(48)) also takes '
  'the shorter period whatever this column says, and that is a third fact '
  'this product does not hold.';

COMMENT ON COLUMN public.capital_gains.fmv_31_01_2018_paise IS
  'Fair market value on 31 JANUARY 2018 of the WHOLE holding transferred — '
  'not a per-share price; there is no quantity column here and the two '
  'amounts this is ranked against are both totals. IT Act s.55(2)(ac) deems '
  'the cost of a s.112A asset acquired before 01-02-2018 to be the higher of '
  'the actual cost and the lower of this and the sale value. It is an INPUT, '
  'a fixed historical fact about one scrip on one day (the Explanation makes '
  'it the highest quoted price, or the net asset value for an unlisted unit), '
  'and nothing here can derive it. NULL means NOT RECORDED: the actual cost '
  'stands, and because limb (i) makes that cost a FLOOR on the deemed cost, '
  'the gain is then the LARGEST the section can give — an upper bound rather '
  'than a guess — and the gap is named. The DEEMED COST is never stored: it '
  'is derived on every read.';
