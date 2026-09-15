-- 396 — freight inward, insurance and non-creditable duty in the cost of
-- stock (INV-05, second half).
--
-- WHAT WAS WRONG
--     `apply_purchase_to_inventory` costs a receipt at the line's taxable
--     value plus its s.17(5)-blocked tax (INV-05a, closed) and NOTHING ELSE.
--     AS-2 paragraph 6 says the cost of purchase "consists of the purchase
--     price including duties and taxes ..., FREIGHT INWARDS and OTHER
--     EXPENDITURE DIRECTLY ATTRIBUTABLE TO THE ACQUISITION". So a client who
--     pays ₹50,000 to bring a consignment in carries stock at less than it
--     cost, expenses the freight in the month it was billed rather than when
--     the goods are sold, and — because the cost formula runs off the same
--     figure — gets every later COGS wrong too.
--
--     The same sentence reaches CUSTOMS. Migration 389 records basic customs
--     duty and the social welfare surcharge on a Bill of Entry and posts them
--     to an expense account, with a caveat saying in terms that they are not
--     apportioned because the basis is a judgement nothing here holds. This
--     migration is that judgement, taken.
--
-- THE BASIS IS AN ACCOUNTING POLICY, NOT AN ANSWER THE STANDARD GIVES
--     AS-2 settles what goes IN the cost of purchase. It does not say how to
--     split one freight bill across the lines it covered, because there is no
--     single right split: by value is wrong for a container of identical
--     t-shirts, by quantity is wrong for 200 chairs and 20 tables.
--
--     So it is a policy, and it is stored the way `inventory_costing_method`
--     is (migration 394): on the CLIENT, applied consistently. Owner decision
--     of 14-09-2026, taken after reading what the market ships — TallyPrime
--     offers "Appropriate by Qty" or "Appropriate by Value" per expense
--     ledger, Zoho Books offers Quantity or Value in a popup when the bill is
--     saved, QuickBooks Enterprise offers Quantity / Amount / Percentage, and
--     Xero has no landed-cost allocation at all. Every one of them that has
--     the feature offers BOTH bases and lets the user pick.
--
--     A PER-BILL OVERRIDE exists because one consignment legitimately differs
--     from the client's usual, which is the case Zoho's per-bill popup exists
--     for. It is nullable and means "use the client's".
--
--     ⚠️ WEIGHT AND VOLUME ARE NOT OFFERED. They are the most accurate basis
--     for freight and no mainstream product in this tier ships them, for the
--     same reason this one does not: `service_catalogue` holds no weight, so
--     it would need a column and a figure typed for every stock item before
--     any of it worked. Named here so the next reader knows it was considered.
--
-- WHY A TABLE AND NOT THREE COLUMNS
--     A charge has to name the EXPENSE ACCOUNT it already landed on, because
--     that is the account the receipt journal relieves — the mechanism INV-05a
--     established and the reason it needed no new account: the transporter's
--     bill has already posted Dr Freight / Cr Transporter, so the receipt
--     posts Dr Inventory / Cr Freight and the expense nets to zero while the
--     transporter stays owed. Three fixed columns could not carry three
--     different accounts, and a client with two freight bills on one
--     consignment would have nowhere to put the second.
--
-- `applied_at` IS THE HONEST BOUNDARY
--     A landed cost is included in the receipt cost only if it is recorded
--     BEFORE the bill is received. After that the receipt journal is posted
--     and migration 251 makes it immutable, so re-costing is not available.
--     The charge is still RECORDED — it is a fact, and refusing the data entry
--     would send it somewhere worse — and `applied_at` stays NULL, which is
--     what lets the register report it rather than leaving it silently out of
--     a figure that reads as complete.

ALTER TABLE public.clients
  ADD COLUMN IF NOT EXISTS landed_cost_basis TEXT;

