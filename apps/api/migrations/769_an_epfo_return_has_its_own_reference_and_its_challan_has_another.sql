-- POST-A-518. On EPFO's revamped return system (User Manual for the Re-engineered ECR, v3.0, read 19-11-2026) a return and the
-- challan that pays its dues carry DIFFERENT references, issued at different moments:
--
--   * the RETURN gets a Return File ID when the uploaded file passes the portal's checks (12 digits in the manual's own example,
--     250100001024), with a return statement the employer then approves or rejects;
--   * the CHALLAN gets a TRRN only when it is prepared and finalised, after the return is approved (15 digits in the manual's
--     example, 250113000000438), and is then paid through a bank.
--
-- Migration 335 built this table from the older flow and named the one reference column `trrn`, "EPFO's Temporary Return
-- Reference Number for the upload", and the hand-off asked the CA for "the TRRN the portal gives back" beside the date they filed,
-- as one record. The reference the portal gives for a return is the Return File ID. This migration adds that column and says what
-- `trrn` now means. It is additive and nullable, so the running API is unaffected until the code that writes it deploys, and
-- nothing is backfilled: no row here is a real filing (the product has never filed), and a row recorded before this holds in
-- `trrn` whichever reference the CA typed.
--
-- Free text and unvalidated, like `trrn` and for the same reason (migration 335, domain/payroll/identity.py): a pattern written
-- from memory would refuse a real reference somebody is reading off the portal, which is the wrong direction of error.

ALTER TABLE public.epfo_ecr_filings
    ADD COLUMN IF NOT EXISTS return_file_id text;

COMMENT ON COLUMN public.epfo_ecr_filings.return_file_id IS
    'The Return File ID the EPFO portal gave this return when the uploaded file passed its checks (12 digits in the manual''s '
    'example). The return''s own reference, as the TRRN is the challan''s. Free text, unvalidated.';

COMMENT ON COLUMN public.epfo_ecr_filings.trrn IS
    'The TRRN EPFO issues when the challan for this return''s dues is prepared and finalised, after the return is approved (15 '
    'digits in the manual''s example). Not the return''s reference: that is return_file_id. Before 19-11-2026 the screen asked for '
    '"the TRRN" at the return, so a row recorded then holds whichever reference the CA typed. Deliberately unvalidated.';
