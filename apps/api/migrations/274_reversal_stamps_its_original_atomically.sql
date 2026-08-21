-- Migration 274: the reversal and its original's is_reversed flag become one
-- atomic write.
--
-- WHAT WAS WRONG, SEEN IN PRODUCTION
--     2026-08-21 12:32:27  permission denied for table journal_entries  42501
--     UPDATE "public"."journal_entries" SET "is_reversed" = ...
--
-- reverse_entry posts the reversal through post_journal_atomic -- which is
-- SECURITY DEFINER since migration 271, so that half works -- and then issued a
-- SEPARATE, plain UPDATE to stamp the original. That update goes through
-- PostgREST as `authenticated`, and `authenticated` has SELECT on
-- journal_entries and nothing else. It is the same grant gap that broke posting
-- (271); only the INSERT half was closed.
--
-- The reversal committed and the flag never got set, so the CA saw
-- "0 of 1 reversed / API error 500" over a reversal that had in fact posted.
-- It is on the books today: JNL-001 carries is_reversed = false while
-- REV-D4692E6C points at it.
--
-- THREE THINGS THE MISSING FLAG BREAKS, IN ORDER OF HOW MUCH THEY MATTER
--   1. _create_journal's idempotency fast-path keys on
--      (firm, client, reference_no, entry_date) AND is_reversed = false. A
--      reversed entry is dead and must stop matching; while it still matches,
--      re-posting the same document RETURNS THE DEAD ENTRY'S ID instead of
--      posting a fresh one. That is a wrong ledger, not a wrong badge.
--   2. JournalEditor locks a reversed entry from editing off this flag, so a
--      reversed entry stayed editable.
--   3. The 500 itself.
--
-- WHY NOT JUST GRANT UPDATE
-- Because `authenticated` is also the browser. journal_entries deliberately has
-- no DML grant: roughly 320 direct PostgREST calls reach ~83 tables from
-- apps/web, and the general ledger is not one of them -- the posting kernel is
-- the only writer. Granting UPDATE to make one backend statement work would
-- hand every logged-in browser the ability to rewrite posted journals, guarded
-- by nothing but RLS.
--
-- WHY IN THE RPC RATHER THAN A SECOND FUNCTION
-- The insert already carries reversal_of, and the two facts -- "a reversal
-- exists" and "the original is flagged" -- should not be able to diverge. Doing
-- them in one function makes that structural rather than a convention someone
-- has to remember. It also means one round trip instead of two.
--
-- The immutability trigger was already built for exactly this write:
-- prevent_posted_journal_update permits an is_reversed FALSE->TRUE flip on a
-- posted row when NOTHING ELSE changes, and refuses everything else. This
-- migration does not touch that trigger, and the guard below keeps the update
-- inside what it permits.
--
-- Idempotent, and safe to re-run.

BEGIN;

-- ── 1. Fold the stamp into the atomic post ───────────────────────────────────
-- Only the two statements before RETURN are new; everything else is migration
-- 271's body verbatim, restated because CREATE OR REPLACE FUNCTION needs the
-- whole definition.
CREATE OR REPLACE FUNCTION public.post_journal_atomic(p_entry jsonb, p_lines jsonb)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public', 'pg_catalog'
AS $function$
DECLARE
  v_id            uuid;
  v_existing      uuid;
  v_keys          text;
  v_total_debit   bigint;
  v_total_credit  bigint;
  v_my_firm       uuid;
  v_internal      uuid;
  v_reversed      uuid;
BEGIN
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

  -- ── NEW ────────────────────────────────────────────────────────────────────
  -- This entry IS a reversal, so stamp the original in the same transaction.
  --
  -- The firm_id match is not redundant with the guard above: it pins the stamp
  -- to the firm whose payload was just validated, so a forged reversal_of
  -- cannot reach another tenant's row even though SECURITY DEFINER means RLS
  -- is not running.
  --
  -- COALESCE(is_reversed, false) = false is load-bearing, not defensive.
  -- prevent_posted_journal_update permits the flip only FROM false; attempting
  -- it on an already-stamped row RAISES. Without this predicate a re-post of
  -- the same reversal would error instead of being the no-op it should be.
  v_reversed := NULLIF(p_entry->>'reversal_of', '')::uuid;
  IF v_reversed IS NOT NULL THEN
    UPDATE public.journal_entries
       SET is_reversed = true
     WHERE id = v_reversed
       AND firm_id = (p_entry->>'firm_id')::uuid
       AND COALESCE(is_reversed, false) = false;
  END IF;

  RETURN v_id;
END
$function$;

REVOKE EXECUTE ON FUNCTION public.post_journal_atomic(jsonb, jsonb) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.post_journal_atomic(jsonb, jsonb) FROM anon;
GRANT EXECUTE ON FUNCTION public.post_journal_atomic(jsonb, jsonb) TO authenticated;
GRANT EXECUTE ON FUNCTION public.post_journal_atomic(jsonb, jsonb) TO service_role;

