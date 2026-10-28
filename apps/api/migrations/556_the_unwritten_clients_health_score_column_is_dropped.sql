-- Migration 556: drop `clients.health_score`, the column nothing writes and nothing reads (ledger POST-A-283).
--
-- Migration 003 gave `clients` a `health_score INTEGER DEFAULT 100 CHECK (health_score BETWEEN 0 AND 100)`. Nothing has ever written it, so
-- every client carries its default of 100, and a roll-up that read it called every client healthy. The dashboard, the assistant, the memory
-- profile and the compliance roll-up read the health engine's STORED score instead (`domain/health/client_scores`), which answers "not yet
-- scored" for a client with none. The column is a trap: a new reader who selects it gets a confident, wrong 100. Read from production on
-- 28-10-2026: 10 clients, all 100; no function body mentions it; no index or policy uses it; ONE view does.
--
-- THE VIEW. `public.clients_external` (migration 073, Guardrail G2, `WHERE is_internal = false`) was created as `SELECT *`, which Postgres
-- expands to a column list at creation, so production's copy names `health_score` and the column cannot be dropped while it does. Nothing in
-- the product reads the view (`tests/test_the_revenue_ops_design_record_names_what_exists.py::test_nothing_reads_the_clients_external_view`),
-- but it is the single predicate the design record names, so it is recreated and not dropped: the same predicate, `security_invoker` so the
-- caller's row security on `clients` still applies through it, the same explicit column list MINUS `health_score`, SELECT for the three roles
-- that held it. Its grants are restated because a dropped view loses them.
--
-- WHAT THIS DOES NOT DO. It does not touch `public.health_scores` (the engine's table) or any other table's `health_score` column.
--
-- One transaction (the runner applies each file in one). Locks `clients` for the length of the ALTER, which on ten rows is nothing.
-- Reversible: 554_..._rollback.sql adds the column back at its default and recreates the view as it was. Idempotent.

DROP VIEW IF EXISTS public.clients_external;

ALTER TABLE public.clients DROP COLUMN IF EXISTS health_score;   -- its CHECK constraint goes with it

CREATE VIEW public.clients_external
WITH (security_invoker = true) AS
  SELECT id, client_name, entity_type, pan, gstin, mobile, email, address_line1, address_line2, city, state, pincode, state_code,
         financial_year_start, financial_year_end, gst_registration_date, gst_filing_frequency, assigned_to, status, notes,
         created_at, updated_at, deleted_at, firm_id, legal_name, trade_name, constitution, assigned_manager, assigned_executive,
         onboarding_status, phone, portal_enabled, portal_user_id, portal_invited_at, credit_limit_paise, payment_terms_days,
         is_internal
    FROM public.clients
   WHERE is_internal = false;

REVOKE ALL ON public.clients_external FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT ON public.clients_external TO anon, authenticated, service_role;

COMMENT ON VIEW public.clients_external IS
  'Amd v1.1 Guardrail G2: the single predicate (is_internal=false) feeding client counts, Clients list, Health triage, lifecycle dashboards, and client-facing Deadlines.';

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'clients' AND column_name = 'health_score') THEN
        RAISE EXCEPTION 'migration 556: clients.health_score is still there';
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'clients_external' AND column_name = 'health_score') THEN
        RAISE EXCEPTION 'migration 556: clients_external still names health_score';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_class c WHERE c.oid = 'public.clients_external'::regclass
                      AND 'security_invoker=true' = ANY (c.reloptions)) THEN
        RAISE EXCEPTION 'migration 556: clients_external is not security_invoker, so the caller''s row security would not apply through it';
    END IF;
    IF NOT (has_table_privilege('anon', 'public.clients_external', 'SELECT')
            AND has_table_privilege('authenticated', 'public.clients_external', 'SELECT')
            AND has_table_privilege('service_role', 'public.clients_external', 'SELECT')) THEN
        RAISE EXCEPTION 'migration 556: clients_external lost its SELECT grants';
    END IF;
    IF has_table_privilege('authenticated', 'public.clients_external', 'INSERT')
       OR has_table_privilege('authenticated', 'public.clients_external', 'UPDATE')
       OR has_table_privilege('authenticated', 'public.clients_external', 'DELETE') THEN
        RAISE EXCEPTION 'migration 556: clients_external can be written through';
    END IF;
END $$;
