-- 340 — gstr2a_records holds what GSTR-2B actually says, and which bill it
-- matched (GST-04, PUR-11).
--
-- WHAT WAS WRONG
--     Nothing anywhere INSERTed into this table. `grep gstr2a_records` across
--     apps/api and apps/web found only reads, so `_gstr2a_for_period` always
--     returned [] and every GSTR-3B ever computed printed
--     `gstr2a_record_count: 0` in its Rule 36(4) working.
--
--     The reconciliation that was supposed to fill it ran in the BROWSER
--     (apps/web/app/gst/reconciliation/page.tsx), over a purchase register the
--     CA had to export from this product and upload back into it, and threw
--     the answer away on refresh. So the one purchase-side task an Indian
--     practice performs every single month — which of my client's bills has
--     the supplier not filed, and how much ITC must I hold back — could not be
--     done here, and could not be seen from the Purchases tab at all.
--
-- WHAT THIS ADDS, AND WHY EACH ONE IS NOT DECORATION
--
--   purchase_bill_id   The match. Without it there is nowhere to record that
--                      THIS 2B document is THIS bill, which is why the browser
--                      reconciliation could not persist even in principle.
--   match_status       'matched' | 'amount_mismatch' | 'missing_in_books' |
--                      'unmatched'. 'missing_in_books' is the supplier-filed-
--                      but-we-have-no-bill case, which is a DIFFERENT question
--                      from a bill with no 2B document and needs a different
--                      action (chase the document, not the supplier).
--   itc_available      GSTR-2B's own `itcavl` flag, and `itc_unavailable_
--   itc_unavailable_*  reason` its `rsn` code. §16(2)(aa) makes the credit
--                      depend on what 2B says, so a reconciliation that
--                      matches an invoice and drops this flag tells a CA the
--                      credit is safe when the portal has already said it is
--                      not. 'P' is place-of-supply, 'C' is a return filed
--                      after the §16(4) cut-off.
--   document_type      invoice / credit_note / debit_note / bill_of_entry. A
--   section            credit note REDUCES credit and an import has no
--                      supplier GSTIN at all — one row shape cannot mean the
--                      same thing for all four without saying which it is.
--   cess_paise         The fourth head. It was simply absent.
--   invoice_value_paise `inv.val` — the whole invoice including tax, which is
--                      what a CA reads off the portal screen and compares by
--                      eye. Kept because it is the figure they will quote.
--   supplier_trade_name / supplier_filed_on
--                      `trdnm` and `supfildt`. The filing date is what makes a
--                      supplier-wise defaulter list possible.
--   is_amendment / amends_document_number
--                      b2ba and cdnra are amendments reported in their own
--                      sections. Merging them needs the original's period,
--                      which this client may not have downloaded — so they are
--                      MARKED rather than merged.
--
-- ONE DOCUMENT PER (client, period, section, supplier, number), so a re-upload
-- of the same 2B REPLACES rather than duplicates. Uploading twice is what a CA
-- does when the first download was for the wrong month.
--
-- NOTHING IS BACKFILLED. The table is empty in every deployment — that is the
-- defect this closes.

ALTER TABLE public.gstr2a_records
  ADD COLUMN IF NOT EXISTS purchase_bill_id          UUID REFERENCES public.purchase_bills(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS match_status              TEXT NOT NULL DEFAULT 'unmatched',
  ADD COLUMN IF NOT EXISTS match_difference_paise    BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS itc_available             TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS itc_unavailable_reason_code TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS itc_unavailable_reason    TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS document_type             TEXT NOT NULL DEFAULT 'invoice',
  ADD COLUMN IF NOT EXISTS section                   TEXT NOT NULL DEFAULT 'b2b',
  ADD COLUMN IF NOT EXISTS cess_paise                BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS invoice_value_paise       BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS supplier_trade_name       TEXT,
  ADD COLUMN IF NOT EXISTS supplier_filed_on         DATE,
  ADD COLUMN IF NOT EXISTS is_amendment              BOOLEAN NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS amends_document_number    TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS reconciled_at             TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS updated_at                TIMESTAMPTZ NOT NULL DEFAULT now();

-- 'unmatched' is the honest default for a row that has not been through the
-- matcher; 'missing_in_books' is a CONCLUSION and must only be written by one.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'gstr2a_records_match_status_check') THEN
    ALTER TABLE public.gstr2a_records
      ADD CONSTRAINT gstr2a_records_match_status_check
      CHECK (match_status IN ('unmatched', 'matched', 'amount_mismatch', 'missing_in_books'));
  END IF;
END $$;

-- A re-upload replaces. Partial on deleted rows is unnecessary — this table has
-- no soft delete — but the index is deliberately on the natural key rather than
-- on id, because that is what the upsert conflicts on.
CREATE UNIQUE INDEX IF NOT EXISTS uq_gstr2a_records_document
  ON public.gstr2a_records (client_id, return_period, section, supplier_gstin, invoice_number);

-- The Purchases tab asks "what is the 2B status of THIS bill", and the
-- supplier-wise defaulter list asks "which suppliers have not filed".
CREATE INDEX IF NOT EXISTS idx_gstr2a_records_bill
  ON public.gstr2a_records (purchase_bill_id) WHERE purchase_bill_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_gstr2a_records_client_period
  ON public.gstr2a_records (client_id, return_period);

COMMENT ON COLUMN public.gstr2a_records.match_status IS
  'unmatched (not yet reconciled) | matched | amount_mismatch | '
  'missing_in_books (the supplier filed it and we hold no bill).';
COMMENT ON COLUMN public.gstr2a_records.itc_available IS
  'GSTR-2B''s own itcavl flag: Y, N, or empty where the section does not carry '
  'one (imports). §16(2)(aa) makes the credit depend on it.';
