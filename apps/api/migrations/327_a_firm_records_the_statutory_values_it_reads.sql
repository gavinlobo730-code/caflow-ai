-- Migration 327: a firm records the state statutory figures IT reads, and the
-- payroll run uses them.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- THE PROBLEM THIS SOLVES, WHICH IS COMMERCIAL AS MUCH AS TECHNICAL
-- ═══════════════════════════════════════════════════════════════════════════
-- Professional tax is levied by twenty-two states, each setting its own slabs
-- by its own notification, revised on its own cycle.
--
-- domain/payroll/professional_tax.py models FOUR of the twenty-two. It says so
-- rather than returning a silent zero: an employee in Gujarat comes back as a
-- named gap on the run, not as a nil deduction. That refusal is correct and it
-- is not going away.
--
-- What it is not is a product. A CA whose client has staff in Telangana is told
-- the software cannot compute a deduction the employer is liable for, and the
-- only remedy on offer is that somebody edits Python. Writing the other
-- eighteen states' slabs from memory would put eighteen confidently wrong
-- deductions into people's pay, and maintaining them against notification
-- cycles is a compliance research desk this product has no revenue to fund.
--
-- So the CA records what they READ. One firm-scoped table per figure, each row
-- carrying the notification it came from, its date and who entered it —
-- recorded once and reused across every client of that firm. The marginal cost
-- of the next state becomes zero, for us and very nearly for them.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- PROVENANCE IS NOT DECORATION — IT IS WHY THE FIGURE CAN BE USED AT ALL
-- ═══════════════════════════════════════════════════════════════════════════
-- notification_reference and notification_date are NOT NULL on both tables.
--
-- The whole argument for letting a hand-entered number drive a statutory
-- deduction is that a named person read a named notification on a named date.
-- A row without that is an unsourced number in a payslip, which is what the
-- refusals in professional_tax.py and lwf.py exist to prevent — it would be
-- the same fault with a nicer interface. Both are printed beside the computed
-- figure on the register, so the reviewer sees the authority, not just the
-- amount.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- A FIRM SLAB FILLS A GAP; IT DOES NOT OVERRIDE A MODELLED STATE
-- ═══════════════════════════════════════════════════════════════════════════
-- Maharashtra, Tamil Nadu, Karnataka and West Bengal are modelled in code,
-- verified against the state Act and pinned by tests — including Maharashtra's
-- February differential and women's exemption and Tamil Nadu's half-yearly
-- levy, which are not expressible as plain slabs.
--
-- For those four the CODE wins, and a firm row recorded against one of them is
-- REPORTED rather than silently ignored or silently applied. Silently applying
-- would let one typo replace a tested table for every client of the firm;
-- silently ignoring would leave a CA believing they had fixed something.
-- Naming the disagreement is the only option that cannot mislead: a state
-- notification that has genuinely moved is then a code change somebody knows
-- to make.
--
-- The gap this migration exists to close is the EIGHTEEN unmodelled states, and
-- it closes those completely.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT IS DELIBERATELY NOT A COLUMN
-- ═══════════════════════════════════════════════════════════════════════════
-- No gender column, and no general rule engine. Maharashtra's women's exemption
-- and its February rate are real, and they are also the reason MH stays in code:
-- adding a dimension per state quirk is how a slab table becomes a formula
-- engine, which is the classic payroll trap and is on this design's
-- deliberately-not-built list. A state whose rule does not fit
-- (from, to, amount, months) needs code, and the run says so rather than
-- computing something plausible.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHY PROFESSIONAL TAX AND NOT ALSO THE LABOUR WELFARE FUND
-- ═══════════════════════════════════════════════════════════════════════════
-- Both are refused for the same reason and both belong to this mechanism, but
-- PT already has somewhere to go: payroll_slips.pt_paise, a general-ledger leg
-- and a line on the payslip. Recording a PT slab therefore turns a gap into a
-- deduction the same day.
--
-- LWF has none of that — this system has never deducted it anywhere — so its
-- table arrives WITH the slip column, the journal leg and the payslip line
-- that make a recorded amount actually come out of somebody's pay. Shipping
-- the table first would give a CA a screen that records figures nothing reads,
-- which looks like the gap is closed and is not.
--
-- Idempotent, safe to re-run. One new table and nothing altered.

BEGIN;

