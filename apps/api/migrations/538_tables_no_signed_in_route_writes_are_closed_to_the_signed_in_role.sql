-- Migration 538 — sixteen tables that no signed-in route writes are closed to the signed-in role, and the `ri_*` tables that only a
-- migration-built database ever had are dropped (POST-A-305's dead-table half).
--
-- WHAT WAS WRONG
--   The signed-in role (`authenticated`) held every privilege on sixteen tables that carry no client, behind a firm policy (a per-user
--   one on permission_grants, one that follows its client-bearing parent on recurring_journal_template_lines) and no role tier, so any
--   member of the firm, a read-only Reviewer included, could insert, change or delete their rows over PostgREST whatever the API's
--   own checks say. Production's ACLs were read on 22-10-2026: `authenticated` held INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES and
--   TRIGGER on each, and `anon` held TRUNCATE, REFERENCES and TRIGGER. A search of apps/api and apps/web (the table-use scanner the
--   earlier writer guards share, then a grep for every spelling, then a second reader) found no signed-in writer for any of them, so
--   closing the grant costs no route anything:
--     NOTHING READS OR WRITES IT (ten): ai_trigger_registry, entity_addresses, entity_documents, lead_activities, lead_contacts,
--       pending_invites (an e-mail, a role and an invite token), permission_grants, retainer_logs, team_members (the retired table
--       three comments still mention) and xbrl_tag_mappings. Production holds no row in the first three named.
--     ONLY THE PRIVILEGED CLIENT USES IT (one): recurring_journal_template_lines, read and written only through
--       `recurring_journal_service._db`, which is `service_db`, and no route hands that service a client of its own.
--     ONLY THE PRIVILEGED CLIENT WRITES IT (four): email_templates, firm_branding, invoice_settings (the bank details printed on
--       every invoice) and invoice_templates, all through `branding_repository._svc`, behind `branding:write`, a Partner's. The
--       signed-in role reads them (the invoice PDF, the settings screens' loaders).
--     NOTHING CALLS ITS WRITERS (one): escalation_rules. The API only reads it (`escalation_service`, and the escalation route under
--       the caller's own sign-in); the repository's create, update and delete exist and have no caller.
--   The invoice settings are the sharpest of these: a Reviewer could change the bank account an invoice tells a customer to pay
--   into, with no route, no audit row and no trace but the row itself.
--
-- WHAT THIS DOES (one transaction)
--   * The eleven tables the signed-in role neither reads nor writes lose every privilege from `authenticated`, `anon` and PUBLIC.
--   * The five it only reads lose every privilege from `authenticated`, `anon` and PUBLIC and `authenticated` is given SELECT back.
--     Their policies are unchanged, so a member still reads only their own firm's rows.
--   * The service role's four privileges are granted explicitly on all sixteen, so that nothing above can have removed them through
--     PUBLIC.
--   * The four `ri_*` tables (migration 047: ri_entities, ri_cross_client_signals, ri_entity_relationships, ri_client_entity_links)
--     are dropped where they exist (IF EXISTS: production has none), so a migration-built database matches production.
--   * A DO block checks it and fails the migration otherwise: the effective privilege (table, column, through PUBLIC) of
--     `authenticated` and `anon` on every table, SELECT kept on the five, the service role's writes kept, `ri_*` absent.
--   * Each table is closed only where it exists: `xbrl_tag_mappings` is in production and in no migration, so a database built from
--     the migrations does not have it. Its production ACL was read: every grant on it was made by `postgres`, the role the runner
--     connects as, so the REVOKE removes what it names.
--
-- WHAT IT DOES NOT DO, ON PURPOSE
--   * No row is deleted and no table is dropped in production (they exist there, and a drop needs the production fixtures
--     refreshed, docs/schema-drift.md). Closing is reversible; the rollback gives back what the migrations granted.
--   * No role tier on the tables the request's client DOES write (account_group_mappings, assignment_rules, the HSN library,
--     entities, leads, dsc_records, automation, the reminder settings, the recurring templates and the document line tables):
--     that is a policy per table and a decision per tier, and is the next change (POST-A-328 and POST-A-329). This one only closes
--     what nobody signed in uses.
--   * `users.invite_token` is not changed: a signed-in session reads only its OWN `users` row (`users_own_row_select`) and a
--     pending invitee has no auth id yet, so the staff invite secret is not exposed to the firm (a test below keeps it so).
--   * `entities` stays firm-wide: it is shared across clients on purpose, because that sharing is what makes cross-client match
--     detection possible (the note at the top of routers/relationships.py).
--
-- DEPLOY ORDER
--   Every signed-in writer of the sixteen is absent: the writers are on the privileged client or have no caller (the guard test of
--   this change reads that from the source), so there is no writer to move first and no ordering with the API deploy.

SELECT set_config('lock_timeout', '15s', true);

-- Each table is closed only where it exists: `xbrl_tag_mappings` is in production and in no migration (a table made outside them),
-- so a database built from the migrations does not have it, and every other table here is in both.
DO $$
DECLARE
  t text;
BEGIN
  -- ── 1. nothing signed-in reads or writes these: no privilege at all ─────────────────────────────────────────────────────
  FOREACH t IN ARRAY ARRAY['ai_trigger_registry', 'entity_addresses', 'entity_documents', 'lead_activities', 'lead_contacts',
                           'pending_invites', 'permission_grants', 'recurring_journal_template_lines', 'retainer_logs',
                           'team_members', 'xbrl_tag_mappings'] LOOP
    IF to_regclass('public.' || t) IS NULL THEN
      RAISE NOTICE 'migration 538: public.% does not exist here, nothing to close', t;
      CONTINUE;
    END IF;
    EXECUTE format('REVOKE ALL ON public.%I FROM authenticated, anon, PUBLIC', t);
    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON public.%I TO service_role', t);
  END LOOP;

  -- ── 2. only the privileged client (or nobody) writes these: the signed-in role keeps its read ─────────────────
  FOREACH t IN ARRAY ARRAY['email_templates', 'escalation_rules', 'firm_branding', 'invoice_settings', 'invoice_templates'] LOOP
    IF to_regclass('public.' || t) IS NULL THEN
      RAISE EXCEPTION 'migration 538: public.% should exist', t;
    END IF;
    EXECUTE format('REVOKE ALL ON public.%I FROM authenticated, anon, PUBLIC', t);
    EXECUTE format('GRANT SELECT ON public.%I TO authenticated', t);
    -- the service role's own privileges are explicit, so that nothing above can have removed them through PUBLIC
    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON public.%I TO service_role', t);
  END LOOP;
END $$;

-- ── 3. the tables that only a database built from the migrations has ───────────────────────────────────────────
DROP TABLE IF EXISTS public.ri_client_entity_links;
DROP TABLE IF EXISTS public.ri_entity_relationships;
DROP TABLE IF EXISTS public.ri_cross_client_signals;
DROP TABLE IF EXISTS public.ri_entities;

-- ── 4. check it ────────────────────────────────────────────────────────────────────────────────────────────────
DO $$
DECLARE
  t text;
  v_priv text;
  v_closed text[] := ARRAY['ai_trigger_registry', 'entity_addresses', 'entity_documents', 'lead_activities', 'lead_contacts',
                           'pending_invites', 'permission_grants', 'recurring_journal_template_lines', 'retainer_logs',
                           'team_members', 'xbrl_tag_mappings'];
  v_read_only text[] := ARRAY['email_templates', 'escalation_rules', 'firm_branding', 'invoice_settings', 'invoice_templates'];
BEGIN
  FOREACH t IN ARRAY v_closed || v_read_only LOOP
    IF to_regclass('public.' || t) IS NULL THEN
      CONTINUE;
    END IF;
    FOR v_priv IN SELECT unnest(ARRAY['INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER']) LOOP
      IF has_table_privilege('authenticated', 'public.' || t, v_priv) OR has_table_privilege('anon', 'public.' || t, v_priv) THEN
        RAISE EXCEPTION 'migration 538: the signed-in or anonymous role can still % public.%', v_priv, t;
      END IF;
    END LOOP;
    IF has_table_privilege('anon', 'public.' || t, 'SELECT') THEN
      RAISE EXCEPTION 'migration 538: the anonymous role can still read public.%', t;
    END IF;
    IF has_any_column_privilege('authenticated', 'public.' || t, 'INSERT, UPDATE, REFERENCES')
       OR has_any_column_privilege('anon', 'public.' || t, 'SELECT, INSERT, UPDATE, REFERENCES') THEN
      RAISE EXCEPTION 'migration 538: a column privilege on public.% is still held by the signed-in or anonymous role', t;
    END IF;
    FOREACH v_priv IN ARRAY ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE'] LOOP
      IF NOT has_table_privilege('service_role', 'public.' || t, v_priv) THEN
        RAISE EXCEPTION 'migration 538: the service role lost % on public.%', v_priv, t;
      END IF;
    END LOOP;
  END LOOP;

  FOREACH t IN ARRAY v_closed LOOP
    IF to_regclass('public.' || t) IS NOT NULL AND (has_table_privilege('authenticated', 'public.' || t, 'SELECT')
       OR has_any_column_privilege('authenticated', 'public.' || t, 'SELECT')) THEN
      RAISE EXCEPTION 'migration 538: the signed-in role can still read public.%', t;
    END IF;
  END LOOP;

  FOREACH t IN ARRAY v_read_only LOOP
    IF NOT has_table_privilege('authenticated', 'public.' || t, 'SELECT') THEN
      RAISE EXCEPTION 'migration 538: the signed-in role lost its read of public.%', t;
    END IF;
  END LOOP;

  IF to_regclass('public.ri_entities') IS NOT NULL OR to_regclass('public.ri_cross_client_signals') IS NOT NULL
     OR to_regclass('public.ri_entity_relationships') IS NOT NULL OR to_regclass('public.ri_client_entity_links') IS NOT NULL THEN
    RAISE EXCEPTION 'migration 538: an ri_* table survived';
  END IF;
END $$;
