-- ============================================================================
-- 298 — is this employee covered by the Payment of Gratuity Act?
--
-- WHY IT IS A FIELD AND NOT A DERIVATION
--     §1(3) applies the Act to every factory, mine, plantation, port, railway
--     and shop or establishment in which TEN OR MORE persons are employed, or
--     were employed on any day of the preceding twelve months. §1(3A) then
--     says an establishment to which the Act has once applied "shall continue
--     to be governed by this Act notwithstanding that the number of persons
--     therein at any time after it has become so applicable falls below ten".
--
--     Neither fact is derivable from a payroll run. Today's headcount is not
--     the headcount on the qualifying date, and §1(3A) means an establishment
--     with four employees may still be covered because it once had twelve.
--     Counting active employees would get both wrong, and would get them wrong
--     SILENTLY — the number always looks plausible.
--
-- WHY THE DEFAULT IS TRUE
--     Coverage is the common case, and the two branches are not symmetrical.
--     §10(10)(ii), for a covered employee, exempts the §4 formula amount.
--     §10(10)(iii), for an uncovered one, exempts half a month's AVERAGE salary
--     of the last ten months per COMPLETED year — a different formula, a
--     different divisor, and part years dropped rather than rounded up.
--     Defaulting to covered states the ordinary case and leaves the exception
--     visible, which is the same reasoning migration 295 applied to
--     eps_eligible.
--
-- Additive and idempotent. No backfill is possible or wanted: every existing
-- row takes the default, which is the position for the large majority.
-- ============================================================================

ALTER TABLE public.payroll_employees
  ADD COLUMN IF NOT EXISTS gratuity_act_covered boolean NOT NULL DEFAULT true;

COMMENT ON COLUMN public.payroll_employees.gratuity_act_covered IS
  'Whether the Payment of Gratuity Act 1972 applies to this employee''s '
  'establishment (§1(3), and §1(3A) which keeps it applying once it has). Not '
  'derived from headcount — today''s count is not the count on the qualifying '
  'date. Drives which limb of IT Act §10(10) computes the exemption: clause '
  '(ii) for a covered employee, clause (iii) for one who is not.';
