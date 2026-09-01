-- Migration 304: where the Schedule III ratio note keeps the two things a CA
-- has to supply — the >25% explanations, and the principal repaid.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHY
-- ═══════════════════════════════════════════════════════════════════════════
-- MCA Notification G.S.R. 207(E) of 24-03-2021 inserted Additional Regulatory
-- Information into Schedule III Division I's General Instructions. Clause (Q)
-- prescribes eleven ratios and then imposes two obligations that are not
-- arithmetic:
--
--   "The company shall explain the items included in numerator and denominator
--    for computing the above ratios. Further explanation shall be provided for
--    any change in the ratio by more than 25% as compared to the preceding
--    year."
--
-- The first is computable and is computed — domain/reporting/ratios.py carries
-- the numerator and denominator labels with every ratio, because those words
-- are part of the filing. The second is not: WHY a ratio moved is a fact about
-- the business that only the CA and their client know, and it has to be typed
-- and kept. That is what schedule_iii_ratio_explanations is.
--
-- schedule_iii_ratio_inputs holds the one number the ledger genuinely does not
-- have. Debt Service Coverage is earnings available for debt service over debt
-- service, and debt service includes the PRINCIPAL repaid on long-term
-- borrowings during the year. The books hold the movement in the borrowing
-- balance, which is drawdowns LESS repayments — a client who repaid 40 lakh and
-- drew 35 lakh shows a movement of 5 lakh, and a DSCR built on that overstates
-- cover eightfold. Lenders read this ratio. So the figure is refused until a
-- human supplies it, and this is where it goes.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHY TWO TABLES AND NOT ONE WITH A NULLABLE ratio_key
-- ═══════════════════════════════════════════════════════════════════════════
-- They are different things: one is per ratio per year, the other is per year.
-- Folding them together needs a nullable ratio_key whose NULL means "this row
-- is not about a ratio at all", and a partial unique index to keep one of them
-- singular. That is a trick, and a trick in a table two reports read is how a
-- year-level figure ends up attributed to a ratio.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- SCOPE AND ACCESS
-- ═══════════════════════════════════════════════════════════════════════════
-- firm_id + client_id on both, like every other row in this schema, with
-- firm-scoped RLS as defence in depth behind the app-layer filter. Writes are
-- role-guarded RESTRICTIVE at the Manager tier, matching migrations 260/261 and
-- the accounting:write permission the endpoints use: recording why a ratio
-- moved 40% is part of the signed disclosure, not a preference.
--
-- fy_label is the '2026-27' financial-year string the rest of the codebase
-- uses (ist_fy_label), not a date range — the disclosure is annual and the
-- comparison is with "the preceding year".
--
-- New tables only; nothing existing changes. Idempotent, safe to re-run.

BEGIN;

CREATE TABLE IF NOT EXISTS public.schedule_iii_ratio_explanations (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id      uuid NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id    uuid NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  -- '2026-27'. Annual, because clause (Q) compares with "the preceding year".
  fy_label     text NOT NULL,
  -- The ratio this explains, e.g. 'current_ratio'. Matches the keys in
  -- domain/reporting/ratios.py; deliberately not an enum, so adding a ratio is
  -- a code change rather than a migration.
  ratio_key    text NOT NULL,
  explanation  text NOT NULL,
  recorded_by  uuid REFERENCES public.users(id),
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (firm_id, client_id, fy_label, ratio_key)
);

COMMENT ON TABLE public.schedule_iii_ratio_explanations IS
    'The explanations Schedule III Division I clause (Q) requires for any ratio '
    'that moved more than 25% from the preceding year (MCA G.S.R. 207(E), '
    '24-03-2021). Not derivable — why a ratio moved is a fact about the '
    'business. Migration 304.';

CREATE INDEX IF NOT EXISTS idx_ratio_expl_client_fy
    ON public.schedule_iii_ratio_explanations (firm_id, client_id, fy_label);

CREATE TABLE IF NOT EXISTS public.schedule_iii_ratio_inputs (
  id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id                uuid NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id              uuid NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  fy_label               text NOT NULL,
  -- Integer paise, like every other monetary column. NULLABLE with no default,
  -- for the same reason vendors.msme_status is (migration 303): zero and "not
  -- supplied" are different claims, and a zero here reports infinite debt
  -- service cover.
  principal_repaid_paise bigint,
  recorded_by            uuid REFERENCES public.users(id),
  created_at             timestamptz NOT NULL DEFAULT now(),
  updated_at             timestamptz NOT NULL DEFAULT now(),
  UNIQUE (firm_id, client_id, fy_label),
  CONSTRAINT schedule_iii_ratio_inputs_principal_non_negative
    CHECK (principal_repaid_paise IS NULL OR principal_repaid_paise >= 0)
);

COMMENT ON COLUMN public.schedule_iii_ratio_inputs.principal_repaid_paise IS
    'Principal repaid on long-term borrowings during the year, in paise — the '
    'denominator half of the Debt Service Coverage Ratio that the ledger cannot '
    'supply, because the movement in the borrowing balance is drawdowns less '
    'repayments. NULL means not supplied, and the ratio is then reported as a '
    'gap rather than computed. Migration 304.';

ALTER TABLE public.schedule_iii_ratio_explanations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.schedule_iii_ratio_inputs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "firm_ratio_explanations" ON public.schedule_iii_ratio_explanations;
CREATE POLICY "firm_ratio_explanations" ON public.schedule_iii_ratio_explanations
    FOR ALL TO authenticated
    USING (firm_id = public.get_my_firm_id())
    WITH CHECK (firm_id = public.get_my_firm_id());

DROP POLICY IF EXISTS "firm_ratio_inputs" ON public.schedule_iii_ratio_inputs;
CREATE POLICY "firm_ratio_inputs" ON public.schedule_iii_ratio_inputs
    FOR ALL TO authenticated
    USING (firm_id = public.get_my_firm_id())
    WITH CHECK (firm_id = public.get_my_firm_id());

-- Role-aware write guards, the shape migrations 260/261 established. RESTRICTIVE
-- so they narrow rather than widen: a permissive policy here would GRANT.
-- Manager tier, matching accounting:write — which is what the endpoints require.
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['schedule_iii_ratio_explanations', 'schedule_iii_ratio_inputs'] LOOP
    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_role_insert', t);
    EXECUTE format(
      'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR INSERT '
      'WITH CHECK (public.my_role_at_least(%L))', t || '_role_insert', t, 'Manager');

    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_role_update', t);
    EXECUTE format(
      'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR UPDATE '
      'USING (public.my_role_at_least(%L)) WITH CHECK (public.my_role_at_least(%L))',
      t || '_role_update', t, 'Manager', 'Manager');

    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_role_delete', t);
    EXECUTE format(
      'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR DELETE '
      'USING (public.my_role_at_least(%L))', t || '_role_delete', t, 'Manager');
  END LOOP;
END $$;

GRANT SELECT, INSERT, UPDATE, DELETE ON public.schedule_iii_ratio_explanations TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.schedule_iii_ratio_inputs TO authenticated;

COMMIT;
