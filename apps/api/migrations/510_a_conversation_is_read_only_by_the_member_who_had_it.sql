-- Migration 510: an AI conversation, and its messages, are read only by the member who had the conversation.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG (ledger POST-A-258, found while building migration 505)
-- ═══════════════════════════════════════════════════════════════════════════
-- Migration 505 put the owner rule on the API: a conversation is its owner's, and a member who is not the owner is told
-- "Conversation not found". The database never agreed. `ai_conversations` and `ai_messages` each carry one permissive
-- policy, `<table>_firm_isolation` (FOR ALL, TO PUBLIC, `firm_id = get_my_firm_id()`), so a member's own JWT reads every
-- other member's chat over PostgREST, including the client-scoped conversations the API would refuse them. No screen reads
-- these tables (the copilot page goes through the API), so nothing needs it.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═══════════════════════════════════════════════════════════════════════════
-- Adds one RESTRICTIVE SELECT policy to each table, ANDed with the firm policy that stays as it is:
--   * `ai_conversations`  `user_id = auth.uid()`. The column holds the SIGN-IN id (`auth_user_id`), which is what the API
--     stores (`routers/ai_copilot_v2._caller_id`), and not `users.id`.
--   * `ai_messages`       the message's conversation is one the caller owns, asked the same way. `ai_messages` has no
--     `user_id` of its own, so the conversation is its owner record.
-- DECIDED, AND WRITTEN DOWN: a Partner may not read another member's conversations, as the API does not allow it today. A
-- conversation is a person's working-out, and one firm-wide reader would make "who asked the copilot what" a standing
-- surveillance channel that nobody agreed to. If a firm ever needs it, it is a deliberate route with its own audit.
--
-- READS only: writes were taken from the signed-in roles by migration 505, and `service_role`, which the API's writes use,
-- bypasses row security. The API's own reads are the caller's session and are already filtered to the owner, so no answer it
-- gives changes. The firm policy and its grants are untouched.
--
-- Rollback: migration 510_..._rollback.sql drops both policies. That re-opens the firm-wide read.

DROP POLICY IF EXISTS ai_conversations_owner_only ON public.ai_conversations;
CREATE POLICY ai_conversations_owner_only ON public.ai_conversations
    AS RESTRICTIVE FOR SELECT TO authenticated
    USING (user_id = (SELECT auth.uid()));

DROP POLICY IF EXISTS ai_messages_owner_only ON public.ai_messages;
CREATE POLICY ai_messages_owner_only ON public.ai_messages
    AS RESTRICTIVE FOR SELECT TO authenticated
    USING (EXISTS (SELECT 1 FROM public.ai_conversations c
                    WHERE c.id = ai_messages.conversation_id AND c.user_id = (SELECT auth.uid())));
