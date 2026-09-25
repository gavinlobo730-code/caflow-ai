-- Migration 418: a voucher line can say which part of the business it belongs to.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS MISSING (ACC-13, decided as D29)
-- ═══════════════════════════════════════════════════════════════════════════
-- A CA could not tag a voucher to a cost centre, a branch or a project, so
-- there was no departmental or project profit and loss — a routine Tally
-- expectation, and the first thing a client with two shops or three
-- departments asks for. The 16-09-2026 re-read measured it: `grep -rniE
-- 'cost.?cent'` over `apps/api` and `apps/web/{app,components,lib}` returned
-- ONE unrelated comment, and no migration mentioned them at all.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- IT IS A DIMENSION, NOT A SECOND SET OF BOOKS
-- ═══════════════════════════════════════════════════════════════════════════
-- The column changes no figure. A cost centre does not affect the double
-- entry, the trial balance, any statutory output or any return: GST, TDS and
-- the ITR are computed from documents and accounts, and a departmental P&L is
-- MANAGEMENT reporting, not Schedule III. A test asserts no return builder
-- mentions the column, because a dimension that leaked into a statutory total
-- would be the worst possible version of this feature.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- NULLABLE, NO DEFAULT, NO BACKFILL — AND NULL IS THE NORM
-- ═══════════════════════════════════════════════════════════════════════════
-- Migration 411's reason, and one more of its own. 411's: every line already
-- posted was written by a door that did not know the column, so a default
-- would assert a centre nobody chose. The additional one: even on a client who
-- uses the dimension, MOST LINES HAVE NO COST CENTRE. A bank leg, a GST leg
-- and a TDS leg belong to no department — only the expense and revenue legs
-- do — so NULL is not an omission to be chased and a report must show the
-- unallocated balance as its own row rather than dropping it or folding it
-- into a department nobody chose.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- THREE FUNCTIONS ARE REPLACED, EACH DERIVED FROM ITS LAST DEFINER BY SCRIPT
-- ═══════════════════════════════════════════════════════════════════════════
-- `CREATE OR REPLACE` overwrites whatever is there, so a replacement either
-- carries every earlier change forward or silently reverts it — and the revert
-- compiles, deploys and passes a mock suite. Migration 384 got this wrong
-- TWICE before the real-Postgres suite caught it, once by hand-writing the
-- body and once by deriving it faithfully from the WRONG ANCESTOR.
--
--   post_journal_atomic                      ← 384 (243 → 271 → 274 → 384)
--   edit_posted_journal                      ← 384 (266 → 338 → 384)
--   assert_journal_lines_belong_to_the_client ← 360 (its only definer)
--
-- Each was found the way the database finds it — the highest-numbered
-- migration defining it, EXCLUDING `_rollback` files, which define the OLD
-- body and are exactly the trap a `| tail -1` walks into. Each body below is
-- the ancestor's text with a named, counted substitution applied by
-- `/tmp/derive418.py`'s logic rather than retyped, and
-- `tests/test_a_voucher_line_can_name_its_cost_centre.py` re-derives the same
-- comparison from the migration directory so it cannot be pointed at a stale
-- ancestor.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- THE EDIT PATH IS THE HALF THAT WOULD HAVE BEEN FORGOTTEN
-- ═══════════════════════════════════════════════════════════════════════════
-- `edit_posted_journal` DELETEs every line of the entry and re-INSERTs the
-- array it was given — "replace rather than reconcile", in its own words. Left
-- alone it would re-insert them with `cost_centre_id` NULL, so a voucher the
-- CA had allocated LOST its allocation the first time it was corrected, and
-- silently: the departmental P&L would simply show less. That is exactly the
-- defect 384 fixed for `line_order`, on a dimension somebody makes decisions
-- from.
--
-- 384's own comment recorded that this payload carries four keys per line and
-- that an override branch would therefore be dead code.
-- ⚠️ THAT IS NO LONGER TRUE: `manual_journal_service` sends a fifth key now,
-- and a test pins it. A column the edit path does not read is a column the
-- edit path erases.

BEGIN;

