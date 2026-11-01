-- Migration 573: one ledger entry pays one TDS challan, and a stored link to a ledger entry names an entry of the row's own client
-- (POST-A-272, fixes from the independent review of migration 568).
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═══════════════════════════════════════════════════════════════════════════
-- Migration 568 gave `tds_challans` a `journal_entry_id` (the ledger entry that paid the challan). Three things about it were left to the
-- API alone, and the independent review found each of them:
--
--   1. "ONE ENTRY CANNOT BE THE PAYMENT OF TWO CHALLANS" WAS A READ FOLLOWED BY A WRITE. The service reads whether another challan already
--      holds the entry and then updates, so two requests tying two different challans to the same entry at the same moment both read
--      "free" and both wrote. The index 568 added is a plain lookup index, not a constraint. The rule is now the index: a PARTIAL UNIQUE
--      index on the column where it is not NULL. (The service keeps its read for the sentence that names the other challan; the index
--      is what decides.)
--   2. THE LINK COULD NAME ANOTHER CLIENT'S ENTRY. A foreign-key check bypasses row security, so the key is satisfied by any entry in the
--      database. The API asks whose the entry is, and the database did not, so a hand-made PostgREST call by a signed-in Executive (the
--      tier that may update this table) could store a link into another client's books. The same is true of the older
--      `statutory_remittances.journal_entry_id` (migration 365), which this installs the same check on. The check is the rule migrations
--      565 and 570 apply to a client and to an account: the row's entry belongs to the row's own firm and client.
--   3. MIGRATION 568'S HEADER SAID "REVERSING THE PAYMENT ENTRY UNLINKS THE CHALLAN". IT DOES NOT. `ON DELETE SET NULL` fires when an
--      entry is hard-deleted, and a posted entry is never hard-deleted: it is reversed (a reversal is appended and the original flagged)
--      or soft-deleted, and the link then still points at an entry that no longer records the payment. The API reads that state for every
--      tied challan (`ledger_link`) and says so on the screen; the link is never cleared on its own, because whether the challan belongs
--      to a different entry or to none is the CA's decision. This file corrects the column's comment; the header of 568 is a merged file
--      and is left as it was.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═══════════════════════════════════════════════════════════════════════════
--   * Replaces `idx_tds_challans_journal_entry` with `uq_tds_challans_journal_entry`, a partial UNIQUE index on `journal_entry_id` WHERE
--     it is not NULL. If any entry is already tied to two challans, the file STOPS in words rather than choosing which link to drop: which
--     challan an entry paid is the CA's answer. A read-only count on production on 2-11-2026 found two challans, none tied.
--   * `public.guard_journal_entry(table, column)` installs a BEFORE INSERT trigger and a BEFORE UPDATE trigger on one uuid column that
--     names a journal entry, on a table that carries its own uuid `firm_id` and `client_id`: the entry's firm and client must be the row's.
--     The update trigger fires only when the column, the firm or the client changes, so an ordinary edit pays nothing and a row that
--     already breaks the rule can still be edited. It is installed on `tds_challans.journal_entry_id` and
--     `statutory_remittances.journal_entry_id`.
--     SECURITY DEFINER, because the check has to SEE the other client's entry, which row security hides from the writer; the search path is
--     pinned. A refusal is P0001, a business rule written for a person (core/exceptions surfaces its message as it is).
--     An entry id that does not exist is NOT this function's to report: the foreign key says it in its own words. An entry with NO client
--     (a firm-level entry) is refused for a client's row, which is stricter than 565 and 570 ("refuse only what provably crosses") and is
--     what the API already requires of the link (the entry's client equals the challan's); no such entry exists today.
--     The function FAILS CLOSED: a trigger argument that names a column the row no longer has (a later rename) raises instead of passing.
--   * Reports (`RAISE WARNING 'migration 573: ...'`, which the runner keeps) how many existing rows tie an entry of another client or
--     firm, and changes none of them: a row found that way is a finding for a person.
--
-- WHAT IT DELIBERATELY DOES NOT DO
--   * It adds no unique rule to `statutory_remittances`: nothing says one entry cannot be the payment of two of those, and a single bank
--     debit settling an ESI and a professional-tax remittance together is not an error.
--   * It does not judge what happens on the ENTRY's side: an entry that is moved to another client after it was tied is not re-judged
--     (a posted entry's client is not editable), the same limit 570 records for an account.
--   * It does not stop a challan being tied to an entry that is not a payment (a reversed or deleted one, or one that does not debit the
--     right account). Those are questions about the entry's state and lines, asked in words by the API; the database holds the tenant
--     boundary and the one-entry-one-challan rule, which are the two it can decide from the row alone.
--
-- The rollback (573_..._rollback.sql) takes the triggers and the unique index away and puts 568's plain index back. Migration 568's own
-- rollback drops the column, and a column a trigger's WHEN clause names cannot be dropped, so 573's rollback must run before 568's.
--
-- Nothing here transmits anything to a portal.

BEGIN;

-- 1. One entry, one challan.
DO $$
DECLARE
    v_dupes int;
BEGIN
    SELECT count(*) INTO v_dupes
      FROM (SELECT journal_entry_id FROM public.tds_challans WHERE journal_entry_id IS NOT NULL
             GROUP BY journal_entry_id HAVING count(*) > 1) d;
    IF v_dupes > 0 THEN
        RAISE EXCEPTION 'migration 573: % ledger entr(ies) are tied to more than one TDS challan. Which challan an entry paid is the CA''s answer, so this file does not choose: take the wrong links back (unlink-payment) and run it again.', v_dupes;
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_tds_challans_journal_entry
    ON public.tds_challans (journal_entry_id)
    WHERE journal_entry_id IS NOT NULL;

-- The plain index 568 added is the same index without the rule; the unique one answers the same lookups.
DROP INDEX IF EXISTS public.idx_tds_challans_journal_entry;

COMMENT ON COLUMN public.tds_challans.journal_entry_id IS
    'The ledger entry that paid this challan (Dr TDS Payable / Cr Bank). A link only, never a posting; NULL = not tied to an entry. '
    'One entry pays one challan (unique index) and the entry is the challan''s own client''s (guard_journal_entry). Cleared ONLY when the '
    'entry is hard-deleted; a reversed or soft-deleted entry leaves the link in place and the API reports it as stale. POST-A-272, 568 and 573.';

-- 2. The tenant check.
CREATE OR REPLACE FUNCTION public.assert_row_names_a_journal_entry_of_its_client()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'pg_catalog', 'public'
AS $$
DECLARE
    v_col text := TG_ARGV[0];
    v_row jsonb := to_jsonb(NEW);
    v_entry uuid := NULLIF(v_row ->> v_col, '')::uuid;
    v_firm uuid := NULLIF(v_row ->> 'firm_id', '')::uuid;
    v_client uuid := NULLIF(v_row ->> 'client_id', '')::uuid;
    v_efirm uuid;
    v_eclient uuid;
BEGIN
    IF NOT (v_row ? v_col) THEN
        -- A trigger argument that names a column the row no longer has (a rename) must not turn the guard into a pass.
        RAISE EXCEPTION 'guard_journal_entry: % has no column %', TG_TABLE_NAME, v_col;
    END IF;
    IF v_entry IS NULL THEN
        RETURN NEW;
    END IF;
    SELECT e.firm_id, e.client_id INTO v_efirm, v_eclient FROM public.journal_entries e WHERE e.id = v_entry;
    IF NOT FOUND THEN
        RETURN NEW;                       -- no such entry: the foreign key refuses it, in its own words
    END IF;
    IF v_efirm IS DISTINCT FROM v_firm OR v_eclient IS DISTINCT FROM v_client THEN
        RAISE EXCEPTION 'That ledger entry belongs to another client or firm, so it cannot be tied to this record (% in %).',
            v_col, TG_TABLE_NAME;
    END IF;
    RETURN NEW;
END $$;

COMMENT ON FUNCTION public.assert_row_names_a_journal_entry_of_its_client() IS
    'POST-A-272. Row-level check: the journal entry a row names (the column in its first trigger argument) belongs to the row''s own firm and '
    'client. An entry that does not exist is left to the foreign key. Installed by guard_journal_entry. Migration 573.';

-- Only the trigger machinery runs it. A trigger function cannot be called directly, but a role holding TRIGGER on some table could attach it
-- with its own argument, so nobody signed in is given EXECUTE (the installer runs as the owner).
REVOKE ALL ON FUNCTION public.assert_row_names_a_journal_entry_of_its_client() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.assert_row_names_a_journal_entry_of_its_client() FROM anon;
REVOKE ALL ON FUNCTION public.assert_row_names_a_journal_entry_of_its_client() FROM authenticated;

-- 3. The installer. Idempotent. The column must be a uuid and, if it is a foreign key, a key to journal_entries; the table must carry its
--    own uuid firm_id and client_id.
CREATE OR REPLACE FUNCTION public.guard_journal_entry(p_table regclass, p_column text)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    v_ins text := 'row_journal_entry_' || p_column || '_ins';
    v_upd text := 'row_journal_entry_' || p_column || '_upd';
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = p_table AND a.attname = p_column
                      AND a.atttypid = 'uuid'::regtype AND a.attnum > 0 AND NOT a.attisdropped) THEN
        RAISE EXCEPTION 'guard_journal_entry: %.% is not a uuid column', p_table, p_column;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_constraint k
                WHERE k.contype = 'f' AND k.conrelid = p_table
                  AND k.conkey = ARRAY[(SELECT a.attnum FROM pg_attribute a WHERE a.attrelid = p_table AND a.attname = p_column)]
                  AND k.confrelid <> 'public.journal_entries'::regclass) THEN
        RAISE EXCEPTION 'guard_journal_entry: %.% is a foreign key to something other than journal_entries', p_table, p_column;
    END IF;
    IF (SELECT count(*) FROM pg_attribute a
         WHERE a.attrelid = p_table AND a.attname IN ('client_id', 'firm_id')
           AND a.atttypid = 'uuid'::regtype AND a.attnum > 0 AND NOT a.attisdropped) <> 2 THEN
        RAISE EXCEPTION 'guard_journal_entry: % has not the uuid columns client_id and firm_id to judge % by', p_table, p_column;
    END IF;

    EXECUTE format('DROP TRIGGER IF EXISTS %I ON %s', v_ins, p_table);
    EXECUTE format(
        'CREATE TRIGGER %I BEFORE INSERT ON %s FOR EACH ROW WHEN (NEW.%I IS NOT NULL) '
        'EXECUTE FUNCTION public.assert_row_names_a_journal_entry_of_its_client(%L)', v_ins, p_table, p_column, p_column);
    EXECUTE format('DROP TRIGGER IF EXISTS %I ON %s', v_upd, p_table);
    EXECUTE format(
        'CREATE TRIGGER %I BEFORE UPDATE OF %I, firm_id, client_id ON %s FOR EACH ROW WHEN (NEW.%I IS NOT NULL AND '
        '(OLD.%I IS DISTINCT FROM NEW.%I OR OLD.firm_id IS DISTINCT FROM NEW.firm_id OR OLD.client_id IS DISTINCT FROM NEW.client_id)) '
        'EXECUTE FUNCTION public.assert_row_names_a_journal_entry_of_its_client(%L)',
        v_upd, p_column, p_table, p_column, p_column, p_column, p_column);
