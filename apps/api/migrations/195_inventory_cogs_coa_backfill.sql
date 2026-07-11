-- Migration 195: "Inventory" and "Cost of Goods Sold" accounts for the
-- inventory costing module's journal postings (domain/inventory_service.py).
--
-- Migration 188 (Inventory costing) added post_cogs_journal_entry,
-- post_inventory_receipt_journal_entry, post_sale_return_journal_entry,
-- post_purchase_return_journal_entry, post_stock_writeoff_journal_entry,
-- post_stock_surplus_journal_entry and post_nrv_writedown_journal_entry —
-- all of which resolve an "Inventory" account via
-- phase2_journal_service._find_account(..., "%Inventor%", system_key=
-- "inventory"), and the COGS ones also resolve "%Cost of Goods Sold%". Unlike
-- migration 135 (which added "Opening Balance Equity" to STANDARD_COA AND
-- backfilled every existing firm), migration 188 never added either account
-- to STANDARD_COA or backfilled existing firms — so _find_account has been
-- raising "Required account not found" for every firm, on every one of
-- these movement types, since the module shipped. Every call site swallows
-- that exception and returns None (never blocks the sale/purchase/stock
-- movement itself), so this has been a SILENT gap: stock quantities and
-- moving-average costs have always tracked correctly, but not one Rupee of
-- inventory value has ever reached the General Ledger for ANY firm — COGS
-- reductions, purchase capitalisation, write-offs, NRV write-downs and
-- opening stock all missing from the Trial Balance / Balance Sheet.
--
-- Confirmed live: 0 firms had an "Inventory" account, 0 COGS journals had
-- ever been posted, despite the inventory module being in active use.
--
-- coa_seed_service.STANDARD_COA now includes both (1202 Inventory / 5000
-- Cost of Goods Sold) for new firms; this backfills every firm that already
-- has a chart of accounts. Idempotent: skips firms that already have either
-- account (by name) or that already use the target account_code, and only
-- touches firms that have a CoA at all (mirrors migration 135's guards).

INSERT INTO public.chart_of_accounts
    (firm_id, client_id, account_code, account_name, account_type, account_subtype, is_active)
SELECT f.id, NULL, '1202', 'Inventory', 'Asset', 'Current Asset', true
FROM public.firms f
WHERE NOT EXISTS (
        SELECT 1 FROM public.chart_of_accounts c
        WHERE c.firm_id = f.id AND c.client_id IS NULL
          AND c.account_name ILIKE '%Inventor%'
      )
  AND NOT EXISTS (
        SELECT 1 FROM public.chart_of_accounts c2
        WHERE c2.firm_id = f.id AND c2.client_id IS NULL AND c2.account_code = '1202'
      )
  AND EXISTS (
        SELECT 1 FROM public.chart_of_accounts c3
        WHERE c3.firm_id = f.id AND c3.client_id IS NULL
      );

INSERT INTO public.chart_of_accounts
    (firm_id, client_id, account_code, account_name, account_type, account_subtype, is_active)
SELECT f.id, NULL, '5000', 'Cost of Goods Sold', 'Expense', 'Direct Expense', true
FROM public.firms f
WHERE NOT EXISTS (
        SELECT 1 FROM public.chart_of_accounts c
        WHERE c.firm_id = f.id AND c.client_id IS NULL
          AND c.account_name ILIKE '%Cost of Goods Sold%'
      )
  AND NOT EXISTS (
        SELECT 1 FROM public.chart_of_accounts c2
        WHERE c2.firm_id = f.id AND c2.client_id IS NULL AND c2.account_code = '5000'
      )
  AND EXISTS (
        SELECT 1 FROM public.chart_of_accounts c3
        WHERE c3.firm_id = f.id AND c3.client_id IS NULL
      );
