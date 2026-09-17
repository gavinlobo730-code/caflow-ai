-- 399 — the firm's own GSTIN, back-filled into the column the product reads
--
-- WHAT IS WRONG
--
--   public.firms carries BOTH gst_number (migration 003, with a shape CHECK)
--   and gstin (migration 014, given the same CHECK by 112/316). Nothing has
--   ever synced them, and the two sides of the product picked different ones:
--   both screens that edit the firm profile wrote gst_number straight over
--   PostgREST, while every backend reader reads gstin —
--   invoice_pdf_service._firm_party puts it on the practice's own fee invoice
--   as the SUPPLIER's GSTIN (CGST Rule 46(a)), and the same module decides
--   CGST+SGST against IGST from _state_code(firm["gstin"]).
--
--   So a CA who typed their GSTIN into Settings printed a tax invoice with no
--   supplier GSTIN on it and, because _state_code(None) is None, the whole tax
--   on a LOCAL supply landed in IGST.
--
--   The code half shipped without a migration: domain/firm/identity.gstin_of
--   reads gstin and falls back to gst_number, and PATCH /api/firms/profile is
--   now the one writer. This migration makes that fallback INERT for rows
--   written before it, so `gstin` alone answers for every existing firm.
--
-- WHAT THIS DOES, AND WHAT IT DELIBERATELY DOES NOT
--
--   It copies gst_number into gstin where gstin is empty and gst_number is
--   not. The two columns carry the IDENTICAL shape regex — migration 003
--   inline on gst_number, migration 112 as firms_gstin_format — so every value
--   this moves already satisfies the constraint it is moving into, and
--   re-running is a no-op. 003's is VALID, so the source cannot hold anything
--   the target would reject.
--
--   IT DOES NOT DROP gst_number. tests/fixtures/ carries point-in-time
--   production snapshots that test_schema_matches_production_pg.py and
--   test_guards_match_production_pg.py compare a migration-built database
--   against; removing a live column moves both sides of that comparison at
--   once, and docs/schema-drift.md says how to refresh them. Migration 371
--   took the same decision about the dead TDS rate master for the same
--   reason: mark it dead in the database today, delete it in a change a
--   reviewer can read on its own. (That table is deliberately not named here:
--   tests/test_the_dead_tds_rate_master_has_no_readers.py greps for it, and
--   the point of that guard is that a mention is one copy-paste from a read.)
--
--   IT DOES NOT SET gstin NOT NULL. A practice below the CGST s.22 threshold
--   has no registration to record, and the fee invoice already prints without
--   one.
--
-- ⚠️ THE SHAPE IS CARRIED OVER; THE CHECK DIGIT IS NOT.
--
--   A GSTIN also carries a check digit, and nothing that ever wrote
--   gst_number tested it — that is exactly what PATCH /api/firms/profile adds
--   for every save from now on (domain/gst/gstin.problem_with). A firm whose
--   gst_number was typed with a transposition therefore arrives in `gstin`
--   still transposed. That is the right direction rather than a new defect:
--   today that firm's invoice carries NO GSTIN at all and taxes a local supply
--   as IGST, and after this it carries the GSTIN the CA believes they recorded,
--   visible on the document and correctable on the screen that refuses to save
--   a bad one.
--
-- A ROW WHOSE gstin IS MALFORMED BUT NOT EMPTY IS LEFT ALONE, DELIBERATELY.
--
--   firms_gstin_format is NOT VALID — migration 112 declared it so and 316
--   deliberately kept it ("the point of this migration is that production
--   match the declaration, not exceed it") — so
--   existing rows were never checked against it and one may hold a malformed
--   gstin next to a well-shaped gst_number. This migration does not touch it:
--   the WHERE tests only for NULL or blank. Preferring the superseded column
--   over a value somebody deliberately recorded in the canonical one would be
--   a guess about the firm's own legal identity, and it would contradict the
--   rule this migration exists to establish. It is also no regression —
--   invoice_pdf_service read that same malformed value before any of this —
--   and PATCH /api/firms/profile now refuses to save one, so the screen is
--   where it gets fixed. Verified against a migration-built database on
--   17-09-2026: of five shapes (legacy only, both set, blank gstin, neither,
--   malformed gstin) exactly the first and third move.
--
--   MEASURED, 17-09-2026: production holds 2 firms and BOTH columns are NULL
--   on both, so this migration moves no data there today. It exists so the
--   rule holds for every firm created from here, and for any deployment that
--   is not this one.

BEGIN;

UPDATE public.firms
   SET gstin = btrim(gst_number)
 WHERE (gstin IS NULL OR btrim(gstin) = '')
   AND gst_number IS NOT NULL
   AND btrim(gst_number) <> '';

COMMENT ON COLUMN public.firms.gstin IS
  'The firm''s own GSTIN — THE column. Written only by PATCH '
  '/api/firms/profile, which tests the CHECK DIGIT through '
  'domain/gst/gstin.problem_with; firms_gstin_format (migrations 112/316) is a '
  'shape regex and cannot. Read only through domain/firm/identity.gstin_of. '
  'This goes on every fee invoice the practice raises as the supplier''s GSTIN '
  '(CGST Rule 46(a)) and decides CGST+SGST against IGST, and nothing '
  'downstream re-checks it. Migration 399.';

COMMENT ON COLUMN public.firms.gst_number IS
  'SUPERSEDED by firms.gstin and NOT WRITTEN. Migration 003''s column; both '
  'screens that edit the firm profile wrote it straight over PostgREST while '
  'every backend reader read gstin, so a firm''s own GSTIN was invisible to '
  'its own invoice. Migration 399 back-filled gstin from it, so the fallback '
  'in domain/firm/identity.gstin_of is inert for existing rows and exists only '
  'for a row this migration did not reach. Do not write it, and do not read it '
  'directly — identity.gstin_of is the reader. A DROP is the end state and '
  'needs the production-fixture refresh in docs/schema-drift.md, the same '
  'reason migration 371 marked the dead TDS rate master dead rather than '
  'deleting it.';

COMMIT;
