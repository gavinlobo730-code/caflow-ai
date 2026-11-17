-- Migration 640: the payroll ledger accounts carry a key, and one resolver finds them for every reader and writer (POST-A-083).
--
-- WHAT WAS WRONG
--
-- The payroll accrual, a leaver's settlement and the salary disbursement found Salaries Expense, Net Salary Payable, PF, ESI
-- and PT Payable, TDS Payable - Salary, the employer's contribution and Employee Loans & Advances by an ILIKE on the NAME.
-- The 24Q tie-out and the salary challan register read "TDS Payable - Salary" by its exact name, and the ESI and PT
-- remittance register by another ILIKE. A renamed account stopped the posting, or worse, was found by one of them and not by
-- another, so an accrual and its tie-out looked at two different accounts without anything saying so. Migration 092 also
-- stamped `tds_payable` on BOTH TDS accounts, so the purchase bill's key lookup could credit a supplier's TDS to the salary
-- account.
--
-- WHAT THIS DOES
--
--   1. Takes `tds_payable` off an account whose name says it is the SALARY TDS account. That key belongs to the §194-series
--      "TDS Payable" alone.
--   2. Stamps each payroll key (domain/payroll/ledger_accounts.py is the vocabulary, and a test holds this list equal to it)
--      on an account ONLY where exactly one ACTIVE FIRM-LEVEL account of the firm matches the pattern the posting has always
--      used, no active client-level account of the firm matches it, the account carries no key yet, and it matches no other
--      payroll pattern. Anything less certain is left unkeyed and is found by its name as before, with one change made in
--      the resolver and not here: where two accounts at the same level (the client's own, or firm-level) match the name and
--      neither is named exactly as the standard chart names it, the posting is now refused with both names, where it used to
--      post to whichever the database returned first. Such a chart that finalises today is refused until one is renamed or
--      deactivated; production's charts were not counted for it. No firm is moved onto a different account by this migration.
--   3. A unique index: within a firm and a scope (one client, or firm-level), a payroll key is on at most one account, so the
--      resolver never has to choose between two keyed rows.
--
-- One transaction, data-only plus an index on a small table. No function, no policy, no grant changes.

BEGIN;

-- 1. The salary TDS account is not the §194 TDS Payable.
UPDATE public.chart_of_accounts
   SET system_account_key = NULL
 WHERE system_account_key = 'tds_payable'
   AND account_name ILIKE '%tds payable - salary%';

-- 2. The payroll keys, where exactly one firm-level account is the answer.
WITH ledger(key, pattern) AS (
  VALUES ('payroll_salaries_expense',      '%Salaries Expense%'),
         ('payroll_employer_contribution', '%Contribution to Provident%'),
         ('payroll_net_salary_payable',    '%Net Salary Payable%'),
         ('payroll_pf_payable',            '%PF Payable%'),
         ('payroll_esi_payable',           '%ESI Payable%'),
         ('payroll_pt_payable',            '%PT Payable%'),
         ('payroll_tds_payable_salary',    '%TDS Payable - Salary%'),
         ('payroll_employee_loans',        '%Employee Loans%')
),
matches AS (
  SELECT c.id, c.firm_id, c.client_id, c.system_account_key, l.key
    FROM public.chart_of_accounts c
    JOIN ledger l ON c.account_name ILIKE l.pattern
   WHERE c.is_active
),
sole AS (
  SELECT m.firm_id, m.key, min(m.id::text)::uuid AS id
    FROM matches m
   GROUP BY m.firm_id, m.key
  HAVING count(*) FILTER (WHERE m.client_id IS NULL) = 1
     AND count(*) FILTER (WHERE m.client_id IS NOT NULL) = 0
)
UPDATE public.chart_of_accounts c
   SET system_account_key = s.key
  FROM sole s
 WHERE c.id = s.id
   AND c.system_account_key IS NULL
   AND (SELECT count(*) FROM matches m WHERE m.id = c.id) = 1
   AND NOT EXISTS (SELECT 1 FROM public.chart_of_accounts k
                    WHERE k.firm_id = s.firm_id AND k.system_account_key = s.key);

-- 3. One account per payroll key per firm and scope.
CREATE UNIQUE INDEX IF NOT EXISTS uq_chart_of_accounts_payroll_key
  ON public.chart_of_accounts (firm_id, COALESCE(client_id, '00000000-0000-0000-0000-000000000000'::uuid), system_account_key)
  WHERE system_account_key LIKE 'payroll\_%';

COMMIT;
