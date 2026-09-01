-- Migration 305: unbilled dues — the separate disclosure both Schedule III
-- ageing schedules require, and where the marking that makes it possible lives.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT THE STATUTE ASKS FOR
-- ═══════════════════════════════════════════════════════════════════════════
-- MCA Notification G.S.R. 207(E) of 24-03-2021 ends BOTH ageing notes with the
-- same sentence: "Unbilled dues shall be disclosed separately." Migration 303
-- built the two tables and reported a permanent gap in place of that figure,
-- saying this platform held no unbilled-revenue or accrued-liability document
-- keyed to a customer or vendor.
--
-- That was true, and it was looking in the wrong place. AN UNBILLED DUE HAS NO
-- DOCUMENT — having no document is what makes it unbilled. Revenue earned but
-- not yet invoiced, or goods received whose supplier invoice has not arrived,
-- reach the books as a JOURNAL ENTRY to an accrued-income or accrued-liability
-- account. The accrual is a BALANCE. And the statute asks for one figure
-- disclosed separately under each table, not an aged or party-attributed one,
-- which is exactly the shape an account balance has.
--
-- WHY THEY ARE NOT AGED, which is the same reason they are disclosed at all:
-- both tables age from the due date of payment, or where none is specified from
-- the date of the transaction. An unbilled due has neither. It cannot be put in
-- a bucket, so the statute gives it a line beside the table instead.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHICH ACCOUNTS HOLD THEM IS A HUMAN STEP
-- ═══════════════════════════════════════════════════════════════════════════
-- Like the MSMED classification this schedule already needs, and like the ITR
-- schemas. No keyword on an account name decides it: "Accrued Interest" may be
-- income receivable or an expense payable, and reading it the wrong way puts a
-- liability in the receivables note. So chart_of_accounts.unbilled_dues_side is
-- recorded and nothing infers it.
--
-- The CHECK makes the pairing structural rather than conventional. 'receivable'
-- is an ASSET balance (accrued income, unbilled revenue, a contract asset);
-- 'payable' is a LIABILITY balance (accrued expenses, goods received not
-- invoiced). A revenue or expense account cannot be marked at all — the P&L leg
-- of an accrual is not the due, and marking it would double the disclosure.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- AND AN UNREVIEWED NIL IS NOT A NIL — WHY THERE IS A SECOND TABLE
-- ═══════════════════════════════════════════════════════════════════════════
-- If no account carries the marking, the honest answer is not zero. Zero on a
-- signed note asserts the client has no unbilled dues; the truth until somebody
-- looks is that nobody has. So schedule_iii_unbilled_reviews records that a
-- human has been through this client's chart of accounts, and only then does
-- the figure become a number — which may legitimately be zero, now affirmed by
-- somebody rather than assumed.
--
-- This is the same distinction vendors.msme_status draws with its absent
-- default (migration 303) and schedule_iii_ratio_inputs.principal_repaid_paise
-- draws with its nullable column (304): an absent figure and a zero are
-- opposite claims, and only one of them is safe to print.
--
-- Per CLIENT, not per financial year. Which accounts hold accruals is a fact
-- about the chart of accounts, not about a year; reviewed_on is returned with
-- the schedule so a CA signing this year's accounts can see how old the review
-- is and judge it.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- THE BALANCE, AND THE REPORTING RULE
-- ═══════════════════════════════════════════════════════════════════════════
-- Computed here, in the database, from the marked accounts' own posting lines —
-- a correlated aggregate per marked account, on idx_journal_lines_account_id
-- (migration 017). Bounded by those accounts' activity, not by the ledger: an
-- accrual account with four entries a year reads four entries however long the
-- client has been trading. CLAUDE.md's reporting rule, in the shape it
-- prescribes for a per-row rule that cannot be pre-bucketed.
--
-- Posted and not deleted, entry_date <= the reporting date, transcribed from
-- cash_flow_report (migrations 277/279) so the three agree on what a live line
-- is. Unlike the document ageing above it, this figure IS exact as at a past
-- date: an account balance is a sum over dated lines, with none of the
-- "how much has been paid today" problem that makes outstanding_paise a
-- present-tense number.
--
-- THE SIGN IS PER SIDE and is the one arithmetic rule here worth stating twice.
-- Accrued income is an asset and reads debit less credit; an accrued liability
-- reads credit less debit. A single convention for both would report every
-- payable accrual as a negative receivable — the same money with its sign
-- inverted, which beside a balance sheet is not a rounding difference. A
-- balance that lands on the wrong side is REPORTED at its real negative figure
-- and flagged, never hidden: it is usually a reversal posted twice or an
-- accrual nobody released, and both are things a CA wants to see.
--
-- domain/reporting/ageing.py carries the identical rule for mock mode and local
-- dev, and tests/test_schedule_iii_ageing_parity_pg.py runs every scenario
-- through both halves and asserts the documents are equal.
--
-- Idempotent, safe to re-run. The column addition is additive and nullable, the
-- table is new, and the function is replaced in place with the same signature.

