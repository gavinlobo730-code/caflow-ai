-- Rollback of migration 660. The rows are recomputed every night, so dropping the table loses nothing that is not rebuilt.
DROP TABLE IF EXISTS public.nightly_exception_results;
