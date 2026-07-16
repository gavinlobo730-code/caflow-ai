-- Migration 210 — the two correction directions Phase 1 was missing.
--
-- CGST Act §34 covers BOTH directions of a value/tax correction to an
-- already-issued document, not just reductions:
--   §34(1) reduction  -> the seller/supplier issues a Credit Note
--   §34(3) increase   -> the seller/supplier issues a Debit Note
--
-- This platform already has the reduction side for both parties (Sales
-- Credit Note reduces what a customer owes; Purchase Debit Note reduces
-- what we owe a vendor — see migrations 050/145). It never had the increase
-- side: a Sales Debit Note (we undercharged a customer, need to bill more)
-- or a Purchase Credit Note (a vendor undercharged us, we owe them more).
--
-- Naming follows the existing double-entry convention already used by the
-- reduction-side tables, just mirrored: on the sales side "Debit Note"
-- DEBITS the customer's receivable (increases it, §34(3)); on the purchase
-- side "Credit Note" CREDITS the vendor's payable (increases it, the AP
-- mirror of §34(3) exactly like the existing Purchase Debit Note already
-- mirrors §34(1) from the buyer's own bookkeeping side).
--
-- sales_debit_notes / sales_debit_note_lines / sales_debit_note_allocations
-- mirror credit_notes / credit_note_lines / credit_note_allocations exactly
-- (same column shapes, same NOT NULL / default choices) — just the
-- increasing counterpart.
--
-- purchase_credit_notes / purchase_credit_note_lines /
-- purchase_credit_note_allocations mirror debit_notes / debit_note_lines /
-- debit_note_allocations exactly, including debit_notes' own already-live
-- quirks (nullable line columns, no FK on vendor_id — resolved via the
-- vendor list client-side, same as the existing Debit Notes tab).
--
-- debit_note_paise on client_sales_invoices and credit_note_paise on
-- purchase_bills track how much has been added by the new document types,
-- mirroring how credited_paise/debited_paise already track the reductions:
--   sales invoice outstanding    = (total_paise + debit_note_paise) - paid_paise - credited_paise
--   purchase bill outstanding    = (net_payable_paise + credit_note_paise) - paid_paise - debited_paise
--
-- Idempotent: every statement uses IF NOT EXISTS.

CREATE TABLE IF NOT EXISTS public.sales_debit_notes (
  id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id                  UUID NOT NULL REFERENCES firms(id) ON DELETE CASCADE,
  client_id                UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  customer_id              UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  -- nullable: a debit note may not link to a specific invoice (CGST Act §34)
  sales_invoice_id         UUID REFERENCES client_sales_invoices(id),
  debit_note_no            TEXT NOT NULL,
  debit_note_date          DATE NOT NULL,
  reason                   TEXT,
  is_interstate            BOOLEAN NOT NULL DEFAULT false,
  taxable_amount_paise     BIGINT NOT NULL DEFAULT 0,
  cgst_paise               BIGINT NOT NULL DEFAULT 0,
  sgst_paise               BIGINT NOT NULL DEFAULT 0,
  igst_paise               BIGINT NOT NULL DEFAULT 0,
  total_paise              BIGINT NOT NULL DEFAULT 0,
  total_gst_paise          BIGINT NOT NULL DEFAULT 0,
  status                   TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','issued')),
  journal_entry_id         UUID,
  applied_paise            BIGINT NOT NULL DEFAULT 0,
  created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at               TIMESTAMPTZ,
  UNIQUE (firm_id, debit_note_no)
);

