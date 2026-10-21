-- Rollback of migration 531: drops the six policies, which puts the three tables back to the firm-wide read the firm policy
-- gave them. Nothing else was changed by the migration.
SELECT set_config('lock_timeout', '15s', true);

DROP POLICY IF EXISTS "client_statutory_identity_assignment_scope" ON public.client_statutory_identity;
DROP POLICY IF EXISTS "client_statutory_identity_internal_partner_only" ON public.client_statutory_identity;
DROP POLICY IF EXISTS "client_payroll_settings_assignment_scope" ON public.client_payroll_settings;
DROP POLICY IF EXISTS "client_payroll_settings_internal_partner_only" ON public.client_payroll_settings;
DROP POLICY IF EXISTS "client_pt_registrations_assignment_scope" ON public.client_pt_registrations;
DROP POLICY IF EXISTS "client_pt_registrations_internal_partner_only" ON public.client_pt_registrations;
