-- Migration 316: the guards the migrations declare and production does not have
--
-- scripts/db/guard_drift.py compared the RLS switches, policies and constraints
-- of a database built from these migrations against production for the first
-- time on 2026-09-03 (tests/fixtures/production_guards_2026-09-03.json). This
-- migration closes the part of that report that is provably safe to close from
-- here; docs/audits/2026-09-03-guard-drift-first-run.md carries the rest.
--
-- Every object below EXISTS in a database built from the migrations and is
-- ABSENT in production, so on a replayed database this is a no-op and in
-- production it adds what the migrations always said was there. Each is
-- guarded on its own existence, so it is idempotent in both places.
--
-- THE TWO THAT WERE LIVE BUGS
--
--   clients_status_check. Migration 042 widened it to admit 'archived' and
--   production never got the change: its CHECK still reads ('active',
--   'inactive'). routers/clients.py archives a client by writing 'archived',
--   so archiving fails in production while the whole suite passes here. The
--   constraint is dropped and re-created to the declared form on both sides.
--
--   form_26as_uploads_parse_status_check. Migration 234 declares ('pending',
--   'parsed', 'failed'); production has ('pending', 'parsing', 'parsed',
--   'error'). The code writes only 'pending' and 'parsed', and production
--   holds no rows, so converging production to the declared set changes no
--   data. Re-created on both sides so the two definitions hash the same.
--
-- WHAT WAS CHECKED IN PRODUCTION BEFORE WRITING THIS (02:15 IST, 2026-09-03)
--
--   * every foreign key below: zero orphans in the child column
--   * both unique constraints: zero duplicate groups
--   * every CHECK: zero rows that would fail it
--
-- The foreign keys are added NOT VALID and then VALIDATED, so a row that
-- appears between now and the deploy fails the migration loudly rather than
-- being locked in. The format CHECKs from migration 112 are added NOT VALID
-- and deliberately NOT validated, because that is the form 112 declares —
-- the migration-built template carries them unvalidated, and a validated
-- copy in production would read as drift.
--
-- NOT DONE HERE, ON PURPOSE
--
--   client_profiles_firm_id_client_id_key. The migrations declare UNIQUE
--   (firm_id, client_id); production holds 94 rows in 6 groups because
--   repositories/memory_repository.upsert_profile VERSIONS profiles — it
--   retires the current row (is_current = false) and inserts the next, and
--   client_profile_history points at the retired rows. The declaration is
--   what is wrong, not the data. That is a design decision, not a
--   reconciliation, and is recorded in the audit for a human.

-- ── Foreign keys: NOT VALID, then VALIDATE ──────────────────────────────────
DO $$
DECLARE
  spec record;
BEGIN
  FOR spec IN
    SELECT * FROM (VALUES
      ('automation_executions',  'automation_executions_firm_id_fkey',
         'FOREIGN KEY (firm_id) REFERENCES firms(id)'),
      ('client_timeline_events', 'client_timeline_events_client_id_fkey',
         'FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE'),
      ('escalation_rules',       'escalation_rules_firm_id_fkey',
         'FOREIGN KEY (firm_id) REFERENCES firms(id) ON DELETE CASCADE'),
      ('filings',                'filings_firm_id_fkey',
         'FOREIGN KEY (firm_id) REFERENCES firms(id)'),
      ('gst_portal_snapshots',   'gst_portal_snapshots_sync_job_id_fkey',
         'FOREIGN KEY (sync_job_id) REFERENCES gst_sync_jobs(id) ON DELETE SET NULL'),
      ('invoice_sequences',      'invoice_sequences_firm_id_fkey',
         'FOREIGN KEY (firm_id) REFERENCES firms(id) ON DELETE CASCADE'),
      ('pending_invites',        'pending_invites_firm_id_fkey',
         'FOREIGN KEY (firm_id) REFERENCES firms(id) ON DELETE CASCADE'),
      ('permission_grants',      'permission_grants_firm_id_fkey',
         'FOREIGN KEY (firm_id) REFERENCES firms(id)'),
      ('task_escalations',       'task_escalations_task_id_fkey',
         'FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE'),
      ('tasks',                  'tasks_workflow_step_id_fkey',
         'FOREIGN KEY (workflow_step_id) REFERENCES workflow_steps(id)'),
      ('workflow_steps',         'workflow_steps_workflow_id_fkey',
         'FOREIGN KEY (workflow_id) REFERENCES workflows(id)'),
      ('year_end_engagements',   'year_end_engagements_approved_by_fkey',
         'FOREIGN KEY (approved_by) REFERENCES users(id)'),
      ('year_end_engagements',   'year_end_engagements_final_approved_by_fkey',
         'FOREIGN KEY (final_approved_by) REFERENCES users(id)'),
      ('year_end_engagements',   'year_end_engagements_prepared_by_fkey',
         'FOREIGN KEY (prepared_by) REFERENCES users(id)'),
      ('year_end_engagements',   'year_end_engagements_reviewed_by_fkey',
         'FOREIGN KEY (reviewed_by) REFERENCES users(id)'),
      ('year_end_engagements',   'year_end_engagements_revision_requested_by_fkey',
         'FOREIGN KEY (revision_requested_by) REFERENCES users(id)'),
      ('year_end_engagements',   'year_end_engagements_submitted_by_fkey',
         'FOREIGN KEY (submitted_by) REFERENCES users(id)'),
      ('year_end_exports',       'year_end_exports_version_id_fkey',
         'FOREIGN KEY (version_id) REFERENCES financial_statement_versions(id)')
    ) AS v(tbl, con, def)
  LOOP
    IF to_regclass('public.' || spec.tbl) IS NULL THEN CONTINUE; END IF;
    IF EXISTS (SELECT 1 FROM pg_constraint
               WHERE conname = spec.con
                 AND conrelid = ('public.' || spec.tbl)::regclass) THEN
      CONTINUE;
    END IF;
    EXECUTE format('ALTER TABLE public.%I ADD CONSTRAINT %I %s NOT VALID',
                   spec.tbl, spec.con, spec.def);
    EXECUTE format('ALTER TABLE public.%I VALIDATE CONSTRAINT %I', spec.tbl, spec.con);
  END LOOP;
