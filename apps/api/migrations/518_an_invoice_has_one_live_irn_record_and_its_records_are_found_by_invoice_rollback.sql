-- Rollback of migration 518: drops the three indexes. After this nothing stops a second live e-invoice record for one invoice
-- again, and the invoice drawer's per-invoice read is a scan of the client's records. For fidelity with the previous schema,
-- not for use.
DROP INDEX IF EXISTS public.idx_eway_bill_records_invoice;
DROP INDEX IF EXISTS public.idx_einvoice_records_invoice;
DROP INDEX IF EXISTS public.uq_einvoice_records_one_live_per_invoice;
