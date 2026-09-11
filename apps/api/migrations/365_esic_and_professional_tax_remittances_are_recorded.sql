-- 365 — ESIC and professional tax have somewhere to record a remittance.
--
-- THE GAP
--
-- Of the statutory outputs this product prepares, three are monthly scheme
-- remittances a CA pays and then has to be able to prove they paid: EPF, ESI
-- and professional tax. EPF got its record in migration 335
-- (public.epfo_ecr_filings). The other two had nowhere at all.
--
-- The consequence is not cosmetic. `domain/payroll/esic.py` builds a correct
-- contribution file and `routers/payroll.py` computes PT for four states, and
-- the moment the CA uploads either one the product forgets it happened: no
-- challan number, no amount, no date, no way to answer "is October's ESI paid"
-- except by logging in to the portal. An obligation that cannot be closed is an
-- obligation that gets paid twice or not at all.
--
-- WHY THIS IS NOT ONE UNIVERSAL public.statutory_filings TABLE
--
-- The plan this comes from said "one filing record, for everything". Reading
-- what already exists says otherwise, and the plan was wrong:
--
--   * public.filings is the GST/ITR record and it DRIVES THE PERIOD LOCK
--     through journal_period_lock_reason. Migrating it would put the one thing
--     that works at risk to tidy the ones that do not.
--   * public.epfo_ecr_filings carries return_type, a submitted-vs-approved
--     state, and a sequence rule where an unapproved month BLOCKS the next.
--     That is EPFO's own machinery, not a generic filing lifecycle, and
--     flattening it into a shared table would lose it.
--   * MCA filings hang off a company and an SRN, and an SRN is not a filing.
--
-- So this closes the actual hole — ESI and PT — in the shape migration 335
-- proved, rather than unifying four things that are not the same thing.
--
-- ESI and PT DO share a shape: monthly, per client, settled by a challan, and
-- with an amount that has to tie to what payroll computed. They differ in two
-- ways the columns carry: PT is levied per STATE, so a client with staff in two
-- states files twice for one month; and ESI has a contribution PERIOD
-- (April-September, October-March) that the portal shows the remittance under.
--
-- # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT. Nothing here transmits; every row
-- records something a human did on the portal.

BEGIN;