-- ── THE MASTER ───────────────────────────────────────────────────────────────
--
-- Client-scoped, not firm-scoped, and `client_id` is NOT NULL. A cost centre
-- divides ONE CLIENT's operations: "Factory" and "Retail" are Acme's
-- departments, not the practice's. A firm-level one would be a department of
-- the practice itself, which is a different feature (the practice's own
-- internal client already exists for its own books) and which the trigger
-- below relies on being impossible.
CREATE TABLE IF NOT EXISTS public.cost_centres (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id     UUID NOT NULL REFERENCES public.firms(id)   ON DELETE CASCADE,
    client_id   UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,

    -- What the CA types on a voucher. Trimmed and upper-cased by the API door,
    -- so `factory` and `FACTORY` cannot become two centres.
    code        TEXT NOT NULL CHECK (btrim(code) <> '' AND length(code) <= 24),
    name        TEXT NOT NULL CHECK (btrim(name) <> ''),
    description TEXT,

    -- RETIRED, NEVER DELETED, for the reason every master in this schema is:
    -- posted lines point at it and a posted line cannot be rewritten
    -- (migration 251). Closing a department does not un-spend last year's
    -- money, so the centre stays and stops being offered.
    is_active   BOOLEAN NOT NULL DEFAULT true,

    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT cost_centres_code_unique_per_client UNIQUE (client_id, code)
);

CREATE INDEX IF NOT EXISTS cost_centres_client_active_idx
    ON public.cost_centres (client_id, is_active);

COMMENT ON TABLE public.cost_centres IS
  'ACC-13. A division of ONE CLIENT''s operations — a department, a branch, a '
  'project — that a journal line may be tagged with. A DIMENSION, not a second '
  'set of books: it changes no figure, no total and no statutory output. '
  'Retired with is_active rather than deleted, because posted lines point at '
  'it and migration 251 makes a posted line immutable.';

ALTER TABLE public.cost_centres ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "firm_isolation" ON public.cost_centres;
CREATE POLICY "firm_isolation" ON public.cost_centres
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());

-- Migration 084's assignment scope, applied at creation rather than left for a
-- sweep that has not run since 2024. The row names a client, so an Executive
-- who is not assigned to them must not read their departments.
DROP POLICY IF EXISTS "cost_centres_assignment_scope" ON public.cost_centres;
CREATE POLICY "cost_centres_assignment_scope" ON public.cost_centres
  AS RESTRICTIVE FOR ALL TO authenticated
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));

GRANT SELECT, INSERT, UPDATE, DELETE ON public.cost_centres TO authenticated;

-- ── THE DIMENSION ON THE LINE ────────────────────────────────────────────────
--
-- ⚠️ ON DELETE RESTRICT, deliberately, and it is the only sound choice. CASCADE
-- would delete POSTED JOURNAL LINES when somebody tidied a master — the general
-- ledger destroyed by a housekeeping click — and SET NULL would silently
-- un-allocate history that a filed management report was built on. RESTRICT
-- makes the master row un-deletable once anything is posted against it, which
-- is what `is_active` exists to make unnecessary.
ALTER TABLE public.journal_lines
  ADD COLUMN IF NOT EXISTS cost_centre_id UUID
    REFERENCES public.cost_centres(id) ON DELETE RESTRICT;

CREATE INDEX IF NOT EXISTS journal_lines_cost_centre_idx
    ON public.journal_lines (cost_centre_id)
    WHERE cost_centre_id IS NOT NULL;

COMMENT ON COLUMN public.journal_lines.cost_centre_id IS
  'ACC-13. Which part of the client''s business this line belongs to. NULLABLE '
  'and NULL on most lines BY DESIGN — a bank leg and a tax leg belong to no '
  'department — so a report shows the unallocated balance as its own row '
  'rather than dropping it. Never back-filled: every line written before '
  'migration 418 came through a door that did not know the column. It changes '
  'no figure and no statutory output.';

-- ── post_journal_atomic ── derived from migration 384 ───────────────────────
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
    rate_source, rate_type, rate_date, line_order, cost_centre_id
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
    NULLIF(l->>'rate_date', '')::date,
    -- WITH ORDINALITY is 1-based; the column is 0-based so it reads as an
    -- index. A caller that sent its own line_order still wins, which is what
    -- lets manual_journal_service re-number an edited voucher.
    COALESCE((l->>'line_order')::integer, (ord - 1)::integer),
    -- ACC-13. Absent or empty is NULL, which is the NORM rather than an
    -- omission: a bank leg and a tax leg belong to no cost centre, and only
    -- the expense and revenue legs of a voucher carry one. The dimension
    -- never touches the double entry — the balance guard above is unchanged.
    NULLIF(l->>'cost_centre_id', '')::uuid
  FROM jsonb_array_elements(p_lines) WITH ORDINALITY AS t(l, ord);

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

