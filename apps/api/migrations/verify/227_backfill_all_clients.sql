-- One-time backfill of the reporting passbook (account_period_balances) for ALL
-- existing clients. Run ONCE, after migration 228's triggers are live (so this
-- and the triggers can't race to a wrong value: this statement sets ABSOLUTE
-- bucket values, overwriting any partial a trigger added while it ran).
--
-- It is a pure GROUP BY of the posted ledger — the exact bucket definition proven
-- (0 mismatches, identical totals) against the 12k-entry client. Safe to re-run:
-- ON CONFLICT overwrites, so a second run just re-sets the same values.
--
-- Requires DML approval (writes to a money-derived cache). After it runs, the
-- nightly balance_cache_audit job keeps every client's buckets verified/healed.
INSERT INTO public.account_period_balances
  (firm_id, client_id, account_id, period_month, debit_paise, credit_paise, updated_at)
SELECT je.firm_id, je.client_id, jl.account_id,
       date_trunc('month', je.entry_date)::date,
       sum(jl.debit_paise), sum(jl.credit_paise), now()
FROM public.journal_entries je
JOIN public.journal_lines jl ON jl.journal_entry_id = je.id
WHERE je.is_posted = true AND je.deleted_at IS NULL
GROUP BY je.firm_id, je.client_id, jl.account_id, date_trunc('month', je.entry_date)
ON CONFLICT (firm_id, client_id, account_id, period_month)
DO UPDATE SET debit_paise  = EXCLUDED.debit_paise,
              credit_paise = EXCLUDED.credit_paise,
              updated_at   = now();

-- Post-backfill sanity: bucket-summed trial balance == raw for one known client.
-- (Replace the client id; expect mismatched_accounts = 0.)
-- WITH raw AS (
--   SELECT jl.account_id, sum(jl.debit_paise) dr, sum(jl.credit_paise) cr
--   FROM journal_entries je JOIN journal_lines jl ON jl.journal_entry_id=je.id
--   WHERE je.client_id='...' AND je.is_posted AND je.deleted_at IS NULL
--   GROUP BY jl.account_id),
-- buck AS (
--   SELECT account_id, sum(debit_paise) dr, sum(credit_paise) cr
--   FROM account_period_balances WHERE client_id='...' GROUP BY account_id)
-- SELECT count(*) AS mismatched_accounts FROM raw r FULL OUTER JOIN buck b USING(account_id)
--   WHERE coalesce(r.dr,0)<>coalesce(b.dr,0) OR coalesce(r.cr,0)<>coalesce(b.cr,0);
