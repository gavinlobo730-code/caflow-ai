-- 152 — Atomic journal posting (fixes audit finding F2).
--
-- Problem
-- -------
-- The posting kernel inserted the journal header and its lines as TWO separate
-- PostgREST calls with no transaction. If the line insert failed (e.g. an
-- archived-account line trigger, or a transient error) after the header
-- committed, it left a POSTED header with no lines — and the journal-immutability
-- trigger (migration 055) blocks UPDATE/DELETE on posted entries, so the orphan
-- was unrepairable. The idempotency dedup then returned that orphan's id forever.
--
-- Fix
-- ---
-- Insert the header and all lines inside ONE server-side transaction. A plpgsql
-- function body is a single transaction, so if the line insert raises, the header
-- insert rolls back with it — no orphan can ever be committed. The kernel now
-- calls this via db.rpc('post_journal_atomic', ...). Concurrency/retry dedup on
-- the (firm, client, reference_no, entry_date) idempotency key (unique index from
-- migration 143) is handled here too: on a unique violation we return the winning
-- entry's id, exactly as the kernel's previous 23505-recovery did.
--
-- The header is inserted as a PARTIAL row (only the keys present in p_entry), so
-- columns omitted by the caller keep their DB defaults — byte-for-byte identical
-- to the previous PostgREST .insert(payload) behaviour.

CREATE OR REPLACE FUNCTION post_journal_atomic(p_entry jsonb, p_lines jsonb)
RETURNS uuid
LANGUAGE plpgsql
AS $$
DECLARE
  v_keys text;
  v_id   uuid;
  v_existing uuid;
BEGIN
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
