-- Migration 216: restore SECURITY DEFINER on post_journal_atomic.
--
-- 213_journal_reversal_flag.sql's CREATE OR REPLACE FUNCTION
-- post_journal_atomic(...) (written to add an `is_reversed = false` filter to
-- the unique_violation fallback SELECT) omitted the SECURITY DEFINER clause
-- that the original 152_atomic_journal_posting.sql version had.
-- CREATE OR REPLACE FUNCTION replaces the ENTIRE function definition,
-- including its security context — so applying 213 as written silently
-- downgraded the function to SECURITY INVOKER (the PL/pgSQL default).
--
-- 171_harden_journal_entries_lines_rls.sql deliberately REVOKEs
-- INSERT/UPDATE/DELETE on journal_entries/journal_lines from `authenticated`,
-- on the assumption that ALL writes go through this SECURITY DEFINER
-- function (owned by `postgres`) instead. Once the function silently became
-- SECURITY INVOKER, every journal posting made under a per-user-JWT
-- (`authenticated`) request started failing with "permission denied for
-- table journal_entries" — caught by each journal_for_* method's generic
-- exception handler and surfaced as an unhelpful "Unable to ... Please try
-- again." (identically for every document type that posts a journal: sales
-- invoices, purchase bills, receipts, payments, credit/debit notes).
--
-- Re-applies the exact same function body as 213 with SECURITY DEFINER
-- restored — no other behavioural change.
CREATE OR REPLACE FUNCTION post_journal_atomic(p_entry jsonb, p_lines jsonb)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_catalog
AS $$
DECLARE
  v_keys text;
  v_id   uuid;
  v_existing uuid;
BEGIN
  SELECT string_agg(quote_ident(k), ', ')
    INTO v_keys
    FROM jsonb_object_keys(p_entry) AS k;
  IF v_keys IS NULL THEN
    RAISE EXCEPTION 'post_journal_atomic: empty entry payload';
  END IF;

  BEGIN
    EXECUTE format(
      'INSERT INTO public.journal_entries (%1$s) '
      'SELECT %1$s FROM jsonb_populate_record(NULL::public.journal_entries, $1) '
      'RETURNING id', v_keys
    ) INTO v_id USING p_entry;
  EXCEPTION WHEN unique_violation THEN
    SELECT id INTO v_existing
      FROM public.journal_entries
     WHERE firm_id      = (p_entry->>'firm_id')::uuid
       AND client_id    = (p_entry->>'client_id')::uuid
       AND reference_no = p_entry->>'reference_no'
       AND entry_date   = (p_entry->>'entry_date')::date
       AND deleted_at IS NULL
       AND is_reversed  = false
     ORDER BY created_at
     LIMIT 1;
    RETURN v_existing;
  END;

  INSERT INTO public.journal_lines (
    journal_entry_id, account_id, debit_paise, credit_paise, narration,
    txn_currency, base_currency, exchange_rate, txn_debit, txn_credit,
    rate_source, rate_type, rate_date
  )
  SELECT
    v_id,
    (l->>'account_id')::uuid,
    COALESCE((l->>'debit_paise')::bigint, 0),
    COALESCE((l->>'credit_paise')::bigint, 0),
    l->>'narration',
    COALESCE(NULLIF(l->>'txn_currency', ''), 'INR'),
    COALESCE(NULLIF(l->>'base_currency', ''), 'INR'),
    COALESCE((l->>'exchange_rate')::numeric, 1),
    NULLIF(l->>'txn_debit', '')::bigint,
    NULLIF(l->>'txn_credit', '')::bigint,
    l->>'rate_source',
    COALESCE(NULLIF(l->>'rate_type', ''), 'booking'),
    NULLIF(l->>'rate_date', '')::date
  FROM jsonb_array_elements(p_lines) AS l;

  RETURN v_id;
END
$$;

GRANT EXECUTE ON FUNCTION post_journal_atomic(jsonb, jsonb) TO authenticated, service_role;
