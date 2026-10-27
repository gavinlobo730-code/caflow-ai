-- Migration 553: an intangible asset can name the ledger its accumulated amortisation is kept in (POST-A-345, stage 1 of 3).
--
-- WHY
--
-- Every fixed asset's depreciation is credited to ONE ledger, the firm's "Accumulated Depreciation" (code 1590, subtype 'Fixed Asset'
-- or 'Contra Asset'). On the standard chart that ledger sits on the TANGIBLE line of Schedule III, so the accumulated amortisation of
-- an intangible asset (software, a licence, goodwill) is shown against property, plant and equipment: the tangible line is understated
-- by exactly what the intangible line is overstated by, and the ITR-3, ITR-5 and ITR-6 Part A split of the fixed-asset register
-- (POST-A-344) cannot tie to the books and says so ("withheld"). Nothing is wrong with the totals; the two lines are wrong by the same
-- sum in opposite directions.
--
-- WHAT THIS STAGE DOES, AND DOES NOT
--
-- It adds the two facts a later change needs and changes no behaviour. NOTHING READS OR WRITES EITHER FACT YET (stage 2 teaches the
-- depreciation and disposal journals to read the first; stage 3 adds the writers and the reclassification a Partner posts), so a
-- deploy of the code before this migration is not affected and a rollback of the code after it is safe until stage 3.
--
--   1. `fixed_assets.accumulated_account_id` names the ledger an asset's accumulated depreciation is credited to and its disposal
--      debits. NULL, which is every existing row and the default, means what it has always meant: the shared Accumulated Depreciation
--      ledger found by pattern. It is a POINTER, not a flag, so that a rename or a re-code of the ledger cannot make the asset
--      forget where its history is, and so that the entry that moved it can be joined to it. ON DELETE RESTRICT: a ledger an asset
--      points at cannot be deleted from under it. No default, no backfill, no CHECK that could refuse an existing row.
--
--   2. Each firm that keeps an Intangible Assets ledger gets an "Accumulated Amortisation" ledger beside it (Asset, firm-level, the
--      lowest free code from 1591 to 1599, computed per firm and never assumed: a fixed code is what failed 397 for CWIP). It carries
--      NO balance and NO journal line; it only exists to be pointed at.
--
--      ITS SUBTYPE IS LOAD-BEARING TWICE. `schedule_iii.classify` buckets on it, so it must land on the same Schedule III line as the
--      cost ledger it amortises; and the cash-flow statement (both the Python builder and `public.cash_flow_report`) treats an Asset
--      as INVESTING only when its subtype contains "fixed". The cost ledger's own subtype is 'Intangible Asset' (migration 208),
--      which contains neither "fixed" nor anything the cash-flow classifier reads, so an amortisation entry credited to a ledger of
--      THAT subtype is a working-capital movement and the statement stops reconciling (reproduced by an independent review on
--      27-10-2026). So the new ledger takes the subtype 'Intangible Fixed Asset': `classify` tests "intangible" first, so it is on the
--      intangible line, and it contains "fixed", so the cash-flow statement keeps it investing, exactly as the shared ledger is today.
--      Where the firm's cost ledger is NOT on the intangible line (migration 093 seeded 'Intangible Assets' with subtype 'Fixed
--      Asset' on an older chart), the new ledger copies the cost ledger's subtype, so the pair classify identically by construction,
--      and the later stages route an asset to it only when the two agree.
--      The cost ledger's own cash-flow classification (a bank-paid intangible purchase reads as an OPERATING outflow) is NOT touched
--      here and is a separate ledger item for a chartered accountant to confirm against AS 3.
--      The cost ledger's `schedule_iii_mapping` is copied (NULL stays NULL), so a CA's own mapping, which outranks the subtype, applies
--      to both.
--
--      "Served" is judged the way `_find_account` judges it (ACTIVE, firm-level, Asset, name ILIKE '%Accumulated Amortisation%'). A
--      firm with a firm-level chart that is not served after the insert is named in a WARNING with the reason (no Intangible Assets
--      ledger to copy from, or no free code or the name already taken), because `ON CONFLICT DO NOTHING` with no target, which is
--      deliberate (UNIQUE (firm_id, account_code) and UNIQUE (firm_id, account_name) both exist, so a client-level or inactive account
--      of the same name would otherwise abort the whole deploy), would otherwise skip it in silence. The name does not contain
--      "Intangible Assets" or "Accumulated Depreciation", so neither of the two patterns the engine already searches can find it.
--
-- Each practice's chart gains one empty ledger, no balance moves, and the Schedule III mapping screen's "not yet mapped" count rises
-- by one for each practice whose cost ledger has no mapping (migration 482 recorded the same effect).
--
-- NOT HERE: any change to the posting code, the depreciation or disposal journals, the register, a screen, or the cash-flow
-- classifier; and the reclassification of amortisation already credited to the shared ledger, which is a Partner's posting, dated
-- by a Partner, and arrives in stage 3.
--
-- Production was not read for this migration; the migration reads what it finds and says what it skipped.