BEGIN;

-- ═══════════════════════════════════════════════════════════════════════════
-- 1. The marking
-- ═══════════════════════════════════════════════════════════════════════════

ALTER TABLE public.chart_of_accounts
  ADD COLUMN IF NOT EXISTS unbilled_dues_side text;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'chart_of_accounts_unbilled_dues_side_check'
                      AND conrelid = 'public.chart_of_accounts'::regclass) THEN
        -- Both halves of the pairing in one constraint: the side must be one of
        -- the two, AND it must match the account's own type. An asset cannot be
        -- marked as an accrued liability, and a revenue account cannot be
        -- marked at all.
        ALTER TABLE public.chart_of_accounts
          ADD CONSTRAINT chart_of_accounts_unbilled_dues_side_check
          CHECK (unbilled_dues_side IS NULL
                 OR (unbilled_dues_side = 'receivable' AND account_type = 'Asset')
                 OR (unbilled_dues_side = 'payable'    AND account_type = 'Liability'));
    END IF;
END $$;

COMMENT ON COLUMN public.chart_of_accounts.unbilled_dues_side IS
    'Marks an account as holding unbilled dues for the Schedule III ageing '
    'notes (MCA G.S.R. 207(E), 24-03-2021: "Unbilled dues shall be disclosed '
    'separately"). ''receivable'' is an ASSET balance — accrued income, '
    'unbilled revenue; ''payable'' is a LIABILITY balance — accrued expenses, '
    'goods received not invoiced. NULL means the account holds none. Recorded '
    'by a human, never inferred from the account name: "Accrued Interest" may '
    'be either side. Migration 305.';

-- Partial: only the marked accounts are ever read through it, and on a real
-- chart that is a handful of rows out of several hundred.
CREATE INDEX IF NOT EXISTS idx_coa_unbilled_dues
    ON public.chart_of_accounts (firm_id, client_id)
    WHERE unbilled_dues_side IS NOT NULL;

-- ═══════════════════════════════════════════════════════════════════════════
-- 2. The review that turns an absent figure into an affirmed one
-- ═══════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS public.schedule_iii_unbilled_reviews (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id     uuid NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id   uuid NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  -- A DATE, in IST, not a timestamptz: it is read back onto a note a CA signs,
  -- and CLAUDE.md's presentation rule says IST. Storing the date the review
  -- happened removes any question of which day a late-evening UTC timestamp
  -- belongs to.
  reviewed_on date NOT NULL DEFAULT ((now() AT TIME ZONE 'Asia/Kolkata')::date),
  reviewed_by uuid REFERENCES public.users(id),
  note        text,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (firm_id, client_id)
);

