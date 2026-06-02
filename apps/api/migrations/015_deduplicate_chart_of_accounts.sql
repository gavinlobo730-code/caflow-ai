-- Migration 015: Deduplicate chart_of_accounts and add unique constraint
-- The migration 011 seed ran twice for some firms, causing duplicate entries.
-- This removes duplicates keeping the oldest record, then adds a unique constraint.

-- Step 1: Remove duplicates — keep the earliest created row per (firm_id, account_code)
DELETE FROM public.chart_of_accounts
WHERE id IN (
  SELECT id FROM (
    SELECT id,
      ROW_NUMBER() OVER (
        PARTITION BY firm_id, account_code
        ORDER BY created_at ASC, id ASC
      ) AS rn
    FROM public.chart_of_accounts
  ) ranked
  WHERE rn > 1
);

-- Step 2: Also remove duplicates by (firm_id, account_name) in case code differs
DELETE FROM public.chart_of_accounts
WHERE id IN (
  SELECT id FROM (
    SELECT id,
      ROW_NUMBER() OVER (
        PARTITION BY firm_id, LOWER(account_name)
        ORDER BY created_at ASC, id ASC
      ) AS rn
    FROM public.chart_of_accounts
  ) ranked
  WHERE rn > 1
);

-- Step 3: Add unique constraints to prevent future duplicates
ALTER TABLE public.chart_of_accounts
  DROP CONSTRAINT IF EXISTS chart_of_accounts_firm_code_unique;
ALTER TABLE public.chart_of_accounts
  ADD CONSTRAINT chart_of_accounts_firm_code_unique UNIQUE (firm_id, account_code);

ALTER TABLE public.chart_of_accounts
  DROP CONSTRAINT IF EXISTS chart_of_accounts_firm_name_unique;
ALTER TABLE public.chart_of_accounts
  ADD CONSTRAINT chart_of_accounts_firm_name_unique UNIQUE (firm_id, account_name);

-- Done — chart_of_accounts is now deduplicated and protected against future duplicates.
