-- Migration 377: recurring journals become templates the firm owns (ACC-06).
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═══════════════════════════════════════════════════════════════════════════
-- `/accounting/recurring` kept every template a CA set up in
-- `localStorage["practicesync_recurring_templates"]`, worked out the next due
-- date in the browser, and posted nothing. A partner who configured the firm's
-- recurring journals on their laptop found an empty screen on the office
-- machine; clearing site data lost the lot; and the hub card said "Automate
-- monthly, quarterly & yearly entries" while nothing anywhere posted a due
-- template.
--
-- This is the LAST of ACC-06's three screens and the only genuine build among
-- them. The budget went onto `account_budgets` (migration 376) and the
-- retainer tracker onto `billing_schedules`, which was already built and had
-- no caller.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- THE SHAPE IS `recurring_invoice_templates`' (migration 107), DELIBERATELY
-- ═══════════════════════════════════════════════════════════════════════════
-- A template, its LINES, and a runs ledger keyed (template, occurrence) that
-- is both the history a screen shows and the idempotency record the engine
-- reads. That trio has been running the recurring SALES invoices since Phase
-- 4.3; copying its shape means one set of habits, one catch-up rule, and one
-- answer to "did this month already generate".
--
-- LINES, not two account columns. The screen offers one debit and one credit,
-- and that is what it will write — but the posting kernel takes N lines and a
-- real recurring journal (rent plus its GST, a loan instalment split between
-- interest and principal) needs three. A child table costs nothing now and is
-- the difference between adding a field later and writing a second migration.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT IT POSTS, AND WHY THE ENTRY IS STAMPED `manual`
-- ═══════════════════════════════════════════════════════════════════════════
-- A DRAFT manual journal. Never a posted one: this product acts unprompted in
-- exactly one place — a bank rule a Manager has marked trusted — and that was
-- a recorded owner decision, not a default to copy.
--
-- The generated entry carries `source_type = 'manual'`, which looks wrong and
-- is not. `manual_journal_service._is_manual` is
-- `(source_type or "") == "manual"`, and migrations 275/338 refuse the edit
-- and discard paths on anything else. Stamping `recurring_journal` would
-- therefore produce a draft the CA is invited to review and FORBIDDEN to
-- amend, which defeats the whole point of generating a draft. It is also the
-- honest reading: a person wrote the template and a person reviews and posts
-- the entry — the machine saved them the typing, and that does not make it an
-- auto-posted document.
--
-- Traceability is kept WITHOUT touching source_type: `journal_entries` gains
-- `recurring_template_id` and `recurring_occurrence`, exactly as
-- `client_sales_invoices` did in migration 107, and the partial unique index
-- below is the authoritative backstop behind the runs table's own key.
--
-- Additive. Idempotent. Reversible: 377_..._rollback.sql.

CREATE TABLE IF NOT EXISTS public.recurring_journal_templates (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id        uuid NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
    client_id      uuid NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
    name           text NOT NULL,
    -- The same five the sales templates allow, so one cadence helper serves
    -- both. The screen offers three of them today.
    frequency      text NOT NULL
        CHECK (frequency IN ('weekly','monthly','quarterly','half_yearly','yearly')),
    -- 1–28 only. 29, 30 and 31 do not exist in every month, and a template
    -- that silently slides to the 28th in February is a template that posts on
    -- a date nobody chose. The screen has always capped at 28; the CHECK makes
    -- it a property of the data rather than of one form.
    day_of_month   integer NOT NULL DEFAULT 1 CHECK (day_of_month BETWEEN 1 AND 28),
    narration      text,
    start_date     date NOT NULL,
    end_date       date,
    next_run_date  date NOT NULL,
    status         text NOT NULL DEFAULT 'active'
        CHECK (status IN ('active','paused','archived')),
    created_by     uuid REFERENCES public.users(id),
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT recurring_journal_period_is_a_period
        CHECK (end_date IS NULL OR end_date >= start_date)
);

COMMENT ON TABLE public.recurring_journal_templates IS
    'A recurring journal a CA set up: what to post, to which accounts, how '
    'often. Generation produces a DRAFT manual journal and never posts one. '
    'Migration 377 (ACC-06).';
