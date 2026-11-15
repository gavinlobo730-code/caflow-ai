-- Rollback of migration 589: drop the trigger, its function, the index and the column. The column holds only links the CA made by
-- raising an invoice from an order; dropping it loses those links and nothing else (the invoices, their lines and their amounts stay).
-- Safe to run twice. The API before this migration neither reads nor writes the column.

DROP TRIGGER IF EXISTS trg_invoice_line_names_its_clients_order_line ON public.client_sales_invoice_lines;
DROP FUNCTION IF EXISTS public.assert_invoice_line_names_its_clients_order_line();
DROP INDEX IF EXISTS public.idx_client_sales_invoice_lines_order_line;
ALTER TABLE public.client_sales_invoice_lines DROP COLUMN IF EXISTS sales_order_line_id;
