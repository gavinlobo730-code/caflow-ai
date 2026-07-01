-- Migration 139: remove the abandoned alternate transaction model (dead tables).
--
-- Phase 0.5 hardening — single posting engine. The live double-entry GL is
-- journal_entries + journal_lines ONLY. An earlier design introduced a parallel
-- transaction model that the engine never adopted:
--
--   * transactions        — 0 rows; no code reads or writes it
--   * transaction_lines   — 0 rows; child of transactions; unused
--   * invoice_lines       — 0 rows; orphan; unused (the live line table is
--                           client_sales_invoice_lines)
--
-- bank_transactions.transaction_id is a vestigial FK into transactions: 0 rows,
-- 0 non-null values, and never written by code (the bank import insert does not
-- set it). It is dropped so `transactions` can be removed.
--
-- Verified before drop: all three tables empty; no application code references
-- them; no views or other objects depend on them. The drop is therefore
-- data-loss-free. Order matters so no FK blocks the drop (no CASCADE needed):
--   1) drop the inbound FK column on the live bank_transactions table,
--   2) drop transaction_lines (child of transactions),
--   3) drop invoice_lines,
--   4) drop transactions (its self-referential FK drops with the table).
ALTER TABLE IF EXISTS public.bank_transactions DROP COLUMN IF EXISTS transaction_id;
DROP TABLE IF EXISTS public.transaction_lines;
DROP TABLE IF EXISTS public.invoice_lines;
DROP TABLE IF EXISTS public.transactions;
