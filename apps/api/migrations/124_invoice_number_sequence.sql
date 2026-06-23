-- Migration 124: Atomic invoice number sequence + UNIQUE constraint
--
-- Problem 1: generate_next_invoice_number() calls the RPC `next_invoice_number`
-- which does not exist anywhere in the migrations — would raise a 500 on every
-- invoice creation in production.
--
-- Problem 2: fee_invoices.invoice_no is TEXT NOT NULL with no UNIQUE constraint,
-- so concurrent requests can generate duplicate invoice numbers.
--
-- Fix: create an atomic sequence function backed by a per-firm counter table
-- (INSERT ... ON CONFLICT DO UPDATE is a single atomic statement in Postgres),
-- then add UNIQUE(firm_id, invoice_no) to enforce uniqueness at the DB level.
--
-- The function name matches what invoice_repository.py already calls:
--   _get_db().rpc("next_invoice_number", {"p_firm_id": firm_id})

-- ── Per-firm counter table ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.invoice_sequences (
    firm_id   UUID    NOT NULL PRIMARY KEY REFERENCES public.firms(id) ON DELETE CASCADE,
    last_seq  INTEGER NOT NULL DEFAULT 0
);

COMMENT ON TABLE public.invoice_sequences IS
  'Atomic per-firm invoice sequence counter. Never updated except via next_invoice_number().';

-- ── Atomic sequence function ──────────────────────────────────────────────────
-- Returns the next integer for the firm. INSERT on first call; atomic increment
-- on subsequent calls. Safe under concurrent requests — no TOCTOU window.
CREATE OR REPLACE FUNCTION public.next_invoice_number(p_firm_id UUID)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_next INTEGER;
BEGIN
  INSERT INTO public.invoice_sequences (firm_id, last_seq)
  VALUES (p_firm_id, 1)
  ON CONFLICT (firm_id) DO UPDATE
    SET last_seq = invoice_sequences.last_seq + 1
  RETURNING last_seq INTO v_next;
  RETURN v_next;
END;
$$;

COMMENT ON FUNCTION public.next_invoice_number(UUID) IS
  'Returns the next sequential invoice number for the given firm. Atomic — safe '
  'under concurrent requests. Called by invoice_repository.generate_next_invoice_number().';

-- ── UNIQUE constraint ─────────────────────────────────────────────────────────
-- Prevents duplicate invoice_no within a firm even if the application generates
-- two identical numbers in an unusual race (belt-and-suspenders).
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'fee_invoices_firm_invoice_no_unique'
      AND conrelid = 'public.fee_invoices'::regclass
  ) THEN
    ALTER TABLE public.fee_invoices
      ADD CONSTRAINT fee_invoices_firm_invoice_no_unique UNIQUE (firm_id, invoice_no);
  END IF;
END $$;
