/**
 * DIN — Companies Act 2013 §§153–154 — and the one browser implementation.
 *
 * ── THE RULE THIS FILE BELONGS TO ───────────────────────────────────────────
 * Every validator in `lib/identifiers/` mirrors its own authority in
 * `apps/api/core/validators.py` EXACTLY, normalisation included. See `pan.ts`
 * for the finding that created this directory. This one had the same defect in
 * a single copy, on the MCA directors screen.
 *
 * ── WHY BLANK IS AN ERROR HERE AND NOWHERE ELSE IN THIS DIRECTORY ───────────
 * Eight digits, allotted by the Central Government to every individual
 * intending to be a director. `core/validators.validate_din` opens
 * `if not value: return "DIN is required…"` where `validate_pan` and
 * `validate_tan` return None — a director without a DIN is not a director, so
 * §153 makes it mandatory in a way §139A and §203A do not. That is the
 * SERVER's rule, reproduced, not a choice made here.
 *
 * It also does not uppercase: a DIN is digits, so there is no case to fold.
 *
 * The copy this replaced cited "IT Act / Companies Act 2013" in its message.
 * The IT Act does not allot a DIN.
 */

/** Companies Act 2013 §154: eight digits. */
const DIN_SHAPE = /^[0-9]{8}$/;

export const DIN_LENGTH = 8;

/** What is wrong with this DIN, or `null`. Blank is an error — see above. */
export function dinProblem(din: string | null | undefined): string | null {
  if (!din || !din.trim()) {
    return "DIN is required. Companies Act 2013 §153: every director must hold "
      + "a valid DIN.";
  }
  const d = din.trim();
  if (!DIN_SHAPE.test(d)) {
    return "DIN format is invalid. Expected: 8 digits (e.g. 00012345).";
  }
  return null;
}

/** Well-formed once trimmed. Blank is NOT valid: see `dinProblem`. */
export function isValidDin(din: string | null | undefined): boolean {
  return dinProblem(din) === null;
}