END $$;

-- ── Format CHECKs from migration 112, plus fee_invoices' length: NOT VALID ──
-- Left unvalidated on purpose: that is what 112 declares, and the point of
-- this migration is that production match the declaration, not exceed it.
DO $$
DECLARE
  spec record;
BEGIN
  FOR spec IN
    SELECT * FROM (VALUES
      ('customers',  'customers_pan_format',
         $q$CHECK (pan IS NULL OR pan ~ '^[A-Z]{5}[0-9]{4}[A-Z]$')$q$),
      ('customers',  'customers_gstin_format',
         $q$CHECK (gstin IS NULL OR gstin ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$')$q$),
      ('firms',      'firms_pan_format',
         $q$CHECK (pan IS NULL OR pan ~ '^[A-Z]{5}[0-9]{4}[A-Z]$')$q$),
      ('firms',      'firms_gstin_format',
         $q$CHECK (gstin IS NULL OR gstin ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$')$q$),
      ('firms',      'firms_pincode_format',
         $q$CHECK (pincode IS NULL OR pincode ~ '^[1-9][0-9]{5}$')$q$),
      ('vendors',    'vendors_pan_format',
         $q$CHECK (pan IS NULL OR pan ~ '^[A-Z]{5}[0-9]{4}[A-Z]$')$q$),
      ('vendors',    'vendors_gstin_format',
         $q$CHECK (gstin IS NULL OR gstin ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$')$q$),
      ('gstr1_returns', 'gstr1_returns_gstin_format',
         $q$CHECK (gstin IS NULL OR gstin ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$')$q$),
      ('payroll_employees', 'payroll_employees_pan_format',
         $q$CHECK (pan IS NULL OR pan ~ '^[A-Z]{5}[0-9]{4}[A-Z]$')$q$),
      ('tds_certificates', 'tds_certificates_pan_format',
         $q$CHECK (deductee_pan IS NULL OR deductee_pan ~ '^[A-Z]{5}[0-9]{4}[A-Z]$' OR deductee_pan IN ('PANNOTAVBL', 'PANAPPLIED'))$q$),
      ('tds_challans', 'tds_challans_bsr_code_format',
         $q$CHECK (bsr_code IS NULL OR bsr_code ~ '^[0-9]{7}$')$q$),
      ('fee_invoices', 'fee_invoices_invoice_no_length',
         $q$CHECK (invoice_no IS NULL OR length(invoice_no) <= 16)$q$)
    ) AS v(tbl, con, def)
  LOOP
    IF to_regclass('public.' || spec.tbl) IS NULL THEN CONTINUE; END IF;
    IF EXISTS (SELECT 1 FROM pg_constraint
               WHERE conname = spec.con
                 AND conrelid = ('public.' || spec.tbl)::regclass) THEN
      CONTINUE;
    END IF;
    EXECUTE format('ALTER TABLE public.%I ADD CONSTRAINT %I %s NOT VALID',
                   spec.tbl, spec.con, spec.def);
  END LOOP;
END $$;

-- ── Plain CHECKs and UNIQUEs (a UNIQUE cannot be NOT VALID) ─────────────────
DO $$
DECLARE
  spec record;
BEGIN
  FOR spec IN
    SELECT * FROM (VALUES
      ('account_group_mappings', 'account_group_mappings_statement_type_check',
         $q$CHECK (statement_type IN ('balance_sheet', 'profit_loss'))$q$),
      ('workflow_steps', 'workflow_steps_default_assignee_role_check',
         $q$CHECK (default_assignee_role IN ('owner', 'manager', 'staff', 'viewer'))$q$),
      ('account_group_mappings', 'account_group_mappings_firm_id_account_id_key',
         'UNIQUE (firm_id, account_id)'),
      ('workflow_steps', 'workflow_steps_workflow_id_step_order_key',
         'UNIQUE (workflow_id, step_order)')
    ) AS v(tbl, con, def)
  LOOP
    IF to_regclass('public.' || spec.tbl) IS NULL THEN CONTINUE; END IF;
    IF EXISTS (SELECT 1 FROM pg_constraint
               WHERE conname = spec.con
                 AND conrelid = ('public.' || spec.tbl)::regclass) THEN
      CONTINUE;
    END IF;
    EXECUTE format('ALTER TABLE public.%I ADD CONSTRAINT %I %s',
                   spec.tbl, spec.con, spec.def);
  END LOOP;
END $$;

-- ── The two CHECKs whose expression differed: re-created on both sides ──────
ALTER TABLE clients DROP CONSTRAINT IF EXISTS clients_status_check;
ALTER TABLE clients ADD CONSTRAINT clients_status_check
  CHECK (status IN ('active', 'inactive', 'archived'));

ALTER TABLE form_26as_uploads DROP CONSTRAINT IF EXISTS form_26as_uploads_parse_status_check;
ALTER TABLE form_26as_uploads ADD CONSTRAINT form_26as_uploads_parse_status_check
  CHECK (parse_status IN ('pending', 'parsed', 'failed'));
