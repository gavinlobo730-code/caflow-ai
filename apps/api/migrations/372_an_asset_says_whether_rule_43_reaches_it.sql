-- An asset says whether CGST Rule 43 reaches it (FA-19).
--
-- WHAT WAS MISSING
--
-- A registered person who makes both taxable and exempt supplies cannot keep
-- the whole input tax credit on a machine used for both. CGST Rule 43 spreads
-- that credit over SIXTY tax periods and, in each one, adds the exempt-turnover
-- share back to output tax:
--
--     A   the credit taken on one common capital good        43(1)(c)
--     Tm  a period's share of that credit, A / 60            43(1)(e)
--     Tr  the sum of Tm over goods whose life REMAINS        43(1)(f)
--     Te  (E / F) * Tr, added to output tax                  43(1)(g)/(h)
--
-- Nothing in this product computed it. `fixed_assets` has carried the tax split
-- (igst_paise / cgst_paise / sgst_paise) since migration 343 and
-- `itc_eligible` since the same one, and the outward turnover E and F are
-- already computed for GSTR-3B. The ONE fact nobody held is which of Rule
-- 43(1)'s three uses an asset is put to.
--
-- WHY IT IS A COLUMN AND NOT A DERIVATION
--
--   43(1)(a) exclusively for non-business or exempt supplies -- NO credit.
--   43(1)(b) exclusively for supplies other than exempt ones, zero-rated
--            included -- FULL credit, and Rule 43 never reaches the asset.
--   43(1)(c) everything else -- COMMON, and the sixty-month apportionment runs.
--
-- Which one an asset is put to is a fact about the business, not about the
-- document. A lathe and a delivery van bought on the same bill, by the same
-- client, at the same rate, can fall in different clauses. No ledger holds it
-- and no amount is evidence of it.
--
-- SO IT IS NULLABLE AND A NULL IS REFUSED RATHER THAN ASSUMED. Guessing is
-- unsafe in BOTH directions, which is the whole reason for the column:
--
--   * assuming COMMON reverses credit on a machine used only for taxable
--     supplies -- the business loses credit s.16(1) gives it, monthly, for
--     five years;
--   * assuming EXCLUSIVELY TAXABLE leaves Te undeclared, and Rule 43(1)(h)
--     attaches interest to it, so the shortfall grows.
--
-- domain/gst/rule_43.py leaves an unclassified asset OUT and names it in
-- `gaps`, the same shape as vendors.msme_status and
-- chart_of_accounts.unbilled_dues_side: a fact about the world that no ledger
-- holds, refused and named.
--
-- NOTHING IS BACKFILLED, and there is deliberately no DEFAULT. A default would
-- classify every asset in every register the moment this applies, which is
-- exactly the guess the column exists to avoid. Every existing asset reads
-- NULL and reports itself.
--
-- WHAT THIS DOES NOT ADD. The provisos to Rule 43(1)(c) and (d) reduce an
-- asset's input tax by five percentage points per quarter or part thereof when
-- it MOVES from an exclusive use into common use. A single column records only
-- what an asset is now, not when it changed, so that transition is not
-- modelled and every Rule 43 answer says so. Modelling it needs a history of
-- the classification, which is a second table and a second migration.

ALTER TABLE public.fixed_assets
  ADD COLUMN IF NOT EXISTS rule_43_use TEXT;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                  WHERE conname = 'fixed_assets_rule_43_use_check') THEN
    ALTER TABLE public.fixed_assets
      ADD CONSTRAINT fixed_assets_rule_43_use_check
      CHECK (rule_43_use IS NULL
             OR rule_43_use IN ('common', 'exclusively_exempt',
                                'exclusively_taxable'));
  END IF;
END $$;

-- The Rule 43 working reads every asset of one client for one tax period and
-- keeps only the commons whose five years still run. Assets are few per client
-- and the query is already client-scoped, so this index exists for the
-- partial scan rather than for selectivity.
CREATE INDEX IF NOT EXISTS idx_fixed_assets_rule_43_common
  ON public.fixed_assets (client_id, purchase_date)
  WHERE rule_43_use = 'common' AND deleted_at IS NULL;

COMMENT ON COLUMN public.fixed_assets.rule_43_use IS
  'CGST Rule 43(1): common = used partly for exempt supplies, so 1/60th of the '
  'credit is apportioned by exempt turnover every month for five years; '
  'exclusively_exempt = 43(1)(a), no credit was available; exclusively_taxable '
  '= 43(1)(b), the whole credit stands. NULL = the CA has not said, and the '
  'asset is left OUT of the working and named as a gap -- assuming either way '
  'is wrong in a direction that costs somebody money.';
