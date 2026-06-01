-- Migration 012: Fix missing tables and views
-- Bridges naming mismatches between frontend queries and actual DB tables

-- ─── 1. journal_entry_lines view over journal_lines ───────────────────────────
-- Frontend queries journal_entry_lines with columns: account_id, debit_paise, credit_paise
-- and joins journal_entries for: firm_id, entry_date, status
-- Real table is journal_lines; journal_entries uses is_posted not status

-- Add status column to journal_entries (derived from is_posted)
ALTER TABLE journal_entries
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft', 'posted', 'void'));

-- Sync status with existing is_posted values
UPDATE journal_entries SET status = 'posted' WHERE is_posted = TRUE AND status = 'draft';

-- Create journal_entry_lines as a view over journal_lines
CREATE OR REPLACE VIEW public.journal_entry_lines AS
SELECT
    jl.id,
    jl.journal_entry_id,
    jl.account_id,
    jl.debit_paise,
    jl.credit_paise,
    jl.narration,
    jl.created_at
FROM public.journal_lines jl;

GRANT SELECT, INSERT, UPDATE, DELETE ON public.journal_entry_lines TO authenticated;

-- ─── 2. compliance_entries view over compliance_calendar ─────────────────────
-- Frontend queries: id, client_id, firm_id, category, form_type, period, due_date, status, filed_date
-- Real table compliance_calendar has: compliance_type, filing_status, period_start, period_end

CREATE OR REPLACE VIEW public.compliance_entries AS
SELECT
    id,
    firm_id,
    client_id,
    -- Map compliance_type to category + form_type
    CASE
        WHEN compliance_type IN ('GSTR1', 'GSTR3B', 'GSTR9') THEN 'GST'
        WHEN compliance_type IN ('ITR', 'ADVANCE_TAX') THEN 'Income Tax'
        WHEN compliance_type IN ('TDS24Q', 'TDS26Q') THEN 'TDS'
        WHEN compliance_type IN ('MCA_AOC4', 'MCA_MGT7') THEN 'MCA'
        ELSE 'Other'
    END AS category,
    CASE
        WHEN compliance_type = 'GSTR1' THEN 'GSTR-1'
        WHEN compliance_type = 'GSTR3B' THEN 'GSTR-3B'
        WHEN compliance_type = 'GSTR9' THEN 'GSTR-9'
        WHEN compliance_type = 'ITR' THEN 'ITR'
        WHEN compliance_type = 'ADVANCE_TAX' THEN 'Advance Tax'
        WHEN compliance_type = 'TDS24Q' THEN '24Q'
        WHEN compliance_type = 'TDS26Q' THEN '26Q'
        WHEN compliance_type = 'MCA_AOC4' THEN 'AOC-4'
        WHEN compliance_type = 'MCA_MGT7' THEN 'MGT-7'
        ELSE compliance_type
    END AS form_type,
    compliance_type,
    -- Period as text (e.g. "May 2026")
    TO_CHAR(period_start, 'Mon YYYY') AS period,
    period_start,
    period_end,
    due_date,
    -- Map filing_status to simple status
    CASE
        WHEN filing_status = 'filed' THEN 'filed'
        WHEN filing_status = 'overdue' THEN 'overdue'
        WHEN filing_status IN ('pending', 'in_progress') THEN
            CASE WHEN due_date < CURRENT_DATE THEN 'overdue' ELSE 'pending' END
        ELSE filing_status
    END AS status,
    filing_status,
    filed_date,
    arn_number,
    created_at
FROM public.compliance_calendar;

GRANT SELECT ON public.compliance_entries TO authenticated;

-- Allow inserts into compliance_calendar via compliance_entries (use an INSERT rule)
-- Frontend inserts into compliance_entries, so we redirect to compliance_calendar
CREATE OR REPLACE RULE compliance_entries_insert AS
ON INSERT TO public.compliance_entries DO INSTEAD
INSERT INTO public.compliance_calendar (
    firm_id, client_id, compliance_type, period_start, period_end,
    due_date, filing_status, filed_date
)
VALUES (
    NEW.firm_id,
    NEW.client_id,
    COALESCE(NEW.compliance_type,
        CASE NEW.form_type
            WHEN 'GSTR-1' THEN 'GSTR1'
            WHEN 'GSTR-3B' THEN 'GSTR3B'
            WHEN 'GSTR-9' THEN 'GSTR9'
            WHEN 'ITR' THEN 'ITR'
            WHEN 'Advance Tax' THEN 'ADVANCE_TAX'
            WHEN '24Q' THEN 'TDS24Q'
            WHEN '26Q' THEN 'TDS26Q'
            WHEN 'AOC-4' THEN 'MCA_AOC4'
            WHEN 'MGT-7' THEN 'MCA_MGT7'
            ELSE 'ITR'
        END
    ),
    COALESCE(NEW.period_start, CURRENT_DATE - INTERVAL '1 month'),
    COALESCE(NEW.period_end, CURRENT_DATE),
    NEW.due_date,
    COALESCE(NEW.filing_status, NEW.status, 'pending'),
    NEW.filed_date
);

-- Allow updates (mark as filed)
CREATE OR REPLACE RULE compliance_entries_update AS
ON UPDATE TO public.compliance_entries DO INSTEAD
UPDATE public.compliance_calendar
SET
    filing_status = COALESCE(NEW.filing_status, NEW.status, filing_status),
    filed_date = COALESCE(NEW.filed_date, filed_date)
WHERE id = OLD.id;

-- ─── 3. mca_filings table ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.mca_filings (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    firm_id     UUID NOT NULL REFERENCES firms(id),
    client_id   UUID REFERENCES clients(id),
    client_name TEXT,
    cin         TEXT,
    form_type   TEXT NOT NULL,
    due_date    DATE NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'filed', 'overdue')),
    filed_date  DATE,
    notes       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.mca_filings ENABLE ROW LEVEL SECURITY;

CREATE POLICY "mca_filings_own_firm" ON public.mca_filings
    FOR ALL USING (firm_id = get_my_firm_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON public.mca_filings TO authenticated;

-- ─── 4. Grant permissions on journal_lines (may be missing) ──────────────────
GRANT SELECT, INSERT, UPDATE, DELETE ON public.journal_lines TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.journal_entries TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.compliance_calendar TO authenticated;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO authenticated;
