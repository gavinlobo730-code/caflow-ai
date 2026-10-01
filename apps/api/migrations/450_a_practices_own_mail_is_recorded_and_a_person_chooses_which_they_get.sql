-- ============================================================================
-- 450 — a practice's own mail is RECORDED, and a person says which of it they get
--      (practice_management-02 and -03)
--
-- WHY
--     Four email functions in services/email_service.py were written and never
--     called, a client's portal message and a new document request recorded a
--     row and told nobody, and the escalation sweeps created in-app
--     notifications only — so a preparer away from the screen never heard that
--     a GSTR-3B was due in three days, and a client's reply sat unseen until
--     somebody opened that client's portal tab. Wiring the mails is only half
--     of the job, because mail nobody can switch off and nobody can audit is
--     the thing a practice learns to filter away: three things need a place to
--     live.
--
-- 1. user_notification_preferences — EMAIL ON OR OFF, PER EVENT TYPE, PER PERSON
--     `granted` in migration 403 is NOT NULL and the ROW is what is optional;
--     this is the same shape for the same reason. No row means the event's own
--     default decides (domain/practice_notices.DEFAULT_EMAIL), a row says what
--     the person chose, and there is no backfill, so nobody's mail changed on
--     the day this landed. The event type is free TEXT with no CHECK: the
--     vocabulary is a Python dict (domain/practice_notices.EVENT_TYPES), SQL
--     cannot read one, and a hand-copied list here would be a second authority.
--     An unrecognised type is inert in the resolver, so a row written under an
--     older vocabulary cannot switch on a mail somebody adds next year.
--
-- 2. practice_email_log — EVERY SEND, AND THE KEY THAT MAKES A RE-RUN SEND NONE
--     The escalation job is "idempotent per day" only by a scheduler flag, and
--     two doors (POST /api/tasks/trigger-escalations, POST /api/compliance/
--     run-escalations) bypass it, so a sweep run twice sent two in-app
--     notifications and, once mail is wired, would have sent two mails. A
--     partial UNIQUE index on (firm_id, dedupe_key) WHERE status = 'sent'
--     makes "one mail per recipient per item per day" a property of the
--     database rather than of whoever remembered to check. `dedupe_key` is
--     NULL for an event that is not a sweep (an assignment is an event, and
--     assigning the same task twice in a day is two events), and a FAILED
--     attempt is recorded without the key so it never blocks a retry.
--     `recipient_kind` keeps a STAFF member apart from a CLIENT CONTACT: the
--     second has no preference screen and is never mailed about anything but
--     their own request or their own accountant's message.
--
-- 3. notifications.type — ONE VALUE ADDED, DERIVED FROM THE LAST DEFINER
--     `portal_message` is the in-app half of "a client wrote to you". The
--     CHECK was last defined by migration 157 (122 before it), found by
--     number — `grep -ln notifications_type_check migrations/*.sql | sort |
--     tail -1` — and this list is a SUPERSET of 157's, never a re-derivation
--     of 122's: the next widening must extend the CURRENT constraint.
--     DROP and ADD share one transaction, so a failure between them cannot
--     leave the column unconstrained. Every existing row already satisfies
--     157's list, which is a subset of this one, so the ADD cannot fail on
--     data.
--
-- 4. portal_messages — NOTHING NEW, AND THE INDEX IS THE POINT
--     `is_read` and `read_at` have existed since migration 094 and nothing read
--     or wrote either. A client's message is READ when the firm has opened the
--     thread; the firm-wide unread count is the rows with sender_type =
--     'client' AND is_read = false. The partial index is what keeps that count
--     proportional to the answer.
--
-- 5. document_requests.due_date — A FIELD THE API DECLARED AND THE TABLE LACKED
--     POST /api/portal/document-requests has named `due_date` in its INSERT
--     since it was written and the table has never had the column, so the
--     door has failed with 42703 on every call (the GET was repaired for the
--     same reason; the POST was not). The screen worked around it by writing
--     the table straight over PostgREST, which is why nobody noticed — and why
--     rbac() never ran on it and no mail could ever be sent from the server.
--     "Needed by" is a fact a client acts on, so the column is added rather
--     than the field dropped. Nullable, no default, no backfill.
--
-- Additive and idempotent; no data is rewritten and no policy is removed.
-- ============================================================================

BEGIN;

-- ── 1. per-person email preferences ─────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.user_notification_preferences (
    firm_id        uuid        NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
    user_id        uuid        NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    event_type     text        NOT NULL,
    email_enabled  boolean     NOT NULL,
    updated_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT user_notification_preferences_pkey PRIMARY KEY (user_id, event_type)
);

COMMENT ON TABLE public.user_notification_preferences IS
    'One row per (person, event type) the person has CHOSEN about email. No '
    'row means the event''s own default decides; the vocabulary and the '
    'defaults are domain/practice_notices, not a CHECK. Migration 450.';
COMMENT ON COLUMN public.user_notification_preferences.email_enabled IS
    'NOT NULL: the third state is the absence of the row, as in '
    'user_permissions.granted (migration 403).';

CREATE INDEX IF NOT EXISTS idx_user_notification_preferences_firm
    ON public.user_notification_preferences (firm_id);

