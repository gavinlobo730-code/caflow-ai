-- 482: every firm chart has an Office Equipment ledger.
--
-- WHY
--   `phase2_journal_service` books an asset of category "Office Equipment" to
--   the ledger its pattern `%Office Equipment%` finds. The chart a firm gets
--   when it onboards through the product (services/coa_seed_service.
--   STANDARD_COA) held Plant & Machinery, Furniture & Fixtures, Computers &
--   Software, Vehicles, Land & Building and Intangible Assets -- and no Office
--   Equipment. So for every firm onboarded through the app, POST /api/fixed-
--   assets with that category wrote the asset row, failed to find the ledger
--   ("Required account not found: %Office Equipment%"), and answered 500: the
--   commonest office purchase there is. The chart migration 011 seeded (the
--   Admin firm) does carry the account, at 1501; STANDARD_COA never did. Same
--   shape as migration 425, one ledger over (CWIP).
--
-- WHAT THIS DOES
--   For each firm that has a firm-level chart (client_id IS NULL) and no ACTIVE
--   firm-level ASSET ledger the engine's `%Office Equipment%` finds, inserts
--   one `Office Equipment` (Asset / Fixed Asset) at the LOWEST FREE CODE from
--   1508 to 1599 -- computed per firm, never assumed, because a fixed code is
--   what failed the first time 397 tried it for CWIP. 1508 is where
--   STANDARD_COA now seeds it for new firms, so the two agree wherever 1508 is
--   free.
--
--   INSERTS ROWS ONLY. It updates, deletes and re-codes nothing that exists,
--   moves no balance (the new ledger has no journal line) and touches no
--   system_account_key (the engine finds this ledger by name, as it finds the
--   other five fixed-asset ledgers). A firm with no firm-level chart gets
--   nothing: it has no chart to complete, and seed_firm_coa seeds the whole
--   list, this row included, the first time it runs.
--
--   "Served" is judged the way _find_account judges it -- ACTIVE, firm-level,
--   name ILIKE '%Office Equipment%' -- and only an ASSET counts. A firm whose
--   only match is an expense such as "Office Equipment Repairs" is not served:
--   the engine would debit an asset's cost to an expense, and the right ledger
--   has to exist before anyone can tell it apart.
--
--   `ON CONFLICT DO NOTHING` with NO target, deliberately: chart_of_accounts
--   carries UNIQUE (firm_id, account_code) AND UNIQUE (firm_id, account_name),
--   so a client-level or INACTIVE account already called "Office Equipment"
--   would otherwise abort the whole deploy. A firm skipped that way is left
--   exactly as it was.
--
--   The subtype 'Fixed Asset' is load-bearing, as it is on the other tangible
--   asset ledgers: schedule_iii.classify buckets on it, so the new ledger
--   presents under Property, Plant and Equipment. It has no
--   schedule_iii_mapping, so it adds one account to the "not yet mapped" count
--   on the Schedule III screen until a CA maps it (or leaves it to the subtype,
--   which already puts it in the right place).
--
--   Idempotent: re-running finds every firm already served.
--
--   Production was read on 9 Oct 2026 (read-only): two firms, both with a
--   firm-level chart, one without an Office Equipment ledger, code 1508 free in
--   both. On that data this adds exactly ONE row.

BEGIN;

WITH served AS (
  SELECT DISTINCT r.firm_id
  FROM public.chart_of_accounts r
  WHERE r.client_id IS NULL
    AND r.is_active IS TRUE
    AND r.account_type = 'Asset'
    AND r.account_name ILIKE '%Office Equipment%'
),
missing AS (
  SELECT DISTINCT c.firm_id
  FROM public.chart_of_accounts c
  WHERE c.client_id IS NULL
    AND NOT EXISTS (SELECT 1 FROM served s WHERE s.firm_id = c.firm_id)
),
picked AS (
  SELECT m.firm_id,
         (SELECT min(g)::text
            FROM generate_series(1508, 1599) AS g
           WHERE NOT EXISTS (
             SELECT 1 FROM public.chart_of_accounts x
             WHERE x.firm_id = m.firm_id AND x.account_code = g::text)) AS code
  FROM missing m
)
INSERT INTO public.chart_of_accounts
  (firm_id, client_id, account_code, account_name, account_type, account_subtype,
   is_active)
SELECT p.firm_id, NULL::uuid, p.code, 'Office Equipment',
       'Asset', 'Fixed Asset', TRUE
FROM picked p
WHERE p.code IS NOT NULL
ON CONFLICT DO NOTHING;

COMMIT;
