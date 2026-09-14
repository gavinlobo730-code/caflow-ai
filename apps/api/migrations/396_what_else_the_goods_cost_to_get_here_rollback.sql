-- Rollback for 396.
--
-- REFUSES while any landed cost has been APPLIED to a receipt. Those rows are
-- the only record of why the stock ledger carries what it carries: the value
-- is in `inventory_stock_ledger.value_delta_paise` and in a posted journal,
-- neither of which this rollback can undo, so dropping the table would leave
-- a cost in the books that nothing explains.
DO $$
DECLARE n INTEGER;
BEGIN
  SELECT count(*) INTO n FROM public.purchase_bill_landed_costs
   WHERE applied_at IS NOT NULL;
  IF n > 0 THEN
    RAISE EXCEPTION
      'Refusing to roll back 396: % landed costs have been applied to a goods '
      'receipt. Their value is in the stock ledger and in a posted journal that '
      'this rollback cannot undo, so the table is the only record of why the '
      'stock carries what it carries.', n;
  END IF;
END $$;

DROP TABLE IF EXISTS public.purchase_bill_landed_costs;

ALTER TABLE public.purchase_bills DROP CONSTRAINT IF EXISTS purchase_bills_landed_cost_basis_check;
ALTER TABLE public.purchase_bills DROP COLUMN IF EXISTS landed_cost_basis;
ALTER TABLE public.clients DROP CONSTRAINT IF EXISTS clients_landed_cost_basis_check;
ALTER TABLE public.clients DROP COLUMN IF EXISTS landed_cost_basis;
