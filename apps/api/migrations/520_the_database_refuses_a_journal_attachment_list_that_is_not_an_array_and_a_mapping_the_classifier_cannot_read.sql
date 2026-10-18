-- Migration 520: two shapes the application already insists on are now insisted on by the database (POST-A-163, POST-A-164).
--
-- 1. journal_entries.attachments (migration 138) is a plain jsonb column. Migration 259 gave the sibling column on
--    bank_transactions a CHECK (a JSON array, at most 20 elements) and the journal one never got it, so the only thing standing
--    between the column and a string, an object or a ten-thousand-element array was the API model (domain/attachments). The
--    element shape and the URL scheme stay in the API on purpose, for the reason 259 gives: SQL is a poor place to say "not a
--    javascript: URL" and a half-check reads as a guarantee it does not give.
--
-- 2. chart_of_accounts.schedule_iii_mapping (migration 057) is free text. The API refuses a value that is not a Schedule III
--    caption and the classifier ignores one, but a write that does not come through the API (the CSV import screen writes the
--    table straight over PostgREST) could leave garbage at rest that every report then silently disregards. The CHECK accepts
--    exactly what domain/reporting/schedule_iii.canonical_caption can READ: the 24 captions the engine presents, the five
--    older spellings CAPTION_ALIASES honours, and the heading 'Fixed Assets' that resolves from the account's own subtype. It
--    does NOT accept only the new spellings, because production holds the heading on three accounts and the older spellings are
--    still rescued by the engine; a CHECK stricter than the reader would reject data the product reads correctly. A second copy
--    of the vocabulary in SQL is what the posting-kernel rule exists to prevent, so it is pinned to the Python list both by a
--    source test in the mock suite and by a real-Postgres test (tests/test_520_*).
--
-- READ FROM PRODUCTION on 18-10-2026: all 13,082 journal entries hold an empty array; of the 144 accounts every one holds either NULL
-- or one of 17 distinct values, all of them captions the engine presents except the heading 'Fixed Assets' on three accounts (none
-- padded, none empty). Each constraint is added NOT VALID, so it binds every new and changed row at
-- once without a scan under a long lock, and VALIDATE then checks the old rows; if an old row ever fails (one written between
-- that read and this run) the constraint is left NOT VALID with a NOTICE rather than failing the deploy, and VALIDATE can be run
-- by hand once the row is fixed.
--
-- Idempotent (each constraint is added only if absent) and reversible: the rollback drops both.

DO $$
BEGIN
    IF to_regclass('public.journal_entries') IS NULL OR to_regclass('public.chart_of_accounts') IS NULL THEN
        RAISE NOTICE 'migration 520: journal_entries or chart_of_accounts does not exist here; skipped';
        RETURN;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conrelid = 'public.journal_entries'::regclass AND conname = 'journal_entries_attachments_check') THEN
        ALTER TABLE public.journal_entries
            ADD CONSTRAINT journal_entries_attachments_check
            CHECK (jsonb_typeof(attachments) = 'array' AND jsonb_array_length(attachments) <= 20) NOT VALID;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conrelid = 'public.chart_of_accounts'::regclass
                      AND conname = 'chart_of_accounts_schedule_iii_mapping_check') THEN
        ALTER TABLE public.chart_of_accounts
            ADD CONSTRAINT chart_of_accounts_schedule_iii_mapping_check
            CHECK (schedule_iii_mapping IS NULL OR schedule_iii_mapping IN (
        'Capital Work-in-Progress',
        'Cash & Cash Equivalents',
        'Cost of Materials Consumed',
        'Deferred Tax Liability',
        'Depreciation & Amortisation',
        'Employee Benefit Expense',
        'Employee Benefits Expense',
        'Finance Costs',
        'Fixed Assets',
        'Intangible Fixed Assets',
        'Inventories',
        'Long Term Borrowings',
        'Long Term Investments',
        'Long-term Borrowings',
        'Long-term Investments',
        'Other Current Assets',
        'Other Current Liabilities',
        'Other Expenses',
        'Other Income',
        'Reserves & Surplus',
        'Revenue from Operations',
        'Share Capital',
        'Short Term Borrowings',
        'Short Term Loans & Advances',
        'Short-term Borrowings',
        'Short-term Loans & Advances',
        'Tangible Fixed Assets',
        'Tax Expense',
        'Trade Payables',
        'Trade Receivables'
            )) NOT VALID;
    END IF;

    BEGIN
        ALTER TABLE public.journal_entries VALIDATE CONSTRAINT journal_entries_attachments_check;
    EXCEPTION WHEN check_violation THEN
        RAISE NOTICE 'journal_entries_attachments_check left NOT VALID: an older entry holds attachments that are not an array of at most 20';
    END;

    BEGIN
        ALTER TABLE public.chart_of_accounts VALIDATE CONSTRAINT chart_of_accounts_schedule_iii_mapping_check;
    EXCEPTION WHEN check_violation THEN
        RAISE NOTICE 'chart_of_accounts_schedule_iii_mapping_check left NOT VALID: an older account holds a mapping that is not a caption';
    END;
END $$;

-- Closing check: both constraints exist (valid or not), so the migration cannot report success having added nothing.
DO $verify$
BEGIN
    IF to_regclass('public.journal_entries') IS NULL OR to_regclass('public.chart_of_accounts') IS NULL THEN
        RETURN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conrelid = 'public.journal_entries'::regclass AND conname = 'journal_entries_attachments_check') THEN
        RAISE EXCEPTION 'migration 520 failed: journal_entries_attachments_check is missing';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conrelid = 'public.chart_of_accounts'::regclass
                      AND conname = 'chart_of_accounts_schedule_iii_mapping_check') THEN
        RAISE EXCEPTION 'migration 520 failed: chart_of_accounts_schedule_iii_mapping_check is missing';
    END IF;
END $verify$;