CREATE TABLE IF NOT EXISTS public.statutory_remittances (
  id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id   uuid NOT NULL REFERENCES public.firms(id)   ON DELETE CASCADE,
  client_id uuid NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,

  scheme text NOT NULL CHECK (scheme IN ('esic', 'professional_tax')),

  -- The payroll run the figures came from, where there was one. ON DELETE SET
  -- NULL and never CASCADE, for migration 335's reason: deleting a run must not
  -- erase the record that money was remitted. The remittance happened at the
  -- portal and outlives anything we hold about how it was prepared.
  run_id uuid REFERENCES public.payroll_runs(id) ON DELETE SET NULL,

  -- The WAGE month, 'YYYY-MM' — the month whose liability is being settled, not
  -- the month it was paid in. ESI for September is paid by 15 October and both
  -- dates matter for different questions. CHECKed because anything that sorts
  -- these as text sorts a malformed one into the wrong place silently.
  wage_month text NOT NULL CHECK (wage_month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),

  -- PT is a STATE levy: one client with staff in Maharashtra and Karnataka owes
  -- two different authorities for one month, on two different due dates, with
  -- two challans. NULL for ESI, which is central — and the CHECK below makes
  -- that conditional rather than leaving it to convention.
  state text,

  -- ESI's contribution period, 'YYYY-H1' (April-September) or 'YYYY-H2'
  -- (October-March), labelled by the year the period STARTED. October to March
  -- is one period spanning a calendar year boundary, which is why the label
  -- cannot be derived from the wage month's year alone. NULL for PT.
  contribution_period text CHECK (
    contribution_period IS NULL
    OR contribution_period ~ '^[0-9]{4}-H[12]$'
  ),

  -- What the portal gave back. Free text and unvalidated, for the same reason
  -- the ECR's TRRN is: a pattern written from memory would refuse a real
  -- reference somebody is reading off the screen, and that is the wrong
  -- direction of error on a field whose whole purpose is evidence.
  challan_number text,
  challan_date   date,

  -- What was actually remitted, in paise. This is the CHALLAN's figure and not
  -- necessarily what payroll computed: interest and damages under ESI Act s.39(5)
  -- can be added at the portal, and a CA reconciling the two needs the number
  -- that left the bank.
  amount_paise bigint NOT NULL DEFAULT 0 CHECK (amount_paise >= 0),

  -- 'submitted' is the return filed; 'paid' is the money gone. They are two
  -- events and ESIC separates them — the contribution is submitted first and
  -- the challan generated after — so a single boolean would collapse the state
  -- a CA is actually chasing at month end.
  status text NOT NULL DEFAULT 'submitted'
         CHECK (status IN ('submitted', 'paid')),

  submitted_on date NOT NULL,
  paid_on      date,

  -- The journal entry that actually paid it, once the bank line is passed.
  --
  -- A LINK, NOT A SECOND POSTING PATH, and the difference is the whole point.
  -- The plan this comes from said "the challan is money, so it has to reach the
  -- GL" — which would have posted Dr ESI Payable / Cr Bank from here. The bank
  -- statement path ALREADY posts exactly that when the CA passes the payment
  -- line against the liability account, so recording it here too would debit
  -- the liability twice. services/bank_posting_service.post is the one path for
  -- money movement (and public.epfo_ecr_filings, the table this is modelled on,
  -- deliberately carries no journal reference for the same reason).
  --
  -- What was actually missing is the LINK. Without it there is no way to tell a
  -- liability nobody has paid from one that was paid and never tied back, so
  -- the statutory accounts look uncleared either way at year end. NULL means
  -- "not yet matched to a payment", which is a question a CA can act on.
  --
  -- ON DELETE SET NULL: reversing the payment entry unlinks the remittance, it
  -- does not erase the evidence that the return was filed.
  journal_entry_id uuid REFERENCES public.journal_entries(id) ON DELETE SET NULL,

  notes text,

  recorded_by uuid REFERENCES public.users(id),
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),

  -- Soft delete, like public.filings and epfo_ecr_filings. The CA types this
  -- from the portal and can type it wrong, so it has to be retractable — but a
  -- hard DELETE would remove the evidence that a liability was ever settled.
  deleted_at timestamptz,

  -- A paid remittance has a date it was paid. Without this a row could claim
  -- the settled state while recording no evidence of when it settled.
  CONSTRAINT statutory_remittance_paid_needs_a_date CHECK (
    status <> 'paid' OR paid_on IS NOT NULL
  ),
  CONSTRAINT statutory_remittance_paid_not_before_submitted CHECK (
    paid_on IS NULL OR paid_on >= submitted_on
  ),

  -- PT needs a state and ESI must not carry one. Enforced rather than
  -- documented: without it a PT row with no state is indistinguishable from a
  -- second Maharashtra filing, and the uniqueness below would not catch it.
  CONSTRAINT statutory_remittance_state_belongs_to_pt CHECK (
    (scheme = 'professional_tax' AND state IS NOT NULL)
    OR (scheme = 'esic' AND state IS NULL)
  ),

  -- Symmetrically: the contribution period is ESI's, and PT has none.
  CONSTRAINT statutory_remittance_contribution_period_belongs_to_esi CHECK (
    scheme = 'esic' OR contribution_period IS NULL
  )
);

-- ONE LIVE REMITTANCE PER CLIENT, SCHEME, MONTH AND STATE.
--
-- A partial index on deleted_at IS NULL, so a retracted row does not block the
-- corrected one that replaces it — the same reason public.filings uses a
-- partial unique index rather than a table constraint.
--
-- COALESCE on state because NULL is not equal to NULL in a unique index: two
-- ESI rows for one month would both be accepted without it, which is the exact
-- double-payment this table exists to prevent.
CREATE UNIQUE INDEX IF NOT EXISTS uq_statutory_remittance_live
  ON public.statutory_remittances (client_id, scheme, wage_month, COALESCE(state, ''))
  WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_statutory_remittances_client_month
  ON public.statutory_remittances (firm_id, client_id, wage_month)
  WHERE deleted_at IS NULL;

ALTER TABLE public.statutory_remittances ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "firm_reads_statutory_remittances" ON public.statutory_remittances;
CREATE POLICY "firm_reads_statutory_remittances" ON public.statutory_remittances
  FOR SELECT TO authenticated
  USING (firm_id = public.get_my_firm_id());

DROP POLICY IF EXISTS "firm_writes_statutory_remittances" ON public.statutory_remittances;
CREATE POLICY "firm_writes_statutory_remittances" ON public.statutory_remittances
  FOR INSERT TO authenticated
  WITH CHECK (firm_id = public.get_my_firm_id());

DROP POLICY IF EXISTS "firm_updates_statutory_remittances" ON public.statutory_remittances;
CREATE POLICY "firm_updates_statutory_remittances" ON public.statutory_remittances
  FOR UPDATE TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());

-- No DELETE policy and the grant revoked to match: a remittance is retracted by
-- setting deleted_at. Migration 335's reasoning applies unchanged — a hard
-- delete removes the evidence with no trace that it was ever there.
REVOKE DELETE ON public.statutory_remittances FROM authenticated;
GRANT  SELECT, INSERT, UPDATE ON public.statutory_remittances TO authenticated;

COMMIT;
