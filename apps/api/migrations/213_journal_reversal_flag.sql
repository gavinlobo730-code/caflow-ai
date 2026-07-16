-- Migration 213: Journal reversal flag (task #102 finding — idempotency vs
-- reversed entries).
--
-- reverse_entry() posts a new balanced opposite journal but never marks the
-- ORIGINAL entry as reversed. _create_journal's idempotency fast-path
-- (firm_id, client_id, reference_no, entry_date) — backed by the partial
-- UNIQUE index from migration 143 — therefore can't distinguish a live entry
-- from one that has already been reversed: re-posting the same document
-- (e.g. re-processing an invoice after its journal was reversed) silently
-- dedupes onto the dead original instead of creating a fresh entry.
--
-- is_reversed is append-only: the immutability triggers (055, 058) still
-- block every other mutation of a posted entry; only the narrow
-- FALSE→TRUE flip (with every other column unchanged) is now permitted,
-- stamped by reverse_entry() right after it posts the reversal.

ALTER TABLE journal_entries ADD COLUMN IF NOT EXISTS is_reversed boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN journal_entries.is_reversed IS
    'Set true when this entry has been reversed via reverse_entry(). Append-only — the sole column immutability triggers permit changing on a posted row. Excluded from the reference_no+entry_date idempotency match so a reversed document can be legitimately re-posted.';

-- Recreate the migration-143 idempotency index to also exclude reversed
-- entries — a reversed original must not dedupe-block a legitimate re-post.
DROP INDEX IF EXISTS uq_journal_entries_firm_client_ref_date;
CREATE UNIQUE INDEX IF NOT EXISTS uq_journal_entries_firm_client_ref_date
  ON public.journal_entries (firm_id, client_id, reference_no, entry_date)
  WHERE deleted_at IS NULL AND reference_no IS NOT NULL AND is_reversed = false;

-- ── Immutability triggers: permit the single is_reversed FALSE→TRUE flip ──

CREATE OR REPLACE FUNCTION prevent_posted_journal_modification()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    old_with_new_flag journal_entries;
BEGIN
    IF OLD.is_posted = TRUE THEN
        old_with_new_flag := OLD;
        old_with_new_flag.is_reversed := NEW.is_reversed;
        IF COALESCE(OLD.is_reversed, FALSE) = FALSE AND NEW.is_reversed IS TRUE
           AND NEW IS NOT DISTINCT FROM old_with_new_flag THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION 'Cannot modify or delete a posted journal entry (id: %). '
            'Create a reversal entry instead.', OLD.id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION prevent_posted_journal_update()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    old_with_new_flag journal_entries;
BEGIN
    IF OLD.is_posted = TRUE THEN
        old_with_new_flag := OLD;
        old_with_new_flag.is_reversed := NEW.is_reversed;
        IF COALESCE(OLD.is_reversed, FALSE) = FALSE AND NEW.is_reversed IS TRUE
           AND NEW IS NOT DISTINCT FROM old_with_new_flag THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION 'Cannot modify a posted journal entry (id: %). Create a reversal instead.', OLD.id;
    END IF;
    RETURN NEW;
END;
$$;

ALTER FUNCTION public.prevent_posted_journal_modification() SET search_path = public, pg_catalog;
ALTER FUNCTION public.prevent_posted_journal_update()        SET search_path = public, pg_catalog;

-- post_journal_atomic's (migration 152) unique_violation fallback SELECT must
-- also exclude reversed rows — otherwise a genuine concurrent-duplicate race
-- on a LIVE entry could return a stale reversed row (same reference_no+
-- entry_date, older created_at) instead of the actual live winner, since the
-- SELECT was never filtered by is_reversed and ORDER BY created_at LIMIT 1
-- picks the oldest match. The INSERT itself needs no change — the partial
-- unique index (redefined above) already excludes is_reversed=true rows, so
-- inserting a fresh live entry over a reversed original no longer raises
-- unique_violation at all.
CREATE OR REPLACE FUNCTION post_journal_atomic(p_entry jsonb, p_lines jsonb)
RETURNS uuid
LANGUAGE plpgsql
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
