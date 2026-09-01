-- Migration 303: the Schedule III ageing schedules for trade receivables and
-- trade payables — the classification the note needs, and the aggregate that
-- produces it in the database.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHY THIS NOTE EXISTS AT ALL
-- ═══════════════════════════════════════════════════════════════════════════
-- MCA Notification G.S.R. 207(E) of 24 March 2021 amended Schedule III to the
-- Companies Act 2013 with effect from 1 April 2021. Among the additional
-- disclosures it inserted are two ageing schedules in the notes to the balance
-- sheet — one for trade receivables, one for trade payables — and neither can be
-- derived from anything this codebase already computes. `grep -rn ageing
-- domain/reporting/` returned nothing before this migration.
--
-- These are DIVISION I (Accounting Standards) tables. routers/accounting.py's
-- get_schedule_iii already says the engine builds Division I, and the two
-- divisions differ here: Division II (Ind AS) splits the doubtful receivables
-- row into "which have significant increase in credit risk" and "credit
-- impaired", following Ind AS 109's expected-credit-loss language. Division I
-- says "considered doubtful" and has four rows. If Ind AS is ever supported, the
-- receivables row set changes and the payables one does not.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- THE TWO TABLES ARE NOT THE SAME SHAPE, AND THAT IS THE EASY THING TO GET WRONG
-- ═══════════════════════════════════════════════════════════════════════════
-- Receivables age in FIVE columns starting at six months:
--     Less than 6 months | 6 months - 1 year | 1-2 years | 2-3 years | > 3 years
-- Payables age in FOUR columns starting at one year:
--     Less than 1 year | 1-2 years | 2-3 years | > 3 years
--
-- The row sets differ too. Receivables split on disputed/undisputed and
-- good/doubtful; payables split on disputed/undisputed and MSME/other:
--     receivables: (i) Undisputed - considered good
--                  (ii) Undisputed - considered doubtful
--                  (iii) Disputed - considered good
--                  (iv) Disputed - considered doubtful
--     payables:    (i) MSME
--                  (ii) Others
--                  (iii) Disputed dues - MSME
--                  (iv) Disputed dues - Others
--
-- Both age "from due date of payment". Where a document specifies no due date
-- the ageing runs from the date of the transaction, which is also what
-- customer_statement_service.ar_aging already does (`due_date or invoice_date`),
-- so the two agree on the reference date and only the buckets differ.
--
-- THE "NOT DUE" COLUMN. The prescribed table has none, and every outstanding
-- amount must nonetheless appear in some column for the total to tie to the
-- balance sheet. An amount not yet due has been outstanding from its due date
-- for a negative period, so folding it into "less than 6 months" is the common
-- filing choice and it overstates the ageing of a current book. This function
-- returns `not_due` as its own figure so both presentations are available from
-- one answer: a filer presenting the prescribed five columns adds not_due into
-- the first bucket, and one presenting six shows it separately. Nothing is
-- lost or invented either way — the row totals are the same number.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT THE SCHEMA COULD NOT ANSWER, AND WHY TWO OF THE THREE GAPS DEFAULT
-- ═══════════════════════════════════════════════════════════════════════════
-- Three facts the note needs and no column held.
--
--   is_disputed (invoices and bills) and considered_doubtful (invoices) default
--   to false, and that is not a guess. A dispute and a doubt are both
--   AFFIRMATIVE positions somebody takes about a specific document; until
--   somebody takes one, the document is undisputed and considered good, which
--   is what the row set means. Defaulting a receivable to "undisputed -
--   considered good" states exactly what is known.
--
--   vendors.msme_status is NULLABLE with no default, and that IS the point.
--   A vendor is not "Others" until someone has looked; and the difference is not
--   presentational. Section 43B(h) of the IT Act, inserted by the Finance Act
--   2023 with effect from AY 2024-25, disallows a deduction for any sum payable
--   to a MICRO or SMALL enterprise beyond the time limit in section 15 of the
--   MSMED Act 2006 unless it is actually paid. Classifying an unclassified
--   vendor as "Others" therefore does not merely misplace a row — it changes the
--   client's taxable income. So an unclassified vendor's balance is reported as
--   an unclassified TOTAL beside the table, never folded into a row, and the
--   caller is told which vendors are missing a classification.
--
--   MEDIUM ENTERPRISES BELONG IN "OTHERS". Row (i) of the payables table is read
--   with the balance-sheet line item Schedule III already prescribes — "total
--   outstanding dues of micro enterprises and small enterprises" — which comes
--   from section 22 of the MSMED Act and covers micro and small only. Section 15
--   (and so section 43B(h)) works off "supplier", which section 2(n) also
--   confines to micro and small. A medium enterprise is registered under MSMED
--   and is still not in row (i). That is why msme_status has four values rather
--   than a boolean: 'medium' and 'not_registered' are both Others, and they are
--   different facts about the vendor that a CA will want to keep.
--
-- UNBILLED DUES. Both notes end "Unbilled dues shall be disclosed separately."
-- There is no unbilled-revenue or accrued-liability document in this schema
-- keyed to a party, so there is nothing to disclose from and nothing is
-- invented: the answer carries a gap saying so rather than a zero, because a
-- zero and "not modelled" are opposite claims.
--
-- msme_vendors (migration 014) is NOT what this builds on. It is a separate
-- register keyed by vendor NAME rather than by vendor id, it has its own
-- outstanding and due-date columns that nothing maintains, and no Python or
-- TypeScript in this repository reads or writes it. Keying a statutory
-- disclosure to a free-text name against a table nothing keeps current would
-- have been the wrong foundation; this puts the classification on the vendor
-- row the bills actually reference.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT "AS AT" MEANS HERE, STATED PLAINLY BECAUSE IT IS A REAL LIMIT
-- ═══════════════════════════════════════════════════════════════════════════
-- p_as_of does two exact things: it sets the date the ageing is measured from,
-- and it excludes documents dated after it (an invoice raised in April is not a
-- receivable at 31 March).
--
-- It does NOT reconstruct each document's balance as it stood on that date. The
-- amount is outstanding_paise — the generated column from migration 278, which
-- is the single definition of what a document still owes. So a document settled
-- between p_as_of and today is absent, and a partly settled one shows its
-- smaller figure. The error is one-directional: the schedule UNDERSTATES a past
-- position, never overstates it.
--
-- That is deliberate, and the alternative was worse. Reconstructing a past
-- balance means re-deriving "paid as at a date" per document, and on the payable
-- side purchase_bills.paid_paise has no single derivation to transcribe: it is
-- maintained by signed deltas from purchase_payment_service, the bank posting
-- path, reversal_service and the fx adjustments, through both the single-FK
-- purchase_payments.purchase_bill_id and the purchase_payment_allocations
-- bridge. A fourth implementation of "how much has been paid", written for one
-- report, is exactly the drift CLAUDE.md exists to prevent — and a wrong number
-- here is a wrong statutory disclosure in a signed balance sheet. So the
-- function reports the limit instead of guessing past it: any call with p_as_of
-- earlier than today comes back with a gap that names what is excluded.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHY A SQL FUNCTION
-- ═══════════════════════════════════════════════════════════════════════════
-- CLAUDE.md's reporting rule, and its own instruction that "aged receivables and
-- payables are the same shape and should be built this way from the start". The
-- answer is twenty-four numbers. The input is every open document the client
-- has. domain/reporting/ageing.py keeps the identical rule for mock mode and
-- local dev, where there is no DATABASE_URL and no SQL functions, and
-- tests/test_schedule_iii_ageing_parity_pg.py runs every scenario through BOTH
-- and asserts they are identical, so the two cannot drift.
--
-- SECURITY DEFINER with the RLS restated — the pattern of migrations 271, 275,
-- 276, 279, 281 and 282, and not optional here either. Migration 279 is the
-- worked lesson: cash_flow_report shipped as INVOKER, measured at 35 ms as a
-- superuser, and timed out in production because journal_lines' policy is a
-- correlated subquery the planner cannot hoist. This reads five policy-carrying
-- tables. The checks below are transcribed from post_journal_atomic — same
-- predicates, same SQLSTATE, same order — so isolation is identical to what the
-- policies would enforce, checked once per call instead of once per row.
--
-- Idempotent, and safe to re-run. The three column additions are additive and
-- nullable-or-defaulted, so no existing insert or select changes.