COMMENT ON TABLE public.schedule_iii_unbilled_reviews IS
    'One row per client, recording that somebody has been through its chart of '
    'accounts and marked every account holding unbilled dues '
    '(chart_of_accounts.unbilled_dues_side). Its ABSENCE is what makes the '
    'Schedule III unbilled figure NULL rather than zero — an unreviewed nil '
    'asserts the client has no unbilled dues, when the truth is that nobody has '
    'looked. Deleting the row puts the disclosure back into that gap. '
    'Migration 305.';

ALTER TABLE public.schedule_iii_unbilled_reviews ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "firm_unbilled_reviews" ON public.schedule_iii_unbilled_reviews;
CREATE POLICY "firm_unbilled_reviews" ON public.schedule_iii_unbilled_reviews
    FOR ALL TO authenticated
    USING (firm_id = public.get_my_firm_id())
    WITH CHECK (firm_id = public.get_my_firm_id());

-- Role-aware write guards, the shape migrations 260/261/304 established.
-- RESTRICTIVE so they narrow rather than widen: a permissive policy here would
-- GRANT. Manager tier, matching the accounting:write the endpoint requires —
-- affirming that a client has no unbilled dues is part of a signed disclosure.
DO $$
DECLARE t text := 'schedule_iii_unbilled_reviews';
BEGIN
  EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_role_insert', t);
  EXECUTE format(
    'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR INSERT '
    'WITH CHECK (public.my_role_at_least(%L))', t || '_role_insert', t, 'Manager');

  EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_role_update', t);
  EXECUTE format(
    'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR UPDATE '
    'USING (public.my_role_at_least(%L)) WITH CHECK (public.my_role_at_least(%L))',
    t || '_role_update', t, 'Manager', 'Manager');

  EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_role_delete', t);
  EXECUTE format(
    'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR DELETE '
    'USING (public.my_role_at_least(%L))', t || '_role_delete', t, 'Manager');
END $$;

GRANT SELECT, INSERT, UPDATE, DELETE ON public.schedule_iii_unbilled_reviews TO authenticated;

-- ═══════════════════════════════════════════════════════════════════════════
-- 3. The aggregate, replaced in place
-- ═══════════════════════════════════════════════════════════════════════════
-- Same signature, same SECURITY DEFINER body and the same restated RLS as
-- migration 303 — only the unbilled CTEs, the two gaps and the payload change.

CREATE OR REPLACE FUNCTION public.schedule_iii_ageing(
    p_firm   uuid,
    p_client uuid,
    p_as_of  date
) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = public, pg_catalog
AS $fn$
DECLARE
    v_my_firm  uuid;
    v_internal uuid;
    v_out      jsonb;
