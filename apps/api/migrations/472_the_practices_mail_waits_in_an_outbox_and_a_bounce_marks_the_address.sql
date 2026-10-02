-- ============================================================================
-- 472 — the practice's own mail waits in an OUTBOX, is retried, and a bounce
--       marks the address (ops-21)
--
-- WHY
--     `email_service._send` posted to Resend synchronously from the request, with a
--     10-second timeout, and answered True or False. Nothing retried. A slow
--     provider held one of the worker's ~40 threads for ten seconds per mail, and a
--     failed mail was lost unless somebody noticed: an assignment notice or a
--     client's portal message that hit one provider hiccup simply never arrived,
--     and the only trace was a row in practice_email_log saying `failed`. Nothing
--     listened to the provider afterwards either, so an address that hard-bounced
--     was mailed again on the next sweep, every day, from the one sending domain
--     every firm shares.
--
-- WHAT THIS ADDS
--     `email_outbox`      a message waiting to be delivered, with how many times it has
--                         been tried, when it is next due, and how it ended. The API's
--                         scheduler drains it every minute (services/email_outbox_service)
--                         with backoff, and a message that fails for good is marked
--                         `failed` and its record in practice_email_log is flipped to
--                         `failed` so the next sweep may try again.
--     `email_suppressions` addresses that must not be mailed again: a PERMANENT bounce
--                         or a spam complaint, reported by the provider's signed webhook.
--     `claim_email_outbox` takes due rows for ONE drainer with FOR UPDATE SKIP LOCKED,
--                         so two instances (or the minute tick and a drain started by a
--                         send) never hold the same message. A row whose drainer died is
--                         `sending` with an expired lease and is handed out again.
--
-- WHAT IT DOES NOT CARRY, and why that is the point
--     * NO client_id. Like practice_email_log (migration 450) the row names the firm and
--       the recipient and nothing about which client the mail concerned; a client-scoped
--       table would fall under the assignment-scope rule for a reader that needs nothing
--       of the kind. (There is no browser reader: see below.)
--     * NO copy of what was said once it is over. `subject` and `html` hold a client's
--       name and a task's title while the message waits; the moment it is sent, failed,
--       cancelled or suppressed the service blanks both. What stays is who, when, how
--       often, and how it ended.
--     * NO provider message text. `last_error_code` is the provider's short error NAME
--       ("validation_error") or an exception's class name, never its message, which can
--       quote the recipient's address.
--     * NO attachment. The outbox carries the practice's own notices, which have none.
--       The customer-facing invoice, statement and reminder mails (a person pressed Send
--       and is told whether it went) stay synchronous and do not use it.
--
-- BOTH TABLES ARE SERVICE-ROLE ONLY: RLS is on with NO policy and `anon` and
-- `authenticated` hold no privilege. The outbox holds mail bodies and addresses and a
-- signed-in session has no reason to read or forge one (a forged row would send mail
-- under the product's name). The suppression list is global, not per firm — one
-- sending domain, one reputation — and so it has no firm_id and no reader but the
-- service. The user-visible record of mail remains practice_email_log (firm- and
-- recipient-scoped) and the two delivery tables, whose `bounced` status the webhook now
-- sets and nothing ever did.
--
-- Additive and idempotent: CREATE ... IF NOT EXISTS, CREATE OR REPLACE for the function,
-- no data rewritten, no policy removed, no existing function touched.
-- ============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS public.email_outbox (
    id                  uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id             uuid        NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
    -- Whose mail it is. The vocabulary lives in Python (services/email_outbox_service);
    -- today only 'practice_notice'. Free text so a row written under an older vocabulary
    -- stays readable.
    origin              text        NOT NULL,
    event_type          text        NOT NULL,
    recipient_kind      text        NOT NULL DEFAULT 'staff'
                            CHECK (recipient_kind IN ('staff', 'client_contact')),
    recipient_user_id   uuid        NULL REFERENCES public.users(id) ON DELETE SET NULL,
    to_address          text        NOT NULL,
    subject             text        NOT NULL DEFAULT '',
    html                text        NOT NULL DEFAULT '',
    sender_name         text        NULL,
    reply_to            text        NULL,
    status              text        NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending', 'sending', 'sent', 'failed',
                                              'cancelled', 'suppressed')),
    attempts            integer     NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    max_attempts        integer     NOT NULL DEFAULT 6 CHECK (max_attempts BETWEEN 1 AND 20),
    next_attempt_at     timestamptz NOT NULL DEFAULT now(),
    lease_expires_at    timestamptz NULL,
    last_attempt_at     timestamptz NULL,
    sent_at             timestamptz NULL,
    provider_message_id text        NULL,
    last_status_code    integer     NULL,
    last_error_code     text        NULL,
    -- Why a message ended without being sent: a short code, not a sentence.
    final_reason        text        NULL,
    -- What the provider said about it AFTER it was accepted (the signed webhook).
    delivery_event      text        NULL CHECK (delivery_event IN ('bounced', 'complained')),
    delivery_event_at   timestamptz NULL,
    -- The practice_email_log rows this message stands for, so a message that fails for
    -- good can flip them to `failed` and let a later sweep try again.
    log_ids             uuid[]      NOT NULL DEFAULT '{}',
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.email_outbox IS
    'The practice''s own mail waiting to be delivered: attempts, next due time and how '
    'it ended. Drained by the scheduler with backoff; claimed with FOR UPDATE SKIP LOCKED. '
    'subject and html are blanked once the message is over. Service-role only. Migration 472.';
