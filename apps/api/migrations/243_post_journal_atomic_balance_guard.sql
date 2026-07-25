-- Migration 243: DB-level debit=credit + non-zero guard on post_journal_atomic.
--
-- Audit finding (task #244 follow-up, comparative-reliability review): every
-- journal posted in production goes through post_journal_atomic (migration
-- 152) -- services/phase2_journal_service.py._create_journal is its ONLY
-- caller, and it already validates debit=credit and non-zero in Python
-- BEFORE calling the RPC (lines ~1367-1376). But that check lives entirely
-- in application code -- post_journal_atomic itself will happily insert
-- whatever (p_entry, p_lines) it's given, balanced or not. A future caller
-- that reaches this RPC directly (a new code path, a refactor that drops the
-- Python check, a manual RPC call) has NO backstop.
--
-- This is an inconsistency with the codebase's OWN existing practice:
-- settle_receipt_atomic (migrations 160/162/211/217/235) already duplicates
-- its balance/non-zero check inside the SQL function itself, specifically so
-- "the invariant holds at the database layer itself... regardless of which
-- application code path calls it" (235's own words). post_journal_atomic --
-- the MORE heavily used of the two -- was missing that same defense-in-depth
-- guard. This migration closes that gap, mirroring 235's check exactly.
--
-- Checked BEFORE any INSERT (header or lines) -- an invalid post must never
-- create even a rolled-back-later side effect, and must never risk minting
-- an orphan header the immutability trigger (migration 055) would then make
-- unrepairable.
--
-- Not a behavior change for the one real caller: _create_journal already
-- guarantees balance/non-zero before calling this RPC, so every existing,
-- correctly-behaving code path is unaffected. Proven on real Postgres by
-- tests/test_atomic_journal_posting.py's new balance-guard tests.
CREATE OR REPLACE FUNCTION post_journal_atomic(p_entry jsonb, p_lines jsonb)
RETURNS uuid
LANGUAGE plpgsql
SET search_path = public, pg_catalog
AS $$
DECLARE
  v_keys text;
  v_id   uuid;
  v_existing uuid;
  v_total_debit  bigint;
  v_total_credit bigint;
BEGIN
  -- ── 0. Balance/non-zero guard (mirrors settle_receipt_atomic, migration 235) ──
  SELECT COALESCE(sum(COALESCE((l->>'debit_paise')::bigint, 0)), 0),
         COALESCE(sum(COALESCE((l->>'credit_paise')::bigint, 0)), 0)
    INTO v_total_debit, v_total_credit
    FROM jsonb_array_elements(p_lines) AS l;

  IF v_total_debit <> v_total_credit THEN
    RAISE EXCEPTION 'post_journal_atomic: journal imbalance debit=% credit=% for ref=%',
      v_total_debit, v_total_credit, p_entry->>'reference_no';
  END IF;
  IF v_total_debit = 0 THEN
    RAISE EXCEPTION 'post_journal_atomic: refusing to post a zero-value journal entry for ref=%',
      p_entry->>'reference_no';
  END IF;

  -- Column list = the keys the caller actually supplied (mirrors a partial insert).
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
    -- Concurrent post / retry on the same idempotency key — return the winner.
    SELECT id INTO v_existing
      FROM public.journal_entries
     WHERE firm_id      = (p_entry->>'firm_id')::uuid
       AND client_id    = (p_entry->>'client_id')::uuid
       AND reference_no = p_entry->>'reference_no'
       AND entry_date   = (p_entry->>'entry_date')::date
       AND deleted_at IS NULL
     ORDER BY created_at
     LIMIT 1;
    RETURN v_existing;
  END;

  -- Lines — attached to the new entry, in the SAME transaction as the header.
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