COMMENT ON COLUMN public.recurring_journal_templates.day_of_month IS
    '1-28. Higher days do not exist in every month, and sliding to the 28th in '
    'February would post on a date nobody chose.';

CREATE TABLE IF NOT EXISTS public.recurring_journal_template_lines (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    template_id  uuid NOT NULL
        REFERENCES public.recurring_journal_templates(id) ON DELETE CASCADE,
    account_id   uuid NOT NULL REFERENCES public.chart_of_accounts(id) ON DELETE CASCADE,
    -- Integer paise, and exactly one side of each line is non-zero — the same
    -- rule journal_lines carries. The kernel asserts the entry balances; this
    -- stops a line that is nonsense before it gets there.
    debit_paise  bigint NOT NULL DEFAULT 0 CHECK (debit_paise >= 0),
    credit_paise bigint NOT NULL DEFAULT 0 CHECK (credit_paise >= 0),
    narration    text,
    sort_order   integer NOT NULL DEFAULT 0,
    CONSTRAINT recurring_journal_line_has_one_side
        CHECK ((debit_paise = 0) <> (credit_paise = 0))
);

COMMENT ON TABLE public.recurring_journal_template_lines IS
    'The lines a recurring journal posts. A child table rather than two '
    'account columns on the template: the posting kernel takes N lines, and a '
    'rent journal with its GST needs three. Migration 377.';

-- Generation history AND the idempotency ledger, exactly as
-- recurring_invoice_runs is for the sales templates.
CREATE TABLE IF NOT EXISTS public.recurring_journal_runs (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id          uuid NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
    template_id      uuid NOT NULL
        REFERENCES public.recurring_journal_templates(id) ON DELETE CASCADE,
    occurrence_date  date NOT NULL,
    journal_entry_id uuid REFERENCES public.journal_entries(id) ON DELETE SET NULL,
    status           text NOT NULL DEFAULT 'generated'
        CHECK (status IN ('generated','skipped','failed')),
    detail           jsonb,
    created_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (template_id, occurrence_date)
);

COMMENT ON TABLE public.recurring_journal_runs IS
    'One row per (template, occurrence): the history a screen shows and the '
    'record that makes generation idempotent. A failed occurrence is RECORDED '
    'rather than retried silently — a template that cannot post needs a CA, '
    'not another attempt. Migration 377.';

-- Traceability on the generated entry, mirroring what migration 107 did for
-- client_sales_invoices. NOT `source_type`: see the header — stamping anything
-- but 'manual' would make the draft unamendable by the very CA meant to review
-- it (migrations 275/338).
ALTER TABLE public.journal_entries
    ADD COLUMN IF NOT EXISTS recurring_template_id uuid
        REFERENCES public.recurring_journal_templates(id) ON DELETE SET NULL;
ALTER TABLE public.journal_entries
    ADD COLUMN IF NOT EXISTS recurring_occurrence date;

COMMENT ON COLUMN public.journal_entries.recurring_template_id IS
    'The recurring_journal_templates row that generated this entry, where one '
    'did. source_type stays ''manual'' deliberately — a generated DRAFT must '
    'stay editable, and every guard reads source_type, not this. Migration 377.';

CREATE UNIQUE INDEX IF NOT EXISTS uq_journal_entries_recurring
    ON public.journal_entries (recurring_template_id, recurring_occurrence)
    WHERE recurring_template_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_recurring_journal_templates_due
    ON public.recurring_journal_templates (firm_id, status, next_run_date);
CREATE INDEX IF NOT EXISTS idx_recurring_journal_lines_template
    ON public.recurring_journal_template_lines (template_id, sort_order);

ALTER TABLE public.recurring_journal_templates      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.recurring_journal_template_lines ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.recurring_journal_runs           ENABLE ROW LEVEL SECURITY;

