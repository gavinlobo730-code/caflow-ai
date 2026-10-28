-- Rollback of migration 558: gives `authenticated` and `anon` back TRUNCATE on the two reference tables, which is what production held on
-- 28-10-2026 (a platform default PostgREST does not expose). The write verbs are NOT given back: production never held them on these tables,
-- and a database built from the migrations holding them was the defect the migration closed.
GRANT TRUNCATE ON public.hsn_master, public.tds_section_limits TO authenticated, anon;
