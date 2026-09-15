-- 397 — capital work-in-progress: its own balance-sheet line, its own ageing
-- schedule, and the reason an asset under construction must not depreciate
-- (FA-11a).
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═══════════════════════════════════════════════════════════════════════════
-- There is no CWIP anywhere in this product. `fixed_assets` is the only place
-- an asset can live, and everything in it is depreciated. So a client building
-- a factory had two choices and both were wrong:
--
--   * leave it out of the register, and the balance sheet is short by the
--     whole of what has been spent on it; or
--   * put it in, and `_compute_annual_depreciation` charges depreciation on an
--     asset that is not ready for use — which overstates the expense, understates
--     the asset, and understates the depreciation of every later year because
--     the written-down value starts lower.
--
-- AS-10 paragraph 20 and Schedule II are agreed on the rule: depreciation
-- begins when the asset is available for use, in the location and condition
-- necessary for it to operate as management intends. Migration 357 already
-- added `put_to_use_date` for the second half of that; nothing held the first.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- AND IT IS A DISCLOSURE, NOT A CONVENIENCE
-- ═══════════════════════════════════════════════════════════════════════════
-- MCA Notification G.S.R. 207(E) of 24 March 2021 — the SAME notification that
-- added the two ageing schedules migration 303 built — did three things to
-- CWIP in Schedule III Division I:
--
--   * it is a line of its own under Non-current assets, immediately after
--     Property, Plant and Equipment, and is never merged into it;
--   * an AGEING SCHEDULE in the notes: the amount in CWIP for less than 1
--     year, 1-2 years, 2-3 years and more than 3 years, with the total split
--     between "Projects in progress" and "Projects temporarily suspended";
--   * a COMPLETION SCHEDULE for every project overdue against its originally
--     approved completion date OR over its originally approved cost — in the
--     same four bands, of when it is now expected to finish.
--
-- Disclosure is at the TOTAL level rather than per project, but it has to
-- reconcile to the CWIP figure in the financial statements, which is what
-- makes a real ledger account below load-bearing rather than presentational.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHY TWO TABLES, AND WHY THE ADDITION CARRIES THE DATE
-- ═══════════════════════════════════════════════════════════════════════════
-- "The amount in CWIP for a period of less than 1 year" ages MONEY, not
-- projects: a factory started three years ago whose last contractor bill
-- arrived last month has amounts in three different buckets at once. A single
-- `cost_paise` on a project could not be aged at all, and a project-level date
-- would put every rupee of a long build in the oldest band.
--
-- So `cwip_additions` is the cost, one row per tranche, each with its own
-- `incurred_on`. That is also simply what a construction account IS: a
-- contractor's running bill, materials, a professional fee, an interest cost
-- capitalised under AS-16 — accumulated until the asset is ready.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- CAPITALISATION IS A ONE-WAY DOOR AND IT CREATES THE ASSET
-- ═══════════════════════════════════════════════════════════════════════════
-- When the project is ready, the accumulated cost becomes a `fixed_assets` row
-- whose `put_to_use_date` is the date it became ready, and depreciation starts
-- there — through the register that already exists, with no second
-- depreciation path. `capitalised_asset_id` records which asset it became, so
-- the CWIP note as at an EARLIER date can still see the project (it was CWIP
-- then) while the register sees the asset (it is an asset now). The same
-- as-at-a-date discipline `stock_position_as_at` uses.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT IS REFUSED RATHER THAN GUESSED
-- ═══════════════════════════════════════════════════════════════════════════
--   `approved_completion_date` and `approved_cost_paise` are NULLABLE with no
--   default. The completion schedule reaches a project that is OVERDUE against
--   its originally approved date or OVER its originally approved cost; with
--   neither recorded, nobody can say whether it is either. Defaulting the date
--   to the start would report every project as overdue on day two, and
--   defaulting the cost to what has been spent would report none as over ever.
--   So the project is NAMED as undeterminable and the CA records the approval.
--
--   `expected_completion_date` is separate from the approved one and also
--   nullable: the schedule asks when an overdue project is NOW expected to
--   finish, which is a fresh judgement rather than the original promise.

BEGIN;

