-- Rollback for 344. The CHECK goes back to its four values, which will fail if
-- any 'reopened' row has been written — deliberately: dropping the rows would
-- erase the record of a closed year being opened.
ALTER TABLE public.year_end_review_events
  DROP CONSTRAINT IF EXISTS year_end_review_events_event_type_check;
ALTER TABLE public.year_end_review_events
  ADD CONSTRAINT year_end_review_events_event_type_check
  CHECK (event_type = ANY (ARRAY[
    'submitted_for_review'::text,
    'approved'::text,
    'revision_requested'::text,
    'final_approved_and_locked'::text
  ]));

ALTER TABLE public.year_end_engagements
  DROP COLUMN IF EXISTS reopened_at,
  DROP COLUMN IF EXISTS reopened_by,
  DROP COLUMN IF EXISTS reopen_reason;
