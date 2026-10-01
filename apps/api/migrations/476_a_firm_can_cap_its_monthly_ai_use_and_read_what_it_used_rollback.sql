-- Rollback for 476. DISCARDS every firm's recorded AI allowance.
--
-- Nothing else reads the table or the two functions. domain/ai/budget_gate treats an
-- allowance it cannot read as NO LIMIT (it fails open), so the gateway keeps working with
-- these gone — it logs that the budget could not be read and carries on. Roll the code back
-- with this file if you want the refusals not to be attempted. ai_usage_events and the
-- usage rows already written are untouched.

BEGIN;

DROP FUNCTION IF EXISTS public.ai_usage_totals(uuid, timestamptz, timestamptz);
DROP FUNCTION IF EXISTS public.ai_usage_by_feature(uuid, timestamptz, timestamptz);
DROP FUNCTION IF EXISTS public.ai_usage_by_day(uuid, timestamptz, timestamptz);
DROP TABLE IF EXISTS public.ai_firm_budgets;

COMMENT ON COLUMN public.ai_usage_events.outcome IS
    'domain/ai/gateway.OUTCOMES: ok, truncated, empty_reply, unreadable_reply, '
    'timeout, network, rate_limited, provider_error, auth, model_gone, too_long, '
    'refused, param_rejected. Free text on purpose; the vocabulary is Python.';

COMMIT;