BEGIN;

-- ═══════════════════════════════════════════════════════════════════════════
-- 1. The classification the note needs
-- ═══════════════════════════════════════════════════════════════════════════

ALTER TABLE public.client_sales_invoices
  ADD COLUMN IF NOT EXISTS is_disputed        boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS considered_doubtful boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN public.client_sales_invoices.is_disputed IS
    'Schedule III trade receivables ageing schedule (MCA G.S.R. 207(E), '
    '24-03-2021): rows (iii) and (iv) are disputed receivables. False by '
    'default because a dispute is an affirmative position somebody records, '
    'not an absence of information. Migration 303.';

COMMENT ON COLUMN public.client_sales_invoices.considered_doubtful IS
    'Schedule III Division I trade receivables ageing schedule: rows (ii) and '
    '(iv) are "considered doubtful". Division II (Ind AS) splits this into '
    '"significant increase in credit risk" and "credit impaired"; this engine '
    'builds Division I. Migration 303.';

ALTER TABLE public.purchase_bills
  ADD COLUMN IF NOT EXISTS is_disputed boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN public.purchase_bills.is_disputed IS
    'Schedule III trade payables ageing schedule (MCA G.S.R. 207(E), '
    '24-03-2021): rows (iii) and (iv) are "Disputed dues". Migration 303.';

