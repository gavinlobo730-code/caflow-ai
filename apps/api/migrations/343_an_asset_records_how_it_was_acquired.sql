-- An asset records HOW it was acquired, and from whom (FA-07).
--
-- WHAT WAS WRONG
--
-- journal_for_asset_acquisition posted exactly two lines:
--
--     Dr <category account>   cost
--       Cr Bank               cost
--
-- unconditionally. FixedAssetIn carried no vendor, no bill reference, no
-- payment mode and no GST fields, so every asset the register has ever held was
-- recorded as bought outright, for cash, from nobody, with no input tax.
--
-- THE DOUBLE COUNT. A CA who buys a machine on a purchase bill gets the bill's
-- own journal — Dr Purchases/Expense, Dr GST Input, Cr Trade Payables — and
-- then adds the machine to the fixed-asset register, which posts Dr Fixed Asset
-- Cr Bank. The cost is now in BOTH Purchases and Fixed Assets, Bank has been
-- credited for something bought on credit, and the payable is still outstanding.
-- The balance sheet overstates assets, the P&L overstates expenses, and nothing
-- anywhere says so. routers/purchase_bills.py routes goods lines only to
-- apply_purchase_to_inventory; there is no fixed-asset path at all.
--
-- WHY THREE ACQUISITION MODES AND NOT A BOOLEAN
--
-- The credit leg is genuinely different in three cases, and collapsing any two
-- of them posts a wrong entry rather than an imprecise one:
--
--   'paid'      bought and paid for now. Credit the account the money actually
--               left, resolved by domain/accounting/payment_account.py — the
--               same resolver Phase 1a gave receipts and vendor payments, which
--               is why this finding belongs in the same phase.
--   'credit'    bought on credit from a named vendor, no bill in the system.
--               Credit Trade Payables. The vendor is then owed, which is true,
--               and a later payment relieves it through the ordinary path.
--   'from_bill' the purchase bill ALREADY POSTED. Its cost is sitting in
--               Purchases/Expense and its payable is already recorded, so
--               posting an acquisition entry at all would double it. What is
--               needed is a RECLASSIFICATION — Dr Fixed Asset, Cr the expense
--               account the bill used — moving cost out of the P&L and into the
--               balance sheet, touching neither Bank nor the payable.
--
-- GST IS NOT ALWAYS INPUT CREDIT, AND WHERE IT IS NOT IT IS PART OF THE COST.
-- CGST Act §17(5) blocks credit on, among others, a motor vehicle for personal
-- carriage. Blocked tax is not an expense either — it is part of the cost of
-- the asset, so it is capitalised and DEPRECIATES. That makes `itc_eligible`
-- a fact with a balance-sheet consequence and a depreciation consequence, not
-- a presentational flag, which is why the split is stored rather than derived.
--
-- NOTHING IS BACKFILLED. Every existing asset posted Dr Asset Cr Bank and its
-- journal says so. `acquisition_mode` is NULL for those, and the reconciliation
-- report reads NULL as "recorded before this was captured" rather than
-- inventing a mode for it.

ALTER TABLE public.fixed_assets
  ADD COLUMN IF NOT EXISTS acquisition_mode   TEXT,
  ADD COLUMN IF NOT EXISTS vendor_id          UUID REFERENCES public.vendors(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS purchase_bill_id   UUID REFERENCES public.purchase_bills(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS bank_account_id    UUID REFERENCES public.bank_accounts(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS payment_mode       TEXT,
  -- The tax on the acquisition, split by head, as it appeared on the document.
  ADD COLUMN IF NOT EXISTS igst_paise         BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS cgst_paise         BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS sgst_paise         BIGINT NOT NULL DEFAULT 0,
  -- NULL = not stated (a pre-343 asset). true = claimed as ITC. false = blocked
  -- under §17(5) and therefore capitalised into purchase_cost_paise.
  ADD COLUMN IF NOT EXISTS itc_eligible       BOOLEAN,
  ADD COLUMN IF NOT EXISTS itc_blocked_reason TEXT;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                  WHERE conname = 'fixed_assets_acquisition_mode_check') THEN
    ALTER TABLE public.fixed_assets
      ADD CONSTRAINT fixed_assets_acquisition_mode_check
      CHECK (acquisition_mode IS NULL
             OR acquisition_mode IN ('paid', 'credit', 'from_bill'));
  END IF;
END $$;

-- ONE ASSET PER BILL LINE. Capitalising the same bill twice is the double count
-- this migration exists to stop, and a CA doing it twice by hand is exactly how
-- it happens. Partial so the unlinked assets — every existing one — are
-- unaffected.
CREATE UNIQUE INDEX IF NOT EXISTS uq_fixed_assets_purchase_bill
  ON public.fixed_assets (purchase_bill_id)
  WHERE purchase_bill_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_fixed_assets_vendor
  ON public.fixed_assets (vendor_id) WHERE vendor_id IS NOT NULL;

COMMENT ON COLUMN public.fixed_assets.acquisition_mode IS
  'paid | credit | from_bill. Decides the CREDIT leg of the acquisition entry: '
  'the resolved payment account, Trade Payables, or — for from_bill — no '
  'acquisition entry at all, only a reclassification out of the expense the '
  'bill already posted. NULL means recorded before migration 343.';
COMMENT ON COLUMN public.fixed_assets.itc_eligible IS
  'false = CGST Act s.17(5) blocked, so the tax is capitalised into '
  'purchase_cost_paise and depreciates. NULL = not stated (pre-343).';
