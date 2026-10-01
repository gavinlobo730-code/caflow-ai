-- ============================================================================
-- 465 — every model call leaves a usage row, and the row holds no text (ai-04)
--
-- WHY
--     Eight places called an AI model and none of them kept a record of the call.
--     What a firm's AI use costs, which model answered, how often the primary
--     failed and the fallback was tried, how long a call took and how many tokens
--     a reasoning model spent thinking were all unknowable after the fact: the
--     only trace was whatever a log line happened to say, on a Render instance
--     that sleeps. The gateway (domain/ai/gateway) now writes ONE ROW PER
--     ATTEMPT — a call that is retried or falls back leaves one row for each
--     model it tried, joined by `call_id` — and this is where they go.
--
-- WHAT IS DELIBERATELY NOT IN IT
--     * NO TEXT. There is no prompt column, no reply column, no error-message
--       column and no field a GSTIN, a PAN or a client's name could be written
--       into. `provider_code` is the provider's own short error code
--       ("model_not_found"), never the message. What reaches a provider is
--       governed by domain/ai/redaction and the guard beside it; this table is
--       about the call, and a row that could hold what was said would be a
--       second copy of the thing that guard exists to keep short.
--     * NO CLIENT. The row is attributable to a FIRM and, where known, the
--       person who asked, and not to a client: usage is a cost of the practice,
--       the only reader (a Partner) reads it for the firm, and a client column
--       would put the table under the assignment-scope rule (migration 370) for
--       a reader that needs nothing of the kind. If a per-client breakdown is
--       ever wanted it is a column and a policy then, decided with that screen.
--
-- WHAT IT IS NOT
--     The per-firm monthly token or page BUDGET and the Partner usage screen are
--     their own piece of work. This is the table that work reads; nothing here
--     enforces a limit, and `middleware/rate_limit` is untouched and still the
--     only brake on a firm.
--
-- OUTCOME AND PROVIDER ARE FREE TEXT, with the vocabulary in Python
--     (domain/ai/gateway.OUTCOMES): SQL cannot read a Python set, a hand-copied
--     CHECK here would be a second authority, and a row written under an older
--     vocabulary must still be readable. The numeric columns do carry CHECKs.
--
-- WRITTEN AS THE SERVICE ROLE, READ BY A PARTNER
--     The API inserts as the service role (a usage row is the system's, not the
--     user's, and a browser session has no business inserting one). A signed-in
--     user can SELECT only their own firm's rows, and only if they are a Partner.
--
-- Additive and idempotent; no data is rewritten and no policy is removed.
-- ============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS public.ai_usage_events (
    id                 uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id            uuid        NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
    user_id            uuid        NULL REFERENCES public.users(id) ON DELETE SET NULL,
    feature            text        NOT NULL,
    provider           text        NOT NULL,
    model              text        NOT NULL,
    call_id            text        NOT NULL,
    attempt            smallint    NOT NULL CHECK (attempt >= 1),
    outcome            text        NOT NULL,
    fallback_used      boolean     NOT NULL DEFAULT false,
    http_status        integer     NULL,
    provider_code      text        NULL,
    latency_ms         integer     NOT NULL CHECK (latency_ms >= 0),
    prompt_tokens      integer     NULL CHECK (prompt_tokens >= 0),
    completion_tokens  integer     NULL CHECK (completion_tokens >= 0),
    reasoning_tokens   integer     NULL CHECK (reasoning_tokens >= 0),
    total_tokens       integer     NULL CHECK (total_tokens >= 0),
    input_units        integer     NULL CHECK (input_units >= 0),
    created_at         timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.ai_usage_events IS
    'One row per ATTEMPT at a model call: firm, feature, model, token counts, '
    'latency and outcome. Holds NO prompt, reply, identifier or client name — '
    'there is no column for one. Written by domain/ai/gateway as the service '
    'role; read by a Partner for their own firm. Migration 465.';
COMMENT ON COLUMN public.ai_usage_events.call_id IS
    'Shared by every attempt of one gateway call (a retry or a fallback is a '
    'further row with the same call_id and a higher attempt).';
COMMENT ON COLUMN public.ai_usage_events.outcome IS
    'domain/ai/gateway.OUTCOMES: ok, truncated, empty_reply, unreadable_reply, '
    'timeout, network, rate_limited, provider_error, auth, model_gone, too_long, '
    'refused, param_rejected. Free text on purpose; the vocabulary is Python.';
COMMENT ON COLUMN public.ai_usage_events.provider_code IS
    'The provider''s own short error code, never its message.';
COMMENT ON COLUMN public.ai_usage_events.reasoning_tokens IS
    'Tokens a reasoning model spent before answering, where the provider says. '
    'They are drawn from the same allowance as the answer, which is why this is '
    'recorded: it is the evidence the response budgets are tuned from.';
COMMENT ON COLUMN public.ai_usage_events.input_units IS
    'Page images sent, for the vision path — the unit that costs there.';

-- What the monthly budget and the usage screen will read: a firm, over a period.
CREATE INDEX IF NOT EXISTS idx_ai_usage_events_firm_time
    ON public.ai_usage_events (firm_id, created_at DESC);

ALTER TABLE public.ai_usage_events ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  EXECUTE 'DROP POLICY IF EXISTS firm_ai_usage_events ON public.ai_usage_events';
  EXECUTE 'CREATE POLICY firm_ai_usage_events ON public.ai_usage_events '
          'FOR SELECT TO authenticated '
          'USING (firm_id = public.get_my_firm_id())';

  -- A firm's AI spend is the Partner's to read. RESTRICTIVE, so it narrows the
  -- permissive policy above rather than widening it.
  EXECUTE 'DROP POLICY IF EXISTS ai_usage_events_partner_only ON public.ai_usage_events';
  EXECUTE 'CREATE POLICY ai_usage_events_partner_only '
          'ON public.ai_usage_events AS RESTRICTIVE '
          'FOR SELECT USING (public.get_my_role() = ''Partner'')';
END $$;

-- SELECT only: the API writes this table as the service role, and a browser
-- session has no business inserting a record that a call happened.
GRANT SELECT ON public.ai_usage_events TO authenticated;
GRANT ALL ON public.ai_usage_events TO service_role;

COMMIT;