-- ── edit_posted_journal ── derived from migration 384 ──────────────────────
CREATE OR REPLACE FUNCTION public.edit_posted_journal(
    p_firm         uuid,
    p_client       uuid,
    p_entry_id     uuid,
    p_lines        jsonb,
    p_narration    text     DEFAULT NULL,
    p_reference_no text     DEFAULT NULL,
    p_entry_date   date     DEFAULT NULL,
    p_actor        uuid     DEFAULT NULL
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_catalog AS $$
DECLARE
    v_entry      public.journal_entries;
    v_new_date   date;
    v_reason     text;
    v_debit      bigint;
    v_credit     bigint;
    v_count      int;
BEGIN
    SELECT * INTO v_entry
      FROM public.journal_entries
     WHERE id = p_entry_id AND firm_id = p_firm AND client_id = p_client
       AND deleted_at IS NULL
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Journal entry not found.' USING ERRCODE = 'no_data_found';
    END IF;

    -- (1) Manual only — the gate migration 275 gave the discard path, in the
    -- same words, because it is the same rule about the same entries.
    IF COALESCE(v_entry.source_type, '') <> 'manual' THEN
        RAISE EXCEPTION
            'This entry was posted automatically from a %. Correct the document '
            'itself — editing its journal would leave the document and the '
            'ledger saying different things.',
            COALESCE(NULLIF(v_entry.source_type, ''), 'source document');
    END IF;

    IF COALESCE(v_entry.is_reversed, FALSE) THEN
        RAISE EXCEPTION 'This entry has been reversed and can no longer be edited.';
    END IF;

    v_new_date := COALESCE(p_entry_date, v_entry.entry_date);

    -- BOTH dates are checked. Moving an entry OUT of a locked period is as much
    -- a change to that period's numbers as editing one already in it, and a
    -- check on the new date alone would let a locked year be quietly emptied.
    v_reason := public.journal_period_lock_reason(p_firm, p_client, v_entry.entry_date);
    IF v_reason IS NOT NULL THEN RAISE EXCEPTION '%', v_reason; END IF;
    IF v_new_date <> v_entry.entry_date THEN
        v_reason := public.journal_period_lock_reason(p_firm, p_client, v_new_date);
        IF v_reason IS NOT NULL THEN RAISE EXCEPTION '%', v_reason; END IF;
    END IF;

    SELECT count(*),
           COALESCE(sum((ln->>'debit_paise')::bigint), 0),
           COALESCE(sum((ln->>'credit_paise')::bigint), 0)
      INTO v_count, v_debit, v_credit
      FROM jsonb_array_elements(p_lines) ln;

    IF v_count < 2 THEN
        RAISE EXCEPTION 'A journal entry needs at least two lines.';
    END IF;
    -- Double entry. Integer paise on both sides, compared exactly — the same
    -- invariant post_journal_atomic enforces on the way in, enforced again on
    -- the way through, because an edit is a posting too.
    IF v_debit <> v_credit THEN
        RAISE EXCEPTION 'Unbalanced entry: debit % paise <> credit % paise.', v_debit, v_credit;
    END IF;

    PERFORM set_config('app.journal_edit', 'on', true);

    UPDATE public.journal_entries
       SET entry_date   = v_new_date,
           narration    = COALESCE(p_narration, narration),
           reference_no = COALESCE(p_reference_no, reference_no),
           updated_at   = now()
     WHERE id = p_entry_id;

    -- Replace rather than reconcile. The audit trigger records the deletes and
    -- the inserts, so the before/after of every figure survives in the log.
    DELETE FROM public.journal_lines WHERE journal_entry_id = p_entry_id;

    INSERT INTO public.journal_lines
        (journal_entry_id, account_id, debit_paise, credit_paise, narration, line_order,
         cost_centre_id)
    SELECT p_entry_id,
           (ln->>'account_id')::uuid,
           (ln->>'debit_paise')::bigint,
           (ln->>'credit_paise')::bigint,
           NULLIF(ln->>'narration', ''),
           -- The array the CA saved IS the order (migration 384). WITH
           -- ORDINALITY is 1-based and the column is 0-based.
           (ord - 1)::integer,
           -- ACC-13. THIS PATH REPLACES EVERY LINE, so without it a
           -- correction would silently WIPE the cost centre the CA had
           -- allocated — exactly the defect 384 fixed for line_order, on a
           -- dimension a departmental P&L is built from. 384's own comment
           -- recorded that this payload carries four keys per line;
           -- `manual_journal_service` now sends a fifth, and a test pins
           -- it, because a column the edit path does not read is a column
           -- the edit path erases.
           NULLIF(ln->>'cost_centre_id', '')::uuid
      FROM jsonb_array_elements(p_lines) WITH ORDINALITY AS t(ln, ord);

    PERFORM set_config('app.journal_edit', '', true);

    -- The passbook's triggers are additive-only and did not see any of the
    -- above. Rebuild, then PROVE it — an unasserted rebuild is how 249's drift
    -- went unnoticed in the first place.
    PERFORM public.apb_rebuild_client(p_firm, p_client);
    PERFORM public.apb_assert_no_drift();

    RETURN jsonb_build_object(
        'id', p_entry_id,
        'entry_date', v_new_date,
        'lines', v_count,
        'total_debit_paise', v_debit,
        'total_credit_paise', v_credit,
        'edited_by', p_actor
    );
END;
$$;

REVOKE ALL ON FUNCTION public.edit_posted_journal(uuid, uuid, uuid, jsonb, text, text, date, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.edit_posted_journal(uuid, uuid, uuid, jsonb, text, text, date, uuid) TO authenticated, service_role;

-- ── the tenancy trigger ── derived from migration 360 ──────────────────────
CREATE OR REPLACE FUNCTION public.assert_journal_lines_belong_to_the_client()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public', 'pg_catalog'
AS $$
DECLARE
    v_bad text;
    v_bad_cc text;
BEGIN
    -- ONE anti-join over the whole statement. A line is bad when no account
    -- exists that is BOTH the named id and inside the entry's firm and client.
    SELECT string_agg(DISTINCT nl.account_id::text, ', ')
      INTO v_bad
      FROM new_lines nl
      JOIN public.journal_entries je ON je.id = nl.journal_entry_id
      LEFT JOIN public.chart_of_accounts coa
             ON coa.id = nl.account_id
            AND coa.firm_id = je.firm_id
            AND (coa.client_id = je.client_id OR coa.client_id IS NULL)
     WHERE coa.id IS NULL;

    IF v_bad IS NOT NULL THEN
        RAISE EXCEPTION
            'journal line account(s) % do not belong to this entry''s firm and client',
            v_bad
            USING ERRCODE = '42501';
    END IF;

    -- ACC-13, migration 418. THE SAME HOLE, ON THE SAME TABLE, FOR THE SAME
    -- REASON: `journal_lines.cost_centre_id` carries only a global FK to
    -- `cost_centres(id)`, so without this every cost centre in the database
    -- satisfies it and one firm's voucher can be tagged with another firm's
    -- department. It is here rather than in each posting function for 360's
    -- own reason: a rule enforced in twenty-six places is a rule with
    -- twenty-six chances to be forgotten.
    --
    -- A NULL cost centre PASSES, and must: it is the norm. A bank leg and a
    -- tax leg belong to no department, and a client who does not use the
    -- dimension has NULL on every line.
    --
    -- The client match is EXACT, with no `IS NULL` arm — unlike the account
    -- join above, which allows a firm-level account. A cost centre divides
    -- ONE CLIENT's own operations; a firm-level one would be a department of
    -- the practice, which is not what this dimension is for and which
    -- `cost_centres.client_id NOT NULL` forbids anyway.
    SELECT string_agg(DISTINCT nl.cost_centre_id::text, ', ')
      INTO v_bad_cc
      FROM new_lines nl
      JOIN public.journal_entries je ON je.id = nl.journal_entry_id
      LEFT JOIN public.cost_centres cc
             ON cc.id = nl.cost_centre_id
            AND cc.firm_id = je.firm_id
            AND cc.client_id = je.client_id
     WHERE nl.cost_centre_id IS NOT NULL
       AND cc.id IS NULL;

    IF v_bad_cc IS NOT NULL THEN
        RAISE EXCEPTION
            'journal line cost centre(s) % do not belong to this entry''s firm and client',
            v_bad_cc
            USING ERRCODE = '42501';
    END IF;
    RETURN NULL;
END $$;

COMMENT ON FUNCTION public.assert_journal_lines_belong_to_the_client() IS
    'ACC-21 and ACC-13. post_journal_atomic and edit_posted_journal scope the '
    'ENTRY and not its lines, and journal_lines.account_id and cost_centre_id '
    'each carry only a GLOBAL FK — so any account id, and (from migration 418) '
    'any cost centre id, in the database satisfied them. Statement-level with a '
    'transition table because journal_lines is the highest-volume table here. '
    'Migrations 360 and 418.';

COMMIT;
