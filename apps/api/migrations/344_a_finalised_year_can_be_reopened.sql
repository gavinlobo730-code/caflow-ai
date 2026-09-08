-- ============================================================================
-- 344 — a finalised year-end can be reopened, and the reopening is recorded
--
-- WHAT WAS WRONG (ACC-05)
--     Finalising a year-end engagement writes a client_year_locks row
--     (migration 289), and the posting kernel then refuses every entry for
--     that client and year with, in its own words:
--
--         "FY 2025-26 is closed for this client — its year-end has been
--          finalised. Reopen the year before posting to it."
--
--     There was no way to reopen it. year_lock_service.set_client_lock has
--     taken lock=False since 289 and the only caller in the repository passed
--     lock=True; routers/year_end.py mapped "locked" to an empty list of
--     transitions; no screen referenced client_year_locks at all. The kernel
--     was naming an action the product did not have.
--
--     Every Indian practice reopens a closed year at least once a season — a
--     revised bank interest certificate in October, a §143(1) intimation, an
--     audit adjustment found while filing the ITR. The remedies left were a
--     DELETE straight on client_year_locks, or posting the correction into the
--     wrong year.
--
-- WHAT THIS ADDS
--     The three columns the reopen writes on the engagement, and the event
--     type the review history needs to hold it.
--
--     It does NOT clear final_approved_by / final_approved_at. Those record
--     that the approval happened; erasing them would make the history claim it
--     never did. A reopen is an event ON TOP of that history, which is the
--     same append-only posture the general ledger takes.
--
--     reopen_reason is NOT NULL-able by convention rather than by constraint —
--     the API refuses an empty one (year_end.REOPEN_REASON_REQUIRED) and a
--     historical row has none to give. Making the column NOT NULL would refuse
--     the migration on any row that predates it.
-- ============================================================================

ALTER TABLE public.year_end_engagements
  ADD COLUMN IF NOT EXISTS reopened_at   TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS reopened_by   UUID REFERENCES public.users(id),
  ADD COLUMN IF NOT EXISTS reopen_reason TEXT;

COMMENT ON COLUMN public.year_end_engagements.reopened_at IS
  'When a Partner last reopened this finalised engagement (ACC-05). NULL means it never was.';
COMMENT ON COLUMN public.year_end_engagements.reopened_by IS
  'public.users.id of the Partner who reopened it. The INTERNAL user id, not the Supabase auth id.';
COMMENT ON COLUMN public.year_end_engagements.reopen_reason IS
  'Why a closed year was opened. Required by the API; the audit answer at the next review.';

-- The review history's CHECK listed exactly the four event types the router
-- emitted. _record_review_event swallows its exception, so a fifth type would
-- have been silently dropped rather than loudly rejected — the exact failure
-- mode that docstring already records happening once, when the whole insert
-- targeted a table that did not exist.
ALTER TABLE public.year_end_review_events
  DROP CONSTRAINT IF EXISTS year_end_review_events_event_type_check;

ALTER TABLE public.year_end_review_events
  ADD CONSTRAINT year_end_review_events_event_type_check
  CHECK (event_type = ANY (ARRAY[
    'submitted_for_review'::text,
    'approved'::text,
    'revision_requested'::text,
    'final_approved_and_locked'::text,
    'reopened'::text
  ]));
