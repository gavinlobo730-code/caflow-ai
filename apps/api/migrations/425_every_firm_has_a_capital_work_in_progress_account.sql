-- 425: every firm has a Capital Work-in-Progress account.
--
-- WHY
--   Migration 397 seeded the CWIP ledger at code 1504 with
--   `ON CONFLICT ON CONSTRAINT chart_of_accounts_firm_code_unique DO NOTHING`,
--   and its own comment chose 1504 because "1501-1503 are Office Equipment,
--   Computers & Laptops and Furniture & Fixtures (migration 011)". That is the
--   chart migration 011 seeded. It is NOT the chart a firm gets when it
--   onboards through the product: services/coa_seed_service.STANDARD_COA has
--   1501-1506 as Plant & Machinery .. Intangible Assets, with 1504 = VEHICLES.
--   So for every firm onboarded through the app the insert collided and was
--   skipped silently -- exactly the failure 397's comment says it was written
--   to avoid, one table away.
--
--   Measured on 28-09-2026: of the two firms in production, the Admin firm
--   (chart from migration 011) has its CWIP account and "Test Firm" (chart
--   from STANDARD_COA) has none. Every CWIP addition there then fails at
--   `_find_account(..., "%Capital Work-in-Progress%", system_key="cwip")`, the
--   tranche is saved and never posted, and the Schedule III CWIP line cannot
--   tie to the ageing schedule it exists for.
--
-- WHAT THIS DOES
--   For each firm with a firm-level chart and no account the posting engine
--   could find (system key 'cwip', or a name matching its ILIKE fallback),
--   inserts one at the LOWEST FREE CODE from 1507 to 1599 -- computed per firm
--   rather than assumed, because a fixed code is what failed the first time.
--   1507 is where STANDARD_COA now seeds it for new firms, so the two agree
--   wherever 1507 is free.
--
--   `ON CONFLICT DO NOTHING` with NO target, deliberately: chart_of_accounts
--   also has UNIQUE (firm_id, account_name), and a client-level account of
--   the same name would otherwise abort the whole deploy. A firm skipped that
--   way already has an account the name fallback can find.
--
--   The subtype 'Capital Work-in-Progress' is load-bearing, as in 397:
--   schedule_iii.classify buckets on it.
--
--   Idempotent: re-running finds every firm already served.

BEGIN;

WITH served AS (
  SELECT DISTINCT r.firm_id
  FROM public.chart_of_accounts r
  WHERE r.system_account_key = 'cwip'
     OR r.account_name ILIKE '%Capital Work-in-Progress%'
),
missing AS (
  SELECT DISTINCT c.firm_id
  FROM public.chart_of_accounts c
  WHERE c.client_id IS NULL
    AND c.firm_id NOT IN (SELECT firm_id FROM served)
),
picked AS (
  SELECT m.firm_id,
         (SELECT min(g)::text
            FROM generate_series(1507, 1599) AS g
           WHERE NOT EXISTS (
             SELECT 1 FROM public.chart_of_accounts x
             WHERE x.firm_id = m.firm_id AND x.account_code = g::text)) AS code
  FROM missing m
)
INSERT INTO public.chart_of_accounts
  (firm_id, client_id, account_code, account_name, account_type, account_subtype,
   is_active, system_account_key)
SELECT p.firm_id, NULL::uuid, p.code, 'Capital Work-in-Progress',
       'Asset', 'Capital Work-in-Progress', TRUE, 'cwip'
FROM picked p
WHERE p.code IS NOT NULL
ON CONFLICT DO NOTHING;

COMMIT;