ALTER TABLE public.user_notification_preferences ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  EXECUTE 'DROP POLICY IF EXISTS firm_user_notification_preferences ON public.user_notification_preferences';
  EXECUTE 'CREATE POLICY firm_user_notification_preferences ON public.user_notification_preferences '
          'FOR ALL TO authenticated '
          'USING (firm_id = public.get_my_firm_id()) '
          'WITH CHECK (firm_id = public.get_my_firm_id())';

  -- A preference is personal: even a Partner does not edit a colleague's mail.
  EXECUTE 'DROP POLICY IF EXISTS user_notification_preferences_own_row ON public.user_notification_preferences';
  EXECUTE 'CREATE POLICY user_notification_preferences_own_row '
          'ON public.user_notification_preferences AS RESTRICTIVE '
          'FOR ALL USING (user_id = public.get_my_user_id()) '
          'WITH CHECK (user_id = public.get_my_user_id())';
END $$;

GRANT SELECT, INSERT, UPDATE, DELETE ON public.user_notification_preferences TO authenticated;
GRANT ALL ON public.user_notification_preferences TO service_role;

-- ── 2. the record of every send ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.practice_email_log (
    id                 uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id            uuid        NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
    event_type         text        NOT NULL,
    recipient_kind     text        NOT NULL DEFAULT 'staff'
                           CHECK (recipient_kind IN ('staff', 'client_contact')),
    recipient_user_id  uuid        NULL REFERENCES public.users(id) ON DELETE SET NULL,
    recipient_email    text        NOT NULL,
    ref_type           text        NULL,
    ref_id             text        NULL,
    tier               text        NULL,
    -- The IST day the mail is FOR, never the UTC date of the insert: between
    -- 00:00 and 05:30 IST they differ, and a sweep's "today" is the Indian one.
    sent_for_date      date        NOT NULL,
    dedupe_key         text        NULL,
    status             text        NOT NULL CHECK (status IN ('sent', 'failed')),
    detail             text        NULL,
    created_at         timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.practice_email_log IS
    'Every mail the practice''s own paths ATTEMPTED — staff notices and the two '
    'client-contact notices. A skipped mail (preference off, no address) is not '
    'a send and is not recorded. No client_id on purpose: ref_type/ref_id name '
    'the thing the mail was about, and a client-scoped table would fall under '
    'the assignment-scope rule for no reader that needs it. Migration 450.';
COMMENT ON COLUMN public.practice_email_log.dedupe_key IS
    'event|recipient|ref|tier|day for a SWEEP mail, NULL for an event mail. '
    'Unique among SENT rows, so a sweep run twice sends once.';

CREATE UNIQUE INDEX IF NOT EXISTS uq_practice_email_log_sent
    ON public.practice_email_log (firm_id, dedupe_key)
    WHERE status = 'sent' AND dedupe_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_practice_email_log_firm_day
    ON public.practice_email_log (firm_id, sent_for_date DESC);
CREATE INDEX IF NOT EXISTS idx_practice_email_log_recipient
    ON public.practice_email_log (recipient_user_id, created_at DESC);

ALTER TABLE public.practice_email_log ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  EXECUTE 'DROP POLICY IF EXISTS firm_practice_email_log ON public.practice_email_log';
  EXECUTE 'CREATE POLICY firm_practice_email_log ON public.practice_email_log '
          'FOR SELECT TO authenticated '
          'USING (firm_id = public.get_my_firm_id())';

  -- A staff member reads the mails sent to THEM; a Partner reads the firm's.
  EXECUTE 'DROP POLICY IF EXISTS practice_email_log_recipient_scope ON public.practice_email_log';
  EXECUTE 'CREATE POLICY practice_email_log_recipient_scope '
          'ON public.practice_email_log AS RESTRICTIVE '
          'FOR SELECT USING (public.get_my_role() = ''Partner'' '
          'OR recipient_user_id = public.get_my_user_id())';
END $$;

-- SELECT only: the API writes this table as the service role, and a browser
-- session has no business inserting a record that a send happened.
GRANT SELECT ON public.practice_email_log TO authenticated;
GRANT ALL ON public.practice_email_log TO service_role;

-- ── 3. notifications.type gains 'portal_message' ────────────────────────────

ALTER TABLE public.notifications
    DROP CONSTRAINT IF EXISTS notifications_type_check;

ALTER TABLE public.notifications
    ADD CONSTRAINT notifications_type_check CHECK (type IN (
        'task_assigned', 'risk_detected', 'document_processed',
        'compliance_due', 'ai_recommendation', 'status_changed',
        'task_reassigned', 'due_soon', 'overdue', 'task_overdue',
        'recurring_generated',
        'workflow',
        -- migration 450: the in-app half of "a client wrote to you"
        'portal_message'
    ));

COMMENT ON CONSTRAINT notifications_type_check ON public.notifications IS
    'Superset of migration 157''s list (which was a superset of 122''s). The '
    'next widening must extend THIS list, found by number, not re-derive it. '
    'Migration 450 added portal_message.';

-- ── 4. the firm-wide unread count stays proportional to the answer ──────────

CREATE INDEX IF NOT EXISTS idx_portal_messages_unread_from_client
    ON public.portal_messages (firm_id, client_id)
    WHERE sender_type = 'client' AND is_read = false;

-- ── 5. a document request can say when it is needed by ──────────────────────

ALTER TABLE public.document_requests
    ADD COLUMN IF NOT EXISTS due_date date;

COMMENT ON COLUMN public.document_requests.due_date IS
    'Needed-by date the CA stated, or NULL. The API declared this field and '
    'the table lacked it, so POST /api/portal/document-requests failed on '
    'every call until migration 450.';

COMMIT;
