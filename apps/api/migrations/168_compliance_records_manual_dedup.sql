-- 168 — close the compliance_records "manual create" dedup gap found during the
-- compliance data-model consolidation (compliance_calendar/compliance_tasks
-- retirement). Migration 108's uq_compliance_records_obligation only protects
-- auto-generated rows (WHERE obligation_type IS NOT NULL) — the manual
-- POST /api/compliance-records endpoint never sets obligation_type, so it was
-- fully unprotected against duplicate (client, compliance_type, period_start)
-- rows, unlike the compliance_calendar table it replaces (which had a plain
-- UNIQUE(client_id, compliance_type, period_start)). This adds the mirror-image
-- partial index for that path; application-level dedup in
-- compliance_record_service.create_record() is the primary guard, this is the
-- DB-level backstop against a concurrent race, same pattern as migration 108.

CREATE UNIQUE INDEX IF NOT EXISTS uq_compliance_records_manual
    ON public.compliance_records (firm_id, client_id, compliance_type, period_start)
    WHERE obligation_type IS NULL AND deleted_at IS NULL;
