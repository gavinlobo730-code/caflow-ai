-- Migration 097: invoice_deliveries — per-send delivery tracking for sales invoices
--
-- One row per send/resend attempt. Multiple rows per invoice are allowed —
-- resend always creates a new record, preserving the full delivery audit trail.
-- Status lifecycle: queued → sending → sent / failed / bounced
-- provider_message_id carries the Resend API message ID (for future webhook
-- reconciliation). Firm isolation enforced by the standard firm_members RLS.
-- Authenticated users get SELECT/INSERT/UPDATE only — no DELETE (deliveries are
-- immutable evidence of every send attempt, whether successful or not).

CREATE TABLE IF NOT EXISTS public.invoice_deliveries (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id             UUID        NOT NULL,
    client_id           UUID        NOT NULL,
    invoice_id          UUID        NOT NULL
                            REFERENCES public.client_sales_invoices(id) ON DELETE CASCADE,
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

CREATE INDEX IF NOT EXISTS idx_invoice_deliveries_invoice
    ON public.invoice_deliveries (invoice_id);
CREATE INDEX IF NOT EXISTS idx_invoice_deliveries_firm
    ON public.invoice_deliveries (firm_id, created_at DESC);

ALTER TABLE public.invoice_deliveries ENABLE ROW LEVEL SECURITY;

-- RLS pattern: three-policy stack matching receipts and client_sales_invoices
-- (migration 084 assignment-scoped pattern).
CREATE POLICY firm_invoice_deliveries
    ON public.invoice_deliveries
    FOR ALL TO authenticated
    USING (firm_id = get_my_firm_id());

CREATE POLICY invoice_deliveries_assignment_scope
    ON public.invoice_deliveries
    AS RESTRICTIVE
    FOR ALL TO authenticated
    USING (can_access_client((client_id)::text));

CREATE POLICY invoice_deliveries_internal_partner_only
    ON public.invoice_deliveries
    AS RESTRICTIVE
    FOR ALL TO authenticated
    USING (
        (get_my_role() = 'Partner'::text)
        OR ((client_id)::text IS DISTINCT FROM (my_internal_client_id())::text)
    );

GRANT SELECT, INSERT, UPDATE ON public.invoice_deliveries TO authenticated;
GRANT ALL                     ON public.invoice_deliveries TO service_role;
