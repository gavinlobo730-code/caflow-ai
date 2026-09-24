/**
 * PAN — Income-tax Act §139A with Rule 114 — and the ONE browser
 * implementation of it.
 *
 * ── THE DEFECT ──────────────────────────────────────────────────────────────
 * Seven screens each carried `/^[A-Z]{5}[0-9]{4}[A-Z]$/` and tested it against
 * the RAW field value. `core/validators.validate_pan` — the server's authority,
 * reached by the MCA, lifecycle and payroll doors — does
 *
 *     v = value.strip().upper()
 *
 * FIRST. So the two disagreed on every PAN that was merely typed in lower case
 * or pasted with a space, and they disagreed in the direction that BLOCKS: the
 * browser refused what the server would have accepted.
 *
 * On two of the seven it was plainly visible. The firm's own PAN on Settings
 * and at onboarding is rendered by a shared `Field` that does NOT uppercase
 * what is typed — several other identifier inputs in this product do
 * (`e.target.value.toUpperCase()`), these two do not — and the submit path
 * `.trim()`s the value on its way out while the validator did not trim before
 * testing it. So a CA typing `aabcu9603r`, or pasting `AABCU9603R ` out of an
 * email, was told "Invalid PAN format (e.g. AABCU9603R)" about a PAN that is
 * correct.
 *
 * ── WHAT THIS DOES AND DOES NOT CLAIM ───────────────────────────────────────
 * It is the SHAPE, normalised, and nothing more — exactly what the server
 * checks, so the two cannot disagree. In particular:
 *
 * **THE FOURTH CHARACTER'S HOLDER TYPE IS DELIBERATELY NOT TESTED.** Rule 114
 * makes it a status code (P individual, C company, H HUF, F firm, and so on),
 * so a PAN whose fourth character is outside that set cannot exist and the
 * test would be a real strengthening. It is not made here because the full
 * set could not be confirmed — egress is refused at this environment's proxy —
 * and the error direction is UNSAFE: an incomplete set refuses a genuine PAN
 * and blocks a client record, where the current behaviour merely fails to
 * catch a typo. Settle it against Rule 114 before adding it, on BOTH sides at
 * once, or the two drift again.
 *
 * **BLANK IS VALID.** PAN is optional on most of these forms — an unregistered
 * party has none — and `validate_pan` returns None for an empty value for the
 * same reason. Refusing blank is the caller's own `required` to impose.
 *
 * `apps/api/tests/test_one_identifier_rule_in_the_browser.py` pins this to
 * `core/validators.validate_pan` and holds the sweep.
 */

/** IT Act §139A: five letters, four digits, one letter. */
const PAN_SHAPE = /^[A-Z]{5}[0-9]{4}[A-Z]$/;

export const PAN_LENGTH = 10;

/**
 * What is wrong with this PAN, as a sentence to put beside the field — or
 * `null` when there is nothing wrong. Shaped like `lib/gst/gstin.gstinProblem`
 * so there is one idea of "what is wrong with this identifier".
 */
export function panProblem(pan: string | null | undefined): string | null {
  // THE SERVER'S OWN ORDER, EDGE INCLUDED. `core/validators.validate_pan`
  // opens `if not value: return None` and normalises AFTER — so an EMPTY
  // string is "not held" and a string of SPACES is a format error, which is a
  // small asymmetry in the authority rather than a considered rule. It is
  // reproduced here rather than tidied, because the whole point of this module
  // is that the browser must not accept what the server refuses; being kinder
  // in one place is how the two came to disagree in the first place. Tidy it
  // on the server if it is worth tidying, and this follows.
  if (!pan) return null;
  // NORMALISE, exactly as validate_pan does. This single line is the defect
  // the module was written for: seven screens tested the RAW value.
  const p = pan.trim().toUpperCase();

  if (p.length !== PAN_LENGTH) {
    return `A PAN is ${PAN_LENGTH} characters; this one is ${p.length}.`;
  }
  if (!PAN_SHAPE.test(p)) {
    return "Not a PAN pattern. It is five letters, then four digits, then one "
      + "letter — e.g. AABCU9603R.";
  }
  return null;
}

/** Well-formed once normalised. Blank is valid: see `panProblem`. */
export function isValidPan(pan: string | null | undefined): boolean {
  return panProblem(pan) === null;
}