-- ── 2. The is_reversed allowance must not depend on trigger name order ───────
--
-- Migration 266 lets a posted row take an is_reversed FALSE->TRUE flip when
-- NOTHING ELSE changes, tested as `NEW IS NOT DISTINCT FROM old_with_new_flag`.
-- journal_entries also carries trg_journal_updated_at -> set_updated_at, a
-- BEFORE UPDATE trigger that stamps NEW.updated_at. Triggers fire in NAME
-- order, so whether the allowance still holds depends on where the checking
-- trigger sorts relative to that one:
--
--     trg_journal_immutability          prevent_posted_journal_update
--     trg_journal_updated_at            set_updated_at        <- stamps updated_at
--     trg_prevent_posted_journal_update prevent_posted_journal_modification
--
-- The first sees a clean NEW and permits. The third sees updated_at differing
-- as well and RAISES, refusing the write the first just allowed. Production
-- happens to carry only the first (055_v131_hardening.sql, which creates the
-- third, is on test_migrations_apply's known-failure baseline), so the flip
-- works there by luck of which migrations applied -- and fails in any database
-- that has both, including the CI template.
--
-- Neutralising updated_at in the comparison makes the rule mean what it says --
-- nothing MATERIAL changed -- independently of trigger ordering. Both functions
-- are updated: they enforce the same rule and either may be the one that runs.
-- Every other field is still compared, so this narrows nothing else.

CREATE OR REPLACE FUNCTION public.prevent_posted_journal_update()
RETURNS TRIGGER LANGUAGE plpgsql
SET search_path = public, pg_catalog AS $$
DECLARE
    old_with_new_flag journal_entries;
BEGIN
    IF OLD.is_posted = TRUE THEN
        IF public.journal_edit_in_progress() THEN
            RETURN NEW;
        END IF;
        old_with_new_flag := OLD;
        old_with_new_flag.is_reversed := NEW.is_reversed;
        -- set_updated_at may already have stamped this row; that is not a
        -- material change and must not void the allowance.
        old_with_new_flag.updated_at := NEW.updated_at;
        IF COALESCE(OLD.is_reversed, FALSE) = FALSE AND NEW.is_reversed IS TRUE
           AND NEW IS NOT DISTINCT FROM old_with_new_flag THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION
            'Cannot modify a posted journal entry (id: %) directly. Use the '
            'edit endpoint, which checks the period lock and repairs the '
            'reporting cache, or create a reversal.', OLD.id;
    END IF;
    RETURN NEW;
END;
$$;

-- This one fires BEFORE UPDATE OR DELETE, so it is NOT the same body as the
-- function above and must not be written as if it were. Migration 266's
-- delete handling is preserved verbatim: NEW is NULL in a DELETE trigger, and
-- returning NULL from a BEFORE DELETE row trigger silently CANCELS the delete
-- while reporting success. Both pre-266 versions ended in a bare RETURN NEW,
-- which made deleting a draft a no-op from 055 until 266 returned OLD on that
-- path. tests/test_r266_journal_edit_until_locked_pg.py pins it, and caught
-- this exact regression in a first draft of this migration.
CREATE OR REPLACE FUNCTION public.prevent_posted_journal_modification()
RETURNS TRIGGER LANGUAGE plpgsql
SET search_path = public, pg_catalog AS $$
DECLARE
    old_with_new_flag journal_entries;
BEGIN
    IF OLD.is_posted = TRUE THEN
        -- Deletion of a posted entry stays forbidden, edit or no edit.
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION
                'Cannot delete a posted journal entry (id: %). Create a reversal instead.',
                OLD.id
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        IF public.journal_edit_in_progress() THEN
            RETURN NEW;
        END IF;
        old_with_new_flag := OLD;
        old_with_new_flag.is_reversed := NEW.is_reversed;
        old_with_new_flag.updated_at := NEW.updated_at;
        IF COALESCE(OLD.is_reversed, FALSE) = FALSE AND NEW.is_reversed IS TRUE
           AND NEW IS NOT DISTINCT FROM old_with_new_flag THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION
            'Cannot modify a posted journal entry (id: %) directly. Use the '
            'edit endpoint, which checks the period lock and repairs the '
            'reporting cache, or create a reversal.', OLD.id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

-- ── 3. Repair what the gap left behind ───────────────────────────────────────
-- Every entry that HAS a reversal pointing at it but is not flagged. Derived
-- from reversal_of rather than a hand-written id list, so it repairs whatever
-- the bug touched rather than only the one entry that was reported.
--
-- Runs as the migration's owner, but the trigger still fires — and still
-- permits this exact write, because nothing but is_reversed changes.
UPDATE public.journal_entries o
   SET is_reversed = true
 WHERE COALESCE(o.is_reversed, false) = false
   AND EXISTS (
     SELECT 1 FROM public.journal_entries r
      WHERE r.reversal_of = o.id
        AND r.deleted_at IS NULL
   );

COMMIT;