COMMENT ON COLUMN public.email_outbox.final_reason IS
    'switched_off, preference_off, inactive_recipient, suppressed, abandoned, or the '
    'provider''s error code for a message that failed after its last attempt.';
COMMENT ON COLUMN public.email_outbox.delivery_event IS
    'bounced (a PERMANENT bounce) or complained, set by the provider''s signed webhook '
    'on the message it names. A soft bounce is not recorded here.';
COMMENT ON COLUMN public.email_outbox.log_ids IS
    'practice_email_log ids this message stands for; flipped to failed if it never goes.';

-- What the drain scans: due and pending, or sending with an expired lease.
CREATE INDEX IF NOT EXISTS idx_email_outbox_due
    ON public.email_outbox (next_attempt_at) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_email_outbox_leases
    ON public.email_outbox (lease_expires_at) WHERE status = 'sending';
-- What the webhook looks a message up by.
CREATE INDEX IF NOT EXISTS idx_email_outbox_provider_message
    ON public.email_outbox (provider_message_id) WHERE provider_message_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_email_outbox_firm_created
    ON public.email_outbox (firm_id, created_at DESC);

ALTER TABLE public.email_outbox ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.email_outbox FROM anon, authenticated;
GRANT ALL ON public.email_outbox TO service_role;

CREATE TABLE IF NOT EXISTS public.email_suppressions (
    -- Lower-cased: an address is compared case-insensitively and stored once.
    address             text        PRIMARY KEY CHECK (address = lower(address)),
    reason              text        NOT NULL CHECK (reason IN ('hard_bounce', 'complaint')),
    provider_message_id text        NULL,
    first_event_at      timestamptz NOT NULL DEFAULT now(),
    last_event_at       timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.email_suppressions IS
    'Addresses the product must not mail: a permanent bounce or a spam complaint, from '
    'the provider''s signed webhook. GLOBAL (no firm_id): all firms send from one domain '
    'and share one reputation. Service-role only. Migration 472.';

ALTER TABLE public.email_suppressions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.email_suppressions FROM anon, authenticated;
GRANT ALL ON public.email_suppressions TO service_role;

-- ── hand out due rows to ONE drainer ────────────────────────────────────────
-- FOR UPDATE SKIP LOCKED is what makes two drainers get disjoint rows instead of
-- waiting on each other: a row another transaction is claiming is skipped, not
-- queued behind. `attempts` is raised here, at the claim, so a drainer that dies
-- mid-send has still used up an attempt and a message that kills its drainer
-- cannot be retried for ever; the service gives up on a row whose attempts have
-- passed max_attempts without sending it.
CREATE OR REPLACE FUNCTION public.claim_email_outbox(
    p_limit         integer DEFAULT 5,
    p_lease_seconds integer DEFAULT 300
) RETURNS SETOF public.email_outbox
LANGUAGE plpgsql
AS $fn$
BEGIN
    IF p_limit IS NULL OR p_limit < 1 OR p_limit > 200 THEN
        RAISE EXCEPTION 'claim_email_outbox: a batch is between 1 and 200 rows, got %', p_limit;
    END IF;
    IF p_lease_seconds IS NULL OR p_lease_seconds < 30 OR p_lease_seconds > 3600 THEN
        RAISE EXCEPTION 'claim_email_outbox: a lease is between 30 seconds and an hour, got %',
            p_lease_seconds;
    END IF;
    RETURN QUERY
    WITH due AS (
        SELECT o.id
          FROM public.email_outbox o
         WHERE (o.status = 'pending' AND o.next_attempt_at <= now())
            OR (o.status = 'sending' AND o.lease_expires_at <= now())
         ORDER BY o.next_attempt_at
         LIMIT p_limit
         FOR UPDATE SKIP LOCKED
    )
    UPDATE public.email_outbox e
       SET status           = 'sending',
           attempts         = e.attempts + 1,
           lease_expires_at = now() + make_interval(secs => p_lease_seconds),
           last_attempt_at  = now(),
           updated_at       = now()
      FROM due
     WHERE e.id = due.id
    RETURNING e.*;
END
$fn$;

REVOKE ALL ON FUNCTION public.claim_email_outbox(integer, integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.claim_email_outbox(integer, integer) TO service_role;

COMMIT;