-- Firm isolation, assignment scope and role-guarded writes, in the shape
-- migrations 260/261 established and 359/376 last used. The assignment policy
-- is here at CREATE time rather than waiting for another sweep like migration
-- 370's: 084's one-shot DO loop has never run again, and six tables created
-- since had to be caught by hand.
--
-- The role tiers: a recurring journal template DECIDES what will be posted to
-- the general ledger every month, so it is Manager+ to create or change —
-- stricter than a budget (Executive+, migration 376) and matching the tier a
-- bank rule needs to be marked trusted. Deleting is Manager+ too.
DO $$
BEGIN
  EXECUTE 'DROP POLICY IF EXISTS firm_recurring_journal_templates ON public.recurring_journal_templates';
  EXECUTE 'CREATE POLICY firm_recurring_journal_templates ON public.recurring_journal_templates '
          'FOR ALL TO authenticated '
          'USING (firm_id = public.get_my_firm_id()) '
          'WITH CHECK (firm_id = public.get_my_firm_id())';

  -- Kept contiguous in ONE string literal: tests/test_direct_write_tables_are_
  -- role_guarded.py reads the migration FILE, and a policy split across
  -- adjacent literals is valid SQL and invisible to that scan.
  EXECUTE 'DROP POLICY IF EXISTS recurring_journal_templates_assignment_scope ON public.recurring_journal_templates';
  EXECUTE 'CREATE POLICY recurring_journal_templates_assignment_scope '
          'ON public.recurring_journal_templates AS RESTRICTIVE '
          'FOR ALL USING (public.can_access_client(client_id::text)) '
          'WITH CHECK (public.can_access_client(client_id::text))';

  EXECUTE 'DROP POLICY IF EXISTS recurring_journal_templates_role_insert ON public.recurring_journal_templates';
  EXECUTE 'CREATE POLICY recurring_journal_templates_role_insert '
          'ON public.recurring_journal_templates AS RESTRICTIVE '
          'FOR INSERT WITH CHECK (public.my_role_at_least(''Manager''))';

  EXECUTE 'DROP POLICY IF EXISTS recurring_journal_templates_role_update ON public.recurring_journal_templates';
  EXECUTE 'CREATE POLICY recurring_journal_templates_role_update '
          'ON public.recurring_journal_templates AS RESTRICTIVE '
          'FOR UPDATE USING (public.my_role_at_least(''Manager'')) '
          'WITH CHECK (public.my_role_at_least(''Manager''))';

  EXECUTE 'DROP POLICY IF EXISTS recurring_journal_templates_role_delete ON public.recurring_journal_templates';
  EXECUTE 'CREATE POLICY recurring_journal_templates_role_delete '
          'ON public.recurring_journal_templates AS RESTRICTIVE '
          'FOR DELETE USING (public.my_role_at_least(''Manager''))';

  -- Lines are firm-scoped THROUGH their parent, the shape migration 107 uses
  -- for recurring_invoice_template_lines: the child has no firm_id of its own,
  -- so inventing one would be a second copy of a fact that can disagree.
  EXECUTE 'DROP POLICY IF EXISTS firm_recurring_journal_lines ON public.recurring_journal_template_lines';
  EXECUTE 'CREATE POLICY firm_recurring_journal_lines ON public.recurring_journal_template_lines '
          'FOR ALL TO authenticated '
          'USING (EXISTS (SELECT 1 FROM public.recurring_journal_templates t '
          '               WHERE t.id = template_id AND t.firm_id = public.get_my_firm_id())) '
          'WITH CHECK (EXISTS (SELECT 1 FROM public.recurring_journal_templates t '
          '                    WHERE t.id = template_id AND t.firm_id = public.get_my_firm_id()))';

  EXECUTE 'DROP POLICY IF EXISTS firm_recurring_journal_runs ON public.recurring_journal_runs';
  EXECUTE 'CREATE POLICY firm_recurring_journal_runs ON public.recurring_journal_runs '
          'FOR ALL TO authenticated '
          'USING (firm_id = public.get_my_firm_id()) '
          'WITH CHECK (firm_id = public.get_my_firm_id())';

  EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON public.recurring_journal_templates TO authenticated';
  EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON public.recurring_journal_template_lines TO authenticated';
  EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON public.recurring_journal_runs TO authenticated';
END $$;
