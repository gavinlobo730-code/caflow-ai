-- Migration 126: Firm Branding, Invoice Settings, Invoice Templates, Email Templates
--
-- Creates the schema for firm-branded document customization (QuickBooks/Xero parity).
-- Tables: firm_branding, invoice_settings, invoice_templates, email_templates.
-- RLS enabled with firm-isolation policies. Idempotent.

-- ── firm_branding ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.firm_branding (
    id                 UUID        NOT NULL DEFAULT uuid_generate_v4() PRIMARY KEY,
    firm_id            UUID        NOT NULL UNIQUE REFERENCES public.firms(id) ON DELETE CASCADE,
    logo_url           TEXT,
    secondary_logo_url TEXT,
    tagline            TEXT,
    primary_color      TEXT        NOT NULL DEFAULT '#2563EB',
    secondary_color    TEXT        NOT NULL DEFAULT '#1E40AF',
    accent_color       TEXT        NOT NULL DEFAULT '#3B82F6',
    font_family        TEXT        NOT NULL DEFAULT 'Inter',
    social_links       JSONB       NOT NULL DEFAULT '{}',
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.firm_branding IS
  'Per-firm branding: logo, colors, fonts. One row per firm. Mutated via /api/settings/branding.';

-- ── invoice_settings ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.invoice_settings (
    id                      UUID        NOT NULL DEFAULT uuid_generate_v4() PRIMARY KEY,
    firm_id                 UUID        NOT NULL UNIQUE REFERENCES public.firms(id) ON DELETE CASCADE,
    prefix                  TEXT        NOT NULL DEFAULT 'INV',
    include_financial_year  BOOLEAN     NOT NULL DEFAULT true,
    sequence_length         INTEGER     NOT NULL DEFAULT 3 CHECK (sequence_length BETWEEN 3 AND 6),
    starting_number         INTEGER     NOT NULL DEFAULT 1 CHECK (starting_number >= 1),
    manual_override_allowed BOOLEAN     NOT NULL DEFAULT false,
    bank_name               TEXT,
    account_number          TEXT,
    account_holder          TEXT,
    ifsc_code               TEXT,
    upi_id                  TEXT,
    upi_qr_url              TEXT,
    footer_text             TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.invoice_settings IS
  'Per-firm invoice numbering config and payment details.';

-- ── invoice_templates ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.invoice_templates (
    id                  UUID        NOT NULL DEFAULT uuid_generate_v4() PRIMARY KEY,
    firm_id             UUID        NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
    name                TEXT        NOT NULL,
    template_type       TEXT        NOT NULL DEFAULT 'classic'
                        CHECK (template_type IN ('classic', 'modern', 'professional_ca', 'corporate', 'minimal')),
    logo_position       TEXT        NOT NULL DEFAULT 'left'
                        CHECK (logo_position IN ('left', 'center', 'right')),
    header_style        TEXT        NOT NULL DEFAULT 'standard'
                        CHECK (header_style IN ('standard', 'compact', 'full')),
    footer_style        TEXT        NOT NULL DEFAULT 'standard'
                        CHECK (footer_style IN ('standard', 'minimal', 'detailed')),
    signature_placement TEXT        NOT NULL DEFAULT 'right'
                        CHECK (signature_placement IN ('left', 'center', 'right', 'none')),
    is_active           BOOLEAN     NOT NULL DEFAULT true,
    is_default          BOOLEAN     NOT NULL DEFAULT false,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.invoice_templates IS
  'Per-firm invoice layout templates. Only one may be default at a time.';

-- Enforce one default template per firm at the DB level
CREATE UNIQUE INDEX IF NOT EXISTS invoice_templates_firm_default_unique
    ON public.invoice_templates (firm_id) WHERE is_default = true;

-- ── email_templates ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.email_templates (
    id            UUID        NOT NULL DEFAULT uuid_generate_v4() PRIMARY KEY,
    firm_id       UUID        NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
    template_type TEXT        NOT NULL
                  CHECK (template_type IN ('invoice', 'engagement', 'document_request', 'reminder')),
    subject       TEXT        NOT NULL,
    body          TEXT        NOT NULL,
    is_active     BOOLEAN     NOT NULL DEFAULT true,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.email_templates IS
  'Per-firm email templates with merge-field support ({{firm_name}}, {{client_name}}, etc.).';

-- One active template per type per firm
CREATE UNIQUE INDEX IF NOT EXISTS email_templates_firm_type_unique
    ON public.email_templates (firm_id, template_type) WHERE is_active = true;

-- ── updated_at triggers ──────────────────────────────────────────────────────
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_firm_branding_updated_at') THEN
    CREATE TRIGGER trg_firm_branding_updated_at
      BEFORE UPDATE ON public.firm_branding
      FOR EACH ROW EXECUTE FUNCTION set_updated_at();
  END IF;
END$$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_invoice_settings_updated_at') THEN
    CREATE TRIGGER trg_invoice_settings_updated_at
      BEFORE UPDATE ON public.invoice_settings
      FOR EACH ROW EXECUTE FUNCTION set_updated_at();
  END IF;
END$$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_invoice_templates_updated_at') THEN
    CREATE TRIGGER trg_invoice_templates_updated_at
      BEFORE UPDATE ON public.invoice_templates
      FOR EACH ROW EXECUTE FUNCTION set_updated_at();
  END IF;
END$$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_email_templates_updated_at') THEN
    CREATE TRIGGER trg_email_templates_updated_at
      BEFORE UPDATE ON public.email_templates
      FOR EACH ROW EXECUTE FUNCTION set_updated_at();
  END IF;
END$$;

-- ── RLS ──────────────────────────────────────────────────────────────────────
ALTER TABLE public.firm_branding ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.invoice_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.invoice_templates ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.email_templates ENABLE ROW LEVEL SECURITY;

-- firm_branding: authenticated users see only their firm; service_role sees all
CREATE POLICY firm_branding_firm_isolation ON public.firm_branding
    FOR ALL TO authenticated
    USING (firm_id = public.get_my_firm_id());
CREATE POLICY firm_branding_service_all ON public.firm_branding
    AS PERMISSIVE FOR ALL TO service_role USING (true);

-- invoice_settings
CREATE POLICY invoice_settings_firm_isolation ON public.invoice_settings
    FOR ALL TO authenticated
    USING (firm_id = public.get_my_firm_id());
CREATE POLICY invoice_settings_service_all ON public.invoice_settings
    AS PERMISSIVE FOR ALL TO service_role USING (true);

-- invoice_templates
CREATE POLICY invoice_templates_firm_isolation ON public.invoice_templates
    FOR ALL TO authenticated
    USING (firm_id = public.get_my_firm_id());
CREATE POLICY invoice_templates_service_all ON public.invoice_templates
    AS PERMISSIVE FOR ALL TO service_role USING (true);

-- email_templates
CREATE POLICY email_templates_firm_isolation ON public.email_templates
    FOR ALL TO authenticated
    USING (firm_id = public.get_my_firm_id());
CREATE POLICY email_templates_service_all ON public.email_templates
    AS PERMISSIVE FOR ALL TO service_role USING (true);

-- ── GRANTs ───────────────────────────────────────────────────────────────────
GRANT ALL ON public.firm_branding TO authenticated, service_role;
GRANT ALL ON public.invoice_settings TO authenticated, service_role;
GRANT ALL ON public.invoice_templates TO authenticated, service_role;
GRANT ALL ON public.email_templates TO authenticated, service_role;
