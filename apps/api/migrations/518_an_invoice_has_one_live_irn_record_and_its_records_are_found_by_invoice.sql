-- POST-A-263. An invoice has one IRN, and the records prepared for it are found by the invoice.
--
-- einvoice_records carried an index on (firm_id, client_id) and nothing on the invoice it names, and nothing refused a second
-- record for one invoice, so create_einvoice_record could prepare a second draft for an invoice that already had one: a draft
-- that is never recorded or cancelled and that the worklist then has to tell apart. The unique index below is the database's
-- half of "an invoice has one live IRN record" (the create route asks first, so it can name the record that is there, and
-- maps this index's violation to the same refusal for two requests at the same moment). A CANCELLED record does not count: an
-- IRN cancelled on the portal is prepared again, so an invoice may carry any number of cancelled records and one live one. A
-- record that names no invoice (an invoice raised outside the product) is unconstrained.
--
-- eway_bill_records gets no uniqueness on purpose: an invoice may legitimately carry several e-way bills (a second
-- consignment, a new vehicle).
--
-- Both list routes now accept sales_invoice_id, so each gets a plain index on it (a partial one, since most rows of the
-- e-way table and some of the other name no invoice). Production holds one e-invoice record, naming no invoice, and no e-way
-- bill, so the unique index cannot fail on existing data; IF NOT EXISTS keeps the migration safe to run twice.

CREATE UNIQUE INDEX IF NOT EXISTS uq_einvoice_records_one_live_per_invoice
    ON public.einvoice_records (sales_invoice_id)
    WHERE sales_invoice_id IS NOT NULL AND status <> 'cancelled';

CREATE INDEX IF NOT EXISTS idx_einvoice_records_invoice
    ON public.einvoice_records (sales_invoice_id)
    WHERE sales_invoice_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_eway_bill_records_invoice
    ON public.eway_bill_records (sales_invoice_id)
    WHERE sales_invoice_id IS NOT NULL;
