-- Migration 184 — Sales invoice lines link back to the Product/Service
-- preset they were created from (Products & Services delete-guard)
--
-- Picking a preset via ServiceCataloguePicker copies its values (name,
-- HSN/SAC, rate) onto the line as free text — by design, so editing or
-- archiving a preset never changes a past invoice (migration 182's own
-- comment). But that also meant there was no way to tell whether a preset
-- had EVER actually been used on a real invoice, the way customer deletion
-- already checks real linked records (routers/customers.py's
-- _customer_dependencies) before allowing a hard delete. This adds that
-- missing link so the Product/Service DELETE endpoint can do the same kind
-- of real check instead of the use_count heuristic it used before.
--
-- Nullable and SET NULL on delete: the line's own description/hsn_sac/rate
-- stay intact regardless of what happens to this pointer — it is pure
-- traceability, never read by any GST/journal computation.
--
-- Scoped to sales invoice lines only: this is currently the ONLY place a CA
-- can pick a Product/Service on a line — ServiceCataloguePicker is not
-- wired into Purchase Bill / Credit Note / Debit Note lines, which stay
-- free-text only (those transaction types deal with a vendor's own
-- goods/services or a reversal of an existing line, not the client's own
-- sales catalogue).

ALTER TABLE public.client_sales_invoice_lines
    ADD COLUMN service_catalogue_id UUID REFERENCES public.service_catalogue(id) ON DELETE SET NULL;

CREATE INDEX idx_sales_invoice_lines_service_catalogue
    ON public.client_sales_invoice_lines (service_catalogue_id)
    WHERE service_catalogue_id IS NOT NULL;
