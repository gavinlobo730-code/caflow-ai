-- Rollback of migration 548: the function is dropped. The employee door's read-back and put-back and the staff door's three
-- separate requests are what stand in for it, so roll back the code that calls it FIRST: a caller of a function that is gone fails.

DROP FUNCTION IF EXISTS public.file_it_declaration(jsonb, jsonb, boolean);
