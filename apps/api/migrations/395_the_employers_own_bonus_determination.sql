-- 395 — the employer's §10/§11 bonus determination, per client per accounting
-- year (PAY-23).
--
-- WHAT WAS WRONG
--     `domain/payroll/bonus.py` has implemented the Payment of Bonus Act 1965
--     since the payroll module was built, and its only caller is a LEAVER'S
--     settlement. So a client's continuing employees — which is all of them,
--     most years — were never computed for at all.
--
--     That is not a reporting gap. §10 makes the minimum bonus payable
--     "whether or not the employer has any allocable surplus in the accounting
--     year", §19 makes it payable within eight months of the year's close, and
--     §28 makes non-payment an offence. It is a DEBT the balance sheet owes and
--     nothing in the product produced the figure.
--
-- WHY THERE IS A TABLE AT ALL
--     Three facts decide a bonus and none of them is in the payroll ledger.
--
--     THE RATE (§10 with §11). Bonus is 8.33% at minimum and 20% at maximum,
--     and where in that band it falls depends on the ALLOCABLE SURPLUS under
--     §§4-7 and the Second Schedule — the employer's own computation from
--     their accounts, which payroll cannot derive and must not guess. It
--     defaults to the §10 minimum, which is the figure that is owed whatever
--     the surplus turns out to be.
--
--     THE §12 MINIMUM WAGE. §12 computes bonus on ₹7,000 a month "or the
--     minimum wage for the scheduled employment, as fixed by the appropriate
--     Government, WHICHEVER IS HIGHER". There is no table of those — per
--     state, per scheduled employment, per skill grade, revised twice yearly —
--     and `domain/payroll/bonus.py` has said so since it was written. It is
--     recorded once a year instead of retyped per employee.
--
--     ⚠️ ONE FIGURE PER CLIENT-YEAR IS A STATED SIMPLIFICATION. §12's
--     comparison is per scheduled employment and per skill grade, so a client
--     with several owes several; the register applies the one recorded and
--     NAMES that limitation on every answer rather than implying a precision
--     the column does not have.
--
--     WHO IS DISQUALIFIED (§9). Dismissal for fraud, riotous or violent
--     behaviour on the premises, or theft, misappropriation or sabotage
--     forfeits the WHOLE bonus. It is a fact about a dismissal that no payroll
--     row holds, and it is per EMPLOYEE, so it lives in its own table.
--
-- WHAT IS DELIBERATELY NOT HERE
--     The computed bonus. It is derived on every read from the declaration and
--     the year's payslips, for migration 278's reason: a stored figure is
--     wrong the moment a backdated payroll run lands or the CA corrects the
--     minimum wage, and it would read as computed.
--
--     A POSTING. The provision is a journal the CA raises, the same refusal
--     `domain/gst/rule_43.py` records: the rate is the employer's own
--     determination and the account it is charged to is theirs to choose.
--
--     FORM C (Rule 4(c)) and FORM D (Rule 5) of the Payment of Bonus Rules
--     1975. The register holds the figures those forms want; the LAYOUTS are
--     published forms this environment cannot read, and a statutory form
--     written from memory is the thing this codebase refuses.

CREATE TABLE IF NOT EXISTS public.bonus_declarations (
  id                            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id                       UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id                     UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  -- §2(1): the accounting year. An FY label, YYYY-YY.
  accounting_year               TEXT NOT NULL,
  -- §10 / §11 — between 833 and 2000 basis points. DEFAULTED to the §10
  -- minimum, which is the only rate that is owed regardless of the surplus,
  -- so a declaration created before the accounts are finalised is right
  -- rather than blank.
  rate_bps                      INTEGER NOT NULL DEFAULT 833
                                CHECK (rate_bps BETWEEN 833 AND 2000),
  -- §§4-7 with the Second Schedule. RECORDED, NOT COMPUTED — it is the
  -- working behind `rate_bps` and exists so a CA can show it, not so
  -- anything derives from it. NULL where the employer paid the minimum
  -- without computing a surplus, which is lawful and common.
  allocable_surplus_paise       BIGINT,
  -- §12. NULL means not supplied, and the engine then computes on ₹7,000 and
  -- SAYS it did. No default: a default would make the ₹7,000 look chosen.
  minimum_wage_monthly_paise    BIGINT CHECK (minimum_wage_monthly_paise IS NULL
                                              OR minimum_wage_monthly_paise >= 0),
  -- What the minimum wage recorded above is the wage FOR. §12 names the
  -- "scheduled employment"; recording which one makes the simplification
  -- visible on the register instead of implicit.
  scheduled_employment          TEXT,
  notes                         TEXT,
  created_by                    UUID REFERENCES public.users(id),
  created_at                    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at                    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (firm_id, client_id, accounting_year)
);

