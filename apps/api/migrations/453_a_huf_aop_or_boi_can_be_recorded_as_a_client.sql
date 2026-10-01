-- 453: a Hindu undivided family, an association of persons or a body of
--      individuals can be recorded as a client.
--
-- WHY
--   clients.entity_type is CHECKed to the eight values migration 001 listed:
--   Proprietorship, Partnership, LLP, Private Limited, Public Limited, Trust,
--   Society, Individual (TDS-INCOME-TAX-16). A HUF, an AOP and a BOI are three
--   of the commonest assessees a practice has and the product could not hold
--   any of them, so each was recorded as "Individual" -- and an Individual is
--   computed on the individual slabs WITH the s.87A rebate, the s.16(ia)
--   standard deduction and the senior-citizen slab, none of which a family or
--   an association gets:
--
--     * s.87A reaches "an assessee, being an individual resident in India";
--     * s.16(ia) is a deduction from SALARY, and neither a family nor an
--       association is an employee;
--     * the higher basic exemption at 60 and 80 is for "every individual".
--
--   An AOP or BOI has a second problem the other two do not: s.167B charges
--   its total income at the MAXIMUM MARGINAL RATE where its members' shares
--   are indeterminate or unknown, or where a member's own income is above the
--   exemption limit, and at the slab rates only otherwise. Recorded as an
--   Individual it was always charged on the slabs.
--
-- WHAT THIS DOES
--   Widens the CHECK to the eleven values the client model, the client form and
--   domain/income_tax/assessee.py now know: the original eight plus 'HUF',
--   'AOP' and 'BOI'. The spelling is the one models/client.EntityType carries,
--   so the two cannot disagree about what a client may be.
--
--   NOTHING IS REWRITTEN. Every client already in the table satisfies the
--   narrower CHECK, which is a subset of this one, so no row changes type: a
--   HUF somebody recorded as an Individual stays one until the CA edits the
--   client, because nobody can tell at this distance which of those rows is a
--   family and which is a person -- the PAN's fourth character says (H for a
--   HUF, A for an AOP, B for a BOI), but a PAN typed wrongly is exactly the
--   record this change is not entitled to overrule.
--
--   NOT VALID + VALIDATE is used, matching 424 and 427, because this runs
--   unattended on merge and a pattern that is right whether or not the table
--   holds data is worth more than one that is right only today.
--
-- WHAT THIS DOES NOT DO
--   clients.constitution (migration 003) carries a second, eight-value CHECK of
--   its own. Nothing in apps/api or apps/web reads or writes that column, so it
--   is left alone rather than widened to match -- widening a dead column is a
--   second place to say the same thing. The production guard fixture still
--   records the eight-value entity_type CHECK: test_guards_match_production_pg
--   excuses it while this migration is in flight because it ADDs the constraint
--   by name, and the next fixture refresh absorbs it.

BEGIN;

ALTER TABLE public.clients
    DROP CONSTRAINT IF EXISTS clients_entity_type_check;

ALTER TABLE public.clients
    ADD CONSTRAINT clients_entity_type_check
    CHECK (entity_type IN (
        'Proprietorship', 'Partnership', 'LLP', 'Private Limited',
        'Public Limited', 'Trust', 'Society', 'Individual',
        'HUF', 'AOP', 'BOI'
    ))
    NOT VALID;

ALTER TABLE public.clients
    VALIDATE CONSTRAINT clients_entity_type_check;

COMMENT ON COLUMN public.clients.entity_type IS
    'The constitution of the assessee: Proprietorship | Partnership | LLP | '
    'Private Limited | Public Limited | Trust | Society | Individual | HUF | AOP | BOI. '
    'domain/income_tax/assessee.py maps each to the tax basis it is computed on. '
    'Migration 453 added HUF, AOP and BOI to the eight 001 allowed.';

COMMIT;
