-- Migration 282: a party's opening position, so a statement stops replaying that
-- party's entire history to print one month of it.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHY
-- ═══════════════════════════════════════════════════════════════════════════
-- customer_statement_service.generate() and its vendor mirror fetch EVERY
-- invoice, receipt, allocation, credit note and debit note the party has ever
-- had — no date bound at all — and then discard everything outside the window
-- in Python:
--
--     for e in events:
--         if e["date"] < start or e["date"] > end:
--             continue
--
-- Five or six unbounded round trips to print, typically, one month. The reason
-- the fetch is unbounded is the OPENING BALANCE: it is the seed plus every
-- movement before the window, so the pre-period history has to be summed. What
-- it contributes to the statement, though, is one number — and summing a party's
-- history to produce one number is what a database is for.
--
-- Smaller in absolute terms than the client-wide reports (this is one customer's
-- history, not 12,838 entries) and the same shape, growing without bound as the
-- relationship ages.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHY A POSITION AND NOT A BALANCE
-- ═══════════════════════════════════════════════════════════════════════════
-- One number turned out not to be enough, and this is the part worth reading.
--
-- statement_currency.attach_currency_outstanding splits the CLOSING outstanding
-- by transaction currency, and its reconciliation guarantee — that the split
-- sums to closing_balance_paise — holds because it accumulates the seed plus
-- EVERY movement dated on or before the period end. Feed it only the windowed
-- events and a party with foreign activity before the window gets a split that
-- does not reconcile. A scalar opening balance cannot repair that: the currency
-- dimension has already been summed away.
--
-- So this returns the whole pre-period POSITION — the balance AND its per-
-- currency composition — which is exactly what the closing split needs as its
-- starting point:
--
--     {"opening_balance_paise": N,
--      "by_currency": [{"currency": "INR", "base_paise": N, "foreign_minor": N},
--                      {"currency": "USD", "base_paise": N, "foreign_minor": N}]}
--
-- The INR slot carries the seed, matching attach_currency_outstanding, which
-- books the seed as INR.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT IS TRANSCRIBED, INCLUDING WHAT LOOKS WRONG
-- ═══════════════════════════════════════════════════════════════════════════
-- Every filter and every sign is copied from the services, not re-derived. Two
-- worth naming because they look like bugs and are not this migration's to fix:
--
--   * receipt_allocations is NOT filtered on is_voided. The Python does not
--     filter it either — a reversed receipt is dropped whole before allocations
--     are read, which is the case the voiding exists for. Adding the filter here
--     would make the SQL disagree with the Python for any voided allocation on a
--     live receipt, and the parity test would (correctly) fail.
--
--   * a receipt relieves AR by allocations + unallocated, and a payment relieves
--     AP by amount + the fx_adjustments delta. These are NOT the same formula
--     because the two settlement paths post differently (task #102): a foreign
--     receipt's journal credits AR at each invoice's booked rate, while a
--     foreign payment's debits AP at the bill's booked rate with the delta
--     routed to Realized FX. Both are the true relief; neither is amount_paise.
--
-- Sign conventions follow the statements: receivable is debit-positive for a
-- customer, payable is credit-positive for a vendor.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- SECURITY DEFINER, WITH THE RLS RESTATED
-- ═══════════════════════════════════════════════════════════════════════════
-- The pattern from migrations 271, 275, 276, 279 and 281, and not optional here
-- either: this reads six tables that each carry firm/client policies, and as
-- INVOKER the per-row cascade is what made cash_flow_report time out (279).
-- Checks transcribed from post_journal_atomic — same predicates, same SQLSTATE,
-- same order.
--
-- PARITY. build_statement keeps its full-replay path for mock mode, local dev
-- and every pure-builder caller; supplying an opening position is optional and
-- changes nothing when it is absent. tests/test_statement_opening_parity_pg.py
-- runs each scenario BOTH ways — full history replayed, and windowed with this
-- function's position — and asserts the statements are byte-identical.
--
-- No table or column changes. Idempotent, and safe to re-run.

BEGIN;

CREATE OR REPLACE FUNCTION public.party_opening_position(
    p_firm   uuid,
    p_client uuid,
    p_party  uuid,
    p_kind   text,            -- 'customer' (receivable) | 'vendor' (payable)
    p_before date             -- events STRICTLY before this date
) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = public, pg_catalog
AS $fn$
DECLARE
    v_my_firm  uuid;
    v_internal uuid;
    v_seed     bigint := 0;
    v_out      jsonb;
BEGIN
    IF p_kind NOT IN ('customer', 'vendor') THEN
        RAISE EXCEPTION 'party_opening_position: p_kind must be customer or vendor, got %', p_kind
            USING ERRCODE = '22023';
    END IF;

    IF auth.uid() IS NOT NULL THEN
        v_my_firm := public.get_my_firm_id();

        IF v_my_firm IS NULL THEN
            RAISE EXCEPTION 'party_opening_position: caller has no user record in this database'
                USING ERRCODE = '42501';
        END IF;

        IF p_firm IS DISTINCT FROM v_my_firm THEN
            RAISE EXCEPTION 'party_opening_position: firm % is not the caller''s firm', p_firm
                USING ERRCODE = '42501';
        END IF;

        IF NOT public.can_access_client(p_client::text) THEN
            RAISE EXCEPTION 'party_opening_position: client % is not assigned to the caller', p_client
                USING ERRCODE = '42501';
        END IF;

        v_internal := public.my_internal_client_id();
        IF v_internal IS NOT NULL
           AND p_client = v_internal
           AND COALESCE(public.get_my_role(), '') <> 'Partner' THEN
            RAISE EXCEPTION 'party_opening_position: only a Partner may read the firm''s internal client'
                USING ERRCODE = '42501';
        END IF;
    END IF;

    IF p_kind = 'customer' THEN
        SELECT COALESCE(c.opening_balance_paise, 0) INTO v_seed
          FROM public.customers c
         WHERE c.id = p_party AND c.firm_id = p_firm AND c.client_id = p_client;
    ELSE
        SELECT COALESCE(v.opening_balance_paise, 0) INTO v_seed
          FROM public.vendors v
         WHERE v.id = p_party AND v.firm_id = p_firm AND v.client_id = p_client;
    END IF;
    v_seed := COALESCE(v_seed, 0);

    WITH ev AS (
        -- ── receivable side ──────────────────────────────────────────────────
        -- Invoice: DEBIT. Foreign leg is txn_total, falling back to the base
        -- amount, which is _ccy_view's rule for every stream below too.
        SELECT i.invoice_date AS when_on,
               COALESCE(i.total_paise, 0) AS dr, 0::bigint AS cr,
               upper(COALESCE(i.txn_currency, 'INR')) AS cur,
               COALESCE(i.txn_total, COALESCE(i.total_paise, 0)) AS txn
          FROM public.client_sales_invoices i
         WHERE p_kind = 'customer'
           AND i.firm_id = p_firm AND i.client_id = p_client AND i.customer_id = p_party
           AND i.deleted_at IS NULL
           AND COALESCE(i.status, '') NOT IN ('draft', 'cancelled')
           AND i.invoice_date < p_before

        UNION ALL
        -- Debit note: DEBIT (CGST Act §34(3) undercharge correction).
        SELECT d.debit_note_date, COALESCE(d.total_paise, 0), 0::bigint,
               'INR', COALESCE(d.total_paise, 0)
          FROM public.sales_debit_notes d
         WHERE p_kind = 'customer'
           AND d.firm_id = p_firm AND d.client_id = p_client AND d.customer_id = p_party
           AND d.deleted_at IS NULL
           AND COALESCE(d.status, '') NOT IN ('draft', 'cancelled')
           AND d.debit_note_date < p_before

        UNION ALL
        -- Credit note: CREDIT.
        SELECT n.credit_note_date, 0::bigint, COALESCE(n.total_paise, 0),
               'INR', COALESCE(n.total_paise, 0)
          FROM public.credit_notes n
         WHERE p_kind = 'customer'
           AND n.firm_id = p_firm AND n.client_id = p_client AND n.customer_id = p_party
           AND n.deleted_at IS NULL
           AND COALESCE(n.status, '') NOT IN ('draft', 'cancelled')
           AND n.credit_note_date < p_before

        UNION ALL
        -- Receipt: CREDIT, by its true AR relief — allocations at each invoice's
        -- BOOKED rate plus any unallocated excess, not the cash-rate total.
        -- receipt_allocations deliberately unfiltered on is_voided: see header.
        SELECT r.receipt_date, 0::bigint,
               COALESCE((SELECT SUM(COALESCE(ra.allocated_paise, 0))
                           FROM public.receipt_allocations ra
                          WHERE ra.receipt_id = r.id), 0)
             + COALESCE(r.unallocated_paise, 0),
               upper(COALESCE(r.txn_currency, 'INR')),
               COALESCE(r.txn_amount,
                        COALESCE((SELECT SUM(COALESCE(ra.allocated_paise, 0))
                                    FROM public.receipt_allocations ra
                                   WHERE ra.receipt_id = r.id), 0)
                      + COALESCE(r.unallocated_paise, 0))
          FROM public.receipts r
         WHERE p_kind = 'customer'
           AND r.firm_id = p_firm AND r.client_id = p_client AND r.customer_id = p_party
           AND NOT COALESCE(r.is_reversed, false)
           AND r.receipt_date < p_before

        -- ── payable side ─────────────────────────────────────────────────────
        UNION ALL
        -- Bill: CREDIT (increases what is owed to the vendor).
        SELECT b.bill_date, 0::bigint, COALESCE(b.net_payable_paise, 0),
               upper(COALESCE(b.txn_currency, 'INR')),
               COALESCE(b.txn_net_payable, COALESCE(b.net_payable_paise, 0))
          FROM public.purchase_bills b
         WHERE p_kind = 'vendor'
           AND b.firm_id = p_firm AND b.client_id = p_client AND b.vendor_id = p_party
           AND b.deleted_at IS NULL
           AND COALESCE(b.status, '') NOT IN ('draft', 'cancelled')
           AND b.bill_date < p_before

        UNION ALL
        -- Purchase credit note: CREDIT.
        SELECT pn.credit_note_date, 0::bigint, COALESCE(pn.total_paise, 0),
               'INR', COALESCE(pn.total_paise, 0)
          FROM public.purchase_credit_notes pn
         WHERE p_kind = 'vendor'
           AND pn.firm_id = p_firm AND pn.client_id = p_client AND pn.vendor_id = p_party
           AND pn.deleted_at IS NULL
           AND COALESCE(pn.status, '') NOT IN ('draft', 'cancelled')
           AND pn.credit_note_date < p_before

        UNION ALL
        -- Debit note raised on the vendor: DEBIT (reduces the payable).
        SELECT vd.debit_note_date, COALESCE(vd.total_paise, 0), 0::bigint,
               'INR', COALESCE(vd.total_paise, 0)
          FROM public.debit_notes vd
         WHERE p_kind = 'vendor'
           AND vd.firm_id = p_firm AND vd.client_id = p_client AND vd.vendor_id = p_party
           AND vd.deleted_at IS NULL
           AND COALESCE(vd.status, '') NOT IN ('draft', 'cancelled')
           AND vd.debit_note_date < p_before

        UNION ALL
        -- Payment: DEBIT, by its true AP relief — the cash amount plus the
        -- booked/settlement rate delta that fx_adjustments recorded. Zero for an
        -- INR payment, so this is the same number the old formula gave there.
        SELECT p.payment_date,
               COALESCE(p.amount_paise, 0)
             + COALESCE((SELECT SUM(COALESCE(a.base_delta_paise, 0))
                           FROM public.fx_adjustments a
                          WHERE a.firm_id = p_firm AND a.client_id = p_client
                            AND a.document_type = 'purchase_payment'
                            AND a.document_id = p.id), 0),
               0::bigint,
               upper(COALESCE(p.txn_currency, 'INR')),
               COALESCE(p.txn_amount,
                        COALESCE(p.amount_paise, 0)
                      + COALESCE((SELECT SUM(COALESCE(a.base_delta_paise, 0))
                                    FROM public.fx_adjustments a
                                   WHERE a.firm_id = p_firm AND a.client_id = p_client
                                     AND a.document_type = 'purchase_payment'
                                     AND a.document_id = p.id), 0))
          FROM public.purchase_payments p
         WHERE p_kind = 'vendor'
           AND p.firm_id = p_firm AND p.client_id = p_client AND p.vendor_id = p_party
           AND NOT COALESCE(p.is_reversed, false)
           AND p.payment_date < p_before
    ),
    signed AS (
        -- One place decides the sign, as build_statement does: receivable is
        -- debit-positive, payable is credit-positive. The foreign leg moves with
        -- the base leg, which is attach_currency_outstanding's fx_signed rule.
        SELECT cur,
               CASE WHEN p_kind = 'customer' THEN dr - cr ELSE cr - dr END AS base_delta,
               txn
          FROM ev
    ),
    per_ccy AS (
        SELECT cur,
               SUM(base_delta)::bigint AS base_paise,
               SUM(CASE WHEN base_delta >= 0 THEN txn ELSE -txn END)::bigint AS foreign_minor
          FROM signed
         GROUP BY cur
    ),
    -- The seed is booked to INR, and the INR slot must exist even when the party
    -- has no INR movements at all, or the split loses it.
    with_seed AS (
        SELECT 'INR'::text AS currency, v_seed AS base_paise, v_seed AS foreign_minor
        UNION ALL
        SELECT cur, base_paise, foreign_minor FROM per_ccy
    ),
    rolled AS (
        SELECT currency,
               SUM(base_paise)::bigint    AS base_paise,
               SUM(foreign_minor)::bigint AS foreign_minor
          FROM with_seed
         GROUP BY currency
    )
    SELECT jsonb_build_object(
               'opening_balance_paise',
               v_seed + COALESCE((SELECT SUM(base_delta) FROM signed), 0),
               'by_currency',
               COALESCE((SELECT jsonb_agg(jsonb_build_object(
                                    'currency',      currency,
                                    'base_paise',    base_paise,
                                    'foreign_minor', foreign_minor)
                                ORDER BY currency)
                           FROM rolled), '[]'::jsonb)
           )
      INTO v_out;

    RETURN v_out;
END
$fn$;

COMMENT ON FUNCTION public.party_opening_position(uuid, uuid, uuid, text, date) IS
    'A customer''s or vendor''s position strictly before a date: the opening '
    'balance and its per-currency composition, seed included. Lets a statement '
    'fetch only the window''s documents instead of the party''s entire history, '
    'while keeping attach_currency_outstanding''s reconciliation guarantee — '
    'which a scalar balance could not, having summed the currency dimension '
    'away. Sign conventions and document filters transcribed from '
    'customer_statement_service / vendor_statement_service and held identical to '
    'them by tests/test_statement_opening_parity_pg.py. SECURITY DEFINER with '
    'RLS restated (migration 279). Migration 282.';

REVOKE EXECUTE ON FUNCTION public.party_opening_position(uuid, uuid, uuid, text, date) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.party_opening_position(uuid, uuid, uuid, text, date) FROM anon;
GRANT EXECUTE ON FUNCTION public.party_opening_position(uuid, uuid, uuid, text, date)
    TO authenticated, service_role;

COMMIT;
