-- Migration 249: rebuild the reporting passbook after migration 248.
--
-- Bug this fixes
-- --------------
-- Migration 248 removed the mandatory round-off from existing invoices: it
-- reduced each affected Trade Receivables debit and DELETED the contra
-- 'Round Off' journal line. It corrected the ledger correctly — but the ledger
-- is not the only place those numbers live.
--
-- domain/reporting/balance_cache.py maintains account_period_balances, a
-- per-account, per-month "passbook" that the accrual reports read INSTEAD of
-- replaying the full posted history (domain/reporting/service.py:
-- _passbook_accrual_lines -> balance_cache.project_lines, served whenever
-- basis == 'accrual' and the passbook mode is not 'off'). 248 never touched it,
-- so the cache kept buckets built from the pre-248 ledger and the P&L kept
-- reporting a 'Round Off' expense line that no longer exists in the books.
--
-- The drift was equal and opposite — Round Off overstated by exactly what
-- Trade Receivables was overstated by — so the cached trial balance still
-- balanced and nothing alerted. It surfaced only as a phantom 'Round Off' row
-- on the Statement of Profit & Loss.
--
-- What this does
-- --------------
-- Rebuilds account_period_balances for every (firm, client) whose cached totals
-- no longer agree with the posted ledger, exactly as
-- services/balance_cache_service.recompute_client does: delete-then-insert, so
-- a bucket that should no longer exist (a Round Off one) cannot linger, and the
-- stored result is a pure function of the current ledger.
--
-- It is self-targeting rather than hard-coded to 248's invoice list: it repairs
-- whatever actually drifted. That makes it correct in any environment
-- regardless of which invoices 248 touched there, and a no-op where the cache
-- is already exact.
--
-- Bucket definition mirrors domain/reporting/balance_cache.build_buckets:
-- for every posted, non-deleted line, add its debit/credit into the
-- (account_id, month-of-entry_date) bucket.
--
-- Safety: idempotent (a second run finds no drift and rebuilds nothing),
-- scoped to drifted clients only, and guarded by a post-condition that aborts
-- the transaction if any drift remains.
--
-- Note: services/balance_cache_service.audit_and_heal_firm runs nightly and
-- would eventually have healed this on its own. That is a safety net, not a
-- licence to leave a migration half-finished — a report must not be wrong in
-- the window between a data migration and the next nightly sweep.

BEGIN;

-- Every (firm, client) whose cache disagrees with the posted ledger on any
-- account. Resolved once, up front, so the rebuild below targets a fixed set.
CREATE TEMP TABLE _mig249_drifted ON COMMIT DROP AS
WITH cache AS (
    SELECT firm_id, client_id, account_id,
           sum(debit_paise)  AS c_dr,
           sum(credit_paise) AS c_cr
      FROM public.account_period_balances
     GROUP BY firm_id, client_id, account_id
),
ledger AS (
    SELECT je.firm_id, je.client_id, jl.account_id,
           sum(jl.debit_paise)  AS l_dr,
           sum(jl.credit_paise) AS l_cr
      FROM public.journal_lines jl
      JOIN public.journal_entries je ON je.id = jl.journal_entry_id
     WHERE je.is_posted = true
       AND je.deleted_at IS NULL
     GROUP BY je.firm_id, je.client_id, jl.account_id
)
SELECT DISTINCT
       COALESCE(cache.firm_id,   ledger.firm_id)   AS firm_id,
       COALESCE(cache.client_id, ledger.client_id) AS client_id
  FROM cache
  FULL OUTER JOIN ledger
    ON  cache.firm_id    = ledger.firm_id
    AND cache.client_id  = ledger.client_id
    AND cache.account_id = ledger.account_id
 WHERE (COALESCE(c_dr, 0) - COALESCE(c_cr, 0))
    <> (COALESCE(l_dr, 0) - COALESCE(l_cr, 0));

-- A client with NO cached buckets at all has never been backfilled; that is a
-- legitimate state (the passbook falls back to the slow full-replay path), not
-- drift to repair. Only rebuild clients that actually have a passbook.
DELETE FROM _mig249_drifted d
 WHERE NOT EXISTS (
    SELECT 1 FROM public.account_period_balances b
     WHERE b.firm_id = d.firm_id AND b.client_id = d.client_id
 );

-- 1. Drop the stale buckets for exactly those clients.
DELETE FROM public.account_period_balances b
 USING _mig249_drifted d
 WHERE b.firm_id = d.firm_id
   AND b.client_id = d.client_id;

-- 2. Rebuild them from the posted ledger.
INSERT INTO public.account_period_balances
    (firm_id, client_id, account_id, period_month, debit_paise, credit_paise, updated_at)
SELECT je.firm_id,
       je.client_id,
       jl.account_id,
       date_trunc('month', je.entry_date)::date AS period_month,
       sum(jl.debit_paise)::bigint,
       sum(jl.credit_paise)::bigint,
       now()
  FROM public.journal_lines jl
  JOIN public.journal_entries je ON je.id = jl.journal_entry_id
  JOIN _mig249_drifted d
    ON d.firm_id = je.firm_id AND d.client_id = je.client_id
 WHERE je.is_posted = true
   AND je.deleted_at IS NULL
 GROUP BY je.firm_id, je.client_id, jl.account_id, date_trunc('month', je.entry_date);

-- Post-condition: the passbook must now agree with the ledger to the paise,
-- everywhere. Any residue means the rebuild is wrong — abort rather than leave
-- the reports reading a cache we have just half-corrected.
DO $verify$
DECLARE v_drift int;
BEGIN
    WITH cache AS (
        SELECT firm_id, client_id, account_id,
               sum(debit_paise) AS c_dr, sum(credit_paise) AS c_cr
          FROM public.account_period_balances
         GROUP BY firm_id, client_id, account_id
    ),
    ledger AS (
        SELECT je.firm_id, je.client_id, jl.account_id,
               sum(jl.debit_paise) AS l_dr, sum(jl.credit_paise) AS l_cr
          FROM public.journal_lines jl
          JOIN public.journal_entries je ON je.id = jl.journal_entry_id
         WHERE je.is_posted = true AND je.deleted_at IS NULL
         GROUP BY je.firm_id, je.client_id, jl.account_id
    )
    SELECT count(*) INTO v_drift
      FROM cache
      FULL OUTER JOIN ledger
        ON  cache.firm_id    = ledger.firm_id
        AND cache.client_id  = ledger.client_id
        AND cache.account_id = ledger.account_id
     WHERE (COALESCE(c_dr, 0) - COALESCE(c_cr, 0))
        <> (COALESCE(l_dr, 0) - COALESCE(l_cr, 0))
       -- Ignore clients with no passbook at all (never backfilled, see above).
       AND EXISTS (
           SELECT 1 FROM public.account_period_balances b
            WHERE b.firm_id   = COALESCE(cache.firm_id,   ledger.firm_id)
              AND b.client_id = COALESCE(cache.client_id, ledger.client_id)
       );

    IF v_drift > 0 THEN
        RAISE EXCEPTION
            'Migration 249 failed: % cached (account, client) balance(s) still '
            'disagree with the posted ledger', v_drift;
    END IF;
END
$verify$;

COMMIT;
