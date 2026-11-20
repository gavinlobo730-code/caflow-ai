-- Migration 774: a person keeps their guided tips: whether they want them, and which they have read (ledger POST-A-531).
--
-- The owner, walking the live Test Firm on 20-11-2026: "I am the one who has been with you and I still do not know the software." A new CA is to
-- be shown round by pop-ups that explain a screen, with a switch in Settings to turn them off. Both facts are about a PERSON, not about the firm
-- ("I do not want tips", "I have read this one"), and both must follow the person to every device, so they are columns on `users`, where
-- migration 557 put the other person-level preference (`first_run_dismissed_at`). A browser's own storage would show every tip again on the next
-- device and could not be read by the Settings switch of another.
--
-- WHAT THIS ADDS
--   users.guided_tips_on    BOOLEAN, nullable, no default. NULL = the person has never chosen; the API then answers the product's default (on).
--                           A person who turns the switch either way has TRUE or FALSE from then on, so a later change of the default moves
--                           only those who never chose.
--   users.guided_tips_seen  TEXT[], NOT NULL, default '{}'. The ids of the tips this person has closed with "Got it". A tip's id is a short
--                           slug the screens own (the API checks its shape, not a list: the tips are written in the frontend).
--
-- Written by the API only (`/api/guided-tips`, with the server's privileged client, naming the person's own id and firm); read by the same
-- routes. Nothing else reads either column and neither carries any meaning for the firm's data. The signed-in role holds no UPDATE privilege
-- on these columns (the only column a signed-in session may write on its own `users` row is its name), so a hand-made request cannot set them.

ALTER TABLE public.users ADD COLUMN IF NOT EXISTS guided_tips_on BOOLEAN;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS guided_tips_seen TEXT[] NOT NULL DEFAULT '{}';

COMMENT ON COLUMN public.users.guided_tips_on IS
  'Whether this person wants guided tips (POST-A-531). NULL = never chosen (the API answers the default, on). Written by the API only; a person-level preference, not firm data.';
COMMENT ON COLUMN public.users.guided_tips_seen IS
  'Ids of the guided tips this person has closed (POST-A-531). Written by the API only; a person-level preference, not firm data.';

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'users'
                      AND column_name = 'guided_tips_on'
                      AND data_type = 'boolean' AND is_nullable = 'YES' AND column_default IS NULL) THEN
        RAISE EXCEPTION 'migration 774: users.guided_tips_on is not a nullable boolean with no default';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'users'
                      AND column_name = 'guided_tips_seen'
                      AND data_type = 'ARRAY' AND udt_name = '_text' AND is_nullable = 'NO') THEN
        RAISE EXCEPTION 'migration 774: users.guided_tips_seen is not a NOT NULL text[]';
    END IF;
END $$;
