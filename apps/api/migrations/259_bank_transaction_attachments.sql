-- Migration 259: supporting documents on a bank transaction (Tier 1.8).
--
-- A bank line is a number and a narration. The receipt, the vendor invoice, the
-- cheque image — the things that actually justify how it was coded — have had
-- nowhere to live, so they end up in email and the reason for a coding is lost
-- the moment the person who chose it moves on.
--
-- SHAPE: the same convention migration 138 established for manual journals — a
-- JSONB array of {name, url}. Deliberately not a table. There is no join, no
-- lifecycle and no per-attachment permission distinct from the transaction's
-- own; a table would add an RLS surface and a foreign key to express nothing
-- the array does not already say. Consistency with 138 also means one mental
-- model for "a document attached to a financial record".
--
-- Additive and behaviour-inert: existing rows default to an empty array, the
-- column is NOT NULL with a constant default (metadata-only on modern
-- PostgreSQL — no table rewrite or long lock), and no posting path reads it.
--
-- ── WHAT THE CHECK DOES AND DOES NOT DO ─────────────────────────────────────
-- The CHECK enforces that the value is a JSON ARRAY and bounded in length. It
-- deliberately does NOT try to validate each element's shape or URL scheme: SQL
-- is a poor place to express "not a javascript: URL", and a half-check reads as
-- a guarantee it does not provide. Element validation lives in
-- domain/banking/attachments.py, where it is tested directly and where the
-- reason for each rule can be written down.

BEGIN;

ALTER TABLE public.bank_transactions
  ADD COLUMN IF NOT EXISTS attachments JSONB NOT NULL DEFAULT '[]'::jsonb;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'public.bank_transactions'::regclass
      AND conname  = 'bank_transactions_attachments_check'
  ) THEN
    ALTER TABLE public.bank_transactions
      ADD CONSTRAINT bank_transactions_attachments_check
      CHECK (jsonb_typeof(attachments) = 'array'
             AND jsonb_array_length(attachments) <= 20);
  END IF;
END $$;

COMMENT ON COLUMN public.bank_transactions.attachments IS
    'Tier 1.8 — supporting documents as a JSONB array of {name, url}. Same '
    'convention as journal_entries.attachments (migration 138). Element shape '
    'and URL scheme are validated in domain/banking/attachments.py, not here.';

-- ── Post-conditions ─────────────────────────────────────────────────────────
DO $verify$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_schema='public' AND table_name='bank_transactions'
                      AND column_name='attachments') THEN
        RAISE EXCEPTION 'Migration 259 failed: attachments column missing.';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conrelid = 'public.bank_transactions'::regclass
                      AND conname = 'bank_transactions_attachments_check') THEN
        RAISE EXCEPTION 'Migration 259 failed: the attachments CHECK is missing.';
    END IF;

    -- Every existing row must satisfy it (all default to '[]', so this is a
    -- no-op today — assert it rather than assume).
    IF EXISTS (SELECT 1 FROM public.bank_transactions
                WHERE jsonb_typeof(attachments) <> 'array') THEN
        RAISE EXCEPTION 'Migration 259 failed: a row has a non-array attachments value.';
    END IF;
END
$verify$;

COMMIT;
