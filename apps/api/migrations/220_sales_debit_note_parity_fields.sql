-- Sales Debit Note feature parity with Sales Invoices: notes on the header,
-- unit (UQC) per line. Unlike the Purchase-side notes (migrations 218/219),
-- no document_url — the Sales Invoice baseline has no attachment/upload
-- feature at all, so sales-side notes don't get one either (parity means
-- matching the baseline, not exceeding it).
ALTER TABLE sales_debit_notes ADD COLUMN IF NOT EXISTS notes text;
ALTER TABLE sales_debit_note_lines ADD COLUMN IF NOT EXISTS unit text;
