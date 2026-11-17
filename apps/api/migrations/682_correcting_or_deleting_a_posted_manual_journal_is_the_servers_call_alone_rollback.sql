-- Rollback of migration 682: a signed-in member may execute the two wrappers again, as migration 486 left them. The wrappers still ask
-- `accounting` `write` for the client and that the recorded actor is the caller, but not the firm's journal-approval switch, so with the
-- switch on a member the API refuses can again correct or delete a posted manual journal directly.
GRANT EXECUTE ON FUNCTION public.edit_posted_journal(uuid, uuid, uuid, jsonb, text, text, date, uuid) TO authenticated;
GRANT EXECUTE ON FUNCTION public.discard_posted_journal(uuid, uuid, uuid, uuid, boolean) TO authenticated;
