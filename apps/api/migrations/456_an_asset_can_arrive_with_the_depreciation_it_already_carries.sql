-- 456 — AN ASSET CAN ARRIVE WITH THE DEPRECIATION IT ALREADY CARRIES (accounting-18)
--
-- WHAT WAS WRONG
--   A client migrating from Tally or Winman owns tens or hundreds of assets that
--   are already part-depreciated. `fixed_assets` could take them in exactly one
--   way: `POST /api/fixed-assets`, which hardcodes `accumulated_depreciation_paise
--   = 0` and posts a fresh acquisition journal. The only route from there to the
--   asset's real position was to let the depreciation runner charge every month
--   since the purchase date — posting years of journals on top of the
--   accumulated-depreciation balance the opening trial balance already carries —
--   or to start the first posting late and accept `foreclosed_months`. Neither
--   states where the asset STANDS, and `accumulated_depreciation_paise` has no
--   writable door at all (it is not on `FixedAssetIn` or `FixedAssetUpdateIn`).
--
-- WHAT THIS COLUMN IS
--   `opening_position_date` is the date an asset's stated cost and accumulated
--   depreciation were brought over AS AT. NULL on every asset acquired here —
--   which is every row that exists today — and a financial-year end on one that
--   arrived with its own history.
--
--   It says ONE thing: "the ledger already carries this asset, from the opening
--   balances, and no acquisition journal of this product's ever put it there".
--   Everything that reads `journal_entry_id IS NULL` as "the register says the
--   client owns a machine and no entry ever put it on the balance sheet" —
--   `domain/fixed_assets/integrity.no_acquisition_journal` — has to be able to
--   tell the two apart, and without this it would report every migrated asset as
--   a defect the CA cannot fix (reposting the acquisition would count the cost
--   twice).
--
--   A DATE and not a boolean, deliberately. The same fact is also what lets the
--   register decide, without a second table, whether an opening asset may still
--   be removed or restated: it may while nothing has been depreciated since its
--   position (`depreciation_posted_through` is still this date), and a reversal
--   of the first month after it must roll the register back TO this date rather
--   than to "never depreciated" — the latter would send the next range run to
--   the purchase month and charge the whole history again.
--
-- IT POSTS NO JOURNAL, AND THAT IS THE DESIGN
--   migration 391's decision, for assets. The ledger's Fixed Assets and
--   Accumulated Depreciation balances arrive through the opening balances or an
--   imported trial balance; the register is the asset-by-asset breakup of them.
--   Posting an acquisition per asset as well would be the second mechanism
--   opening one position, whose double count `trial_balance_import_service`'s
--   `double_openings` exists to find. The import therefore names that nothing was
--   posted, and the CA compares the register totals it returns with the ledger.
--
-- NULLABLE, NO DEFAULT, NO BACKFILL
--   Every existing asset was acquired through `create_asset`, which posts the
--   acquisition and starts accumulated depreciation at nil — so NULL is TRUE of
--   all of them, not a guess. A default would assert otherwise, and a backfill
--   has nothing to back-fill from.
--
-- ADDITIVE AND IDEMPOTENT
--   One column, `IF NOT EXISTS`. No constraint (an existing row cannot violate
--   one, and a CHECK here would only be able to fail the production apply), no
--   index (it is read per client, with the rest of the client's register), no
--   grant change: `authenticated` keeps SELECT only on this table (migrations
--   166 / 245) and the service-role backend stays the only writer. There is no
--   rollback file on purpose: removing the column is only safe after the opening
--   assets are deleted, since without it the register could no longer tell them
--   from an asset whose acquisition journal is missing.

BEGIN;

ALTER TABLE public.fixed_assets
  ADD COLUMN IF NOT EXISTS opening_position_date DATE;

COMMENT ON COLUMN public.fixed_assets.opening_position_date IS
  'accounting-18. The financial-year end an asset''s cost and accumulated depreciation '
  'were brought over AS AT, from the client''s previous books. NULL = acquired '
  'here, with an acquisition journal of its own. Non-NULL = the ledger carries '
  'the asset through the opening balances, NO acquisition journal was posted for '
  'it, and depreciation_posted_through starts at this date so the next run '
  'charges the month after it and never the history. The register-integrity '
  'check for a missing acquisition journal is not raised for such an asset.';

COMMIT;
