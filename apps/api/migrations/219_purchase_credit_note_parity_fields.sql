-- Purchase Credit Note feature parity with Purchase Bills (same fields
-- Debit Notes got in migration 218): document_url + notes on the header,
-- unit (UQC) per line.
ALTER TABLE purchase_credit_notes ADD COLUMN IF NOT EXISTS document_url text;
ALTER TABLE purchase_credit_notes ADD COLUMN IF NOT EXISTS notes text;
ALTER TABLE purchase_credit_note_lines ADD COLUMN IF NOT EXISTS unit text;
