-- 108 — Phase 4.4 Compliance & Engagement Management (ADDITIVE ONLY).
--
-- Reuse-first: compliance_records is the canonical obligation entity (Decision 1),
-- compliance_records remain their own entity with OPTIONAL linked tasks (Decision 2),
-- and fee_engagements is EXTENDED in place (Decision 3). No new obligation/engagement
-- tables, no filing/GST/accounting schema changes, no destructive changes.
--
-- The two status CHECK constraints are widened to a SUPERSET of their current values
-- (so every existing row stays valid) — this is non-destructive.

-- ── Module A: engagement lifecycle + assignment chain on fee_engagements ──────
ALTER TABLE public.fee_engagements ADD COLUMN IF NOT EXISTS assigned_to UUID;
ALTER TABLE public.fee_engagements ADD COLUMN IF NOT EXISTS reviewer_id  UUID;
ALTER TABLE public.fee_engagements ADD COLUMN IF NOT EXISTS partner_id   UUID;
ALTER TABLE public.fee_engagements ADD COLUMN IF NOT EXISTS due_date     DATE;
-- notes already exists.

ALTER TABLE public.fee_engagements DROP CONSTRAINT IF EXISTS fee_engagements_status_check;
ALTER TABLE public.fee_engagements ADD CONSTRAINT fee_engagements_status_check
    CHECK (status IN ('Draft','Active','In Progress','Review','Completed','Closed','Inactive'));

-- ── Modules B–E: obligation linkage, assignment chain, lifecycle on compliance_records ──
ALTER TABLE public.compliance_records ADD COLUMN IF NOT EXISTS engagement_id UUID
    REFERENCES public.fee_engagements(id) ON DELETE SET NULL;
ALTER TABLE public.compliance_records ADD COLUMN IF NOT EXISTS obligation_type      TEXT;   -- granular: GSTR1/GSTR3B/GSTR9/TDS26Q/ITR/ADVANCE_TAX/MCA_AOC4/...
ALTER TABLE public.compliance_records ADD COLUMN IF NOT EXISTS preparer_id          UUID;
ALTER TABLE public.compliance_records ADD COLUMN IF NOT EXISTS reviewer_id          UUID;
ALTER TABLE public.compliance_records ADD COLUMN IF NOT EXISTS approver_id          UUID;
ALTER TABLE public.compliance_records ADD COLUMN IF NOT EXISTS assigned_at          TIMESTAMPTZ;
ALTER TABLE public.compliance_records ADD COLUMN IF NOT EXISTS reassigned_at        TIMESTAMPTZ;
ALTER TABLE public.compliance_records ADD COLUMN IF NOT EXISTS completed_at         TIMESTAMPTZ;
ALTER TABLE public.compliance_records ADD COLUMN IF NOT EXISTS last_escalated_tier  TEXT;
ALTER TABLE public.compliance_records ADD COLUMN IF NOT EXISTS last_escalated_on    DATE;

-- Add 'Completed' to the lifecycle (Filed -> Completed). Superset of the existing set.
ALTER TABLE public.compliance_records DROP CONSTRAINT IF EXISTS compliance_records_status_check;
ALTER TABLE public.compliance_records ADD CONSTRAINT compliance_records_status_check
    CHECK (status IN ('Not Started','Awaiting Documents','In Progress','Ready For Review',
                      'Ready To File','Filed','Completed','Overdue'));

-- Idempotent obligation generation: at most one obligation per
-- (firm, client, obligation_type, period_start). The partial index ignores
-- legacy rows that have no obligation_type and soft-deleted rows.
CREATE UNIQUE INDEX IF NOT EXISTS uq_compliance_records_obligation
    ON public.compliance_records (firm_id, client_id, obligation_type, period_start)
    WHERE obligation_type IS NOT NULL AND deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_compliance_records_engagement
    ON public.compliance_records (engagement_id);
CREATE INDEX IF NOT EXISTS idx_compliance_records_firm_due
    ON public.compliance_records (firm_id, status, due_date);

COMMENT ON COLUMN public.compliance_records.obligation_type IS
    'Phase 4.4: granular statutory obligation (GSTR1/GSTR3B/GSTR9/TDS26Q/ITR/ADVANCE_TAX/MCA_AOC4/MCA_MGT7/TAX_AUDIT). compliance_type stays high-level (GST/TDS/Income Tax/MCA).';
