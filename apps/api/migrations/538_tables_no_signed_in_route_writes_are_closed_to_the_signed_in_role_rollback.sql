-- Rollback of migration 538: gives the sixteen tables back the privileges the migrations that created them granted (and, for
-- xbrl_tag_mappings, which no migration creates, the four privileges production's ACL showed).
-- WHAT IT CANNOT UNDO: the four ri_* tables, which only a database built from the migrations ever had, are not recreated (nothing
-- used them; re-applying the CREATE TABLE statements of migration 047 would bring them back). It restores what the MIGRATIONS granted
-- to the signed-in role, which is not necessarily every right production's platform defaults had given (anon's TRUNCATE,
-- REFERENCES and TRIGGER, for one, stay revoked).
-- THIS RE-OPENS: the signed-in role may again write sixteen tables (each limited to the caller's firm by its policy), among them the
-- invoice settings (the bank details printed on invoices).
SELECT set_config('lock_timeout', '15s', true);

DO $$
DECLARE
  t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['ai_trigger_registry', 'entity_addresses', 'entity_documents', 'lead_activities', 'lead_contacts',
                           'pending_invites', 'permission_grants', 'retainer_logs', 'team_members', 'xbrl_tag_mappings',
                           'escalation_rules', 'recurring_journal_template_lines'] LOOP
    IF to_regclass('public.' || t) IS NOT NULL THEN
      EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON public.%I TO authenticated', t);
    END IF;
  END LOOP;
  FOREACH t IN ARRAY ARRAY['email_templates', 'firm_branding', 'invoice_settings', 'invoice_templates'] LOOP
    IF to_regclass('public.' || t) IS NOT NULL THEN
      EXECUTE format('GRANT ALL ON public.%I TO authenticated', t);
    END IF;
  END LOOP;
END $$;
