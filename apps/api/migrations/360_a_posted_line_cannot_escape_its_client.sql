-- Migration 360: a journal line's account belongs to the entry's own client.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG (ACC-21)
-- ═══════════════════════════════════════════════════════════════════════════
-- `post_journal_atomic` validates three things about the ENTRY — the firm is
-- the caller's, the client is assigned to them, and the firm's internal client
-- is Partner-only (migration 274, restating journal_entries' own RLS because
-- SECURITY DEFINER bypasses it). Then it inserts the lines:
--
--     (l->>'account_id')::uuid
--
-- with no validation at all. `journal_lines.account_id` carries one global
-- foreign key to `chart_of_accounts(id)` (migration 003) and nothing else, so
-- ANY account id in the database satisfies it — including another firm's.
--
-- `edit_posted_journal` has the same omission (migration 338), and
-- `manual_journal_service.create` passes the ids straight through. So a caller
-- who could name an account id could post their own client's balanced entry
-- against another client's ledger, or another FIRM's: the entry is scoped, the
-- money is not.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHY A TRIGGER AND NOT A CHECK IN EACH FUNCTION
-- ═══════════════════════════════════════════════════════════════════════════
-- The finding's own fix says "one EXISTS check per statement" in each of the
-- two functions. That closes the two paths that exist today and leaves the
-- rule living in two places — and the whole reason ACC-21 exists is that the
-- rule lived in ZERO. A third writer (the ORM path, a future RPC, a repair
-- script) would silently not have it.
--
-- The trigger is the gate, and it is STATEMENT-level with a transition table
-- rather than per row. journal_lines is the highest-volume table in this
-- database — a Tally migration inserts tens of thousands of lines in one
-- statement — so a FOR EACH ROW trigger would do one lookup per line where
-- this does one set-based anti-join per statement, whatever the row count.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT IS ALLOWED, AND WHY THE NULL BRANCH IS NOT A HOLE
-- ═══════════════════════════════════════════════════════════════════════════
-- An account satisfies the rule when it belongs to the entry's firm AND either
-- to the entry's client or to no client at all. `chart_of_accounts.client_id`
-- is nullable and a NULL there means a FIRM-level account — the firm's own
-- books rather than a client's — which is a real thing this schema models and
-- which any of that firm's entries may legitimately use. The firm check is
-- what does the isolation work; the client check narrows within it.
--
-- Existing rows are not touched. The trigger fires on writes, so a line posted
-- before today stays exactly as it is — and if any such row violates the rule
-- it is a finding to investigate, not a migration to fail on.
--
-- MEASURED AGAINST PRODUCTION BEFORE MERGING, because a trigger that refuses
-- what the app legitimately writes is an outage the moment this lands:
--
--     33,080 journal_lines,  0 that this rule would refuse
--        133 chart_of_accounts,  2 carrying a client_id at all
--
-- Both of those two are one client's own bank accounts ("HDFC Bank — 7890",
-- "Cosmos Bank — 7899"), used by 59 lines belonging to that same client and no
-- other. So the client branch changes nothing today; the FIRM branch is what
-- closes the hole, and the client branch is there because migration 057
-- deprecated `chart_of_accounts.client_id` without removing it and the column
-- is still being written — bank accounts, above — so the rule has to hold for
-- the rows that use it rather than assume they do not exist.

BEGIN;

CREATE OR REPLACE FUNCTION public.assert_journal_lines_belong_to_the_client()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public', 'pg_catalog'
AS $$
DECLARE
    v_bad text;
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
    RETURN NULL;
END $$;

COMMENT ON FUNCTION public.assert_journal_lines_belong_to_the_client() IS
    'ACC-21. post_journal_atomic and edit_posted_journal scope the ENTRY and '
    'not its lines, and journal_lines.account_id carries only a global FK to '
    'chart_of_accounts — so any account id in the database satisfied it. '
    'Statement-level with a transition table because journal_lines is the '
    'highest-volume table here. Migration 360.';

DROP TRIGGER IF EXISTS journal_lines_belong_to_the_client_ins ON public.journal_lines;
CREATE TRIGGER journal_lines_belong_to_the_client_ins
    AFTER INSERT ON public.journal_lines
    REFERENCING NEW TABLE AS new_lines
    FOR EACH STATEMENT
    EXECUTE FUNCTION public.assert_journal_lines_belong_to_the_client();

-- UPDATE too, and it covers a DIFFERENT case from what it first looks like.
-- On a POSTED entry, migration 251's prevent_posted_journal_line_modification
-- is BEFORE UPDATE and refuses any change before this trigger is reached. What
-- this arm actually guards is a DRAFT entry's lines, which are freely
-- updatable and become permanent the moment the entry is posted: insert clean
-- legs, repoint one, post. Without it the INSERT arm alone would be a gate with
-- a door beside it.
--
-- NOT `AFTER UPDATE OF account_id`, which is what this said first: Postgres
-- refuses a transition table on a trigger with a column list ("transition
-- tables cannot be specified for triggers with column lists"), and the
-- transition table is the whole reason this is affordable. Firing on every
-- update costs nothing extra — it is one set-based anti-join whatever the
-- statement touched.
DROP TRIGGER IF EXISTS journal_lines_belong_to_the_client_upd ON public.journal_lines;
CREATE TRIGGER journal_lines_belong_to_the_client_upd
    AFTER UPDATE ON public.journal_lines
    REFERENCING NEW TABLE AS new_lines
    FOR EACH STATEMENT
    EXECUTE FUNCTION public.assert_journal_lines_belong_to_the_client();

COMMIT;
