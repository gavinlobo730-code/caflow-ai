-- Migration 145: Debit Notes (Production Readiness Phase 5 — accounting completeness).
--
-- Audit H23: debit notes (vendor-side purchase returns) did not exist. A debit note
-- reduces a purchase bill's PAYABLE in the AP sub-ledger and posts a kernel journal
--   Dr Trade Payables  (we owe the vendor less)
--   Cr Purchases/Expense (reverse the expense)   Cr GST Input (reverse the ITC)
-- exactly mirroring the customer-side credit note. CGST Act §34 (debit/credit notes).

CREATE TABLE IF NOT EXISTS public.debit_notes (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id              UUID NOT NULL,
  client_id            UUID NOT NULL,
  vendor_id            UUID NOT NULL,
  purchase_bill_id     UUID REFERENCES public.purchase_bills(id),
  debit_note_no        TEXT,
  debit_note_date      DATE NOT NULL,
  reason               TEXT,
  is_interstate        BOOLEAN NOT NULL DEFAULT FALSE,
  is_reverse_charge    BOOLEAN NOT NULL DEFAULT FALSE,
  taxable_amount_paise BIGINT NOT NULL DEFAULT 0,
  cgst_paise           BIGINT NOT NULL DEFAULT 0,
  sgst_paise           BIGINT NOT NULL DEFAULT 0,
  igst_paise           BIGINT NOT NULL DEFAULT 0,
  total_paise          BIGINT NOT NULL DEFAULT 0,
  total_gst_paise      BIGINT NOT NULL DEFAULT 0,
  applied_paise        BIGINT NOT NULL DEFAULT 0,
  status               TEXT NOT NULL DEFAULT 'draft',
  journal_entry_id     UUID,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by           UUID
);
CREATE INDEX IF NOT EXISTS idx_dn_firm_client ON public.debit_notes (firm_id, client_id);
CREATE INDEX IF NOT EXISTS idx_dn_vendor      ON public.debit_notes (vendor_id);
CREATE INDEX IF NOT EXISTS idx_dn_bill        ON public.debit_notes (purchase_bill_id);

CREATE TABLE IF NOT EXISTS public.debit_note_lines (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  debit_note_id        UUID NOT NULL REFERENCES public.debit_notes(id) ON DELETE CASCADE,
  description          TEXT,
  hsn_sac              TEXT,
  quantity             NUMERIC,
  rate_paise           BIGINT,
  gst_rate_bps         INTEGER,
  taxable_amount_paise BIGINT,
  cgst_paise           BIGINT,
  sgst_paise           BIGINT,
  igst_paise           BIGINT,
  line_total_paise     BIGINT
);
CREATE INDEX IF NOT EXISTS idx_dnl_debit_note ON public.debit_note_lines (debit_note_id);

-- Debit-note → bill application records (mirrors credit_note_allocations).
CREATE TABLE IF NOT EXISTS public.debit_note_allocations (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id          UUID NOT NULL,
  debit_note_id    UUID NOT NULL REFERENCES public.debit_notes(id) ON DELETE CASCADE,
  purchase_bill_id UUID NOT NULL REFERENCES public.purchase_bills(id),
  allocated_paise  BIGINT NOT NULL CHECK (allocated_paise > 0),
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (debit_note_id, purchase_bill_id)
);
CREATE INDEX IF NOT EXISTS idx_dna_debit_note ON public.debit_note_allocations (debit_note_id);
CREATE INDEX IF NOT EXISTS idx_dna_bill       ON public.debit_note_allocations (purchase_bill_id);
CREATE INDEX IF NOT EXISTS idx_dna_firm       ON public.debit_note_allocations (firm_id);

-- Portion of a bill's payable relieved by debit notes (mirrors credited_paise on invoices).
ALTER TABLE public.purchase_bills
  ADD COLUMN IF NOT EXISTS debited_paise BIGINT NOT NULL DEFAULT 0;

-- Tenant isolation (Phase 4 consistency): new tables get RLS + a firm-scoped policy.
ALTER TABLE public.debit_notes            ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.debit_note_lines       ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.debit_note_allocations ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS firm_debit_notes ON public.debit_notes;
CREATE POLICY firm_debit_notes ON public.debit_notes FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id()) WITH CHECK (firm_id = public.get_my_firm_id());

DROP POLICY IF EXISTS firm_debit_note_lines ON public.debit_note_lines;
CREATE POLICY firm_debit_note_lines ON public.debit_note_lines FOR ALL TO authenticated
  USING (debit_note_id IN (SELECT id FROM public.debit_notes WHERE firm_id = public.get_my_firm_id()))
  WITH CHECK (debit_note_id IN (SELECT id FROM public.debit_notes WHERE firm_id = public.get_my_firm_id()));

DROP POLICY IF EXISTS firm_debit_note_allocations ON public.debit_note_allocations;
CREATE POLICY firm_debit_note_allocations ON public.debit_note_allocations FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id()) WITH CHECK (firm_id = public.get_my_firm_id());
