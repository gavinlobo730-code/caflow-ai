-- Migration 361: one definition of "closed", and the two kinds of closed.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG (ACC-12)
-- ═══════════════════════════════════════════════════════════════════════════
-- "Is this period closed" had THREE answers and they were enforced in three
-- different places, so no path asked all three:
--
--   * the FIRM's locked financial year — period_validation_service, called from
--     67 router call sites;
--   * a filed RETURN covering the date — period_lock_service.assert_open,
--     called from exactly two files, sales_invoices.py and purchase_bills.py;
--   * this CLIENT's finalised year-end (migration 289) — the posting kernel,
--     and nowhere else.
--
-- The asymmetry the finding leads with: GSTR-3B for June is filed on 20 July.
-- On 25 July the CA tries to EDIT a June journal and is refused with a clear
-- sentence (migration 266 asks all of period_lock_reason). On the same day they
-- post a NEW June journal and it goes through silently.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHY THIS IS A SQL CHANGE AND NOT A SECOND CALL IN THE KERNEL
-- ═══════════════════════════════════════════════════════════════════════════
-- `period_lock_reason` (migration 267) already answered two of the three. The
-- kernel answered the third separately, because `client_year_locks` did not
-- exist when 267 was written. Folding that branch in means every caller of one
-- function gets the whole rule, and the kernel makes ONE round trip where it
-- made one before — `apps/api` runs in Singapore against a database in Mumbai,
-- and CLAUDE.md measures what a second one costs.
--
-- Migration 267 said exactly this would happen: "Any future change to what
-- 'closed' means belongs here and reaches every document at once, which is the
-- whole point of there being one of it."
--
-- ═══════════════════════════════════════════════════════════════════════════
-- THE PART THAT IS NOT OBVIOUS: A FILED RETURN IS NOT A CLOSURE
-- ═══════════════════════════════════════════════════════════════════════════
-- The finding's suggested fix is "move the filed-return check into
-- _create_journal beside the client year-lock check" — and then, in the same
-- sentence, "make it a warning-with-override for postings ... but keep it a
-- hard refusal for edits". That caveat is the whole design, and taking the
-- first half without the second would have frozen the practice:
--
--   GSTR-1 for June is filed on 11 July. GSTR-3B on the 20th. Bank
--   reconciliation for June happens AFTER those dates, every month, for every
--   client. A hard refusal on every posting dated in June would mean that from
--   11 July no June receipt, no June payment, no June bank entry, no June
--   depreciation and no June payroll accrual could be recorded at all.
--
-- So the three reasons are two different KINDS of thing, and this migration
-- separates them by kind rather than by caller:
--
--   A CLOSURE is a deliberate act by the CA — they locked the firm's year, or
--   they finalised this client's year-end. It says "these books are finished".
--   It stops EVERYTHING, and reopening it is a decision they can make.
--
--   A FILED RETURN is a fact about a document that left for the portal. It
--   freezes what that return REPORTED — supplies and input tax credit — and it
--   is not undoable. It stops the documents that feed the return (invoices,
--   bills, credit and debit notes: already enforced since SALES-15/PUR-08) and
--   the free-form path that can move any account including the tax ledgers (a
--   manual journal, and its edit, already refused by migration 266). It does
--   NOT stop a receipt: `public.filings` records only GSTR-1 and GSTR-3B,
--   returns of SUPPLIES, and a receipt moves Bank and Debtors. That decision is
--   argued in services/receipt_service.py and pinned by
--   test_documents_locked_by_filed_return.py; this migration is careful not to
--   overturn it from underneath.
--
-- Hence TWO entry points and ONE rule. `period_closure_reason` answers the
-- deliberate closures. `period_lock_reason` CALLS it and then adds the filed
-- return, so there is no second copy of anything and the precedence below is
-- stated once.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- THE ORDER OF THE THREE BRANCHES IS THE ORDER OF THE REMEDIES
-- ═══════════════════════════════════════════════════════════════════════════
-- Each reason names a DIFFERENT next action, so the most reopenable wins:
--
--   1. the firm's financial year is locked  → unlock the year, or post to an
--      open one. Widest scope, and the CA already knows they did it.
--   2. this CLIENT's year-end is finalised  → reopen that client's year
--      (migration 344's path). Narrower, and easy to forget when the firm's
--      own year is still open.
--   3. a return covering the date is filed  → reverse and amend in the next
--      return, which is the only remedy the CA cannot simply undo.
--
-- Putting the client year-end BEFORE the filed return is deliberate: a
-- finalised year is reopenable, a filed return is not, and telling a CA to
-- amend a return when all they need to do is reopen a year sends them to the
-- portal for nothing.

BEGIN;

-- ── The deliberate closures ─────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.period_closure_reason(
    p_firm   uuid,
    p_client uuid,
    p_date   date
) RETURNS TEXT LANGUAGE plpgsql STABLE
SET search_path = public, pg_catalog AS $$
DECLARE
    v_fy_start  int;
    v_fy_label  text;
    v_locked    text[];
BEGIN
    IF p_date IS NULL THEN
        RETURN NULL;
    END IF;

    v_fy_start := CASE WHEN EXTRACT(MONTH FROM p_date) >= 4
                       THEN EXTRACT(YEAR FROM p_date)::int
                       ELSE EXTRACT(YEAR FROM p_date)::int - 1 END;
    v_fy_label := v_fy_start::text || '-' || lpad(((v_fy_start + 1) % 100)::text, 2, '0');

    SELECT locked_financial_years INTO v_locked FROM public.firms WHERE id = p_firm;
    IF v_locked IS NOT NULL AND v_fy_label = ANY (v_locked) THEN
        RETURN 'Financial year ' || v_fy_label || ' is locked. Unlock it, or post a reversal in an open year.';
    END IF;

    -- THE BRANCH THIS MIGRATION ADDS. `client_year_locks` (migration 289) is
    -- written when a year-end engagement is finalised, and until now only the
    -- posting kernel read it — so it stopped the kernel and nothing else, while
    -- period_lock_reason stopped everything else and not the kernel. The
    -- sentence names the remedy migration 344 built: reopen the year.
    IF p_client IS NOT NULL AND EXISTS (
        SELECT 1 FROM public.client_year_locks
         WHERE firm_id = p_firm
           AND client_id = p_client
           AND financial_year = v_fy_label
    ) THEN
        RETURN 'FY ' || v_fy_label || ' is closed for this client — its year-end has been '
               || 'finalised. Reopen the year before posting to it.';
    END IF;

    RETURN NULL;
END;
$$;

COMMENT ON FUNCTION public.period_closure_reason(uuid, uuid, date) IS
    'The DELIBERATE closures only: the firm''s locked financial year, then this '
    'client''s finalised year-end (migration 289). Both say "these books are '
    'finished", both stop every posting, and both are reopenable by the CA who '
    'set them — which is why the posting kernel enforces these and not the '
    'filed-return branch. period_lock_reason calls this and adds that branch. '
    'Migration 361 (ACC-12).';

-- ── The whole rule: a closure, or a return that has already gone ────────────
CREATE OR REPLACE FUNCTION public.period_lock_reason(
    p_firm   uuid,
    p_client uuid,
    p_date   date
) RETURNS TEXT LANGUAGE plpgsql STABLE
SET search_path = public, pg_catalog AS $$
DECLARE
    v_reason  text;
    v_filing  record;
BEGIN
    IF p_date IS NULL THEN
        RETURN NULL;
    END IF;

    -- Branches 1 and 2, not repeated here. Two implementations of one rule
    -- drift; one of them calling the other cannot.
    v_reason := public.period_closure_reason(p_firm, p_client, p_date);
    IF v_reason IS NOT NULL THEN
        RETURN v_reason;
    END IF;

    -- A filed return freezes what it REPORTED. The document at the portal
    -- cannot be recalled, so the supplies and the credit behind it must stop
    -- moving — otherwise the return and the ledger disagree with nothing
    -- recording why.
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

COMMENT ON FUNCTION public.period_lock_reason(uuid, uuid, date) IS
    'Is this date still open? THREE reasons it may not be, most-reopenable '
    'first: the firm''s financial year is locked, this client''s year-end is '
    'finalised (migration 289 — added by 361), or a return covering the date '
    'has been filed. The first two come from period_closure_reason, which the '
    'posting kernel calls on its own because a filed return freezes the '
    'documents that fed it rather than the whole ledger — see 361''s header. '
    'Returns the sentence rather than a boolean because each calls for a '
    'different action from the CA. Migration 267 established the function; 361 '
    'split it in two without duplicating a line of it.';

GRANT EXECUTE ON FUNCTION public.period_closure_reason(uuid, uuid, date)
  TO authenticated, service_role;

COMMIT;
