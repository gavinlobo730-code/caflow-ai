-- Rollback of migration 517: drops the Day Book page function. The screen and the export read through it, so after this the Day Book
-- answers an error until the code that reads it is rolled back too. For fidelity with the previous schema, not for use.
DROP FUNCTION IF EXISTS public.day_book_page(uuid, uuid, date, date, boolean, integer, integer);
