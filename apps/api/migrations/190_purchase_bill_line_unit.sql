-- Migration 190 — Purchase bill line unit of measure (audit fix)
--
-- client_sales_invoice_lines, credit_note_lines and debit_note_lines all
-- share InvoiceLineIn's unit field (UQC — CGST Rule 46(h)), but
-- purchase_bill_lines never got the equivalent column at all. Found during
-- the post-completion inventory-module audit while wiring post-receipt
-- edits for purchase bills (CLAUDE.md: "audit it after completion and
-- complete anything missing").

ALTER TABLE public.purchase_bill_lines
    ADD COLUMN IF NOT EXISTS unit TEXT;

COMMENT ON COLUMN public.purchase_bill_lines.unit IS
    'Unit of measure (UQC) for this line, e.g. NOS, KGS — normalized (upper/trim) but never validated against the official UQC list, matching client_sales_invoice_lines.unit (pre-existing lines may carry free-text values).';
