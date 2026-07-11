-- Migration 196 — explicit opening-balance date for stock-tracked products.
--
-- seed_opening_balance / seed_opening_balances_batch (domain/inventory_service.py)
-- previously dated the opening-stock ledger movement (and its GL journal) to
-- whenever the CA happened to type the data in (created_at / "today"), not
-- to the date the opening balance is actually AS OF. Real accounting
-- practice (and QuickBooks Online / Zoho Books, which both expose this as an
-- explicit field) treats an opening balance as pegged to a deliberately
-- chosen "as of" / conversion date — typically the client's financial-year
-- start — distinct from data-entry time. This column persists that chosen
-- date on the product/service row itself (the SAME value used as the
-- inventory_stock_ledger movement_date and the opening journal's entry_date),
-- for audit/display and so a later edit can see what date the original
-- opening balance was struck at.

ALTER TABLE public.service_catalogue
    ADD COLUMN IF NOT EXISTS opening_balance_date DATE;

COMMENT ON COLUMN public.service_catalogue.opening_balance_date IS
    'The "as of" date the opening stock balance (opening_qty_units/opening_cost_paise) is struck at — defaults to the client''s financial-year start, not the date the row was created. Meaningless for kind=service.';
