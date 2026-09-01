-- Migration 306: let the backend's own role WRITE the five money documents.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT IS BROKEN
-- ═══════════════════════════════════════════════════════════════════════════
-- service_role holds SELECT — and no INSERT, UPDATE or DELETE — on receipts,
-- receipt_allocations, credit_notes, purchase_bills and purchase_payments.
-- Every other table in the schema has the write grants.
--
-- The backend writes all five. routers/purchase_bills.py, routers/receipts.py
-- and routers/purchase_payments.py each call core.supabase_client.get_supabase(),
-- which returns the SERVICE-ROLE client unless USE_USER_JWT is on AND a caller
-- token is present for the request. So with the flag off — the code default —
-- creating a bill, a receipt or a vendor payment fails with SQLSTATE 42501
-- before RLS is ever consulted, and reaches the CA as "Unable to create
-- purchase bill. Please try again."
--
-- Found by driving one client through a full financial year over the real API:
-- all 24 purchase bills failed, and one GRANT made all 24 post. The audit is
-- docs/audits/2026-09-01-can-a-ca-run-a-client-for-a-full-year.md.
--
-- The permission set is also internally incoherent, which is the shortest proof
-- that it is an accident rather than a policy. Checked on production:
--
--     purchase_bill_lines   service_role INSERT = true
--     purchase_bills        service_role INSERT = FALSE
--     credit_note_lines     service_role INSERT = true
--     credit_notes          service_role INSERT = FALSE
--
-- A document cannot be half-written. The lines are writable and their headers
-- are not.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHY MIGRATION 269 NARROWED THEM, AND WHY THAT PREMISE WAS WRONG
-- ═══════════════════════════════════════════════════════════════════════════
-- 096 granted these five SELECT because the reporting engine reads them on
-- every Trial Balance, P&L and Balance Sheet call and was raising 42501. Its
-- reasoning — "SELECT-only: the reporting engine never writes to these tables"
-- — is true of the REPORTING engine. 269 then granted the whole schema to
-- service_role and deliberately kept these five in a read_only array, carrying
-- 096's sentence forward as a least-privilege decision, and
-- tests/test_r269_service_role_grants_pg.py pinned it.
--
-- What neither noticed is that the reporting engine is not the only thing
-- running as service_role. The document-creation endpoints are too, and they
-- write exactly these tables. Least privilege aimed at the wrong threat model:
-- it asked what the reporting engine needs, not what the role needs.
--
-- This is the THIRD time the same shape has been patched. 050 created these
-- tables granting only `authenticated`. 096 fixed the reads. 193 hit it again
-- on debit_notes and its header describes the failure mode exactly — the base
-- GRANT was never issued, so access is "rejected by Postgres before RLS was
-- even evaluated" — and granted to `authenticated` only. Each fix was as narrow
-- as the symptom that prompted it. This one closes the write side and the test
-- alongside it stops asserting the shape, not the five names, so a fourth
-- occurrence fails in CI instead of in production.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT THIS DOES NOT WEAKEN
-- ═══════════════════════════════════════════════════════════════════════════
-- service_role BYPASSES RLS already, on every table, by design — it is the
-- role the backend runs as. CLAUDE.md states the consequence plainly: the
-- app-layer .eq("firm_id", ...) filter is the primary isolation control, with
-- firm-scoped RLS as defence in depth. Granting DML here makes these five
-- match every other table in the schema; it does not open a path that
-- service_role could not already take on client_sales_invoices, debit_notes or
-- journal_entries.
--
-- The narrowing also bought nothing in practice: an attacker holding the
-- service key can already read every row of these tables and write every other
-- table, including the general ledger.
--
-- Idempotent, additive, and safe to re-run.

BEGIN;

GRANT SELECT, INSERT, UPDATE, DELETE ON public.receipts             TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.receipt_allocations  TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.credit_notes         TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.purchase_bills       TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.purchase_payments    TO service_role;

-- Sequences, so an INSERT on a serial-keyed row can actually allocate. 269
-- granted these schema-wide; repeated here so this migration stands alone if it
-- is ever applied to a database that predates it.
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO service_role;

COMMIT;