DO $$
BEGIN
  -- Never queue behind a long-running transaction while holding a lock the API's every read of these tables is waiting for.
  PERFORM set_config('lock_timeout', '10s', true);
END $$;

ALTER TABLE public.fixed_assets
    ADD COLUMN IF NOT EXISTS accumulated_account_id uuid REFERENCES public.chart_of_accounts (id) ON DELETE RESTRICT;

-- The foreign key is checked from the chart's side whenever a ledger is deleted, and only the assets that point somewhere matter.
CREATE INDEX IF NOT EXISTS fixed_assets_accumulated_account_idx
    ON public.fixed_assets (accumulated_account_id)
    WHERE accumulated_account_id IS NOT NULL;

COMMENT ON COLUMN public.fixed_assets.accumulated_account_id IS
    'The ledger this asset''s accumulated depreciation is credited to, and its disposal debits. NULL = the shared Accumulated '
    'Depreciation ledger found by pattern (every asset before POST-A-345). Set only by the intangible-amortisation change, together '
    'with the entry that moved the asset''s history; written by the API alone.';

WITH cost AS (
  -- The firm's own ledger intangible assets are debited to: the engine's `%Intangible Assets%`, ACTIVE, firm-level, an Asset, with a
  -- subtype to copy. The lowest code if there are two.
  SELECT DISTINCT ON (c.firm_id) c.firm_id, c.account_subtype, c.schedule_iii_mapping
  FROM public.chart_of_accounts c
  WHERE c.firm_id IS NOT NULL
    AND c.client_id IS NULL
    AND c.is_active IS TRUE
    AND c.account_type = 'Asset'
    AND c.account_subtype IS NOT NULL
    AND c.account_name ILIKE '%Intangible Assets%'
  ORDER BY c.firm_id, c.account_code
),
served AS (
  SELECT DISTINCT r.firm_id
  FROM public.chart_of_accounts r
  WHERE r.client_id IS NULL
    AND r.is_active IS TRUE
    AND r.account_type = 'Asset'
    AND r.account_name ILIKE '%Accumulated Amortisation%'
),
picked AS (
  SELECT k.firm_id, k.account_subtype, k.schedule_iii_mapping,
         (SELECT min(g)::text
            FROM generate_series(1591, 1599) AS g
           WHERE NOT EXISTS (
             SELECT 1 FROM public.chart_of_accounts x
             WHERE x.firm_id = k.firm_id AND x.account_code = g::text)) AS code
  FROM cost k
  WHERE NOT EXISTS (SELECT 1 FROM served s WHERE s.firm_id = k.firm_id)
)
INSERT INTO public.chart_of_accounts
  (firm_id, client_id, account_code, account_name, account_type, account_subtype, schedule_iii_mapping, is_active)
SELECT p.firm_id, NULL::uuid, p.code, 'Accumulated Amortisation', 'Asset',
       CASE WHEN p.account_subtype ILIKE '%intangible%' THEN 'Intangible Fixed Asset' ELSE p.account_subtype END,
       p.schedule_iii_mapping, TRUE
FROM picked p
WHERE p.code IS NOT NULL
ON CONFLICT DO NOTHING;

-- Say which firms were not given the ledger and why: a silent skip would leave that firm unable to use the feature with nobody knowing.
DO $$
DECLARE
  f RECORD;
BEGIN
  FOR f IN
    SELECT DISTINCT c.firm_id,
           EXISTS (SELECT 1 FROM public.chart_of_accounts i
                   WHERE i.firm_id = c.firm_id AND i.client_id IS NULL AND i.is_active IS TRUE
                     AND i.account_type = 'Asset' AND i.account_subtype IS NOT NULL
                     AND i.account_name ILIKE '%Intangible Assets%') AS has_cost_ledger
    FROM public.chart_of_accounts c
    WHERE c.firm_id IS NOT NULL
      AND c.client_id IS NULL
      AND NOT EXISTS (SELECT 1 FROM public.chart_of_accounts r
                      WHERE r.firm_id = c.firm_id AND r.client_id IS NULL AND r.is_active IS TRUE
                        AND r.account_type = 'Asset' AND r.account_name ILIKE '%Accumulated Amortisation%')
  LOOP
    RAISE WARNING 'migration 553: firm % was not given an Accumulated Amortisation ledger: %', f.firm_id,
      CASE WHEN f.has_cost_ledger
           THEN 'codes 1591 to 1599 are all taken, or an inactive or client-level account already has that name'
           ELSE 'it has no active firm-level Intangible Assets ledger (with a subtype) to take its subtype from' END;
  END LOOP;
END $$;

NOTIFY pgrst, 'reload schema';
