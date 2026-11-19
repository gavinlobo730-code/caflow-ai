-- Rollback of migration 769: drops the Return File ID column and restores migration 335's comment on trrn.
-- A Return File ID recorded in the meantime is lost, which is acceptable only because no row here is a real filing.

ALTER TABLE public.epfo_ecr_filings
    DROP COLUMN IF EXISTS return_file_id;

COMMENT ON COLUMN public.epfo_ecr_filings.trrn IS
    'EPFO Temporary Return Reference Number. Deliberately unvalidated - see '
    'domain/payroll/identity.py for why a remembered pattern refuses real '
    'registrations.';
