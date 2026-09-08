-- A GSTR-2B reconciliation records THAT IT HAPPENED, not only what it found.
--
-- WHAT WAS WRONG
--
-- Migration 340 gave `gstr2a_records` one row per PORTAL DOCUMENT. That is the
-- right shape for the documents, and it is the wrong shape for the QUESTION
-- "has this period been reconciled?", because a 2B can legitimately produce no
-- rows at all:
--
--   * nobody the client bought from filed anything for the month;
--   * every document in it is marked itcavl = 'N' and is filtered out of the
--     Rule 36(4) working;
--   * the client genuinely had no inward supplies.
--
-- With no header row, "reconciled and it was empty" and "never reconciled" are
-- the same absence, and three separate readers get it wrong:
--
--   1. services/gst_return_service._gstr2a_for_period returns [], so
--      gstr3b_computer derives have_2b = False and Rule 36(4) does NOT cap.
--      The return then claims book ITC in full — the exact credit s.16(2)(aa)
--      withholds, on the client whose suppliers have filed nothing. That is the
--      opposite of what the reconciliation was built to do.
--   2. the Purchases tab's GSTR-2B column reads "not reconciled" where it
--      should read "supplier has not filed" — again for precisely the client
--      who needs chasing.
--   3. the client GST tab shows nothing for a period that WAS reconciled.
--
-- WHY A TABLE AND NOT A FLAG
--
-- The fact being recorded is about the FILE, not about any document in it: which
-- GSTIN it was downloaded for, when the portal generated it, which sections it
-- carried, and whether it parsed. None of that has a document to hang on, and a
-- boolean on the client would not survive a second period.
--
-- `document_count` is deliberately stored rather than counted from
-- gstr2a_records: a count of zero is the whole point, and a COUNT(*) over a
-- table with no rows cannot tell an empty reconciliation from an absent one.
--
-- `parsed_ok` exists because services/gst_2b_reconciliation_service persists
-- NOTHING for an unparseable file. A header row written with parsed_ok = false
-- would claim a reconciliation happened when it did not, so the service writes
-- no header in that case either; the column is here so a future partial-parse
-- path has somewhere honest to record itself rather than inventing a second
-- table.

CREATE TABLE IF NOT EXISTS public.gstr2b_reconciliations (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id           UUID NOT NULL REFERENCES public.firms(id)   ON DELETE CASCADE,
  client_id         UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  return_period     TEXT NOT NULL,            -- MMYYYY, as gstr2a_records
  -- What the FILE said about itself. Nullable because a 2B that parses can
  -- still omit them, and an absent value must not read as an empty string.
  gstin             TEXT,
  file_return_period TEXT,                    -- what the file claims; may differ
  generated_on      TEXT,
  sections_seen     TEXT[] NOT NULL DEFAULT '{}',
  -- The counts that make "empty" distinguishable from "absent".
  document_count    INTEGER NOT NULL DEFAULT 0,
  book_bill_count   INTEGER NOT NULL DEFAULT 0,
  parsed_ok         BOOLEAN NOT NULL DEFAULT true,
  problems          TEXT[] NOT NULL DEFAULT '{}',
  reconciled_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  reconciled_by     UUID REFERENCES public.users(id) ON DELETE SET NULL,
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One reconciliation per client-period; a re-upload REPLACES it, matching the
-- delete-then-insert the document rows already use.
CREATE UNIQUE INDEX IF NOT EXISTS uq_gstr2b_reconciliations_period
  ON public.gstr2b_reconciliations (client_id, return_period);

ALTER TABLE public.gstr2b_reconciliations ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policies
                  WHERE schemaname = 'public'
                    AND tablename  = 'gstr2b_reconciliations'
                    AND policyname = 'firm_staff_manage_gstr2b_reconciliations') THEN
    CREATE POLICY "firm_staff_manage_gstr2b_reconciliations"
      ON public.gstr2b_reconciliations
      FOR ALL TO authenticated
      USING (firm_id = public.get_my_firm_id())
      WITH CHECK (firm_id = public.get_my_firm_id());
  END IF;
END $$;

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.gstr2b_reconciliations
  TO authenticated, service_role;

COMMENT ON TABLE public.gstr2b_reconciliations IS
  'One row per (client, return period) recording that a GSTR-2B was reconciled '
  'at all. Separate from gstr2a_records because a reconciliation can find zero '
  'documents, and "empty" must not read as "never done" — Rule 36(4) caps at '
  'NIL in the first case and does not cap in the second.';
COMMENT ON COLUMN public.gstr2b_reconciliations.document_count IS
  'Stored, not derived. Zero is a meaningful answer and COUNT(*) over '
  'gstr2a_records cannot distinguish it from an absent reconciliation.';


-- ── the natural key was wrong, and it is a data-loss bug ────────────────────
--
-- uq_gstr2a_records_document was (client_id, return_period, section,
-- supplier_gstin, invoice_number). `document_type` is NOT in it, and in the
-- `cdnr` section GSTR-2B carries `typ` "C" (credit note) and "D" (debit note).
-- A supplier's credit-note and debit-note series are independent, so the same
-- number appearing in both is ordinary rather than exotic.
--
-- Two rows from ONE file then collide. gst_2b_reconciliation_service.reconcile_2b
-- deletes the period's rows and re-inserts, in two separate statements: the
-- DELETE commits, the INSERT raises on this index, and the period's previous
-- reconciliation is gone with nothing written in its place. A first upload of
-- such a file writes nothing at all.
--
-- Proven against the parser before this migration was written: one cdnr entry
-- with ntnum "CN-1" typ "C" and ntnum "CN-1" typ "D" yields two rows whose
-- (section, supplier_gstin, invoice_number) are identical.

DROP INDEX IF EXISTS public.uq_gstr2a_records_document;
CREATE UNIQUE INDEX IF NOT EXISTS uq_gstr2a_records_document
  ON public.gstr2a_records
     (client_id, return_period, section, document_type, supplier_gstin, invoice_number);

COMMENT ON INDEX public.uq_gstr2a_records_document IS
  'document_type is in the key because cdnr carries credit notes and debit '
  'notes in one section, and a supplier numbers the two series independently.';
