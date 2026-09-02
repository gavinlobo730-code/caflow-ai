-- 315: the review trail's actor is a user, so say so.
--
-- WHY
--   routers/year_end_reviews wrote current_user["auth_user_id"] — the Supabase
--   auth id — into year_end_engagements.submitted_by / approved_by /
--   revision_requested_by / final_approved_by. All four FK public.users(id),
--   the INTERNAL id, and users.id never equals auth_user_id (checked on
--   production: 0 of 2). Every submit / approve / request-revision /
--   final-approve therefore raised SQLSTATE 23503, unguarded. Nobody had hit
--   it yet — production holds zero engagements — but the first CA to submit
--   one for review would have.
--
--   The same router wrote the same auth id into year_end_review_events.actor_id
--   and then resolved BOTH sets of ids against users.auth_user_id on read. That
--   was self-consistent and wrong: the engagements write could never succeed,
--   so the read's first source was always empty, and the review trail resolved
--   names off a column no other user reference in the schema uses.
--
-- WHAT THIS DOES
--   The router now writes public.users.id everywhere and resolves by it. This
--   migration adds the foreign key actor_id was always meant to have, so the
--   two halves of the review trail cannot drift apart again — and so the bug
--   class that produced this (an auth id written where an internal id belongs)
--   is a loud 23503 on the review-events side too, instead of a silently
--   unresolvable name.
--
--   Safe to add: year_end_review_events holds zero rows on production, so
--   there is nothing that could fail the constraint. NOT VALID + VALIDATE is
--   used anyway, because the migration runner applies this on merge with no
--   human in between, and a pattern that is correct on an empty table and
--   correct on a full one is worth more than one that is only correct today.

BEGIN;

ALTER TABLE public.year_end_review_events
    DROP CONSTRAINT IF EXISTS year_end_review_events_actor_id_fkey;

ALTER TABLE public.year_end_review_events
    ADD CONSTRAINT year_end_review_events_actor_id_fkey
    FOREIGN KEY (actor_id) REFERENCES public.users(id)
    NOT VALID;

ALTER TABLE public.year_end_review_events
    VALIDATE CONSTRAINT year_end_review_events_actor_id_fkey;

COMMENT ON COLUMN public.year_end_review_events.actor_id IS
    'public.users.id — the INTERNAL user id, never the Supabase auth id. '
    'Migration 315 added the FK; the router resolves names by users.id.';

COMMIT;