-- NULLABLE on purpose, and the one column here that must never acquire a
-- default. See the header: an unclassified vendor is a gap, not an "Other",
-- because IT Act s.43B(h) turns the micro/small classification into a
-- disallowance and so into taxable income.
ALTER TABLE public.vendors
  ADD COLUMN IF NOT EXISTS msme_status text,
  ADD COLUMN IF NOT EXISTS msme_registration_no text;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'vendors_msme_status_check'
                      AND conrelid = 'public.vendors'::regclass) THEN
        ALTER TABLE public.vendors
          ADD CONSTRAINT vendors_msme_status_check
          CHECK (msme_status IS NULL
                 OR msme_status IN ('micro', 'small', 'medium', 'not_registered'));
    END IF;
END $$;

COMMENT ON COLUMN public.vendors.msme_status IS
    'MSMED Act 2006 classification. NULL means nobody has classified this '
    'vendor yet and is NOT "Others": IT Act s.43B(h) disallows a deduction for '
    'sums payable to a MICRO or SMALL enterprise beyond the s.15 time limit '
    'unless paid, so a wrong classification changes taxable income. Only '
    'micro and small go in row (i) "MSME" of the Schedule III payables ageing '
    'schedule — s.22 MSMED and s.2(n) both stop at small, so a MEDIUM '
    'enterprise is registered under MSMED and still belongs in Others. '
    'Migration 303.';

COMMENT ON COLUMN public.vendors.msme_registration_no IS
    'Udyam registration number evidencing the msme_status classification. '
    'Migration 303.';

-- The ageing schedule reads open documents by due date, exactly as the partial
-- indexes from migration 278 do; those already cover this query's shape
-- (firm_id, client_id, due_date WHERE open), so no new index is added here.

-- ═══════════════════════════════════════════════════════════════════════════
-- 2. The aggregate
-- ═══════════════════════════════════════════════════════════════════════════

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
        SELECT 1 AS ord, 'unbilled_dues_not_modelled' AS code,
               'Schedule III requires unbilled dues to be disclosed separately '
               'under both ageing schedules. This platform has no unbilled '
               'revenue or accrued-liability document keyed to a customer or '
               'vendor, so there is nothing to report from and no figure is '
               'shown. A zero would claim there are none.' AS message
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
            'unbilled_dues_paise', NULL
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
            'unbilled_dues_paise', NULL
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
    '24-03-2021. Returns twenty-four figures from every open document, in the '
    'database, per CLAUDE.md''s reporting rule. domain/reporting/ageing.py is '
    'the identical rule for mock mode and the two are pinned by '
    'tests/test_schedule_iii_ageing_parity_pg.py. Migration 303.';

REVOKE EXECUTE ON FUNCTION public.schedule_iii_ageing(uuid, uuid, date) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.schedule_iii_ageing(uuid, uuid, date) FROM anon;
GRANT EXECUTE ON FUNCTION public.schedule_iii_ageing(uuid, uuid, date)
    TO authenticated, service_role;

COMMIT;
