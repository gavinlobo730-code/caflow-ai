-- Migration 266: a posted journal entry may be CORRECTED until the period is
-- locked or its return is filed — with a complete edit log, and without the
-- reporting passbook silently going wrong.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHY THE PREVIOUS RULE WAS WRONG
-- ═══════════════════════════════════════════════════════════════════════════
-- Migration 251 made a posted entry and its lines absolutely immutable:
-- "Create a reversal entry instead." That is stricter than Indian law, and
-- stricter than the software Indian CAs actually use.
--
-- The governing requirement is the proviso to Rule 3(1) of the Companies
-- (Accounts) Rules 2014, in force from 1 April 2023, which obliges a company to
-- use accounting software having
--
--     "a feature of recording audit trail of each and every transaction,
--      creating an edit log of each change made in books of account along with
--      the date when such changes were made, and ensuring that the audit trail
--      cannot be disabled."
--
-- The rule PRESUMES entries can be changed — an edit log of an unchangeable
-- book would be an empty file. Nothing in the Companies Act 2013 or the Income
-- Tax Act 1961 forbids correcting a posted entry. Tally, the incumbent this
-- product replaces, allows a posted voucher to be altered and records it.
--
-- What genuinely ends the right to edit is a HUMAN act, not the software's
-- opinion:
--
--   * the CA locks the financial year (firms.locked_financial_years), or
--   * a return covering the period has been filed with the government
--     (GSTR-1/3B, ITR, TDS) — after which a correction is a reversal plus an
--     amendment in a later return, because the filed document cannot change.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT MUST NOT BREAK
-- ═══════════════════════════════════════════════════════════════════════════
-- 251's immutability was not only a legal stance. account_period_balances --
-- the passbook that serves Trial Balance, P&L and Balance Sheet from ~141 rows
-- instead of replaying ~12,800 entries -- is maintained by ADDITIVE-ONLY
-- triggers, built on the premise that a posted entry never changes. 251 records
-- what happened when that premise failed: "the passbook drifted exactly as
-- migration 249 had to repair by hand."
--
-- So editing is permitted through EXACTLY ONE path, edit_posted_journal below,
-- which rebuilds the affected client's buckets and asserts no drift before it
-- returns. Direct UPDATE/DELETE stays blocked, which is what keeps that
-- guarantee true: the triggers still refuse everything that is not this
-- function.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- 1. THE EDIT LOG HAS TO COVER THE MONEY
-- ═══════════════════════════════════════════════════════════════════════════
-- journal_entries carries trg_audit_capture. journal_lines does NOT — verified
-- against the live catalogue: its only triggers were trg_apb_on_line_insert,
-- trg_archived_account_check and the immutability guard, all INSERT-only or
-- blocking.
--
-- The lines are where the amounts and the accounts live. Enabling edits while
-- that gap remained would produce an edit log recording that an entry changed
-- while saying nothing about what any figure changed FROM or TO — the letter of
-- Rule 3(1) with none of its substance. This must land before, not after.
--
-- BUT NOT WITH audit_capture() ITSELF. That function reads the firm from the
-- row being changed:
--
--     v_firm := nullif(coalesce(v_new->>'firm_id', v_old->>'firm_id'), '')::uuid;
--     IF v_firm IS NULL THEN RETURN NULL; END IF;
--
-- journal_lines has no firm_id column — verified against the live catalogue.
-- Attaching the generic trigger would therefore return NULL on every row and
-- write nothing, forever, while every schema dump showed an audit trigger
-- sitting on the table. A compliance control that is present and inert is worse
-- than one that is absent, because nobody goes looking for it.
--
-- So the line variant resolves the firm through the parent entry. Everything
-- else — shape of the row written, the actor, the failure behaviour — matches
-- audit_capture exactly, so the two read identically in audit_log.
CREATE OR REPLACE FUNCTION public.audit_capture_journal_line()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public AS $$
DECLARE
  v_actor uuid := auth.uid();
  v_email text;
  v_firm  uuid;
  v_entry uuid;
  v_action text;
  v_old jsonb;
  v_new jsonb;
