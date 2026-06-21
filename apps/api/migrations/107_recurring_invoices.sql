-- 107 — Phase 4.3 Recurring Invoices (additive).
--
-- Recurring invoice TEMPLATES generate DRAFT sales invoices through the EXISTING
-- invoice engine (routers.sales_invoices.create_invoice). There is NO journal,
-- GST, statement, or reminder logic here: a generated invoice is an ordinary
-- draft sales invoice and only becomes an accounting event when a CA issues it
-- (existing draft -> issue path). Reminders (4.2) and statements (4.1) flow from
-- the issued invoice with no extra wiring.
--
-- Kept deliberately SEPARATE from billing_schedules (the practice's own internal
-- fee billing). The two features may share helper code but remain distinct.

CREATE TABLE IF NOT EXISTS public.recurring_invoice_templates (
    id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id        UUID        NOT NULL REFERENCES public.firms(id)     ON DELETE CASCADE,
    client_id      UUID        NOT NULL REFERENCES public.clients(id)   ON DELETE CASCADE,
    customer_id    UUID        NOT NULL REFERENCES public.customers(id) ON DELETE CASCADE,
    title          TEXT        NOT NULL,
    description    TEXT,
    frequency      TEXT        NOT NULL CHECK (frequency IN ('weekly','monthly','quarterly','half_yearly','yearly')),
    start_date     DATE        NOT NULL,
    end_date       DATE,
    next_run_date  DATE        NOT NULL,
    notes          TEXT,
    is_inter_state BOOLEAN     NOT NULL DEFAULT false,
    -- Lifecycle: active (generates), paused (skipped), archived (soft-retired).
    -- Phase 4.3 NEVER auto-issues, auto-posts, or auto-emails (locked decisions).
    status         TEXT        NOT NULL DEFAULT 'active' CHECK (status IN ('active','paused','archived')),
    created_by     UUID,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.recurring_invoice_template_lines (
    id           UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    template_id  UUID    NOT NULL REFERENCES public.recurring_invoice_templates(id) ON DELETE CASCADE,
    description  TEXT    NOT NULL,
    hsn_sac      TEXT,
    quantity     NUMERIC NOT NULL DEFAULT 1,
    rate_paise   BIGINT  NOT NULL DEFAULT 0 CHECK (rate_paise >= 0),
    gst_rate_bps INTEGER NOT NULL DEFAULT 1800,        -- 1800 bps = 18% (GST math is the invoice engine's)
    is_service   BOOLEAN NOT NULL DEFAULT false,
    sort_order   INTEGER NOT NULL DEFAULT 0
);

-- Generation history: one row per (template, occurrence). Drives the History UI
-- and is the idempotency ledger for the run engine.
CREATE TABLE IF NOT EXISTS public.recurring_invoice_runs (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id         UUID        NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
    template_id     UUID        NOT NULL REFERENCES public.recurring_invoice_templates(id) ON DELETE CASCADE,
    occurrence_date DATE        NOT NULL,
    invoice_id      UUID        REFERENCES public.client_sales_invoices(id) ON DELETE SET NULL,
    status          TEXT        NOT NULL DEFAULT 'generated' CHECK (status IN ('generated','skipped','failed')),
    detail          JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (template_id, occurrence_date)
);

-- Traceability on the generated invoice. Reuses the existing `source` text column
-- (set to 'recurring'); adds the template + occurrence link.
ALTER TABLE public.client_sales_invoices
    ADD COLUMN IF NOT EXISTS recurring_template_id UUID
        REFERENCES public.recurring_invoice_templates(id) ON DELETE SET NULL;
ALTER TABLE public.client_sales_invoices
    ADD COLUMN IF NOT EXISTS recurring_occurrence DATE;

-- One invoice per (template, occurrence) — authoritative idempotency backstop.
CREATE UNIQUE INDEX IF NOT EXISTS uq_client_sales_invoices_recurring
    ON public.client_sales_invoices (recurring_template_id, recurring_occurrence)
    WHERE recurring_template_id IS NOT NULL;

-- ── RLS (defense in depth; firm-scoped, mirrors the sales tables) ────────────
ALTER TABLE public.recurring_invoice_templates      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.recurring_invoice_template_lines ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.recurring_invoice_runs           ENABLE ROW LEVEL SECURITY;

CREATE POLICY firm_recurring_templates ON public.recurring_invoice_templates
    FOR ALL TO authenticated
    USING (firm_id = get_my_firm_id())
    WITH CHECK (firm_id = get_my_firm_id());

CREATE POLICY firm_recurring_runs ON public.recurring_invoice_runs
    FOR ALL TO authenticated
    USING (firm_id = get_my_firm_id())
    WITH CHECK (firm_id = get_my_firm_id());

-- Lines are firm-scoped through their parent template.
CREATE POLICY firm_recurring_lines ON public.recurring_invoice_template_lines
    FOR ALL TO authenticated
    USING (EXISTS (SELECT 1 FROM public.recurring_invoice_templates t
                   WHERE t.id = template_id AND t.firm_id = get_my_firm_id()))
    WITH CHECK (EXISTS (SELECT 1 FROM public.recurring_invoice_templates t
                        WHERE t.id = template_id AND t.firm_id = get_my_firm_id()));

GRANT SELECT, INSERT, UPDATE, DELETE ON public.recurring_invoice_templates      TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.recurring_invoice_template_lines TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.recurring_invoice_runs           TO authenticated;
GRANT ALL ON public.recurring_invoice_templates      TO service_role;
GRANT ALL ON public.recurring_invoice_template_lines TO service_role;
GRANT ALL ON public.recurring_invoice_runs           TO service_role;

CREATE INDEX IF NOT EXISTS idx_recurring_templates_due
    ON public.recurring_invoice_templates (firm_id, status, next_run_date);
CREATE INDEX IF NOT EXISTS idx_recurring_lines_template
    ON public.recurring_invoice_template_lines (template_id, sort_order);
CREATE INDEX IF NOT EXISTS idx_recurring_runs_template
    ON public.recurring_invoice_runs (template_id, created_at DESC);

COMMENT ON TABLE public.recurring_invoice_templates IS
    'Phase 4.3: recurring invoice templates. Generate DRAFT sales invoices via the existing invoice engine; never auto-issue/post/email.';
