-- Migration 271: the posting kernel's RPC could not write the ledger it exists to write.
--
-- WHAT WAS BROKEN
-- Every manual journal post returned HTTP 500. The Postgres log has the reason,
-- twice, one per click:
--
--     SQLSTATE 42501 - permission denied for table journal_entries
--     role: authenticator | app: postgrest
--     query: SELECT public.post_journal_atomic(p_entry := ..., p_lines := ...)
--
-- `authenticated` holds SELECT on journal_entries and journal_lines and nothing
-- else. post_journal_atomic was SECURITY INVOKER, so its INSERT ran with the
-- caller's privileges, and with USE_USER_JWT on the caller IS the end user. The
-- insert was refused before RLS was ever consulted -- a missing GRANT is checked
-- first. Nothing was written: the RPC is atomic and never got past its first
-- statement.
--
-- WHY IT IS THIS FUNCTION AND NOT THE OTHERS
-- Every other atomic write RPC in this schema is already SECURITY DEFINER:
--
--     numbered_document_atomic    (sales invoices)      SECURITY DEFINER
--     settle_receipt_atomic       (receipts)            SECURITY DEFINER
--     record_fee_receipt_atomic   (fee receipts)        SECURITY DEFINER
--     post_journal_atomic         (THE POSTING KERNEL)  SECURITY INVOKER  <--
--
-- That is why invoices and receipts kept working while journals did not. It is
-- an oversight, not a decision -- nothing anywhere states an intent for the one
-- function that writes the general ledger to be the one that cannot.
--
-- The underlying gap is the one migration 269 documented from the other side:
-- 041_grant_all_tables_to_authenticated.sql says "Run in Supabase SQL Editor"
-- and never was. 269 repaired service_role's half. `authenticated` still lacks
-- DML on 28 tables, journal_entries and journal_lines among them.
--
-- WHY NOT JUST GRANT INSERT TO `authenticated`
-- Because the browser talks to PostgREST directly on ~83 tables. A GRANT here
-- would let a page write journal_entries without going through
-- phase2_journal_service._create_journal -- no balance assertion, no dedup, no
-- FY-lock check. "One posting kernel, no alternative paths" would stop being an
-- architectural rule and become an honour system. Leaving the GRANT off is what
-- makes this RPC the only way in, which is exactly what we want.
--
-- THE TENANT GUARD, AND WHY IT IS NEW HERE
-- SECURITY DEFINER runs as the owner, and an owner bypasses RLS. So the firm and
-- client scoping that journal_entries' own policies would have applied is not
-- applied to anything this function inserts. Those policies are therefore
-- restated below, in the body, for end-user callers:
--
--     firm_client_isolation                  firm_id = get_my_firm_id()
--     journal_entries_assignment_scope       can_access_client(client_id)
--     journal_entries_internal_partner_only  Partner, or not the internal client
--
-- The three sibling RPCs above carry no equivalent guard. That is a real gap and
-- it is NOT fixed here -- it needs its own change, per function, with its own
-- test. This migration does not widen it.
--
-- A service_role or background-job call has no JWT, so auth.uid() is NULL and the
-- guard does not apply: those callers are trusted by construction and already
-- bypass RLS today. The guard keys on auth.uid() rather than on
-- get_my_firm_id() being non-NULL, so a caller presenting a valid JWT that has
-- no matching users row is REFUSED rather than silently treated as a trusted
-- service call.
--
-- EXECUTE IS REVOKED FROM PUBLIC
-- The function's ACL granted EXECUTE to PUBLIC, which includes `anon`. That was
-- survivable while it was SECURITY INVOKER (anon has no INSERT either, so the
-- call failed at the same place). Under SECURITY DEFINER it would not be: the
-- anon key is published in the browser bundle by design, so anyone at all could
-- have called it. authenticated and service_role hold their own explicit grants
-- and are unaffected.
--
-- NOTE: the same PUBLIC/anon EXECUTE grant is live on all three sibling RPCs,
-- which ARE already SECURITY DEFINER. That is a live exposure right now and is
-- deliberately left for its own migration rather than bundled in here.
--
-- Idempotent, and safe to re-run.

CREATE OR REPLACE FUNCTION public.post_journal_atomic(p_entry jsonb, p_lines jsonb)
 RETURNS uuid
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'pg_catalog'
AS $function$
DECLARE
  v_keys text;
  v_id   uuid;
  v_existing uuid;
  v_total_debit  bigint;
  v_total_credit bigint;
  v_my_firm  uuid;
  v_internal uuid;
BEGIN
  -- ── Tenant guard (end-user callers only; see the header) ──────────────────
  -- Restates journal_entries' own RLS policies, which SECURITY DEFINER bypasses.
  IF auth.uid() IS NOT NULL THEN
    v_my_firm := public.get_my_firm_id();

    IF v_my_firm IS NULL THEN
      RAISE EXCEPTION 'post_journal_atomic: caller has no user record in this database'
        USING ERRCODE = '42501';
    END IF;

    IF (p_entry->>'firm_id')::uuid IS DISTINCT FROM v_my_firm THEN
      RAISE EXCEPTION 'post_journal_atomic: firm_id % is not the caller''s firm',
        p_entry->>'firm_id'
        USING ERRCODE = '42501';
    END IF;

    IF NOT public.can_access_client(p_entry->>'client_id') THEN
      RAISE EXCEPTION 'post_journal_atomic: client % is not assigned to the caller',
        p_entry->>'client_id'
        USING ERRCODE = '42501';
    END IF;

    -- The firm's own internal client is Partner-only (migration 073's pattern).
    v_internal := public.my_internal_client_id();
    IF v_internal IS NOT NULL
       AND (p_entry->>'client_id')::uuid = v_internal
       AND COALESCE(public.get_my_role(), '') <> 'Partner' THEN
      RAISE EXCEPTION 'post_journal_atomic: only a Partner may post to the firm''s internal client'
        USING ERRCODE = '42501';
    END IF;
  END IF;

  -- ── Unchanged from here down ──────────────────────────────────────────────
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
$function$;

-- The anon key is public by design. Under SECURITY DEFINER, PUBLIC EXECUTE would
-- hand the general ledger to anyone holding it.
REVOKE EXECUTE ON FUNCTION public.post_journal_atomic(jsonb, jsonb) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.post_journal_atomic(jsonb, jsonb) FROM anon;

-- Explicit rather than inherited, so a future REVOKE ... FROM PUBLIC elsewhere
-- cannot quietly take the API's own access away with it.
GRANT EXECUTE ON FUNCTION public.post_journal_atomic(jsonb, jsonb) TO authenticated;
GRANT EXECUTE ON FUNCTION public.post_journal_atomic(jsonb, jsonb) TO service_role;
