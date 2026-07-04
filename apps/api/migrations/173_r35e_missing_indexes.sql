-- Migration 173: add missing indexes on the hot-path filter chains
-- identified in R3.5's performance re-scope. Additive/non-destructive.
--
-- government_notices and document_requests have ZERO indexes beyond the
-- implicit primary key (confirmed by grep: migrations 052/024 create the
-- tables with RLS policies only, no CREATE INDEX anywhere). Both are hit by
-- 5+ distinct routers/health.py queries per client-health computation, all
-- filtering .eq(firm_id).eq(client_id).eq/in(status) (+ a date range on
-- some) -- every one of those queries is a full sequential scan today.
--
-- tasks has only single-column indexes (firm_id, client_id, status,
-- due_date, assigned_to) -- no composite -- yet routers/analytics.py's
-- team_analytics/client_analytics/firm_analytics all filter
-- .eq(firm_id).eq(status,'completed').gte(updated_at,...).lte(updated_at,...).
--
-- compliance_records has only single-column indexes (firm_id, client_id,
-- status, due_date) -- no composite -- yet routers/health.py and
-- domain/compliance_record_service.py repeatedly filter
-- .eq(firm_id).eq(client_id)...lt(due_date,...) together.
--
-- Note: the R3.5 re-scope also flagged a "dead migration-055
-- bank_transactions index referencing a non-existent txn_date column" --
-- investigating found migration 094 already superseded it with correct
-- indexes on the real transaction_date/match_status/firm_id+client_id
-- columns (094's own header comment documents this explicitly). No action
-- needed there.

CREATE INDEX IF NOT EXISTS idx_government_notices_firm_client_status
    ON public.government_notices (firm_id, client_id, status);

CREATE INDEX IF NOT EXISTS idx_document_requests_firm_client_status_created
    ON public.document_requests (firm_id, client_id, status, created_at);

CREATE INDEX IF NOT EXISTS idx_tasks_firm_status_updated
    ON public.tasks (firm_id, status, updated_at)
    WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_compliance_records_firm_client_due
    ON public.compliance_records (firm_id, client_id, due_date)
    WHERE deleted_at IS NULL;