ALTER TABLE public.purchase_bills
  ADD COLUMN IF NOT EXISTS landed_cost_basis TEXT;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                  WHERE conrelid = 'public.clients'::regclass
                    AND conname = 'clients_landed_cost_basis_check') THEN
    ALTER TABLE public.clients ADD CONSTRAINT clients_landed_cost_basis_check
      CHECK (landed_cost_basis IS NULL OR landed_cost_basis IN ('value', 'quantity'));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                  WHERE conrelid = 'public.purchase_bills'::regclass
                    AND conname = 'purchase_bills_landed_cost_basis_check') THEN
    ALTER TABLE public.purchase_bills ADD CONSTRAINT purchase_bills_landed_cost_basis_check
      CHECK (landed_cost_basis IS NULL OR landed_cost_basis IN ('value', 'quantity'));
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS public.purchase_bill_landed_costs (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id               UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id             UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  bill_id               UUID NOT NULL REFERENCES public.purchase_bills(id) ON DELETE CASCADE,

  -- What it is, in the CA's own words. AS-2 paragraph 6's own examples are
  -- freight inwards and "other expenditure directly attributable"; a free-text
  -- description is right because the Standard's category is open and a fixed
  -- list would refuse a real charge.
  description           TEXT NOT NULL,
  amount_paise          BIGINT NOT NULL CHECK (amount_paise > 0),

  -- The account this charge ALREADY landed on, which the receipt journal
  -- relieves. Nullable: the same fallback chain the bill journal and INV-05a's
  -- receipt journal use (%Purchase% then %Expense%) applies where it is not
  -- stated, so a charge is never refused for want of an account.
  expense_account_id    UUID REFERENCES public.chart_of_accounts(id) ON DELETE SET NULL,

  -- Where it came from. 'bill_of_entry' rows are the non-creditable customs
  -- duty migration 389 posts to expense, carried across when the Bill of Entry
  -- names this purchase bill; they are written by the system rather than typed,
  -- and the distinction matters because only a manual row may be edited.
  source                TEXT NOT NULL DEFAULT 'manual'
                        CHECK (source IN ('manual', 'bill_of_entry')),
  bill_of_entry_id      UUID REFERENCES public.bills_of_entry(id) ON DELETE CASCADE,

  -- NULL until the goods receipt consumed it. A charge recorded AFTER the bill
  -- was received keeps NULL for ever and is reported, because the receipt
  -- journal is posted and migration 251 makes it immutable.
  applied_at            TIMESTAMPTZ,

  notes                 TEXT,
  created_by            UUID REFERENCES public.users(id),
  created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  -- A Bill of Entry contributes its duty to a bill ONCE. A manual row has no
  -- such key, because two separate freight bills on one consignment are two
  -- charges.
  CONSTRAINT purchase_bill_landed_costs_one_row_per_boe
    UNIQUE (bill_id, bill_of_entry_id),
  -- The two halves of `source` must agree with the FK, or a system row could
  -- be typed by hand and edited.
  CONSTRAINT purchase_bill_landed_costs_source_matches_link
    CHECK ((source = 'bill_of_entry' AND bill_of_entry_id IS NOT NULL)
        OR (source = 'manual'        AND bill_of_entry_id IS NULL))
);

CREATE INDEX IF NOT EXISTS idx_purchase_bill_landed_costs_bill
  ON public.purchase_bill_landed_costs (bill_id);
CREATE INDEX IF NOT EXISTS idx_purchase_bill_landed_costs_unapplied
  ON public.purchase_bill_landed_costs (firm_id, client_id)
  WHERE applied_at IS NULL;

ALTER TABLE public.purchase_bill_landed_costs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS purchase_bill_landed_costs_own_firm ON public.purchase_bill_landed_costs;
CREATE POLICY purchase_bill_landed_costs_own_firm ON public.purchase_bill_landed_costs
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());

-- Migration 084's assignment scoping, declared here rather than left to its
-- one-shot DO loop, which has never re-run (CLAUDE.md).
DROP POLICY IF EXISTS purchase_bill_landed_costs_assignment_scope ON public.purchase_bill_landed_costs;
CREATE POLICY purchase_bill_landed_costs_assignment_scope ON public.purchase_bill_landed_costs
  AS RESTRICTIVE FOR ALL TO authenticated
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));

GRANT SELECT, INSERT, UPDATE, DELETE ON public.purchase_bill_landed_costs TO authenticated;

COMMENT ON COLUMN public.clients.landed_cost_basis IS
  'How a landed cost is split across the stock lines it covered: ''value'' '
  '(pro-rata on each line''s own cost) or ''quantity'' (pro-rata on units). '
  'AS-2 says what goes in the cost of purchase and NOT how to split it, so '
  'this is an accounting policy and lives on the client, applied consistently '
  '— the same shape as inventory_costing_method. NULL means nobody has chosen '
  'and the engine uses value, which is what QuickBooks recommends and the safe '
  'basis for a mixed consignment. No default: a default would make the choice '
  'look made. Weight and volume are deliberately not offered — no weight is '
  'held per item, and no mainstream product in this tier ships them either.';
COMMENT ON COLUMN public.purchase_bills.landed_cost_basis IS
  'Overrides the client''s basis for THIS consignment only. NULL means use the '
  'client''s. Exists because one consignment legitimately differs from a '
  'client''s usual — the case Zoho Books'' per-bill allocation popup serves.';
COMMENT ON TABLE public.purchase_bill_landed_costs IS
  'Freight inward, insurance in transit and non-creditable customs duty — what '
  'AS-2 paragraph 6 puts in the cost of purchase besides the price and the '
  'non-recoverable tax. Each row names the EXPENSE ACCOUNT the charge already '
  'landed on, because the receipt journal relieves exactly that account: the '
  'transporter''s bill posts Dr Freight / Cr Transporter, the receipt posts '
  'Dr Inventory / Cr Freight, the expense nets to zero and the transporter '
  'stays owed. No new account and no second posting path. `applied_at` is NULL '
  'until the goods receipt consumed it, and stays NULL for ever on a charge '
  'recorded after the bill was received — the receipt journal is posted and '
  'migration 251 makes it immutable, so the charge is reported rather than '
  'silently left out of a figure that reads as complete.';
