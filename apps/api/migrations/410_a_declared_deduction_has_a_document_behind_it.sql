-- ============================================================================
-- 410 — a declared deduction has a DOCUMENT behind it, not a sentence about one
--
-- WHY (PAY-26's remaining half)
--     `payroll_it_declaration_items.proof_reference` has been a bare TEXT
--     column since migration 296: somebody types "LIC receipt 12345" and
--     nothing holds the receipt. §192(1) makes the EMPLOYER answerable for a
--     correct deduction, and migration 296's own header says a declaration
--     that never grew a proof must stop reducing tax before the year ends —
--     but the verifier had nothing to look at when deciding that, so
--     `amount_verified_paise` was recorded against a memory of a document.
--     Rule 26C's Form 12BB is a statement of PARTICULARS *with* evidence; the
--     evidence half did not exist.
--
-- ONE ATTACHMENT RULE, AND IT IS NOT NEW
--     `domain/attachments` already holds it, for manual journals (138) and
--     bank transactions (259), and this column takes the same shape and the
--     same CHECK. Its two decisions carry over exactly and both matter here:
--     the scheme vocabulary is CLOSED to http/https, because a stored
--     `javascript:` or `data:` URL is stored XSS delivered by whoever uploaded
--     the "receipt" — and an employee's own portal submission is precisely an
--     untrusted uploader; and an UPLOADED document stores the document id with
--     NO url, because the firm's store hands back a signed url that expires in
--     an hour and would be a dead link by the time an assessing officer asked.
--
-- `proof_reference` IS KEPT AND IS NOT REPLACED
--     It is the employee's own words about what they are producing — a policy
--     number, a receipt number — and it is often all there is for a proof
--     handed over on paper. Dropping it would lose that; making it a caption
--     for the attachment would make a row with paper evidence look empty. The
--     two answer different questions and both are optional.
--
-- Additive and idempotent. DEFAULT '[]' with no backfill: every existing row
-- genuinely has no document, and an empty array says exactly that.
-- ============================================================================

ALTER TABLE public.payroll_it_declaration_items
    ADD COLUMN IF NOT EXISTS proof_attachments JSONB NOT NULL DEFAULT '[]'::jsonb;

DO $$ BEGIN
  IF NOT EXISTS (
      SELECT 1 FROM pg_constraint
      WHERE conrelid = 'public.payroll_it_declaration_items'::regclass
        AND conname  = 'payroll_it_declaration_items_proof_attachments_check') THEN
    -- Mirrors domain/attachments.MAX_ATTACHMENTS. More than a handful of
    -- documents on one Chapter VI-A line means the line is doing too much
    -- work, not that the limit is wrong.
    ALTER TABLE public.payroll_it_declaration_items
      ADD CONSTRAINT payroll_it_declaration_items_proof_attachments_check
      CHECK (jsonb_typeof(proof_attachments) = 'array'
             AND jsonb_array_length(proof_attachments) <= 20);
  END IF;
END $$;

COMMENT ON COLUMN public.payroll_it_declaration_items.proof_attachments IS
  'The DOCUMENTS behind this Chapter VI-A claim — Rule 26C''s evidence half. '
  'Same shape and same rule as journal_entries.attachments (138) and '
  'bank_transactions.attachments (259): domain/attachments is the authority, '
  'the scheme vocabulary is closed to http/https because an employee''s own '
  'portal upload is untrusted input, and a document-backed attachment stores '
  'the document id with NO url so a signed url cannot rot into a dead link. '
  'Does NOT replace proof_reference, which is the employee''s own words about '
  'a proof that may only exist on paper.';
