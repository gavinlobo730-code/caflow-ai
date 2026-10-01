-- ============================================================================
-- 476 — A firm can cap its monthly AI use, and a Partner can read what it used.
-- (ai-17, the half migration 465 left for later)
--
-- WHAT WAS MISSING
--   Migration 465 made every model attempt leave a row in ai_usage_events and
--   said, in its own header, that "the per-firm monthly budget and the usage
--   screen are the next consumer of the table". Nothing summed it, so one busy or
--   misbehaving firm could still run up the provider bill and nobody — the firm
--   included — could see what the AI cost in tokens or pages.
--
-- WHAT THIS ADDS
--   * public.ai_firm_budgets — ONE row per firm, optional. A NULL limit is "no
--     limit set", which is the position of every firm today; it is NOT zero, and
--     zero is refused (it would mean "the AI is off" to one reader and "no limit"
--     to another). There is deliberately NO default limit: any figure written
--     here would be a guess about what a practice should spend. Written ONLY by
--     the API as the service role, after rbac(); read by a Partner of that firm.
--   * public.ai_usage_by_day(firm, from, to) and public.ai_usage_by_feature(firm, from,
--     to) — the month's attempts grouped by IST day and OUTCOME, and by provider, feature,
--     model and OUTCOME, so what crosses the wire is proportional to the answer and not to
--     the number of calls (the reporting rule), in two SMALL answers rather than one wide
--     one (PostgREST caps a response near a thousand rows and says nothing when it does,
--     so the service also refuses to present a response that reached the cap as complete).
--     They count and sum and nothing else: the OUTCOME VOCABULARY STAYS IN PYTHON,
--     domain/ai/gateway says which outcomes are answers and which are failures.
--     `first_attempts` is the number of CALLS (every call has exactly one attempt numbered
--     1, so a retry or a fallback is not counted as a second call).
--   * public.ai_usage_totals(firm, from, to) — tokens and pages and nothing else,
--     for the enforcement path, which must be cheap and asks the same question
--     on every cache refresh.
--
--   Tokens are summed over EVERY attempt, not only the answered ones: a reasoning
--   model that burned its allowance and sent back nothing was still billed, and a
--   retry sends the same pages again.
--
-- THE FUNCTIONS ARE THE SERVICE ROLE'S. They take the firm as an argument and run
-- as the caller (SECURITY INVOKER), so granting them to authenticated would let
-- any signed-in user read any firm's usage by naming it. They are revoked from
-- everybody else and the API calls them after rbac() with the caller's own firm.
--
-- Additive and idempotent: no data is rewritten, nothing is dropped, no policy is
-- removed, and no existing function is touched.
-- ============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS public.ai_firm_budgets (
    firm_id              uuid        PRIMARY KEY REFERENCES public.firms(id) ON DELETE CASCADE,
    monthly_token_limit  bigint      NULL,
    monthly_page_limit   integer     NULL,
    set_by               uuid        NULL REFERENCES public.users(id) ON DELETE SET NULL,
    updated_at           timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ai_firm_budgets_token_limit_is_positive
        CHECK (monthly_token_limit IS NULL OR monthly_token_limit > 0),
    CONSTRAINT ai_firm_budgets_page_limit_is_positive
        CHECK (monthly_page_limit IS NULL OR monthly_page_limit > 0)
);

COMMENT ON TABLE public.ai_firm_budgets IS
    'A firm''s optional monthly AI allowance, counted in IST calendar months from '
    'ai_usage_events. NULL means no limit set, which is every firm''s position until a '
    'Partner sets one; zero is refused. Enforced at the model doors in domain/ai, '
    'fails OPEN when it cannot be read. Written by the API as the service role. Migration 476.';
COMMENT ON COLUMN public.ai_firm_budgets.monthly_token_limit IS
    'Tokens (prompt + completion + reasoning, as the provider counts them) across every '
    'attempt in an IST month. The call that crosses it is allowed to finish; the next is refused.';
COMMENT ON COLUMN public.ai_firm_budgets.monthly_page_limit IS
    'Page images sent to the vision model across every attempt in an IST month. A call that '
    'would take the firm past it is refused BEFORE anything is sent.';

