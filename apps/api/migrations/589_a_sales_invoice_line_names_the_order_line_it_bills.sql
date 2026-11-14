-- Migration 589: a sales invoice line names the sales-order line it bills (ledger POST-A-104).
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═════════════════════════════════════════════════════════════════
-- An order's open position derives what has been DELIVERED from delivery-challan lines, which name the order line they deliver. What has
-- been INVOICED was always shown as zero, and said so, because `client_sales_invoice_lines` carried no link back to an order line: the
-- only way to pair the two would have been to match descriptions and rates, which silently under-bills an order whose invoice line was
-- reworded. So an order never showed what was left to bill, and nothing refused billing a line twice.
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═════════════════════════════════════════════════════════════════
--  * `client_sales_invoice_lines.sales_order_line_id`: NULLABLE, no backfill, no default. Most invoices a practice raises are never
--    ordered, so an unlinked line is ordinary and not a finding; and every invoice already on the books predates the link, so filling it
--    in would be a guess dressed as a fact. ON DELETE RESTRICT, not SET NULL: an order line an invoice bills is not deleted from under
--    it, so the link cannot vanish without anyone deciding it should (the API refuses re-pricing such an order's lines in words first).
--  * An index on it, partial on the linked lines: the order's position reads the lines that name ITS order lines, so the read is the
--    size of the order and not of the client's invoices.
--  * `assert_invoice_line_names_its_clients_order_line()`, BEFORE INSERT OR UPDATE OF the column: the order line must belong to the
--    same firm AND the same client as the invoice the line is on. The line table carries neither, so the check reads both parents. A
--    line that names another client's order line is refused with SQLSTATE 23514 and one sentence; the API asks the same question first.
-- Nothing else changes: no existing row is touched, and an invoice that names no order line is written exactly as before. The draft
-- line replacement (`replace_draft_document_lines`, migration 560) inserts the union of the keys each line carries, so it carries this
-- column with no change.

BEGIN;

ALTER TABLE public.client_sales_invoice_lines
  ADD COLUMN IF NOT EXISTS sales_order_line_id UUID
    REFERENCES public.sales_order_lines(id) ON DELETE RESTRICT;

CREATE INDEX IF NOT EXISTS idx_client_sales_invoice_lines_order_line
  ON public.client_sales_invoice_lines (sales_order_line_id)
  WHERE sales_order_line_id IS NOT NULL;

CREATE OR REPLACE FUNCTION public.assert_invoice_line_names_its_clients_order_line()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $fn$
BEGIN
    IF NEW.sales_order_line_id IS NULL THEN
        RETURN NEW;
    END IF;
    IF NOT EXISTS (
        SELECT 1
          FROM public.sales_order_lines AS ol
          JOIN public.client_sales_invoices AS inv ON inv.id = NEW.sales_invoice_id
         WHERE ol.id = NEW.sales_order_line_id
           AND ol.firm_id = inv.firm_id
           AND ol.client_id = inv.client_id
    ) THEN
        RAISE EXCEPTION 'An invoice line can bill only an order line of the invoice''s own client.'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$fn$;

REVOKE ALL ON FUNCTION public.assert_invoice_line_names_its_clients_order_line() FROM PUBLIC, anon, authenticated;

DROP TRIGGER IF EXISTS trg_invoice_line_names_its_clients_order_line ON public.client_sales_invoice_lines;
CREATE TRIGGER trg_invoice_line_names_its_clients_order_line
    BEFORE INSERT OR UPDATE OF sales_order_line_id ON public.client_sales_invoice_lines
    FOR EACH ROW EXECUTE FUNCTION public.assert_invoice_line_names_its_clients_order_line();

COMMENT ON COLUMN public.client_sales_invoice_lines.sales_order_line_id IS
  'Which sales-order line this invoice line bills, where the invoice was raised from the order (POST-A-104, migration 589). NULLABLE '
  'with no backfill: most invoices are never ordered, and every invoice before this column predates the link. The order''s position '
  'counts it as invoiced once the invoice is issued; the trigger refuses an order line of another client.';

COMMIT;
