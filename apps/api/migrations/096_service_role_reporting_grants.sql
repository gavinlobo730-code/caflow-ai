-- Migration 096: grant service_role SELECT on reporting source tables
--
-- The reporting engine (domain/reporting/sources.py :: SupabaseLedgerSource.snapshot)
-- runs under the service_role key (USE_USER_JWT off) and reads these document
-- tables on EVERY Trial Balance, P&L and Balance Sheet call. service_role held
-- only REFERENCES/TRIGGER/TRUNCATE on them, so the first read (receipts) raised
-- SQLSTATE 42501 (permission denied) → unhandled → HTTP 500 on all three reports,
-- for every client and both bases.
--
-- SELECT-only: the reporting engine never writes to these tables. Firm/client
-- isolation is enforced in-query by the engine (sources.py filters firm_id +
-- client_id explicitly), not via RLS, which service_role bypasses by design.
-- This is the set that migration 095's service-role catch-up missed. Idempotent.

GRANT SELECT ON public.receipts            TO service_role;
GRANT SELECT ON public.receipt_allocations TO service_role;
GRANT SELECT ON public.credit_notes        TO service_role;
GRANT SELECT ON public.purchase_bills      TO service_role;
GRANT SELECT ON public.purchase_payments   TO service_role;
