-- Rollback of migration 575: nothing to put back. The ids the entries named before were ids no row carries (the receipts were stored
-- under a different id), so restoring them would restore a link to nothing. Left as a no-op on purpose.
BEGIN;
COMMIT;