CREATE TABLE IF NOT EXISTS public.capital_work_in_progress (
  id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id                  UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id                UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,

  project_code             TEXT,
  project_name             TEXT NOT NULL,

  -- What it will BE, so capitalisation knows which asset account and which
  -- Schedule II Part C life to carry across. Same vocabulary as
  -- fixed_assets.asset_category.
  asset_category           TEXT,

  started_on               DATE NOT NULL,

  -- The ORIGINAL approval, which is what the completion schedule measures
  -- against. Nullable and not defaulted — see the header.
  approved_completion_date DATE,
  approved_cost_paise      BIGINT CHECK (approved_cost_paise IS NULL OR approved_cost_paise > 0),
  -- When it is NOW expected to finish. A different fact from the approval.
  expected_completion_date DATE,

  -- 'in_progress' and 'suspended' are the two Schedule III presents; the other
  -- two are terminal and take the project out of CWIP.
  status                   TEXT NOT NULL DEFAULT 'in_progress'
                           CHECK (status IN ('in_progress', 'suspended',
                                             'capitalised', 'abandoned')),
  -- Schedule III asks which projects are temporarily suspended AS AT the
  -- reporting date, so the date the status last moved is part of the answer.
  status_changed_on        DATE,

  capitalised_on           DATE,
  capitalised_asset_id     UUID REFERENCES public.fixed_assets(id) ON DELETE SET NULL,
  capitalisation_journal_entry_id UUID REFERENCES public.journal_entries(id) ON DELETE SET NULL,

  notes                    TEXT,
  created_by               UUID REFERENCES public.users(id),
  created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at               TIMESTAMPTZ,
  deleted_at               TIMESTAMPTZ,

  -- A project is capitalised or it is not; the two columns and the status must
  -- agree, or the note and the register disagree about the same project.
  CONSTRAINT cwip_capitalised_carries_its_date
    CHECK ((status = 'capitalised' AND capitalised_on IS NOT NULL)
        OR (status <> 'capitalised' AND capitalised_on IS NULL)),
  CONSTRAINT cwip_project_code_unique_per_client
    UNIQUE (client_id, project_code)
);

CREATE TABLE IF NOT EXISTS public.cwip_additions (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id             UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id           UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  cwip_id             UUID NOT NULL REFERENCES public.capital_work_in_progress(id) ON DELETE CASCADE,

  -- THE COLUMN THE AGEING SCHEDULE IS BUILT ON. Not the project's start date
  -- and not the posting date: the note ages the MONEY, and a factory begun
  -- three years ago whose last bill arrived last month has amounts in three
  -- bands at once.
  incurred_on         DATE NOT NULL,
  description         TEXT NOT NULL,
  amount_paise        BIGINT NOT NULL CHECK (amount_paise > 0),

  -- Tax on the tranche. Same shape as fixed_assets (migration 343) and for the
  -- same reason: credit barred by CGST s.17(5) is recoverable from nobody, so
  -- AS-10 paragraph 9 puts it in the cost of the asset, while eligible tax is
  -- a credit and is not.
  igst_paise          BIGINT NOT NULL DEFAULT 0,
  cgst_paise          BIGINT NOT NULL DEFAULT 0,
  sgst_paise          BIGINT NOT NULL DEFAULT 0,
  itc_eligible        BOOLEAN,
  itc_blocked_reason  TEXT,

  -- Where the money came from, mirroring the acquisition path so the credit
  -- side is resolved by the one `resolve_payment_account` rather than guessed.
  acquisition_mode    TEXT CHECK (acquisition_mode IS NULL
                                  OR acquisition_mode IN ('paid', 'credit', 'from_bill')),
  vendor_id           UUID REFERENCES public.vendors(id) ON DELETE SET NULL,
  purchase_bill_id    UUID REFERENCES public.purchase_bills(id) ON DELETE SET NULL,
  bank_account_id     UUID REFERENCES public.bank_accounts(id) ON DELETE SET NULL,
  payment_mode        TEXT,

  journal_entry_id    UUID REFERENCES public.journal_entries(id) ON DELETE SET NULL,

  notes               TEXT,
  created_by          UUID REFERENCES public.users(id),
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at          TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_cwip_client ON public.capital_work_in_progress (firm_id, client_id);
CREATE INDEX IF NOT EXISTS idx_cwip_open ON public.capital_work_in_progress (firm_id, client_id)
  WHERE deleted_at IS NULL AND status IN ('in_progress', 'suspended');
CREATE INDEX IF NOT EXISTS idx_cwip_additions_project ON public.cwip_additions (cwip_id);
CREATE INDEX IF NOT EXISTS idx_cwip_additions_incurred ON public.cwip_additions (firm_id, client_id, incurred_on);

ALTER TABLE public.capital_work_in_progress ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.cwip_additions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS cwip_own_firm ON public.capital_work_in_progress;
CREATE POLICY cwip_own_firm ON public.capital_work_in_progress
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());

