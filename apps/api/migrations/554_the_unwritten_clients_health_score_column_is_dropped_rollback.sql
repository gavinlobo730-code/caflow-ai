-- Rollback of migration 554: puts `clients.health_score` back as migration 003 declared it (INTEGER DEFAULT 100, CHECK 0..100) and
-- recreates `clients_external` with the column in its original place in the list. Every client comes back at 100, which is what every
-- client held when the column was dropped (read from production on 28-10-2026). For fidelity with the previous schema, not for use: the
-- column is the one that reads "healthy" for a client nobody has scored.
DROP VIEW IF EXISTS public.clients_external;

ALTER TABLE public.clients ADD COLUMN IF NOT EXISTS health_score INTEGER DEFAULT 100
    CHECK (health_score BETWEEN 0 AND 100);

CREATE VIEW public.clients_external
WITH (security_invoker = true) AS
  SELECT id, client_name, entity_type, pan, gstin, mobile, email, address_line1, address_line2, city, state, pincode, state_code,
         financial_year_start, financial_year_end, gst_registration_date, gst_filing_frequency, assigned_to, status, notes,
         created_at, updated_at, deleted_at, firm_id, legal_name, trade_name, constitution, assigned_manager, assigned_executive,
         onboarding_status, health_score, phone, portal_enabled, portal_user_id, portal_invited_at, credit_limit_paise,
         payment_terms_days, is_internal
    FROM public.clients
   WHERE is_internal = false;

REVOKE ALL ON public.clients_external FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT ON public.clients_external TO anon, authenticated, service_role;

COMMENT ON VIEW public.clients_external IS
  'Amd v1.1 Guardrail G2: the single predicate (is_internal=false) feeding client counts, Clients list, Health triage, lifecycle dashboards, and client-facing Deadlines.';
