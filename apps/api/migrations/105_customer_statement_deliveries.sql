-- 105 — Phase 4.1 Customer Statements: per-send delivery tracking (additive).
--
-- One row per statement email send/resend attempt (immutable audit trail).
-- Mirrors invoice_deliveries (migration 097): same status lifecycle, same
-- three-policy RLS stack (firm + assignment scope + internal-partner-only).
-- This is the ONLY schema change for Customer Statements; the statement itself
-- is computed read-only from existing invoices/receipts/credit notes.

CREATE TABLE IF NOT EXISTS public.customer_statement_deliveries (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id             UUID        NOT NULL,
    client_id           UUID        NOT NULL,
    customer_id         UUID        NOT NULL REFERENCES public.customers(id) ON DELETE CASCADE,
    period_start        DATE        NOT NULL,
    period_end          DATE        NOT NULL,
    sent_to             TEXT        NOT NULL,
    sent_by_id          UUID,
    sent_by_email       TEXT,
    status              TEXT        NOT NULL DEFAULT 'queued'
                            CHECK (status IN ('queued', 'sending', 'sent', 'failed', 'bounced')),
    provider_message_id TEXT,
    error_message       TEXT,
    sent_at             TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_cust_stmt_deliveries_customer
    ON public.customer_statement_deliveries (customer_id);
CREATE INDEX IF NOT EXISTS idx_cust_stmt_deliveries_firm
    ON public.customer_statement_deliveries (firm_id, created_at DESC);

ALTER TABLE public.customer_statement_deliveries ENABLE ROW LEVEL SECURITY;

CREATE POLICY firm_cust_stmt_deliveries
    ON public.customer_statement_deliveries
    FOR ALL TO authenticated
    USING (firm_id = get_my_firm_id());

CREATE POLICY cust_stmt_deliveries_assignment_scope
    ON public.customer_statement_deliveries
    AS RESTRICTIVE
    FOR ALL TO authenticated
    USING (can_access_client((client_id)::text));

CREATE POLICY cust_stmt_deliveries_internal_partner_only
    ON public.customer_statement_deliveries
    AS RESTRICTIVE
    FOR ALL TO authenticated
    USING (
        (get_my_role() = 'Partner'::text)
        OR ((client_id)::text IS DISTINCT FROM (my_internal_client_id())::text)
    );

GRANT SELECT, INSERT, UPDATE ON public.customer_statement_deliveries TO authenticated;
GRANT ALL                     ON public.customer_statement_deliveries TO service_role;
