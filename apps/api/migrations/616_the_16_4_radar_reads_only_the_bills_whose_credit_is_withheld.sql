-- Migration 616: the s.16(4) radar reads only the bills whose credit the s.16(2)(aa) pass could withhold (POST-A-062).
--
-- ====================================================================================================================================
-- WHAT WAS WRONG
-- ====================================================================================================================================
-- GET /api/gst-workspace/itc/time-bar (gst-15) lays the credit that is not yet claimed against the CGST Act s.16(4) date it lapses on.
-- To find that credit it read EVERY received bill of the window's reconciled months (at most two financial years), every stored GSTR-2B
-- row of those months and the bills' supplier names, three Singapore-to-Mumbai reads paged a thousand rows at a time, and ran the
-- per-document s.16(2)(aa) pass (`domain/gst/rule_36_4`) over all of them in Python, to keep the handful it withholds. What crossed the
-- wire was proportional to the client's purchases, not to the answer, which the reporting rule forbids.
--
-- ====================================================================================================================================
-- WHAT THIS DOES
-- ====================================================================================================================================
-- `public.itc_time_bar_candidates(firm, client, from, to, periods)` joins, in the database, each received bill of the named reconciled
-- months with the GSTR-2B rows the reconciliation matched to it and with its month's reconciliation header, and returns, as one JSON
-- array, ONLY the bills whose verdict could be other than "allowed": not reverse charge, carrying credit net of s.17(5), and either
-- recorded after its month was reconciled, matched to no 2B row, matched to a row 2B marks ITC-unavailable, or carrying more tax on
-- some head than 2B communicated. Each comes back with the inputs the pass needs (its heads net of s.17(5), whether it was examined, and
-- the summed 2B heads, the blocked flag and the first reason code, the way `gst_return_service._two_b_by_document` sums them), its
-- supplier's name and GSTIN. The VERDICT is still `rule_36_4.assess`, in Python and nowhere else: the function only leaves out the
-- bills the pass would allow, and `tests/test_the_16_4_radar_candidates_parity_pg.py` holds its choice equal to the pass's over every
-- scenario it builds (every bill the pass withholds, blocks or has not assessed is returned, and nothing it allows).
--
-- The filters are the Python read's: the firm and the client, a received status ('received', 'partially_paid', 'paid'), not deleted,
-- not carried over (`is_opening`, migration 391), the bill's own date inside the window and its month among the named reconciled ones;
-- a 2B row counts only from the named months, and "examined" is the bill's `created_at` on or before its month's `reconciled_at`.
--
-- SECURITY INVOKER: the caller's own privileges and row security judge every row read (the API calls it with the privileged client).
-- EXECUTE is revoked from PUBLIC and given to the two roles the API uses. It writes nothing.
--
-- Rollback: 616_..._rollback.sql drops the function; the API then reads the bills as before (it falls back when the call fails).
-- Nothing here transmits anything to a portal.

BEGIN;

