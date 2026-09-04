-- Migration 328: a payroll release is defensible, or somebody signs for it.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS BROKEN
-- ═══════════════════════════════════════════════════════════════════════════
-- POST /api/payroll/runs computes a draft and returns two lists of things it
-- could NOT establish:
--
--   statutory_gaps    a state levies professional tax or a labour welfare fund
--                     that this run did not compute — Article 276 makes the
--                     employer liable to deduct and deposit, so the zero is a
--                     shortfall with interest, not an absence of liability
--   attendance_gaps   nobody entered attendance for this employee, so the run
--                     paid them a full month on the 26-day default (324/326)
--
-- Both are shown on the draft. Nothing stopped the run being FINALISED with
-- them outstanding — and finalising posts a real, immutable general-ledger
-- journal and is the point after which the figures cannot be changed. So the
-- warnings were advice at exactly the moment they stopped being advice.
--
-- The gaps were also computed once, at draft time, and kept nowhere. A run
-- finalised three days later was judged against nothing at all.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT THIS TABLE IS
-- ═══════════════════════════════════════════════════════════════════════════
-- Every status transition a run makes through the API, with the gaps that
-- STOOD AT THAT MOMENT and, where any stood on a release, the reason a Partner
-- typed for going ahead anyway.
--
-- The gaps are recomputed at the transition rather than read from the draft:
-- a CA who records the missing state slabs (migration 327) or enters the
-- missing attendance (326) between drafting and finalising has genuinely
-- closed the gap, and a stored list would still be refusing.
--
-- APPEND-ONLY, AND THAT IS THE WHOLE POINT. There is a SELECT policy and an
-- INSERT policy and no others, and UPDATE and DELETE are revoked outright. A
-- log somebody can edit is not a log — it is a claim. This is the same
-- reasoning CLAUDE.md records for the general ledger: the LOG is what is
-- immutable.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- THE RULE IS A CONSTRAINT, NOT A CONVENTION
-- ═══════════════════════════════════════════════════════════════════════════
-- A release with gaps and no reason cannot be written. Not "the endpoint
-- refuses it" — the endpoint does refuse it, and so does the table, because
-- ~83 tables in this schema are written directly from the browser through
-- PostgREST where rbac() never runs and the constraint is what survives.
--
-- Deliberately scoped to RELEASES. draft -> review and review -> draft carry
-- no journal and no payment, so gaps on those are information; the constraint
-- would only teach people to type "n/a" to move a run to review.

BEGIN;

CREATE TABLE IF NOT EXISTS public.payroll_run_transitions (
  id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id  uuid NOT NULL REFERENCES public.firms(id)        ON DELETE CASCADE,
  run_id   uuid NOT NULL REFERENCES public.payroll_runs(id) ON DELETE CASCADE,

  -- NULL from_status is allowed: a run created straight into a state has no
  -- previous one, and inventing 'draft' would assert a transition that did not
  -- happen.
  from_status text,
  to_status   text NOT NULL CHECK (to_status IN ('draft', 'review', 'finalized', 'paid')),

  -- The sentences the run could not establish, exactly as the CA saw them.
  -- A JSON array of strings; [] means the release was clean, which is a
  -- POSITIVE record and the reason this is NOT NULL.
  gaps jsonb NOT NULL DEFAULT '[]'::jsonb
       CHECK (jsonb_typeof(gaps) = 'array'),

  -- Why the release went ahead anyway. Required only when gaps stood on a
  -- release; forbidden to be blank when it is required.
  override_reason text,

  actor_id uuid REFERENCES public.users(id),
  at       timestamptz NOT NULL DEFAULT now(),

  -- THE RULE. A release (finalized/paid) with gaps must carry a reason of
  -- substance. Twenty characters is not a quality bar — it is a floor under
  -- "ok", "-" and ".", which is what a required free-text field collects when
  -- nothing asks for more.
  -- jsonb_typeof(gaps) <> 'array' comes FIRST because jsonb_array_length RAISES
  -- on a scalar rather than returning anything, and PostgreSQL does not promise
  -- an order between CHECK constraints. Without the guard a `gaps` of "none"
  -- was rejected — correctly — with "cannot get array length of a scalar",
  -- which tells a caller nothing about what was wrong. Guarded, the row still
  -- cannot be written: the gaps CHECK above rejects it, saying so.
  CONSTRAINT payroll_release_with_gaps_needs_a_reason CHECK (
    to_status NOT IN ('finalized', 'paid')
    OR jsonb_typeof(gaps) <> 'array'
    OR jsonb_array_length(gaps) = 0
    OR length(btrim(coalesce(override_reason, ''))) >= 20
  )
);

COMMENT ON TABLE public.payroll_run_transitions IS
    'Append-only log of every payroll-run status transition made through the '
    'API, with the statutory and attendance gaps that stood at that moment and '
    'the Partner''s typed reason where a release went ahead with any '
    'outstanding. UPDATE and DELETE are revoked: a log somebody can edit is a '
    'claim, not a record. Migration 328.';

COMMENT ON COLUMN public.payroll_run_transitions.gaps IS
    'The sentences the run could not establish, as the CA saw them, RECOMPUTED '
    'at the transition rather than read from the draft — a CA who records the '
    'missing state slabs or enters the missing attendance in between has '
    'genuinely closed the gap. NOT NULL because [] is a positive record that '
    'the release was clean.';

COMMENT ON COLUMN public.payroll_run_transitions.override_reason IS
    'Why a release went ahead with gaps outstanding. Required by CHECK for '
    'finalized/paid when gaps is non-empty, with a 20-character floor under '
    '"ok" and ".". Not required for draft/review, which post no journal and '
    'pay nobody — requiring it there would only teach people to type "n/a".';

CREATE INDEX IF NOT EXISTS payroll_run_transitions_run_idx
  ON public.payroll_run_transitions (run_id, at DESC);
CREATE INDEX IF NOT EXISTS payroll_run_transitions_firm_idx
  ON public.payroll_run_transitions (firm_id, at DESC);

-- ═══════════════════════════════════════════════════════════════════════════
-- Access: read and append, never amend
-- ═══════════════════════════════════════════════════════════════════════════

ALTER TABLE public.payroll_run_transitions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "firm_reads_payroll_transitions" ON public.payroll_run_transitions;
CREATE POLICY "firm_reads_payroll_transitions" ON public.payroll_run_transitions
  FOR SELECT TO authenticated
  USING (firm_id = public.get_my_firm_id());

DROP POLICY IF EXISTS "firm_appends_payroll_transitions" ON public.payroll_run_transitions;
CREATE POLICY "firm_appends_payroll_transitions" ON public.payroll_run_transitions
  FOR INSERT TO authenticated
  WITH CHECK (firm_id = public.get_my_firm_id());

-- No UPDATE or DELETE policy exists, so RLS denies both by default. The REVOKE
-- says the same thing at the grant level, so a future migration that adds a
-- broad FOR ALL policy to this table cannot quietly reopen them.
REVOKE UPDATE, DELETE ON public.payroll_run_transitions FROM authenticated;
GRANT  SELECT, INSERT ON public.payroll_run_transitions TO authenticated;

COMMIT;
