-- 106 — Phase 4.2 Payment Reminders (additive).
--
-- (1) Unify delivery history: reminders reuse invoice_deliveries via a `kind`
--     discriminator (existing rows backfill to 'invoice' via the default).
-- (2) Per-firm reminder policy. Reminders are a COLLECTIONS / informational
--     feature — they create no journals and touch no statements/GST/cash flow.

ALTER TABLE public.invoice_deliveries
    ADD COLUMN IF NOT EXISTS kind text NOT NULL DEFAULT 'invoice'
        CHECK (kind IN ('invoice', 'reminder'));

CREATE TABLE IF NOT EXISTS public.reminder_settings (
    firm_id        UUID        PRIMARY KEY REFERENCES public.firms(id) ON DELETE CASCADE,
    enabled        BOOLEAN     NOT NULL DEFAULT true,
    interval_days  INTEGER     NOT NULL DEFAULT 7,
    max_reminders  INTEGER     NOT NULL DEFAULT 3,
    attach_pdf     BOOLEAN     NOT NULL DEFAULT true,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.reminder_settings ENABLE ROW LEVEL SECURITY;
CREATE POLICY firm_reminder_settings ON public.reminder_settings
    FOR ALL TO authenticated
    USING (firm_id = get_my_firm_id())
    WITH CHECK (firm_id = get_my_firm_id());
GRANT SELECT, INSERT, UPDATE ON public.reminder_settings TO authenticated;
GRANT ALL ON public.reminder_settings TO service_role;

CREATE INDEX IF NOT EXISTS idx_invoice_deliveries_kind
    ON public.invoice_deliveries (invoice_id, kind);

COMMENT ON COLUMN public.invoice_deliveries.kind IS
    'Phase 4.2: invoice = original document send; reminder = overdue payment reminder.';
