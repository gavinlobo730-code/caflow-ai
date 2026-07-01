-- Migration 142: Statutory Compliance (Production Readiness Phase 2) — schema support.
--
-- C5 — GSTR-3B Table 3.2 (reverse-charge inward supplies) must be sourced from posted
--      PURCHASE bills, not sales. Flag which purchase bills are liable to RCM so the
--      return derives from the books. CGST Act §9(3)/(4).
ALTER TABLE public.purchase_bills
  ADD COLUMN IF NOT EXISTS is_reverse_charge BOOLEAN NOT NULL DEFAULT FALSE;

-- M1 — persist the GST total on credit notes (already present on invoices and bills)
-- so every document carries its own tax total rather than defaulting to 0 in the DB.
ALTER TABLE public.credit_notes
  ADD COLUMN IF NOT EXISTS total_gst_paise BIGINT NOT NULL DEFAULT 0;
