/**
 * TAN — Income-tax Act §203A — and the one browser implementation of it.
 *
 * ── THE RULE THIS FILE BELONGS TO ───────────────────────────────────────────
 * Every validator in `lib/identifiers/` mirrors its own authority in
 * `apps/api/core/validators.py` EXACTLY, normalisation included. The finding
 * that created this directory is written up in `pan.ts`: seven screens tested a
 * shape regex against the RAW field value while `validate_pan` strips and
 * uppercases first, so the browser refused what the server accepts. This one
 * had the same defect in a single copy, in `components/customers/
 * CustomerFormModal`.
 *
 * ── WHAT THIS ONE IS ────────────────────────────────────────────────────────
 * The SHAPE DIFFERS FROM A PAN — four letters then five digits, where a PAN is
 * five then four — and a TAN cannot be derived from a PAN, so it has to be
 * typed in. Form 26AS identifies a deductor by TAN and nothing else.
 *
 * Blank is valid: `validate_tan` returns None for an empty value, because a
 * customer who is not a deductor holds no TAN.
 */

/** IT Act §203A: four letters, five digits, one letter. */
const TAN_SHAPE = /^[A-Z]{4}[0-9]{5}[A-Z]$/;

export const TAN_LENGTH = 10;

/** What is wrong with this TAN, as a sentence to put beside the field — or
 *  `null` when there is nothing wrong. */
export function tanProblem(tan: string | null | undefined): string | null {
  // The server's own order: `if not value` BEFORE the strip. See `panProblem`.
  if (!tan) return null;
  const t = tan.trim().toUpperCase();

  if (t.length !== TAN_LENGTH) {
    return `A TAN is ${TAN_LENGTH} characters; this one is ${t.length}.`;
  }
  if (!TAN_SHAPE.test(t)) {
    return "Not a TAN pattern. It is four letters, then five digits, then one "
      + "letter — e.g. MUMA12345B. A PAN is the other way round (five then "
      + "four), and a TAN cannot be derived from one.";
  }
  return null;
}

/** Well-formed once normalised. Blank is valid: see `tanProblem`. */
export function isValidTan(tan: string | null | undefined): boolean {
  return tanProblem(tan) === null;
}
