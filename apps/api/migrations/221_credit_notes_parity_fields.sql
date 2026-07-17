-- Sales Credit Note feature parity with Sales Invoices: notes on the header,
-- unit (UQC) per line. No document_url — the Sales Invoice baseline has no
-- attachment/upload feature at all, so sales-side notes don't get one
-- either (parity means matching the baseline, not exceeding it) — same
-- decision as migration 220 (Sales Debit Note).
ALTER TABLE credit_notes ADD COLUMN IF NOT EXISTS notes text;
ALTER TABLE credit_note_lines ADD COLUMN IF NOT EXISTS unit text;
