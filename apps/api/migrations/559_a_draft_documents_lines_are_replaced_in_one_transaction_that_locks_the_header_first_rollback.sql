-- Rollback of migration 559: drops the function. The API then falls back to the two-step replacement it used before.
DROP FUNCTION IF EXISTS public.replace_draft_document_lines(text, uuid, uuid, jsonb);