BEGIN
    -- Restates the RLS that SECURITY DEFINER bypasses. Transcribed from
    -- post_journal_atomic (migration 271) via cash_flow_report (279) so the
    -- three cannot drift in what they consider an authorised caller.
    IF auth.uid() IS NOT NULL THEN
        v_my_firm := public.get_my_firm_id();

        IF v_my_firm IS NULL THEN
            RAISE EXCEPTION 'schedule_iii_ageing: caller has no user record in this database'
                USING ERRCODE = '42501';
        END IF;

        IF p_firm IS DISTINCT FROM v_my_firm THEN
            RAISE EXCEPTION 'schedule_iii_ageing: firm % is not the caller''s firm', p_firm
                USING ERRCODE = '42501';
        END IF;

        IF NOT public.can_access_client(p_client::text) THEN
            RAISE EXCEPTION 'schedule_iii_ageing: client % is not assigned to the caller', p_client
                USING ERRCODE = '42501';
        END IF;

        v_internal := public.my_internal_client_id();
        IF v_internal IS NOT NULL
           AND p_client = v_internal
           AND COALESCE(public.get_my_role(), '') <> 'Partner' THEN
            RAISE EXCEPTION 'schedule_iii_ageing: only a Partner may read the firm''s internal client'
                USING ERRCODE = '42501';
        END IF;
    END IF;

    SELECT (
    WITH cut AS (
        -- Month arithmetic, not day counts: the statute says six months and one
        -- year, and Postgres clamps a month subtraction to a real date
        -- (2026-03-31 less 6 months is 2025-09-30). domain/reporting/ageing.py
        -- clamps identically; the parity test pins month-end as-of dates for
        -- exactly this reason.
        SELECT (p_as_of - interval '6 months')::date AS m6,
               (p_as_of - interval '1 year')::date   AS y1,
               (p_as_of - interval '2 years')::date  AS y2,
               (p_as_of - interval '3 years')::date  AS y3
    ),
    -- ── Trade receivables ────────────────────────────────────────────────────
    ar AS (
        SELECT COALESCE(i.outstanding_paise, 0)         AS amt,
               COALESCE(i.due_date, i.invoice_date)     AS ref,
               COALESCE(i.is_disputed, false)           AS disputed,
               COALESCE(i.considered_doubtful, false)   AS doubtful
          FROM public.client_sales_invoices i
         WHERE i.firm_id = p_firm
           AND i.client_id = p_client
           AND i.deleted_at IS NULL
           AND COALESCE(i.status, '') NOT IN ('draft', 'cancelled')
           AND i.outstanding_paise > 0
           AND i.invoice_date <= p_as_of
    ),
    ar_b AS (
        SELECT a.amt,
               CASE WHEN a.disputed AND a.doubtful     THEN 'disputed_doubtful'
                    WHEN a.disputed                    THEN 'disputed_good'
                    WHEN a.doubtful                    THEN 'undisputed_doubtful'
                    ELSE 'undisputed_good' END AS row_key,
               -- Strictly greater than the cutoff stays in the younger bucket, so
               -- an amount outstanding for EXACTLY six months is not "less than
               -- six months".
               CASE WHEN a.ref IS NULL       THEN 'lt_6m'
                    WHEN a.ref > p_as_of     THEN 'not_due'
                    WHEN a.ref > c.m6        THEN 'lt_6m'
                    WHEN a.ref > c.y1        THEN 'm6_y1'
                    WHEN a.ref > c.y2        THEN 'y1_y2'
                    WHEN a.ref > c.y3        THEN 'y2_y3'
                    ELSE 'gt_y3' END AS bucket
          FROM ar a CROSS JOIN cut c
    ),
    ar_agg AS (
        SELECT row_key, bucket, SUM(amt)::bigint AS amt
          FROM ar_b GROUP BY row_key, bucket
    ),
    ar_rows AS (
        SELECT r.key, r.ord, r.label,
               COALESCE(SUM(g.amt) FILTER (WHERE g.bucket = 'not_due'), 0)::bigint AS not_due,
               COALESCE(SUM(g.amt) FILTER (WHERE g.bucket = 'lt_6m'),   0)::bigint AS lt_6m,
               COALESCE(SUM(g.amt) FILTER (WHERE g.bucket = 'm6_y1'),   0)::bigint AS m6_y1,
               COALESCE(SUM(g.amt) FILTER (WHERE g.bucket = 'y1_y2'),   0)::bigint AS y1_y2,
               COALESCE(SUM(g.amt) FILTER (WHERE g.bucket = 'y2_y3'),   0)::bigint AS y2_y3,
               COALESCE(SUM(g.amt) FILTER (WHERE g.bucket = 'gt_y3'),   0)::bigint AS gt_y3,
               COALESCE(SUM(g.amt), 0)::bigint AS total
          FROM (VALUES
                  ('undisputed_good',     1, '(i) Undisputed Trade receivables – considered good'),
                  ('undisputed_doubtful', 2, '(ii) Undisputed Trade Receivables – considered doubtful'),
                  ('disputed_good',       3, '(iii) Disputed Trade Receivables – considered good'),
                  ('disputed_doubtful',   4, '(iv) Disputed Trade Receivables – considered doubtful')
               ) AS r(key, ord, label)
          LEFT JOIN ar_agg g ON g.row_key = r.key
         GROUP BY r.key, r.ord, r.label
    ),
    -- ── Trade payables ───────────────────────────────────────────────────────
    ap AS (
        SELECT COALESCE(b.outstanding_paise, 0)     AS amt,
               COALESCE(b.due_date, b.bill_date)    AS ref,
               COALESCE(b.is_disputed, false)       AS disputed,
               v.msme_status                        AS msme,
               b.vendor_id                          AS vendor_id,
               v.name                               AS vendor_name
          FROM public.purchase_bills b
          -- Scoped to THIS client's vendors, matching the Python half's
          -- firm+client vendor fetch exactly. A bill pointing at another
          -- client's vendor row is a data-integrity fault, and the right
          -- answer to one is an unclassified balance the CA is told
          -- about — not a classification borrowed from elsewhere.
          LEFT JOIN public.vendors v ON v.id = b.vendor_id
                                    AND v.firm_id = p_firm
                                    AND v.client_id = p_client
         WHERE b.firm_id = p_firm
           AND b.client_id = p_client
           AND b.deleted_at IS NULL
           AND COALESCE(b.status, '') NOT IN ('draft', 'cancelled')
           AND b.outstanding_paise > 0
           AND b.bill_date <= p_as_of
    ),
    ap_b AS (
        SELECT a.amt, a.vendor_id, a.vendor_name,
               -- NULL msme_status produces NULL here, and a NULL row_key joins
               -- to no row: an unclassified vendor's balance never lands in
               -- "Others". Only micro and small are row (i) — MSMED s.22 and
               -- s.2(n) both stop at small, so 'medium' is Others.
               CASE WHEN a.msme IS NULL THEN NULL
                    WHEN a.disputed AND a.msme IN ('micro', 'small') THEN 'disputed_msme'
                    WHEN a.disputed                                  THEN 'disputed_others'
                    WHEN a.msme IN ('micro', 'small')                THEN 'msme'
                    ELSE 'others' END AS row_key,
               CASE WHEN a.ref IS NULL   THEN 'lt_y1'
                    WHEN a.ref > p_as_of THEN 'not_due'
                    WHEN a.ref > c.y1    THEN 'lt_y1'
                    WHEN a.ref > c.y2    THEN 'y1_y2'
                    WHEN a.ref > c.y3    THEN 'y2_y3'
                    ELSE 'gt_y3' END AS bucket
          FROM ap a CROSS JOIN cut c
    ),
    ap_agg AS (
        SELECT row_key, bucket, SUM(amt)::bigint AS amt
          FROM ap_b WHERE row_key IS NOT NULL GROUP BY row_key, bucket
    ),
    ap_rows AS (
        SELECT r.key, r.ord, r.label,
               COALESCE(SUM(g.amt) FILTER (WHERE g.bucket = 'not_due'), 0)::bigint AS not_due,
               COALESCE(SUM(g.amt) FILTER (WHERE g.bucket = 'lt_y1'),   0)::bigint AS lt_y1,
               COALESCE(SUM(g.amt) FILTER (WHERE g.bucket = 'y1_y2'),   0)::bigint AS y1_y2,
               COALESCE(SUM(g.amt) FILTER (WHERE g.bucket = 'y2_y3'),   0)::bigint AS y2_y3,
               COALESCE(SUM(g.amt) FILTER (WHERE g.bucket = 'gt_y3'),   0)::bigint AS gt_y3,
               COALESCE(SUM(g.amt), 0)::bigint AS total
          FROM (VALUES
                  ('msme',            1, '(i) MSME'),
                  ('others',          2, '(ii) Others'),
                  ('disputed_msme',   3, '(iii) Disputed dues – MSME'),
                  ('disputed_others', 4, '(iv) Disputed dues – Others')
               ) AS r(key, ord, label)
          LEFT JOIN ap_agg g ON g.row_key = r.key
         GROUP BY r.key, r.ord, r.label
    ),
    -- ── Unbilled dues ────────────────────────────────────────────────────────
    -- Both notes end "Unbilled dues shall be disclosed separately." There is no
    -- document to read: having no document is what makes a due unbilled. The
    -- accrual is a BALANCE, on an account somebody has marked, and the statute
    -- asks for one figure beside each table rather than an aged or
    -- party-attributed one — which is exactly the shape of an account balance.
    review AS (
        SELECT r.reviewed_on
          FROM public.schedule_iii_unbilled_reviews r
         WHERE r.firm_id = p_firm AND r.client_id = p_client
    ),
    unbilled_acct AS (
        SELECT a.id, a.account_code, a.account_name, a.unbilled_dues_side AS side
          FROM public.chart_of_accounts a
         WHERE a.firm_id = p_firm
           AND a.client_id = p_client
           AND a.unbilled_dues_side IS NOT NULL
    ),
    -- Bounded by the marked accounts' own postings, not by the ledger: the
    -- join is on account_id, so an accrual account with four entries a year
    -- reads four entries however long the client's history is. Aggregated
    -- here, in the database, which is what CLAUDE.md's reporting rule asks of
    -- any figure derived from posting lines.
    --
    -- THE SIGN IS PER SIDE. Accrued income is an asset and reads debit less
    -- credit; an accrued liability reads credit less debit. One convention for
    -- both would report every payable accrual as a negative receivable.
    unbilled_bal AS (
        SELECT ua.id, ua.account_code, ua.account_name, ua.side,
               COALESCE((
                   SELECT SUM(CASE WHEN ua.side = 'receivable'
                                   THEN jl.debit_paise - jl.credit_paise
                                   ELSE jl.credit_paise - jl.debit_paise END)
                     FROM public.journal_lines jl
                     JOIN public.journal_entries je ON je.id = jl.journal_entry_id
                    WHERE jl.account_id = ua.id
                      AND je.firm_id = p_firm
                      AND je.client_id = p_client
                      AND je.is_posted
                      AND je.deleted_at IS NULL
                      AND je.entry_date <= p_as_of), 0)::bigint AS balance
          FROM unbilled_acct ua
    ),
    -- Unclassified payables, per vendor. Bounded by the number of vendors with
    -- an open bill and no classification — which is the size of the ANSWER here,
    -- since the list IS what the caller has to act on.
    unclassified AS (
        SELECT a.vendor_id,
               COALESCE(a.vendor_name, '(vendor not found)') AS vendor_name,
               SUM(a.amt)::bigint AS amt
          FROM ap_b a WHERE a.row_key IS NULL
         GROUP BY a.vendor_id, a.vendor_name
    ),
    gaps AS (
        -- An unreviewed nil is not a nil. Zero would assert the client has no
        -- unbilled dues; NULL says nobody has looked, which is the truth until
        -- somebody records that they have.
        SELECT 1 AS ord, 'unbilled_dues_not_reviewed' AS code,
               'Schedule III requires unbilled dues to be disclosed separately '
               'under both ageing schedules, and nobody has yet been through '
               'this client''s chart of accounts to say which accounts hold '
               'them. No figure is shown, because a zero would claim there are '
               'none rather than that nobody has looked. Mark the '
               'accrued-income and accrued-liability accounts, then record the '
               'review — if there genuinely are none, recording the review '
               'discloses a nil that somebody has affirmed.' AS message
         WHERE NOT EXISTS (SELECT 1 FROM review)
        UNION ALL
        SELECT 1, 'unbilled_account_in_contra_balance',
               'An account marked as holding unbilled dues has a balance on '
               'the wrong side — accrued income in credit, or an accrued '
               'liability in debit. The figure below includes it at its real '
               '(negative) balance rather than hiding it, but a contra balance '
               'on an accrual account is usually a reversal that was posted '
               'twice or an accrual that was never released.'
         WHERE EXISTS (SELECT 1 FROM review)
           AND EXISTS (SELECT 1 FROM unbilled_bal WHERE balance < 0)
        UNION ALL
        SELECT 2, 'vendors_unclassified',
               'One or more vendors with an open bill have no MSMED '
               'classification, so their balances are excluded from both the '
               'MSME and the Others rows. Classify them before signing the '
               'note: IT Act s.43B(h) makes the micro/small distinction change '
               'taxable income, not just presentation.'
         WHERE EXISTS (SELECT 1 FROM unclassified)
        UNION ALL
        SELECT 3, 'as_at_is_current_balance',
               'Amounts are each document''s balance outstanding TODAY, aged '
               'against the requested date. A document settled between that '
               'date and today is not included, so the schedule understates '
               'the position as at that date. Run it at the reporting date for '
               'an exact figure.'
         WHERE p_as_of < CURRENT_DATE
    )
    SELECT jsonb_build_object(
        'as_of', to_char(p_as_of, 'YYYY-MM-DD'),
        'division', 'I',
        'statute', 'Schedule III to the Companies Act 2013, as amended by MCA '
                   'Notification G.S.R. 207(E) dated 24 March 2021',
        'ageing_from', 'due date of payment; where none is specified, the date of the transaction',
        'unbilled_reviewed_on', (SELECT to_char(reviewed_on, 'YYYY-MM-DD') FROM review),
        'receivables', jsonb_build_object(
            'title', 'Trade Receivables ageing schedule',
            'buckets', jsonb_build_array(
                jsonb_build_object('key', 'not_due', 'label', 'Not due', 'prescribed', false),
                jsonb_build_object('key', 'lt_6m',   'label', 'Less than 6 months', 'prescribed', true),
                jsonb_build_object('key', 'm6_y1',   'label', '6 months - 1 year',  'prescribed', true),
                jsonb_build_object('key', 'y1_y2',   'label', '1-2 years',          'prescribed', true),
                jsonb_build_object('key', 'y2_y3',   'label', '2-3 years',          'prescribed', true),
                jsonb_build_object('key', 'gt_y3',   'label', 'More than 3 years',  'prescribed', true)),
            'rows', (SELECT COALESCE(jsonb_agg(jsonb_build_object(
                        'key', key, 'label', label,
                        'amounts', jsonb_build_object(
                            'not_due', not_due, 'lt_6m', lt_6m, 'm6_y1', m6_y1,
                            'y1_y2', y1_y2, 'y2_y3', y2_y3, 'gt_y3', gt_y3),
                        'total_paise', total) ORDER BY ord), '[]'::jsonb) FROM ar_rows),
            'column_totals', (SELECT jsonb_build_object(
                        'not_due', COALESCE(SUM(not_due), 0), 'lt_6m', COALESCE(SUM(lt_6m), 0),
                        'm6_y1', COALESCE(SUM(m6_y1), 0), 'y1_y2', COALESCE(SUM(y1_y2), 0),
                        'y2_y3', COALESCE(SUM(y2_y3), 0), 'gt_y3', COALESCE(SUM(gt_y3), 0))
                       FROM ar_rows),
            'total_paise', (SELECT COALESCE(SUM(total), 0)::bigint FROM ar_rows),
            'unbilled_dues_paise', (SELECT CASE WHEN EXISTS (SELECT 1 FROM review)
                        THEN COALESCE((SELECT SUM(balance) FROM unbilled_bal
                                        WHERE side = 'receivable'), 0)::bigint END),
            'unbilled_accounts', (SELECT COALESCE(jsonb_agg(jsonb_build_object(
                        'account_id', id, 'account_code', account_code,
                        'account_name', account_name, 'balance_paise', balance)
                        ORDER BY balance DESC, account_code COLLATE "C"), '[]'::jsonb)
                       FROM unbilled_bal WHERE side = 'receivable'
                        AND EXISTS (SELECT 1 FROM review))
        ),
        'payables', jsonb_build_object(
            'title', 'Trade Payables ageing schedule',
            'buckets', jsonb_build_array(
                jsonb_build_object('key', 'not_due', 'label', 'Not due', 'prescribed', false),
                jsonb_build_object('key', 'lt_y1',   'label', 'Less than 1 year',  'prescribed', true),
                jsonb_build_object('key', 'y1_y2',   'label', '1-2 years',         'prescribed', true),
                jsonb_build_object('key', 'y2_y3',   'label', '2-3 years',         'prescribed', true),
                jsonb_build_object('key', 'gt_y3',   'label', 'More than 3 years', 'prescribed', true)),
            'rows', (SELECT COALESCE(jsonb_agg(jsonb_build_object(
                        'key', key, 'label', label,
                        'amounts', jsonb_build_object(
                            'not_due', not_due, 'lt_y1', lt_y1, 'y1_y2', y1_y2,
                            'y2_y3', y2_y3, 'gt_y3', gt_y3),
                        'total_paise', total) ORDER BY ord), '[]'::jsonb) FROM ap_rows),
            'column_totals', (SELECT jsonb_build_object(
                        'not_due', COALESCE(SUM(not_due), 0), 'lt_y1', COALESCE(SUM(lt_y1), 0),
                        'y1_y2', COALESCE(SUM(y1_y2), 0), 'y2_y3', COALESCE(SUM(y2_y3), 0),
                        'gt_y3', COALESCE(SUM(gt_y3), 0))
                       FROM ap_rows),
            'total_paise', (SELECT COALESCE(SUM(total), 0)::bigint FROM ap_rows),
            'unclassified_paise', (SELECT COALESCE(SUM(amt), 0)::bigint FROM unclassified),
            'unclassified_vendors', (SELECT COALESCE(jsonb_agg(jsonb_build_object(
                        'vendor_id', vendor_id, 'vendor_name', vendor_name,
                        'outstanding_paise', amt) ORDER BY amt DESC, vendor_name COLLATE "C"), '[]'::jsonb)
                       FROM unclassified),
            'unbilled_dues_paise', (SELECT CASE WHEN EXISTS (SELECT 1 FROM review)
                        THEN COALESCE((SELECT SUM(balance) FROM unbilled_bal
                                        WHERE side = 'payable'), 0)::bigint END),
            'unbilled_accounts', (SELECT COALESCE(jsonb_agg(jsonb_build_object(
                        'account_id', id, 'account_code', account_code,
                        'account_name', account_name, 'balance_paise', balance)
                        ORDER BY balance DESC, account_code COLLATE "C"), '[]'::jsonb)
                       FROM unbilled_bal WHERE side = 'payable'
                        AND EXISTS (SELECT 1 FROM review))
        ),
        'gaps', (SELECT COALESCE(jsonb_agg(jsonb_build_object('code', code, 'message', message)
                        ORDER BY ord), '[]'::jsonb) FROM gaps)
    )) INTO v_out;

    RETURN v_out;
END
$fn$;

COMMENT ON FUNCTION public.schedule_iii_ageing(uuid, uuid, date) IS
    'Trade receivables and trade payables ageing schedules for the notes to the '
    'balance sheet — Schedule III Division I as amended by MCA G.S.R. 207(E) of '
    '24-03-2021. Returns twenty-four figures from every open document, plus the '
    'unbilled dues each note requires disclosed separately, in the database, per '
    'CLAUDE.md''s reporting rule. domain/reporting/ageing.py is the identical '
    'rule for mock mode and the two are pinned by '
    'tests/test_schedule_iii_ageing_parity_pg.py. Migrations 303 and 305.';

GRANT EXECUTE ON FUNCTION public.schedule_iii_ageing(uuid, uuid, date)
    TO authenticated;

COMMIT;