CREATE TABLE IF NOT EXISTS public.sales_debit_note_lines (
  id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  debit_note_id            UUID NOT NULL REFERENCES sales_debit_notes(id) ON DELETE CASCADE,
  description              TEXT NOT NULL,
  hsn_sac                  TEXT,
  quantity                 NUMERIC(10,3) NOT NULL DEFAULT 1,
  rate_paise               BIGINT NOT NULL DEFAULT 0,
  taxable_amount_paise     BIGINT NOT NULL DEFAULT 0,
  gst_rate_bps             INTEGER NOT NULL DEFAULT 1800,
  cgst_paise               BIGINT NOT NULL DEFAULT 0,
  sgst_paise               BIGINT NOT NULL DEFAULT 0,
  igst_paise               BIGINT NOT NULL DEFAULT 0,
  line_total_paise         BIGINT NOT NULL DEFAULT 0,
  sort_order               INTEGER NOT NULL DEFAULT 0,
  service_catalogue_id     UUID
);

CREATE TABLE IF NOT EXISTS public.sales_debit_note_allocations (
  id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id                  UUID NOT NULL,
  debit_note_id            UUID NOT NULL REFERENCES sales_debit_notes(id) ON DELETE CASCADE,
  sales_invoice_id         UUID NOT NULL REFERENCES client_sales_invoices(id),
  allocated_paise          BIGINT NOT NULL,
  created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.client_sales_invoices
  ADD COLUMN IF NOT EXISTS debit_note_paise BIGINT NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_sales_debit_notes_active
  ON public.sales_debit_notes (firm_id, client_id) WHERE deleted_at IS NULL;


CREATE TABLE IF NOT EXISTS public.purchase_credit_notes (
  id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id                  UUID NOT NULL REFERENCES firms(id) ON DELETE CASCADE,
  client_id                UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  -- no FK, matching debit_notes.vendor_id exactly — resolved client-side via
  -- the vendor list (see the existing Debit Notes tab's own comment).
  vendor_id                UUID NOT NULL,
  purchase_bill_id         UUID REFERENCES purchase_bills(id),
  credit_note_no           TEXT,
  credit_note_date         DATE NOT NULL,
  reason                   TEXT,
  is_interstate            BOOLEAN NOT NULL DEFAULT false,
  is_reverse_charge        BOOLEAN NOT NULL DEFAULT false,
  taxable_amount_paise     BIGINT NOT NULL DEFAULT 0,
  cgst_paise               BIGINT NOT NULL DEFAULT 0,
  sgst_paise               BIGINT NOT NULL DEFAULT 0,
  igst_paise               BIGINT NOT NULL DEFAULT 0,
  total_paise              BIGINT NOT NULL DEFAULT 0,
  total_gst_paise          BIGINT NOT NULL DEFAULT 0,
  applied_paise            BIGINT NOT NULL DEFAULT 0,
  status                   TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','issued')),
  journal_entry_id         UUID,
  created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_by                UUID,
  deleted_at               TIMESTAMPTZ,
  UNIQUE (firm_id, credit_note_no)
);

CREATE TABLE IF NOT EXISTS public.purchase_credit_note_lines (
  id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  credit_note_id           UUID NOT NULL REFERENCES purchase_credit_notes(id) ON DELETE CASCADE,
  description              TEXT,
  hsn_sac                  TEXT,
  quantity                 NUMERIC(10,3),
  rate_paise               BIGINT,
  gst_rate_bps             INTEGER,
  taxable_amount_paise     BIGINT,
  cgst_paise               BIGINT,
  sgst_paise               BIGINT,
  igst_paise               BIGINT,
  line_total_paise         BIGINT,
  service_catalogue_id     UUID
);

CREATE TABLE IF NOT EXISTS public.purchase_credit_note_allocations (
  id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id                  UUID NOT NULL,
  credit_note_id           UUID NOT NULL REFERENCES purchase_credit_notes(id) ON DELETE CASCADE,
  purchase_bill_id         UUID NOT NULL REFERENCES purchase_bills(id),
  allocated_paise          BIGINT NOT NULL,
  created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.purchase_bills
  ADD COLUMN IF NOT EXISTS credit_note_paise BIGINT NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_purchase_credit_notes_active
  ON public.purchase_credit_notes (firm_id, client_id) WHERE deleted_at IS NULL;
