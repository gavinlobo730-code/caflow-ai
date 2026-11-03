-- Rollback of migration 577: the invoice issue goes back to posting the entry and marking the invoice issued in two statements.
-- Roll the API change back first (it calls this function); against a database without it the issue route answers "unable to complete".
DROP FUNCTION IF EXISTS public.issue_sales_invoice_atomic(uuid, jsonb, jsonb, timestamptz);
