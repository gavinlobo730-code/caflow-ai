-- Rollback for 410. DISCARDS every proof document recorded against a Chapter
-- VI-A line; `proof_reference` (the employee's own words) is untouched because
-- 410 never wrote it.

ALTER TABLE public.payroll_it_declaration_items
    DROP CONSTRAINT IF EXISTS payroll_it_declaration_items_proof_attachments_check;

ALTER TABLE public.payroll_it_declaration_items
    DROP COLUMN IF EXISTS proof_attachments;