BEGIN
  IF v_actor IS NULL THEN
    RETURN NULL;
  END IF;

  IF (TG_OP = 'INSERT') THEN
    v_action := 'create'; v_new := to_jsonb(NEW); v_entry := NEW.journal_entry_id;
  ELSIF (TG_OP = 'UPDATE') THEN
    v_action := 'update'; v_new := to_jsonb(NEW); v_old := to_jsonb(OLD);
    v_entry := NEW.journal_entry_id;
  ELSE
    v_action := 'delete'; v_old := to_jsonb(OLD); v_entry := OLD.journal_entry_id;
  END IF;

  SELECT je.firm_id INTO v_firm FROM public.journal_entries je WHERE je.id = v_entry;
  IF v_firm IS NULL THEN
    RETURN NULL;
  END IF;

  SELECT u.email INTO v_email FROM public.users u WHERE u.auth_user_id = v_actor LIMIT 1;

  -- entity_id is the PARENT entry, not the line: an auditor asks "what changed
  -- on this entry", and a log keyed on line ids they have never seen cannot
  -- answer that. The line's own id is in old_data/new_data.
  INSERT INTO public.audit_log
    (firm_id, actor_id, actor_email, entity_type, entity_id, action, old_data, new_data, metadata)
  VALUES
    (v_firm, v_actor, v_email, 'journal_line', v_entry::text, v_action, v_old, v_new,
     jsonb_build_object('source', 'db_trigger', 'table', TG_TABLE_NAME));

  RETURN NULL;
EXCEPTION WHEN OTHERS THEN
  RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS trg_audit_capture_line ON public.journal_lines;
CREATE TRIGGER trg_audit_capture_line
    AFTER INSERT OR UPDATE OR DELETE ON public.journal_lines
    FOR EACH ROW EXECUTE FUNCTION public.audit_capture_journal_line();

REVOKE ALL ON FUNCTION public.audit_capture_journal_line() FROM PUBLIC;


-- ═══════════════════════════════════════════════════════════════════════════
-- 2. THE ONE CARVE-OUT, AND HOW IT IS SCOPED
-- ═══════════════════════════════════════════════════════════════════════════
-- A transaction-local GUC. `set_config(..., true)` makes it local, so it dies
-- with the transaction and cannot leak into the next statement on a pooled
-- connection. Only edit_posted_journal sets it, and it is SECURITY DEFINER with
-- EXECUTE revoked from PUBLIC, so an ordinary caller cannot set the flag and
-- then issue its own UPDATE.
CREATE OR REPLACE FUNCTION public.journal_edit_in_progress()
RETURNS BOOLEAN LANGUAGE sql STABLE
SET search_path = public, pg_catalog AS $$
    SELECT COALESCE(current_setting('app.journal_edit', true), '') = 'on';
$$;

-- Entry header. Preserves 251/213's existing carve-out — the single
-- is_reversed FALSE->TRUE flip that changes no amount, account or date — and
-- adds the audited edit path beside it.
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

-- Deletion stays forbidden even inside an edit. A correction rewrites an
-- entry's lines; it never makes the entry itself vanish, because the edit log
-- must still have something to point at.
CREATE OR REPLACE FUNCTION public.prevent_posted_journal_delete()
RETURNS TRIGGER LANGUAGE plpgsql
SET search_path = public, pg_catalog AS $$
BEGIN
    IF OLD.is_posted = TRUE THEN
        RAISE EXCEPTION
            'Cannot delete a posted journal entry (id: %). Create a reversal instead.',
            OLD.id;
    END IF;
    RETURN OLD;
END;
$$;

-- Lines. Deleting a line IS legitimate inside an edit — a three-leg entry
-- corrected to two legs has to lose one — so the carve-out covers DELETE here,
-- unlike the entry header above. The balance check in edit_posted_journal is
-- what stops that leaving Dr <> Cr.
CREATE OR REPLACE FUNCTION public.prevent_posted_journal_line_modification()
RETURNS TRIGGER LANGUAGE plpgsql
SET search_path = public, pg_catalog AS $$
DECLARE
    v_is_posted BOOLEAN;
BEGIN
    SELECT is_posted INTO v_is_posted
      FROM public.journal_entries
     WHERE id = OLD.journal_entry_id;

    IF v_is_posted IS TRUE AND NOT public.journal_edit_in_progress() THEN
        RAISE EXCEPTION
            'Cannot modify or delete lines of a posted journal entry '
            '(journal_entry_id: %) directly. Use the edit endpoint, or create '
            'a reversal entry instead.',
            OLD.journal_entry_id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;


