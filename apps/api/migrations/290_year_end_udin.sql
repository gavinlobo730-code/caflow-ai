-- ============================================================================
-- 290 — record the UDIN a CA obtained for the year-end pack
--
-- WHAT WAS MISSING
--     A signed year-end pack carries a UDIN — the Unique Document
--     Identification Number ICAI issues to the member in practice who signs
--     it, so anyone holding the document can verify on ICAI's portal that the
--     member really signed it. There was nowhere to record one, so a pack
--     went out with no way to tie it back to the signature it carries.
--
-- WHAT THIS IS NOT
--     This does NOT generate a UDIN, and nothing in this codebase may. A UDIN
--     is issued by ICAI's portal against the signing member's own credentials.
--     A number produced here would be a fabricated attestation reference on a
--     document asserting that a CA signed it, which is precisely the harm the
--     number exists to prevent. The column records what the member obtained
--     and typed in; domain/udin.py checks only that the SHAPE could be a UDIN,
--     and makes no claim that it was issued.
--
--     Consequently there is no CHECK constraint on the format. The API
--     validates on the way in and can be corrected in one place; a constraint
--     here would additionally reject historical rows on any future format
--     change ICAI makes — and ICAI has already moved this number from 15
--     characters to 18 once.
--
-- WHY ON THE ENGAGEMENT
--     One year-end set is signed once, so the number belongs to the engagement
--     rather than to each generated export. Regenerating the PDF must not lose
--     it, and must not silently produce a second document carrying the same
--     number as if it were separately attested.
-- ============================================================================

ALTER TABLE public.year_end_engagements
  ADD COLUMN IF NOT EXISTS udin              TEXT,
  ADD COLUMN IF NOT EXISTS udin_recorded_at  TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS udin_recorded_by  UUID REFERENCES public.users(id);

COMMENT ON COLUMN public.year_end_engagements.udin IS
  'UDIN obtained from the ICAI portal by the signing member. Recorded, never '
  'generated — see domain/udin.py and migration 290.';
