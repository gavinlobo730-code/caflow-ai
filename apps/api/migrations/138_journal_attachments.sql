-- Migration 138: manual-journal attachments.
--
-- Phase 0.5 hardening. Manual journals can carry supporting documents (vouchers,
-- scans). Stored as a JSON array of {name, url} references on the entry. The single
-- posting kernel (phase2_journal_service._create_journal) writes this column ONLY
-- when a caller supplies attachments (manual journals); every other posting path
-- (invoices, receipts, opening balances, reversals, …) leaves it at the default.
--
-- Additive and behaviour-inert: existing rows default to an empty array, the column
-- is NOT NULL with a constant default (metadata-only on PostgreSQL 17 — no table
-- rewrite/lock), and no existing INR posting path or report changes.
ALTER TABLE public.journal_entries
  ADD COLUMN IF NOT EXISTS attachments JSONB NOT NULL DEFAULT '[]'::jsonb;
