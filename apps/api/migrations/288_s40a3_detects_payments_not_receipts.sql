-- ============================================================================
-- 288 — §40A(3) auto-detection was reading the wrong side of the ledger
--
-- WHAT WAS WRONG
--     get_cash_payments_above_threshold (migration 156) selected
--
--         jl.debit_paise AS amount_paise ... WHERE jl.debit_paise > threshold
--
--     on accounts whose name or subtype matches 'cash'. In double entry a cash
--     PAYMENT credits the cash account; debiting cash is money coming IN. The
--     function therefore returned the client's cash RECEIPTS — the opposite
--     side of the transaction from the one §40A(3) is about.
--
--     Two failures in one, and the second is the dangerous one:
--       * every row it produced was written up as an auto-detected
--         disallowance (computation_workspace.auto_detect_40a3), so the CA was
--         shown fabricated add-backs that would overstate tax if accepted; and
--       * the client's genuine cash payments were never surfaced at all, so a
--         clean run read as a clean bill of health on the real exposure.
--
-- WHAT §40A(3) ACTUALLY SAYS
--     Where the assessee incurs any EXPENDITURE and the PAYMENT (or aggregate
--     of payments made to a person IN A DAY) exceeds ₹10,000 otherwise than by
--     account-payee cheque, draft or electronic mode, no deduction is allowed
--     for that expenditure. The per-person-per-day aggregate is the Finance
--     Act 2008 amendment; the second proviso raises the limit to ₹35,000 for
--     payments made for plying, hiring or leasing goods carriages.
--
-- WHAT THIS FUNCTION CAN AND CANNOT KNOW
--     journal_entries and journal_lines carry no party dimension (checked:
--     neither table has a party_id, and no later migration adds one), so "the
--     aggregate of payments made to A PERSON in a day" is not derivable from
--     the ledger as it stands. The closest honest proxy is the aggregate per
--     DAY per COUNTERPARTY ACCOUNT — the expense or payable account on the
--     other leg — which is what this returns. It catches the case the per-line
--     test missed entirely: five ₹4,000 cash payments to one account on one
--     day are ₹20,000 in aggregate and disallowable, where no single line
--     crosses ₹10,000.
--
--     It also cannot apply Rule 6DD, which exempts a long list of payments
--     (to banking companies, to government where payment must be in legal
--     tender, to a producer for agricultural produce, in a village with no
--     banking facility, and more), nor decide whether a payee is a transporter
--     within the second proviso. Those are matters of fact about the payee.
--     So what this produces is a REVIEW LIST for the CA, never a
--     determination — the caller records each row for review, and the CA
--     accepts or rejects it. The ₹35,000 proviso is deliberately NOT applied
--     here: applying it would require assuming the payee is a transporter, and
--     wrongly widening the threshold hides a real disallowance.
--
-- NO DATA IS REWRITTEN. Rows already created by the broken scan are the CA's
-- to review and reject — silently deleting recorded disallowances would
-- destroy work, and tax_disallowances carries the status field for exactly
-- this. The caller now labels new rows so the two are distinguishable.
-- ============================================================================

DROP FUNCTION IF EXISTS public.get_cash_payments_above_threshold(UUID, UUID, BIGINT);

CREATE FUNCTION public.get_cash_payments_above_threshold(
  p_firm_id UUID,
  p_client_id UUID,
  p_threshold_paise BIGINT
) RETURNS TABLE (
  journal_entry_id UUID,
  narration TEXT,
  amount_paise BIGINT,
  entry_date DATE,
  counterparty_account TEXT,
  entry_count BIGINT
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  WITH cash_out AS (
    -- The CREDIT side of a cash account: money leaving. This is the half of
    -- the entry §40A(3) is about, and the half the previous version missed.
    SELECT je.id            AS journal_entry_id,
           je.entry_date    AS entry_date,
           je.narration     AS narration,
           jl.credit_paise  AS amount_paise
      FROM public.journal_entries je
      JOIN public.journal_lines jl ON jl.journal_entry_id = je.id
      JOIN public.chart_of_accounts coa ON coa.id = jl.account_id
     WHERE je.firm_id = p_firm_id
       AND je.client_id = p_client_id
       AND je.is_posted = true
       AND je.deleted_at IS NULL
       AND jl.credit_paise > 0
       -- A cash account is an ASSET. Matching on the name alone (as the
       -- previous version did) also caught revenue accounts called
       -- "Cash Sales" and expense accounts called "Petty Cash Expenses";
       -- crediting a revenue account is income, and reporting it as a
       -- disallowable payment is the same fabrication in a new disguise.
       AND coa.account_type = 'Asset'
       AND (coa.account_name ILIKE '%cash%' OR coa.account_subtype ILIKE '%cash%')
  ),
  -- The other leg names what the money was spent on. With no party dimension
  -- on the ledger this is the best available stand-in for "the person paid";
  -- the column is named for what it is so no caller mistakes it for a payee.
  with_counterparty AS (
    SELECT c.journal_entry_id,
           c.entry_date,
           c.narration,
           c.amount_paise,
           COALESCE(
             (SELECT coa2.account_name
                FROM public.journal_lines jl2
                JOIN public.chart_of_accounts coa2 ON coa2.id = jl2.account_id
               WHERE jl2.journal_entry_id = c.journal_entry_id
                 AND jl2.debit_paise > 0
               ORDER BY jl2.debit_paise DESC
               LIMIT 1),
             'Unallocated'
           ) AS counterparty_account
      FROM cash_out c
  )
  SELECT (array_agg(w.journal_entry_id ORDER BY w.amount_paise DESC))[1]
           AS journal_entry_id,
         CASE
           WHEN count(*) = 1
             THEN COALESCE(max(w.narration), '')
           ELSE count(*)::text || ' cash payments to ' || w.counterparty_account
                || ' on this date'
         END AS narration,
         sum(w.amount_paise)::BIGINT AS amount_paise,
         w.entry_date,
         w.counterparty_account,
         count(*)::BIGINT AS entry_count
    FROM with_counterparty w
   GROUP BY w.entry_date, w.counterparty_account
  -- The aggregate crosses the limit, per the Finance Act 2008 amendment —
  -- not each line on its own, which is what the previous version tested.
  HAVING sum(w.amount_paise) > p_threshold_paise
$$;

GRANT EXECUTE ON FUNCTION public.get_cash_payments_above_threshold(UUID, UUID, BIGINT)
  TO authenticated, service_role;
