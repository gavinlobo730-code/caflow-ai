-- 110 — Phase 4.6 Online Payments (ADDITIVE ONLY).
--
-- Online payments NEVER create accounting. A gateway payment is recorded here;
-- on a VERIFIED capture the existing receipt engine (services.receipt_service.
-- create_receipt_core) creates the receipt + allocation + journal + AR update.
-- AR remains invoices + receipts + allocations ONLY. Nothing is added to
-- client_sales_invoices; the link back to AR is customer_payments.receipt_id.
--
-- Three tables + a superset CHECK on invoice_deliveries.kind (to reuse the
-- existing delivery-tracking table for payment-link emails). No destructive
-- change, no backfill.

-- ── Payment links (one hosted link for an invoice's outstanding amount) ───────
CREATE TABLE IF NOT EXISTS public.customer_payment_links (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id           UUID NOT NULL,
    client_id         UUID NOT NULL,
    customer_id       UUID NOT NULL,
    invoice_id        UUID NOT NULL REFERENCES public.client_sales_invoices(id) ON DELETE CASCADE,
    amount_paise      BIGINT NOT NULL CHECK (amount_paise > 0),   -- integer paise; never float
    currency          TEXT NOT NULL DEFAULT 'INR',
    provider          TEXT NOT NULL,
    provider_link_id  TEXT,
    provider_order_id TEXT,
    short_url         TEXT,
    status            TEXT NOT NULL DEFAULT 'created'
                          CHECK (status IN ('created','active','paid','expired','cancelled')),
    expires_at        TIMESTAMPTZ,
    created_by        UUID,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_customer_payment_links_invoice ON public.customer_payment_links (invoice_id);
CREATE INDEX IF NOT EXISTS idx_customer_payment_links_firm    ON public.customer_payment_links (firm_id, created_at DESC);

-- ── Payments (one row per gateway payment attempt; receipt_id seals settlement) ─
CREATE TABLE IF NOT EXISTS public.customer_payments (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id             UUID NOT NULL,
    client_id           UUID NOT NULL,
    customer_id         UUID NOT NULL,
    invoice_id          UUID NOT NULL REFERENCES public.client_sales_invoices(id) ON DELETE CASCADE,
    payment_link_id     UUID REFERENCES public.customer_payment_links(id) ON DELETE SET NULL,
    amount_paise        BIGINT NOT NULL CHECK (amount_paise > 0),  -- integer paise; never float
    currency            TEXT NOT NULL DEFAULT 'INR',
    status              TEXT NOT NULL DEFAULT 'created'
                            CHECK (status IN ('created','authorized','captured','failed','refunded')),
    provider            TEXT NOT NULL,
    provider_payment_id TEXT,
    provider_order_id   TEXT,
    receipt_id          UUID REFERENCES public.receipts(id) ON DELETE SET NULL,  -- settlement seal (idempotency)
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_customer_payments_invoice ON public.customer_payments (invoice_id);
CREATE INDEX IF NOT EXISTS idx_customer_payments_firm    ON public.customer_payments (firm_id, created_at DESC);
-- One payment row per gateway payment id → a redelivered/duplicate capture maps
-- to the SAME row (which already carries receipt_id) → no duplicate receipt.
CREATE UNIQUE INDEX IF NOT EXISTS uq_customer_payments_provider_payment
    ON public.customer_payments (provider, provider_payment_id)
    WHERE provider_payment_id IS NOT NULL;

-- ── Webhook/event log (signature + replay protection) ─────────────────────────
CREATE TABLE IF NOT EXISTS public.customer_payment_events (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id            UUID,
    payment_id         UUID REFERENCES public.customer_payments(id) ON DELETE CASCADE,
    provider           TEXT NOT NULL,
    provider_event_id  TEXT,
    event_type         TEXT,
    status             TEXT,
    signature_verified BOOLEAN NOT NULL DEFAULT false,
    raw_payload        JSONB,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_customer_payment_events_payment ON public.customer_payment_events (payment_id);
-- Replay protection: the same provider event can be ingested at most once.
CREATE UNIQUE INDEX IF NOT EXISTS uq_customer_payment_events_provider_event
    ON public.customer_payment_events (provider, provider_event_id)
    WHERE provider_event_id IS NOT NULL;

-- ── RLS (firm isolation + AR-adjacent assignment/internal scoping) ────────────
ALTER TABLE public.customer_payment_links  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.customer_payments       ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.customer_payment_events ENABLE ROW LEVEL SECURITY;

-- Mirrors the invoice_deliveries / receipts 3-policy stack for the client-scoped
-- tables (firm + assignment scope + internal-partner-only).
CREATE POLICY firm_customer_payment_links ON public.customer_payment_links
    FOR ALL TO authenticated USING (firm_id = get_my_firm_id());
CREATE POLICY customer_payment_links_assignment_scope ON public.customer_payment_links
    AS RESTRICTIVE FOR ALL TO authenticated USING (can_access_client((client_id)::text));
CREATE POLICY customer_payment_links_internal_partner_only ON public.customer_payment_links
    AS RESTRICTIVE FOR ALL TO authenticated
    USING ((get_my_role() = 'Partner'::text)
           OR ((client_id)::text IS DISTINCT FROM (my_internal_client_id())::text));

CREATE POLICY firm_customer_payments ON public.customer_payments
    FOR ALL TO authenticated USING (firm_id = get_my_firm_id());
CREATE POLICY customer_payments_assignment_scope ON public.customer_payments
    AS RESTRICTIVE FOR ALL TO authenticated USING (can_access_client((client_id)::text));
CREATE POLICY customer_payments_internal_partner_only ON public.customer_payments
    AS RESTRICTIVE FOR ALL TO authenticated
    USING ((get_my_role() = 'Partner'::text)
           OR ((client_id)::text IS DISTINCT FROM (my_internal_client_id())::text));

-- Event log is an internal webhook trail (no client_id surface) → firm-scoped only.
CREATE POLICY firm_customer_payment_events ON public.customer_payment_events
    FOR ALL TO authenticated USING (firm_id = get_my_firm_id());

GRANT SELECT, INSERT, UPDATE ON public.customer_payment_links  TO authenticated;
GRANT SELECT, INSERT, UPDATE ON public.customer_payments       TO authenticated;
GRANT SELECT, INSERT, UPDATE ON public.customer_payment_events TO authenticated;
GRANT ALL ON public.customer_payment_links  TO service_role;
GRANT ALL ON public.customer_payments       TO service_role;
GRANT ALL ON public.customer_payment_events TO service_role;

-- ── Reuse invoice_deliveries for payment-link emails (superset CHECK) ─────────
ALTER TABLE public.invoice_deliveries DROP CONSTRAINT IF EXISTS invoice_deliveries_kind_check;
ALTER TABLE public.invoice_deliveries
    ADD CONSTRAINT invoice_deliveries_kind_check
    CHECK (kind IN ('invoice', 'reminder', 'payment_link'));

COMMENT ON TABLE public.customer_payments IS
    'Phase 4.6: gateway payments. Accounting happens only via the receipt engine on a verified capture; receipt_id is the settlement seal that also prevents duplicate receipts.';