-- ═══════════════════════════════════════════════════════════════════════════
-- 1. Professional tax slabs, as the firm read them
-- ═══════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS public.firm_pt_slabs (
  id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id  uuid NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,

  -- The two-letter code payroll_employees.pt_state carries and
  -- domain/payroll/professional_tax.py classifies.
  state text NOT NULL CHECK (state ~ '^[A-Z]{2}$'),

  -- The date the notification takes effect, NOT the date it was entered. A
  -- payroll month uses the latest slab set effective on or before its month
  -- end, so a mid-year revision applies from the right month rather than from
  -- whenever somebody got round to typing it.
  effective_from date NOT NULL,

  -- 'monthly'      the slab is read against the month's gross (the common case)
  -- 'half_yearly'  the slab is read against six months' gross, and is deducted
  --                only in `months` — Tamil Nadu's shape, recorded here so a
  --                state that shares it does not need code.
  basis text NOT NULL DEFAULT 'monthly'
       CHECK (basis IN ('monthly', 'half_yearly')),

  -- Inclusive lower bound, exclusive-of-nothing upper bound. to_paise NULL is
  -- the top slab: "and above". Integer paise throughout, as everything in this
  -- schema is.
  from_paise   bigint NOT NULL CHECK (from_paise >= 0),
  to_paise     bigint CHECK (to_paise IS NULL OR to_paise > from_paise),
  amount_paise bigint NOT NULL CHECK (amount_paise >= 0),

  -- The calendar months (1-12) this row applies in. NULL means every month.
  -- Non-null covers a differential month or a half-yearly deduction.
  months smallint[] CHECK (
    months IS NULL
    OR (array_length(months, 1) BETWEEN 1 AND 12
        AND months <@ ARRAY[1,2,3,4,5,6,7,8,9,10,11,12]::smallint[])),

  -- The authority. NOT NULL on purpose — see the header.
  notification_reference text NOT NULL CHECK (length(btrim(notification_reference)) > 0),
  notification_date      date NOT NULL,

  note        text,
  recorded_by uuid REFERENCES public.users(id),
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),

  -- One row per band per version. Two rows starting at the same figure in the
  -- same version would make the lookup order-dependent.
  UNIQUE (firm_id, state, effective_from, from_paise)
);

COMMENT ON TABLE public.firm_pt_slabs IS
    'Professional-tax slabs a firm has read off a state notification and '
    'recorded, reusable across every client of that firm. Used ONLY for states '
    'domain/payroll/professional_tax.py does not model — MH, TN, KA and WB are '
    'verified in code and win; a row recorded against one of them is reported '
    'on the run rather than applied. notification_reference and '
    'notification_date are NOT NULL because an unsourced number driving a '
    'statutory deduction is the fault the refusals exist to prevent. '
    'Migration 327.';

COMMENT ON COLUMN public.firm_pt_slabs.effective_from IS
    'When the notification takes effect — not when it was typed. A payroll '
    'month uses the latest set effective on or before its month end.';

COMMENT ON COLUMN public.firm_pt_slabs.months IS
    'Calendar months (1-12) this band applies in; NULL means all twelve. '
    'Covers a differential month or a half-yearly deduction without adding a '
    'rule engine.';

CREATE INDEX IF NOT EXISTS firm_pt_slabs_lookup_idx
  ON public.firm_pt_slabs (firm_id, state, effective_from DESC);

-- ═══════════════════════════════════════════════════════════════════════════
-- 2. Access
-- ═══════════════════════════════════════════════════════════════════════════
-- Firm-scoped, and Manager+ to write. These figures drive a deduction from
-- somebody's pay across every client of the firm at once, so the blast radius
-- of a typo here is larger than anything else in payroll — larger than the
-- statutory identity of migration 325, which is per client.
--
-- RESTRICTIVE so the role policies NARROW the firm policy. A permissive one
-- would OR with it and widen access, which reads identically in pg_policies.

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['firm_pt_slabs'] LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);

    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', 'firm_' || t, t);
    EXECUTE format(
      'CREATE POLICY %I ON public.%I FOR ALL TO authenticated '
      'USING (firm_id = public.get_my_firm_id()) '
      'WITH CHECK (firm_id = public.get_my_firm_id())', 'firm_' || t, t);

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

    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON public.%I TO authenticated', t);

    IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'update_updated_at_column'
                                       AND pronamespace = 'public'::regnamespace) THEN
      EXECUTE format('DROP TRIGGER IF EXISTS %I ON public.%I', t || '_updated_at', t);
      EXECUTE format(
        'CREATE TRIGGER %I BEFORE UPDATE ON public.%I '
        'FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column()',
        t || '_updated_at', t);
    END IF;
  END LOOP;
END $$;

COMMIT;