ALTER TABLE public.ai_firm_budgets ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  EXECUTE 'DROP POLICY IF EXISTS firm_ai_firm_budgets ON public.ai_firm_budgets';
  EXECUTE 'CREATE POLICY firm_ai_firm_budgets ON public.ai_firm_budgets '
          'FOR SELECT TO authenticated '
          'USING (firm_id = public.get_my_firm_id())';

  -- A firm's AI allowance is the Partner's to read, like the spend it limits.
  EXECUTE 'DROP POLICY IF EXISTS ai_firm_budgets_partner_only ON public.ai_firm_budgets';
  EXECUTE 'CREATE POLICY ai_firm_budgets_partner_only '
          'ON public.ai_firm_budgets AS RESTRICTIVE '
          'FOR SELECT USING (public.get_my_role() = ''Partner'')';
END $$;

-- SELECT only: the allowance is set through the API, which asks rbac() and audits it.
GRANT SELECT ON public.ai_firm_budgets TO authenticated;
GRANT ALL ON public.ai_firm_budgets TO service_role;

COMMENT ON COLUMN public.ai_usage_events.outcome IS
    'domain/ai/gateway.OUTCOMES: ok, truncated, empty_reply, unreadable_reply, '
    'timeout, network, rate_limited, provider_error, auth, model_gone, too_long, '
    'refused, param_rejected, budget_exhausted (a call refused for want of the firm''s '
    'monthly allowance before anything was sent; no tokens). Free text on purpose; the '
    'vocabulary is Python.';

CREATE OR REPLACE FUNCTION public.ai_usage_by_day(
    p_firm uuid, p_from timestamptz, p_to timestamptz)
RETURNS TABLE (
    day              date,
    outcome          text,
    attempts         bigint,
    first_attempts   bigint,
    tokens           bigint,
    reasoning_tokens bigint,
    pages            bigint
)
LANGUAGE sql STABLE
AS $$
    SELECT (e.created_at AT TIME ZONE 'Asia/Kolkata')::date AS day,
           e.outcome,
           count(*)                                          AS attempts,
           count(*) FILTER (WHERE e.attempt = 1)             AS first_attempts,
           COALESCE(sum(e.total_tokens), 0)::bigint          AS tokens,
           COALESCE(sum(e.reasoning_tokens), 0)::bigint      AS reasoning_tokens,
           COALESCE(sum(e.input_units), 0)::bigint           AS pages
      FROM public.ai_usage_events e
     WHERE e.firm_id = p_firm
       AND e.created_at >= p_from
       AND e.created_at <  p_to
     GROUP BY 1, 2
     ORDER BY 1, 2
$$;

CREATE OR REPLACE FUNCTION public.ai_usage_by_feature(
    p_firm uuid, p_from timestamptz, p_to timestamptz)
RETURNS TABLE (
    provider         text,
    feature          text,
    model            text,
    outcome          text,
    attempts         bigint,
    first_attempts   bigint,
    tokens           bigint,
    reasoning_tokens bigint,
    pages            bigint
)
LANGUAGE sql STABLE
AS $$
    SELECT e.provider, e.feature, e.model, e.outcome,
           count(*)                                          AS attempts,
           count(*) FILTER (WHERE e.attempt = 1)             AS first_attempts,
           COALESCE(sum(e.total_tokens), 0)::bigint          AS tokens,
           COALESCE(sum(e.reasoning_tokens), 0)::bigint      AS reasoning_tokens,
           COALESCE(sum(e.input_units), 0)::bigint           AS pages
      FROM public.ai_usage_events e
     WHERE e.firm_id = p_firm
       AND e.created_at >= p_from
       AND e.created_at <  p_to
     GROUP BY 1, 2, 3, 4
     ORDER BY 1, 2, 3, 4
$$;

CREATE OR REPLACE FUNCTION public.ai_usage_totals(
    p_firm uuid, p_from timestamptz, p_to timestamptz)
RETURNS TABLE (tokens bigint, pages bigint)
LANGUAGE sql STABLE
AS $$
    SELECT COALESCE(sum(e.total_tokens), 0)::bigint,
           COALESCE(sum(e.input_units), 0)::bigint
      FROM public.ai_usage_events e
     WHERE e.firm_id = p_firm
       AND e.created_at >= p_from
       AND e.created_at <  p_to
$$;

REVOKE ALL ON FUNCTION public.ai_usage_by_day(uuid, timestamptz, timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.ai_usage_by_feature(uuid, timestamptz, timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.ai_usage_totals(uuid, timestamptz, timestamptz) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.ai_usage_by_day(uuid, timestamptz, timestamptz) TO service_role;
GRANT EXECUTE ON FUNCTION public.ai_usage_by_feature(uuid, timestamptz, timestamptz) TO service_role;
GRANT EXECUTE ON FUNCTION public.ai_usage_totals(uuid, timestamptz, timestamptz) TO service_role;

COMMIT;
