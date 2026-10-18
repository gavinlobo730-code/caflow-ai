-- Rollback of migration 505: gives `authenticated` back the write privileges migrations 095 and 287 granted on the AI tables.
-- THIS RE-OPENS THE HOLE: any signed-in member of a firm can again write another member's AI conversation, plant an
-- `assistant` message that the next prompt replays as the model's own turn, and rewrite the cached dashboard summaries.
-- Roll the API back FIRST: the repository writes with the privileged client and works either way, but the owner check on a
-- conversation is code, not a grant. It does NOT restore the TRUNCATE privilege on `authenticated` and `anon` that 505 also
-- revoked, because no migration ever granted it (it came from the hosting platform's defaults) and a signed-in role has no
-- use for it.
GRANT INSERT, UPDATE, DELETE ON public.ai_conversations, public.ai_messages, public.ai_summaries,
    public.ai_recommendations, public.ai_feedback, public.ai_actions, public.ai_context_windows TO authenticated;
