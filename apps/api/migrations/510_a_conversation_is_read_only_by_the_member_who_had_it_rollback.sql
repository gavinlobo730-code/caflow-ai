-- Rollback of migration 510: drops the owner-only read policies, so a member's own session reads every conversation and
-- message of their firm again (the firm-isolation policies were never touched). THIS RE-OPENS THAT READ.
DROP POLICY IF EXISTS ai_messages_owner_only ON public.ai_messages;
DROP POLICY IF EXISTS ai_conversations_owner_only ON public.ai_conversations;