DROP POLICY IF EXISTS cwip_additions_own_firm ON public.cwip_additions;
CREATE POLICY cwip_additions_own_firm ON public.cwip_additions
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());

-- Migration 084's assignment scoping, declared here rather than left to its
-- one-shot DO loop, which has never re-run (CLAUDE.md).
DROP POLICY IF EXISTS cwip_assignment_scope ON public.capital_work_in_progress;
CREATE POLICY cwip_assignment_scope ON public.capital_work_in_progress
  AS RESTRICTIVE FOR ALL TO authenticated
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));

DROP POLICY IF EXISTS cwip_additions_assignment_scope ON public.cwip_additions;
CREATE POLICY cwip_additions_assignment_scope ON public.cwip_additions
  AS RESTRICTIVE FOR ALL TO authenticated
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));

GRANT SELECT, INSERT, UPDATE, DELETE ON public.capital_work_in_progress TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.cwip_additions TO authenticated;

-- ═══════════════════════════════════════════════════════════════════════════
-- THE LEDGER ACCOUNT
-- ═══════════════════════════════════════════════════════════════════════════
-- Schedule III presents CWIP on its OWN line, so it needs its own account: a
-- balance inside Plant & Machinery would be presented as PP&E and depreciated
-- in every reader's mind, which is the whole defect.
--
-- CODE 1504 because 1501-1503 are Office Equipment, Computers & Laptops and
-- Furniture & Fixtures (migration 011) and `ON CONFLICT DO NOTHING` would have
-- silently skipped a collision — an account nobody could find rather than an
-- error anybody would see. Migration 389's lesson, applied.
--
-- SUBTYPE 'Capital Work-in-Progress' is LOAD-BEARING: `schedule_iii.classify`
-- buckets on the subtype, and this is the string its new caption resolves
-- from. NOT 'Fixed Asset', which would fold the balance into Tangible Fixed
-- Assets and undo the presentation this migration exists for.
INSERT INTO public.chart_of_accounts
  (firm_id, client_id, account_code, account_name, account_type, account_subtype,
   is_active, system_account_key)
SELECT DISTINCT c.firm_id, NULL::uuid, '1504', 'Capital Work-in-Progress',
       'Asset', 'Capital Work-in-Progress', TRUE, 'cwip'
FROM public.chart_of_accounts c
WHERE c.client_id IS NULL
  AND NOT EXISTS (
    SELECT 1 FROM public.chart_of_accounts r
    WHERE r.firm_id = c.firm_id
      AND r.client_id IS NULL
      AND (r.system_account_key = 'cwip'
           OR r.account_name ILIKE 'Capital Work-in-Progress')
  )
ON CONFLICT ON CONSTRAINT chart_of_accounts_firm_code_unique DO NOTHING;

UPDATE public.chart_of_accounts
   SET system_account_key = 'cwip'
 WHERE client_id IS NULL
   AND system_account_key IS NULL
   AND account_name ILIKE 'Capital Work-in-Progress';

COMMENT ON TABLE public.capital_work_in_progress IS
  'An asset under construction. Schedule III Division I (as amended by MCA '
  'G.S.R. 207(E) of 24-03-2021) gives capital work-in-progress its own line '
  'under Non-current assets, an ageing schedule in the notes, and a completion '
  'schedule for any project overdue against its originally approved completion '
  'date or over its originally approved cost. It is NOT a fixed_assets row: '
  'AS-10 paragraph 20 starts depreciation when the asset is available for use, '
  'and everything in fixed_assets is depreciated. Capitalisation creates the '
  'asset, with put_to_use_date as the date it became ready.';
COMMENT ON COLUMN public.capital_work_in_progress.approved_completion_date IS
  'The ORIGINALLY approved completion date, which is what the Schedule III '
  'completion schedule measures "overdue" against. Nullable with no default: '
  'defaulting it to the start date would report every project as overdue on '
  'day two. A project with none recorded is NAMED as undeterminable.';
COMMENT ON COLUMN public.capital_work_in_progress.approved_cost_paise IS
  'The ORIGINALLY approved cost. Nullable with no default, for the mirror-image '
  'reason: defaulting it to what has been spent reports no project as over '
  'budget, ever.';
COMMENT ON TABLE public.cwip_additions IS
  'One tranche of cost on a project under construction — a contractor''s '
  'running bill, materials, a professional fee. `incurred_on` is what the '
  'Schedule III ageing schedule ages: the note ages the MONEY, so a build begun '
  'three years ago whose last bill arrived last month has amounts in three '
  'bands at once, and a single project-level date would put all of it in the '
  'oldest.';

COMMIT;