-- §9 — dismissal for fraud, violence, theft, misappropriation or sabotage.
-- PER EMPLOYEE PER YEAR, because the disqualification attaches to the
-- accounting year in which the dismissal falls and an employee re-engaged
-- later is not disqualified for ever.
CREATE TABLE IF NOT EXISTS public.bonus_disqualifications (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id           UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id         UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  employee_id       UUID NOT NULL REFERENCES public.payroll_employees(id) ON DELETE CASCADE,
  accounting_year   TEXT NOT NULL,
  -- The Act's own five grounds. A free-text reason would let "poor
  -- performance" forfeit a statutory debt, which §9 does not permit — it
  -- reaches DISMISSAL for these causes and nothing else.
  ground            TEXT NOT NULL CHECK (ground IN (
                      'fraud',
                      'riotous_or_violent_behaviour_on_the_premises',
                      'theft_of_establishment_property',
                      'misappropriation_of_establishment_property',
                      'sabotage_of_establishment_property')),
  -- §9 forfeits on DISMISSAL for those causes, not on the conduct alone, so
  -- the date of dismissal is part of the record.
  dismissed_on      DATE NOT NULL,
  notes             TEXT,
  created_by        UUID REFERENCES public.users(id),
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (firm_id, employee_id, accounting_year)
);

CREATE INDEX IF NOT EXISTS idx_bonus_declarations_client_year
  ON public.bonus_declarations (firm_id, client_id, accounting_year);
CREATE INDEX IF NOT EXISTS idx_bonus_disqualifications_client_year
  ON public.bonus_disqualifications (firm_id, client_id, accounting_year);

ALTER TABLE public.bonus_declarations       ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.bonus_disqualifications  ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS bonus_declarations_own_firm ON public.bonus_declarations;
CREATE POLICY bonus_declarations_own_firm ON public.bonus_declarations
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());

DROP POLICY IF EXISTS bonus_disqualifications_own_firm ON public.bonus_disqualifications;
CREATE POLICY bonus_disqualifications_own_firm ON public.bonus_disqualifications
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());

-- Migration 084's assignment scoping, which its one-shot DO loop has never
-- re-run. Declared here rather than left to that loop, for the reason
-- CLAUDE.md records: six tables created since 084 were firm-wide until
-- migration 370 because nothing re-applied it. A Partner short-circuits to
-- TRUE; everyone else needs a `user_client_assignments` row.
DROP POLICY IF EXISTS bonus_declarations_assignment_scope ON public.bonus_declarations;
CREATE POLICY bonus_declarations_assignment_scope ON public.bonus_declarations
  AS RESTRICTIVE FOR ALL TO authenticated
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));

DROP POLICY IF EXISTS bonus_disqualifications_assignment_scope ON public.bonus_disqualifications;
CREATE POLICY bonus_disqualifications_assignment_scope ON public.bonus_disqualifications
  AS RESTRICTIVE FOR ALL TO authenticated
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));

GRANT SELECT, INSERT, UPDATE, DELETE ON public.bonus_declarations      TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.bonus_disqualifications TO authenticated;

COMMENT ON TABLE public.bonus_declarations IS
  'The employer''s own §10/§11 determination for one client''s accounting year '
  '(Payment of Bonus Act 1965). The RATE is where the allocable surplus under '
  '§§4-7 and the Second Schedule places them between 8.33% and 20% — the '
  'employer''s computation from their accounts, which payroll cannot derive. '
  'The §12 minimum wage is recorded here rather than retyped per employee, and '
  'ONE figure per client-year is a stated simplification: §12 compares against '
  'the minimum wage for the SCHEDULED EMPLOYMENT, so a client with several '
  'owes several, and the register names that on every answer. No computed '
  'bonus is stored — it is derived on every read, because a stored figure is '
  'wrong the moment a backdated payroll run lands.';
COMMENT ON TABLE public.bonus_disqualifications IS
  '§9 of the Payment of Bonus Act 1965 — forfeiture of the WHOLE bonus on '
  'DISMISSAL for fraud, riotous or violent behaviour on the premises, or '
  'theft, misappropriation or sabotage of the establishment''s property. The '
  'ground is CHECKed to those five: a free-text reason would let "poor '
  'performance" forfeit a statutory debt, which §9 does not reach. Per '
  'accounting year, because an employee re-engaged later is not disqualified '
  'for ever.';
