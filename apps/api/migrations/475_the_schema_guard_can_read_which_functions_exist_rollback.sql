-- Rollback for migration 475: the schema guard can no longer list functions.
--
-- core/schema_guard.py treats the missing RPC as "functions not checked", never as drift, so
-- rolling this back removes the function half of the object check and nothing else. /health
-- keeps answering and the column and table checks are unaffected.

DROP FUNCTION IF EXISTS public.get_public_schema_functions();