-- ═══════════════════════════════════════════════════════════════════════════
-- 3. IS THIS PERIOD STILL OPEN?
-- ═══════════════════════════════════════════════════════════════════════════
-- Returns NULL when the date may still be edited, or a human-readable reason
-- when it may not. Returning the REASON rather than a boolean is deliberate:
-- "the year is locked" and "GSTR-3B for this period was filed on 2026-05-18"
-- call for different actions from the CA, and a bare `false` tells them
-- neither.
--
-- Indian financial year runs 1 April to 31 March (Income Tax Act §3), which is
-- why the lock is keyed on a "YYYY-YY" label rather than a calendar year.
CREATE OR REPLACE FUNCTION public.journal_period_lock_reason(
    p_firm   uuid,
    p_client uuid,
    p_date   date
) RETURNS TEXT LANGUAGE plpgsql STABLE
SET search_path = public, pg_catalog AS $$
DECLARE
    v_fy_start  int;
    v_fy_label  text;
    v_locked    text[];
    v_filing    record;
BEGIN
    v_fy_start := CASE WHEN EXTRACT(MONTH FROM p_date) >= 4
                       THEN EXTRACT(YEAR FROM p_date)::int
                       ELSE EXTRACT(YEAR FROM p_date)::int - 1 END;
    v_fy_label := v_fy_start::text || '-' || lpad(((v_fy_start + 1) % 100)::text, 2, '0');

    SELECT locked_financial_years INTO v_locked FROM public.firms WHERE id = p_firm;
    IF v_locked IS NOT NULL AND v_fy_label = ANY (v_locked) THEN
        RETURN 'Financial year ' || v_fy_label || ' is locked. Unlock it, or post a reversal in an open year.';
    END IF;

    -- A filed return freezes the period it covers. The document at the portal
    -- cannot be recalled, so the books behind it must stop moving too —
    -- otherwise the return and the ledger disagree with nothing recording why.
    SELECT filing_type, filed_date INTO v_filing
      FROM public.filings
     WHERE client_id = p_client
       AND deleted_at IS NULL
       AND filed_date IS NOT NULL
       AND p_date BETWEEN period_start AND period_end
     ORDER BY filed_date
     LIMIT 1;
    IF FOUND THEN
        RETURN v_filing.filing_type || ' covering this date was filed on '
               || to_char(v_filing.filed_date, 'DD Mon YYYY')
               || '. Correct it with a reversal and an amendment in the next return.';
    END IF;

    RETURN NULL;
END;
$$;


-- ═══════════════════════════════════════════════════════════════════════════
-- 4. THE ONLY SUPPORTED WAY TO CORRECT A POSTED ENTRY
-- ═══════════════════════════════════════════════════════════════════════════
-- Atomic by construction: validate, rewrite, repair the passbook, prove no
-- drift. If any step raises, the whole transaction rolls back and the ledger is
-- exactly as it was. That is the property migration 249 did not have when it
-- repaired drift by hand.
--
-- p_lines is [{account_id, debit_paise, credit_paise, narration}, ...].
-- All amounts are INTEGER PAISE. No float ever touches a rupee value here.
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
        (journal_entry_id, account_id, debit_paise, credit_paise, narration)
    SELECT p_entry_id,
           (ln->>'account_id')::uuid,
           (ln->>'debit_paise')::bigint,
           (ln->>'credit_paise')::bigint,
           NULLIF(ln->>'narration', '')
      FROM jsonb_array_elements(p_lines) ln;

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

-- SECURITY DEFINER + no PUBLIC execute: the carve-out flag is only reachable
-- through this function, so "posted entries are immutable except here" stays a
-- fact about the database rather than a convention in the application.
REVOKE ALL ON FUNCTION public.edit_posted_journal(uuid, uuid, uuid, jsonb, text, text, date, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.edit_posted_journal(uuid, uuid, uuid, jsonb, text, text, date, uuid) TO authenticated, service_role;
REVOKE ALL ON FUNCTION public.journal_edit_in_progress() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.journal_period_lock_reason(uuid, uuid, date) TO authenticated, service_role;
