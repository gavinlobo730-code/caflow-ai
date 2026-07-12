-- purchase_bills was also created (migration 050) without a notes column,
-- even though the API has always sent one on create AND treats it as an
-- editable soft field on update (_SOFT_BILL_UPDATE_FIELDS in
-- routers/purchase_bills.py). Same class of bug as migration 199
-- (is_interstate) — every INSERT still failed after 199 alone because this
-- second missing column was in the SAME payload dict. Verified by
-- systematically diffing every key the router sends against the live
-- schema (both columns), not just spot-checking.
--
-- Mirrors the column already present on client_sales_invoices (050).
ALTER TABLE purchase_bills
  ADD COLUMN IF NOT EXISTS notes TEXT;
