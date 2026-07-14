-- Purchase Bills had no delete path at all — the list only offered "Receive"
-- for drafts, with no way to remove a bad/duplicate draft. Sales Invoices
-- solved the equivalent problem with a soft-delete column (migration 100,
-- client_sales_invoices.deleted_at) restricted to draft-status rows only
-- (issued+ invoices are legal records with a posted journal and must never
-- be removed). Mirrors that here for purchase_bills.
ALTER TABLE public.purchase_bills ADD COLUMN IF NOT EXISTS deleted_at timestamptz;
