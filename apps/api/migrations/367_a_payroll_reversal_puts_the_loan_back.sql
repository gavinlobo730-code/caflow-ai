-- 367: a payroll reversal puts the employee's loan back (PAY-08)
--
-- WHAT WAS WRONG
--
-- routers/payroll.py::_apply_loan_recoveries writes an employee's loan balance
-- down at FINALISATION, and reverse_run — which reverses both journals and
-- reopens the run at 'review' — never touched payroll_loans at all. So a run
-- that was finalised, reversed and re-finalised (the ordinary correction
-- cycle: finalise, spot a wrong attendance figure, reverse, fix, finalise
-- again) wrote ONE recovery down TWICE.
--
-- The direction matters and is the opposite of the obvious one. The employee's
-- PAY is reduced by the instalment exactly once — the reversed run's journals
-- are reversed, and the corrected run deducts the instalment once. It is the
-- LOAN BALANCE that moves twice, so the balance ends up one instalment too
-- LOW: the employer under-recovers, and the loan ledger understates what the
-- employee owes. A loan the first run closed is worse — closed_on is set, the
-- `.is_("closed_on","null")` query stops reading it, and the final instalment
-- is never recovered at all.
--
-- WHY A TABLE RATHER THAN AN UNDO THAT RECOMPUTES
--
-- The undo cannot be derived. _apply_loan_recoveries walks an employee's open
-- loans in whatever order the rows come back and applies min(remaining, owed)
-- to each — its own comment says "oldest-first is not modelled" — so where an
-- employee has two loans, which one was written down is not recoverable from
-- the balances afterwards. And the loan the run CLOSED has dropped out of the
-- query the undo would use to find it.
--
-- So the apply records what it did, per loan, and the undo reads it. That also
-- removes the ambiguity on the apply side (the row is the answer to "which
-- loan did this month's recovery hit"), and gives the loan a repayment history,
-- which is a thing a loan ledger needs for its own sake: until now the only
-- trace of a recovery was the balance having changed.
--
-- APPEND-ONLY, LIKE THE GL. A reversal does not delete the applied row — it
-- writes an offsetting one. Two rows that net to zero are the record of what
-- happened; one row deleted is a record that it did not. The balance is
-- reconstructable as principal − Σ amount_paise at any date, which is the
-- property that makes this worth a table.
--
-- NOTHING IS BACKFILLED, AND THAT IS DELIBERATE. A run finalised before this
-- migration has no rows here, so its balances were written down with no record
-- of which loan took what. Inventing rows from today's balances would assert a
-- history nobody observed. reverse_run falls back for those runs and SAYS it
-- is falling back — see routers/payroll.py::_undo_loan_recoveries.

CREATE TABLE IF NOT EXISTS public.payroll_loan_recoveries (
  id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  firm_id        UUID NOT NULL REFERENCES public.firms(id)   ON DELETE CASCADE,
  client_id      UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  loan_id        UUID NOT NULL REFERENCES public.payroll_loans(id) ON DELETE CASCADE,
  run_id         UUID NOT NULL REFERENCES public.payroll_runs(id)  ON DELETE CASCADE,
  employee_id    UUID NOT NULL REFERENCES public.payroll_employees(id) ON DELETE CASCADE,

  -- POSITIVE recovers (reduces the balance), NEGATIVE gives back (a reversal).
  -- Signed rather than a kind column plus a magnitude, so the balance is a
  -- plain SUM and no reader has to know the sign convention to add them up.
  amount_paise   BIGINT NOT NULL,
  -- 'recovered' on finalisation, 'reversed' when the run is reversed. The sign
  -- carries the arithmetic; this carries what a human reading the history
  -- needs, which is WHY the row exists.
  kind           TEXT   NOT NULL CHECK (kind IN ('recovered', 'reversed')),
  -- Whether this row also closed the loan (kind='recovered') or reopened it
  -- (kind='reversed'). Recorded rather than inferred from the balance, because
  -- a loan can reach zero and be reopened by a later correction, and "was it
  -- closed by THIS row" is not answerable from a balance afterwards.
  closed_the_loan BOOLEAN NOT NULL DEFAULT false,

  created_by     UUID REFERENCES public.users(id),
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname = 'payroll_loan_recoveries_amount_nonzero') THEN
    ALTER TABLE public.payroll_loan_recoveries
      ADD CONSTRAINT payroll_loan_recoveries_amount_nonzero
      CHECK (amount_paise <> 0);
  END IF;
  -- The sign IS the kind. A 'recovered' row that gives money back, or a
  -- 'reversed' row that takes it, would make the history read backwards while
  -- the SUM still came out right — the failure that is hardest to see.
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname = 'payroll_loan_recoveries_sign_matches_kind') THEN
    ALTER TABLE public.payroll_loan_recoveries
      ADD CONSTRAINT payroll_loan_recoveries_sign_matches_kind
      CHECK ((kind = 'recovered' AND amount_paise > 0)
          OR (kind = 'reversed'  AND amount_paise < 0));
  END IF;
END $$;

-- The two questions asked of this table: "what did this run do" (the undo) and
-- "what is this loan's history" (the screen).
CREATE INDEX IF NOT EXISTS payroll_loan_recoveries_run_idx
  ON public.payroll_loan_recoveries (run_id);
CREATE INDEX IF NOT EXISTS payroll_loan_recoveries_loan_idx
  ON public.payroll_loan_recoveries (loan_id, created_at);

COMMENT ON TABLE public.payroll_loan_recoveries IS
  'One row per loan per payroll run that recovered against it, and an '
  'offsetting row when that run is reversed. Append-only: a reversal writes a '
  'negative row, it never deletes the positive one. A loan''s balance is '
  'principal minus the SUM of amount_paise, which is why the sign convention '
  'is enforced by a CHECK rather than left to each writer.';

-- ─── RLS: firm scope permissive, role gate restrictive (260/261's split) ────
-- Mirrors payroll_loans (migration 300) exactly, because this table says what
-- happened to a loan and a reader who may not see the loan must not see its
-- history either.
ALTER TABLE public.payroll_loan_recoveries ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE t TEXT := 'payroll_loan_recoveries';
BEGIN
  EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_firm_scope', t);
  EXECUTE format(
    'CREATE POLICY %I ON public.%I FOR ALL '
    'USING (firm_id = public.get_my_firm_id()) '
    'WITH CHECK (firm_id = public.get_my_firm_id())',
    t || '_firm_scope', t);

  EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_role_insert', t);
  EXECUTE format(
    'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR INSERT '
    'WITH CHECK (public.my_role_at_least(%L))', t || '_role_insert', t, 'Manager');

  -- No UPDATE policy at all, and that is the point: this is an append-only
  -- history. A correction is another row.
  EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_role_update', t);
  EXECUTE format(
    'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR UPDATE '
    'USING (false) WITH CHECK (false)', t || '_role_update', t);

  EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_role_delete', t);
  EXECUTE format(
    'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR DELETE '
    'USING (public.my_role_at_least(%L))', t || '_role_delete', t, 'Partner');
END $$;

GRANT SELECT, INSERT, UPDATE, DELETE ON public.payroll_loan_recoveries TO authenticated;
