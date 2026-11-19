-- Migration 771 (POST-A-485, 497): a sign-up link is held by the server.
--
-- A sign-up link used to be the sign-in library's own emailed one-time link: the first opener won and a second opener (a mail
-- scanner that opens links before the person does, a double click, the link opened on a phone after the laptop) was refused, and
-- the meaning of the sign-up ("a NEW practice, not the existing one this address belongs to") lived in a note in the browser
-- that sent the sign-up form, so the link opened in another browser entered the practice silently (POST-A-497).
--
-- Now the server keeps the link, the way a staff invitation is kept (`users.invite_token`, migration 153 and POST-A-445):
--   * one row per address holds the HASH of the link's secret (never the secret), the firm name and the person's name typed on the
--     sign-up form, and the instant the link stops working (24 hours after it was mailed);
--   * the link in the mail points at OUR page, which turns the secret into a sign-in only when the person presses a button, so a
--     scanner that fetches the page spends nothing. A press uses nothing up either: the link keeps working, on the laptop and then on
--     the phone, until it expires, until a newer link for the address replaces it, or until the practice is created, which deletes the row;
--   * the firm name and the person's name travel with the link, so the page the link opens does not depend on a note in the
--     browser the form was filled in.
-- Requesting a link again for the same address REPLACES the row (the earlier link stops working), which is also how an address that
-- asks over and over is counted: `send_count` within `window_started_at`. The replacing is a compare-and-set in the API, because
-- reading the row, judging the cooldown and writing are three steps and two requests that overlap would both pass the judging: the
-- first request for an address INSERTs (the unique index on the address refuses the second of two), and a later one UPDATEs the row
-- only while it still holds the link that request read (`WHERE email = ... AND token_hash = <the hash it read>`).
--
-- Written and read by the API only: the signed-in database roles hold nothing on the table. A person who has not signed up yet has
-- no practice, so the table carries no firm. Rows are kept only as long as the link is of use: creating the practice deletes the row,
-- and the API deletes rows that have expired whenever a link is requested and at the close of each daily sweep (an engineering rule,
-- no statutory figure).
--
-- Additive and idempotent; the rollback drops the table.

BEGIN;

SELECT set_config('lock_timeout', '15s', true);

CREATE TABLE IF NOT EXISTS public.signup_links (
  id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  -- The address the link was sent to, lowercased and trimmed by the API; the one row per address is what "send it again" replaces.
  email             TEXT        NOT NULL,
  -- What was typed on the sign-up form, kept so the page the link opens can use it in any browser.
  firm_name         TEXT        NOT NULL,
  full_name         TEXT        NOT NULL,
  -- `sha256:<hex>` of the secret in the mailed link (domain/firm/invite_token.stored_form). The secret exists only in the mail.
  token_hash        TEXT        NOT NULL,
  expires_at        TIMESTAMPTZ NOT NULL,
  -- When the mail for the current link was handed to the mail service: the cooldown between two requests is measured from it.
  sent_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- How many links this address has asked for since `window_started_at` (the hourly cap is the API's rule, kept here so it survives a restart).
  send_count        INTEGER     NOT NULL DEFAULT 1,
  window_started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT signup_links_email_is_trimmed_lowercase CHECK (email <> '' AND email = lower(btrim(email))),
  CONSTRAINT signup_links_names_are_not_blank CHECK (btrim(firm_name) <> '' AND btrim(full_name) <> ''),
  CONSTRAINT signup_links_token_hash_is_a_hash CHECK (token_hash LIKE 'sha256:%'),
  CONSTRAINT signup_links_send_count_is_positive CHECK (send_count >= 1)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_signup_links_one_per_address ON public.signup_links (email);
CREATE UNIQUE INDEX IF NOT EXISTS uq_signup_links_token_hash ON public.signup_links (token_hash);
CREATE INDEX IF NOT EXISTS idx_signup_links_expiry ON public.signup_links (expires_at);

COMMENT ON TABLE public.signup_links IS
  'POST-A-485 and 497, migration 771. A sign-up link kept by the server: the hash of its secret, the address, the firm name and the person''s '
  'name typed on the sign-up form, and when it stops working. One row per address, replaced when another link is asked for. The press of the '
  'button on the page the link opens uses nothing up: the row is deleted when the practice is created or once it has expired. Written and '
  'read by the API only (services/signup_link_service.py); the signed-in database roles hold nothing on it.';
COMMENT ON COLUMN public.signup_links.token_hash IS
  'sha256:<hex> of the secret in the mailed link. The secret itself is never stored.';

ALTER TABLE public.signup_links ENABLE ROW LEVEL SECURITY;

-- No policy: nobody but the privileged API client reads or writes it, and a table with row security on and no policy answers no rows.
REVOKE ALL ON public.signup_links FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.signup_links TO service_role;

-- ── the closing check ─────────────────────────────────────────────────────────────────────────────────────────────────────────
DO $$
DECLARE
    r text;
    verb text;
BEGIN
    FOREACH r IN ARRAY ARRAY['authenticated', 'anon'] LOOP
        FOREACH verb IN ARRAY ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER'] LOOP
            IF has_table_privilege(r, 'public.signup_links', verb) THEN
                RAISE EXCEPTION 'migration 771: % still holds % on public.signup_links', r, verb;
            END IF;
        END LOOP;
    END LOOP;
    IF NOT has_table_privilege('service_role', 'public.signup_links', 'INSERT') THEN
        RAISE EXCEPTION 'migration 771: service_role cannot write public.signup_links';
    END IF;
    IF NOT (SELECT relrowsecurity FROM pg_class WHERE oid = 'public.signup_links'::regclass) THEN
        RAISE EXCEPTION 'migration 771: row security is not on for public.signup_links';
    END IF;
END $$;

COMMIT;
