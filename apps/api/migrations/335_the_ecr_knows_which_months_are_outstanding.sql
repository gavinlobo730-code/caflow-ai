-- Migration 335: record which EPFO returns a client has actually filed.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS MISSING
-- ═══════════════════════════════════════════════════════════════════════════
-- GET /api/payroll/runs/{id}/ecr builds a correct ECR file for one run and
-- knows nothing about any other month. Since the ECR was revamped on
-- 26 September 2025 (launch circular; FAQ circular of 08-10-2025) that is not
-- enough to hand a CA something they can upload:
--
--   * EPFO enforces MONTH-WISE SEQUENCE by blocking. October cannot be filed
--     while September is pending. The four-month relaxation at launch expired
--     around January 2026; enforcement is live, and pending pre-September-2025
--     months go through the revamped system too.
--   * A month has THREE possible returns, and which one it needs is a fact
--     about what has already been accepted for it: Regular (every active
--     member), Supplementary (members registered after that month's Regular was
--     approved), Revised (wages or contributions already submitted, corrected).
--   * RETURN AND PAYMENT ARE SEPARATE AND ORDERED — the return is submitted and
--     APPROVED first, and only then is the challan generated.
--
-- None of that is derivable from payroll_runs. A finalised run says the books
-- were closed for a month; it says nothing about whether anybody uploaded the
-- file. So the product could hand a CA a perfectly-formed October file while
-- September was still outstanding, and the portal would refuse it.
--
-- Verified 2026-09-04; see docs/compliance/04-mca-epfo-esic.md.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHY NOT public.filings
-- ═══════════════════════════════════════════════════════════════════════════
-- That is where GSTR-1 and GSTR-3B are recorded, and reusing it would be the
-- obvious move. It is wrong here for one specific reason:
-- journal_period_lock_reason (migration 266) reads `filings` and REFUSES to
-- edit any journal in a period a return covers. That rule rests on a GST return
-- being unrecallable — CGST Act s.37 corrects a past period in a LATER return's
-- amendment tables, never by re-filing.
--
-- The ECR does not work that way. A REVISED RETURN IS THE SANCTIONED CORRECTION
-- PATH, so the premise of the lock is absent, and recording an ECR in `filings`
-- would freeze a whole month of a client's ledger on a payroll upload — a
-- consequence nobody asked for and one that would fight the very correction
-- EPFO expects.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHY THE MEMBER FIGURES ARE FROZEN HERE
-- ═══════════════════════════════════════════════════════════════════════════
-- "Has this member's wage changed since we filed?" has to compare against what
-- was FILED. Recomputing from the payslip would compare the books against
-- themselves and always agree, which is exactly the case a Revised return
-- exists for. Same reasoning as the GST services freezing a return's payload.
--
-- Three figures per member, not the whole eleven-field line: EPF wages, EPF
-- contribution remitted and EPS contribution remitted are what a Revised return
-- corrects. A changed name is not a revision, and storing the whole file would
-- put a second copy of the return in the database.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- ONE REGULAR PER MONTH, ENFORCED BY THE DATABASE
-- ═══════════════════════════════════════════════════════════════════════════
-- A wage month has exactly one Regular return. Supplementary and Revised are
-- both repeatable — a month can need several of either — so the unique index is
-- partial on return_type, not on the pair. Recording a second Regular is the
-- single most likely wrong entry (it is what a late joiner looks like to
-- someone not watching), and it would clear a month that a Supplementary was
-- actually needed for.
-- ═══════════════════════════════════════════════════════════════════════════

BEGIN;

