-- purchase_bills was created (migration 050) without an is_interstate column,
-- even though the API has always computed and tried to persist one — every
-- INSERT into purchase_bills has therefore failed at the PostgREST layer
-- ("Could not find the 'is_interstate' column ... in the schema cache"),
-- silently masked behind bulk_create_purchase_bills' generic per-row error
-- ("Unable to create this bill. Please try again."). No purchase bill has
-- ever been successfully created in this database as a result.
--
-- Mirrors the column already present on client_sales_invoices (050),
-- credit_notes (051) and debit_notes (145) — IGST vs CGST+SGST determination
-- per CGST Act Section 9 / IGST Act Section 5.
ALTER TABLE purchase_bills
  ADD COLUMN IF NOT EXISTS is_interstate BOOLEAN NOT NULL DEFAULT FALSE;