END $$;

COMMENT ON FUNCTION public.guard_journal_entry(regclass, text) IS
    'POST-A-272. Installs the entry-belongs-to-the-row''s-client check on one uuid column that names a journal entry. DDL: not for a signed-in role. Migration 573.';

REVOKE ALL ON FUNCTION public.guard_journal_entry(regclass, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.guard_journal_entry(regclass, text) FROM anon;
REVOKE ALL ON FUNCTION public.guard_journal_entry(regclass, text) FROM authenticated;

-- 4. Report what already breaks the rule (and change none of it), then install.
DO $$
DECLARE
    v_challans int;
    v_remittances int;
BEGIN
    SELECT count(*) INTO v_challans FROM public.tds_challans t JOIN public.journal_entries e ON e.id = t.journal_entry_id
     WHERE e.firm_id IS DISTINCT FROM t.firm_id OR e.client_id IS DISTINCT FROM t.client_id;
    SELECT count(*) INTO v_remittances FROM public.statutory_remittances t JOIN public.journal_entries e ON e.id = t.journal_entry_id
     WHERE e.firm_id IS DISTINCT FROM t.firm_id OR e.client_id IS DISTINCT FROM t.client_id;
    RAISE WARNING 'migration 573: % TDS challan(s) and % statutory remittance(s) already tie a ledger entry of another client or firm (left as they are)',
        v_challans, v_remittances;
END $$;

SELECT public.guard_journal_entry('public.tds_challans', 'journal_entry_id');
SELECT public.guard_journal_entry('public.statutory_remittances', 'journal_entry_id');

COMMIT;