CREATE OR REPLACE FUNCTION public.itc_time_bar_candidates(
    p_firm_id   uuid,
    p_client_id uuid,
    p_from      date,
    p_to        date,
    p_periods   text[]
) RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY INVOKER
SET search_path = public, pg_catalog
AS $$
WITH bills AS (
    SELECT b.id, b.vendor_id, b.bill_no, b.our_reference, b.bill_date, b.created_at,
           COALESCE(b.is_reverse_charge, false) AS is_reverse_charge,
           COALESCE(b.igst_paise, 0) - COALESCE(b.ineligible_itc_igst_paise, 0) AS igst_paise,
           COALESCE(b.cgst_paise, 0) - COALESCE(b.ineligible_itc_cgst_paise, 0) AS cgst_paise,
           COALESCE(b.sgst_paise, 0) - COALESCE(b.ineligible_itc_sgst_paise, 0) AS sgst_paise,
           COALESCE(b.cess_paise, 0) - COALESCE(b.ineligible_itc_cess_paise, 0) AS cess_paise,
           to_char(b.bill_date, 'MMYYYY') AS period
      FROM public.purchase_bills b
     WHERE b.firm_id = p_firm_id
       AND b.client_id = p_client_id
       AND b.status IN ('received', 'partially_paid', 'paid')
       AND b.deleted_at IS NULL
       AND NOT COALESCE(b.is_opening, false)
       AND b.bill_date BETWEEN p_from AND p_to
       AND to_char(b.bill_date, 'MMYYYY') = ANY (p_periods)
),
judged AS (
    SELECT bl.*,
           (bl.created_at IS NOT NULL AND h.reconciled_at IS NOT NULL AND bl.created_at <= h.reconciled_at) AS examined,
           t.rows_matched,
           COALESCE(t.blocked, false) AS blocked,
           t.reason_code,
           COALESCE(t.igst_paise, 0) AS filed_igst_paise,
           COALESCE(t.cgst_paise, 0) AS filed_cgst_paise,
           COALESCE(t.sgst_paise, 0) AS filed_sgst_paise,
           COALESCE(t.cess_paise, 0) AS filed_cess_paise
      FROM bills bl
      LEFT JOIN public.gstr2b_reconciliations h
             ON h.firm_id = p_firm_id AND h.client_id = p_client_id AND h.return_period = bl.period
      LEFT JOIN LATERAL (
            SELECT count(*) AS rows_matched,
                   bool_or(upper(trim(COALESCE(g.itc_available, ''))) = 'N') AS blocked,
                   (array_agg(g.itc_unavailable_reason_code ORDER BY g.id)
                      FILTER (WHERE COALESCE(g.itc_unavailable_reason_code, '') <> ''))[1] AS reason_code,
                   sum(COALESCE(g.igst_paise, 0)) AS igst_paise,
                   sum(COALESCE(g.cgst_paise, 0)) AS cgst_paise,
                   sum(COALESCE(g.sgst_paise, 0)) AS sgst_paise,
                   sum(COALESCE(g.cess_paise, 0)) AS cess_paise
              FROM public.gstr2a_records g
             WHERE g.firm_id = p_firm_id
               AND g.client_id = p_client_id
               AND g.purchase_bill_id = bl.id
               AND g.return_period = ANY (p_periods)
      ) t ON true
     WHERE NOT bl.is_reverse_charge
       AND (bl.igst_paise <> 0 OR bl.cgst_paise <> 0 OR bl.sgst_paise <> 0 OR bl.cess_paise <> 0)
)
SELECT COALESCE(jsonb_agg(jsonb_build_object(
           'id', j.id, 'vendor_id', j.vendor_id, 'vendor_name', v.name, 'vendor_gstin', v.gstin,
           'bill_no', j.bill_no, 'our_reference', j.our_reference, 'bill_date', j.bill_date,
           'is_reverse_charge', j.is_reverse_charge, 'examined', j.examined,
           'igst_paise', j.igst_paise, 'cgst_paise', j.cgst_paise, 'sgst_paise', j.sgst_paise, 'cess_paise', j.cess_paise,
           'matched', j.rows_matched > 0, 'blocked', j.blocked, 'reason_code', COALESCE(j.reason_code, ''),
           'filed_igst_paise', j.filed_igst_paise, 'filed_cgst_paise', j.filed_cgst_paise,
           'filed_sgst_paise', j.filed_sgst_paise, 'filed_cess_paise', j.filed_cess_paise)
         ORDER BY j.bill_date, j.id), '[]'::jsonb)
  FROM judged j
  LEFT JOIN public.vendors v ON v.id = j.vendor_id AND v.firm_id = p_firm_id
 WHERE NOT j.examined
    OR j.rows_matched = 0
    OR j.blocked
    OR j.igst_paise > j.filed_igst_paise
    OR j.cgst_paise > j.filed_cgst_paise
    OR j.sgst_paise > j.filed_sgst_paise
    OR j.cess_paise > j.filed_cess_paise
$$;

REVOKE ALL ON FUNCTION public.itc_time_bar_candidates(uuid, uuid, date, date, text[]) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.itc_time_bar_candidates(uuid, uuid, date, date, text[]) FROM anon;
GRANT EXECUTE ON FUNCTION public.itc_time_bar_candidates(uuid, uuid, date, date, text[]) TO authenticated, service_role;

DO $$
BEGIN
    IF has_function_privilege('anon', 'public.itc_time_bar_candidates(uuid, uuid, date, date, text[])', 'EXECUTE') THEN
        RAISE EXCEPTION 'migration 616: the function is executable by anon';
    END IF;
    IF (SELECT prosecdef FROM pg_proc WHERE oid = 'public.itc_time_bar_candidates(uuid, uuid, date, date, text[])'::regprocedure) THEN
        RAISE EXCEPTION 'migration 616: the function must be SECURITY INVOKER';
    END IF;
END $$;

COMMIT;
