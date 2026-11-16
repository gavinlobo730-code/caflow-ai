-- Rollback of migration 650: the database stops holding what issued invoices bill against an order line (the API's check stays).
BEGIN;
DROP TRIGGER IF EXISTS trg_invoice_that_starts_to_bill_is_within_its_orders ON public.client_sales_invoices;
DROP TRIGGER IF EXISTS trg_invoice_lines_inserted_bill_within_their_orders ON public.client_sales_invoice_lines;
DROP TRIGGER IF EXISTS trg_invoice_lines_updated_bill_within_their_orders ON public.client_sales_invoice_lines;
DROP TRIGGER IF EXISTS trg_order_line_reduced_stays_above_what_is_billed ON public.sales_order_lines;
DROP FUNCTION IF EXISTS public.invoice_that_starts_to_bill_is_within_its_orders();
DROP FUNCTION IF EXISTS public.invoice_lines_that_bill_are_within_their_orders();
DROP FUNCTION IF EXISTS public.order_line_reduced_stays_above_what_is_billed();
DROP FUNCTION IF EXISTS public.order_lines_billed_beyond_what_was_ordered(uuid[]);
COMMIT;