CREATE TABLE IF NOT EXISTS public.epfo_ecr_filings (
  id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id   uuid NOT NULL REFERENCES public.firms(id)   ON DELETE CASCADE,
  client_id uuid NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,

  -- The run the uploaded file was built from, where there was one. ON DELETE
  -- SET NULL, never CASCADE: deleting a payroll run must not erase the record
  -- that a return was filed with EPFO. The filing happened at the portal and
  -- outlives anything we hold about how it was prepared.
  run_id    uuid REFERENCES public.payroll_runs(id) ON DELETE SET NULL,

  -- The WAGE month, 'YYYY-MM' — the month whose contributions the return
  -- reports, not the month it was filed in. Same shape as payroll_runs.month
  -- so the two join, and CHECKed here because the sequence logic sorts these as
  -- text and a malformed one would sort into the wrong place silently.
  wage_month  text NOT NULL CHECK (wage_month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),

  return_type text NOT NULL
              CHECK (return_type IN ('regular', 'supplementary', 'revised')),

  -- Submitted is NOT approved, and only approved clears a month: the portal
  -- blocks a later month unless the earlier one is filed AND validated.
  status      text NOT NULL DEFAULT 'submitted'
              CHECK (status IN ('submitted', 'approved')),

  -- EPFO's Temporary Return Reference Number for the upload. Free text and
  -- unvalidated, for the same reason the establishment code is (migration 325):
  -- a pattern written from memory would refuse a real reference somebody is
  -- reading off the portal, which is the wrong direction of error.
  trrn         text,

  submitted_on date NOT NULL,
  approved_on  date,

  -- The frozen figures: [{uan, epf_wages, epf_contribution, eps_contribution}].
  -- Whole rupees, as the file carries them. NOT NULL because [] is a positive
  -- record — a return filed for no members — and NULL would be indistinguishable
  -- from "we never captured them", which changes what a Supplementary means.
  members  jsonb NOT NULL DEFAULT '[]'::jsonb
           CHECK (jsonb_typeof(members) = 'array'),

  recorded_by uuid REFERENCES public.users(id),
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),

  -- Soft delete, like public.filings. A mis-recorded filing has to be
  -- retractable — the CA types this from the portal and can type it wrong — but
  -- a hard DELETE would silently un-block every later month with no trace of
  -- why the sequence changed.
  deleted_at  timestamptz,

  -- An approved return has an approval date. Without this a row could claim the
  -- state that clears a month while recording no evidence of when it cleared.
  CONSTRAINT epfo_ecr_approved_needs_a_date CHECK (
    status <> 'approved' OR approved_on IS NOT NULL
  ),
  CONSTRAINT epfo_ecr_approved_not_before_submitted CHECK (
    approved_on IS NULL OR approved_on >= submitted_on
  )
);

-- One live Regular per client per wage month. Partial on return_type because
-- Supplementary and Revised are both legitimately repeatable, and partial on
-- deleted_at so retracting a wrong entry frees the month.
CREATE UNIQUE INDEX IF NOT EXISTS epfo_ecr_one_regular_per_month
  ON public.epfo_ecr_filings (client_id, wage_month)
  WHERE return_type = 'regular' AND deleted_at IS NULL;

-- The sequence read is "every filing for this client, oldest month first".
CREATE INDEX IF NOT EXISTS epfo_ecr_filings_by_client_month
  ON public.epfo_ecr_filings (firm_id, client_id, wage_month)
  WHERE deleted_at IS NULL;

COMMENT ON TABLE public.epfo_ecr_filings IS
    'What the CA actually filed with EPFO, per wage month and return type, '
    'typed in from the portal. Nothing here transmits: this is the record that '
    'lets the product say which months are outstanding, in order, and whether '
    'a month needs a Regular, a Supplementary or a Revised return. Migration '
    '335.';

COMMENT ON COLUMN public.epfo_ecr_filings.wage_month IS
    'The month whose contributions the return reports, YYYY-MM. Not the month '
    'it was filed in.';

COMMENT ON COLUMN public.epfo_ecr_filings.status IS
    'submitted or approved. Only approved clears a month for sequence purposes '
    '- EPFO blocks a later month unless the earlier one is filed AND '
    'validated, and the challan cannot be generated until the return is '
    'approved.';

COMMENT ON COLUMN public.epfo_ecr_filings.members IS
    'The member figures as filed, frozen: [{uan, epf_wages, epf_contribution, '
    'eps_contribution}] in whole rupees. Compared against a later run to tell a '
    'Supplementary (a member not on any approved return) from a Revised (a '
    'member whose figures moved). Recomputing from the payslip instead would '
    'compare the books against themselves and always agree.';

COMMENT ON COLUMN public.epfo_ecr_filings.trrn IS
    'EPFO Temporary Return Reference Number. Deliberately unvalidated - see '
    'domain/payroll/identity.py for why a remembered pattern refuses real '
    'registrations.';

ALTER TABLE public.epfo_ecr_filings ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "firm_reads_epfo_ecr_filings" ON public.epfo_ecr_filings;
CREATE POLICY "firm_reads_epfo_ecr_filings" ON public.epfo_ecr_filings
  FOR SELECT TO authenticated
  USING (firm_id = public.get_my_firm_id());

DROP POLICY IF EXISTS "firm_writes_epfo_ecr_filings" ON public.epfo_ecr_filings;
CREATE POLICY "firm_writes_epfo_ecr_filings" ON public.epfo_ecr_filings
  FOR INSERT TO authenticated
  WITH CHECK (firm_id = public.get_my_firm_id());

DROP POLICY IF EXISTS "firm_updates_epfo_ecr_filings" ON public.epfo_ecr_filings;
CREATE POLICY "firm_updates_epfo_ecr_filings" ON public.epfo_ecr_filings
  FOR UPDATE TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());

-- No DELETE policy, and the grant is revoked to match: a filing is retracted by
-- setting deleted_at, never removed. A hard delete would un-block every later
-- month with nothing recording that it had.
REVOKE DELETE ON public.epfo_ecr_filings FROM authenticated;
GRANT  SELECT, INSERT, UPDATE ON public.epfo_ecr_filings TO authenticated;

COMMIT;
