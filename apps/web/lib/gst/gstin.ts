/**
 * GSTIN structure and its check digit — the browser-side mirror of
 * apps/api/domain/gst/gstin.py.
 *
 * WHY A MIRROR AND NOT A ROUND TRIP
 *     The backend is the authority and refuses a bad GSTIN on save (see
 *     routers/customers.py and routers/vendors.py). This exists so the CA is
 *     told at the keystroke rather than after filling in the rest of the form,
 *     and so the message names the character to look at. A request per keystroke
 *     would be the alternative, and it is worse.
 *
 *     The two are held together by tests/fixtures/gstin.json — the SAME cases
 *     run through both implementations, in tests/test_gstin_check_digit.py and
 *     lib/gst/gstin.test.ts. Adding a case to the fixture adds it to both.
 *
 * WHAT THE CHECK DIGIT BUYS
 *     The shape alone accepts every transposition inside the PAN:
 *     27AAPFU0939F1ZV and 27AAPFU0399F1ZV are both well-formed. A customer's
 *     GSTIN is what puts the supply into THEIR GSTR-2B, so the wrong one means
 *     the recipient never gets the input tax credit, correctable only by an
 *     amendment inside the CGST Act s.37(3) window.
 */

/** 0-9 then A-Z. Position is the value. */
export const ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ";
export const GSTIN_LENGTH = 15;

const GSTIN_SHAPE = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/;

/** 01-38, plus 97 (Other Territory) and 99 (Centre Jurisdiction). */
const VALID_STATE_CODES = new Set<string>([
  ...Array.from({ length: 38 }, (_, i) => String(i + 1).padStart(2, "0")),
  "97", "99",
]);

/** The check digit for the first fourteen characters of a GSTIN. */
export function checksumChar(firstFourteen: string): string {
  if (firstFourteen.length !== GSTIN_LENGTH - 1) {
    throw new Error(
      `a GSTIN check digit is computed over 14 characters, got ${firstFourteen.length}`);
  }
  let total = 0;
  for (let i = 0; i < firstFourteen.length; i++) {
    const value = ALPHABET.indexOf(firstFourteen[i]);
    if (value < 0) throw new Error(`'${firstFourteen[i]}' is not a GSTIN character`);
    // Weights alternate 1, 2, 1, 2 … starting at 1.
    const product = value * (i % 2 ? 2 : 1);
    total += Math.floor(product / ALPHABET.length) + (product % ALPHABET.length);
  }
  return ALPHABET[(ALPHABET.length - (total % ALPHABET.length)) % ALPHABET.length];
}

/**
 * What is wrong with this GSTIN, or null if nothing is. A sentence for a CA,
 * not a code — it is shown beside the field they are typing into, and "invalid
 * GSTIN" does not tell them which character to look at.
 */
export function gstinProblem(gstin: string | null | undefined): string | null {
  if (gstin === null || gstin === undefined) return null;
  const g = gstin.trim().toUpperCase();
  if (g === "") return null;              // blank is "unregistered", not "wrong"

  if (g.length !== GSTIN_LENGTH) {
    return `A GSTIN is ${GSTIN_LENGTH} characters; this one is ${g.length}.`;
  }
  if (!GSTIN_SHAPE.test(g)) {
    return "Not a GSTIN pattern. It is a 2-digit state code, then a 10-character "
      + "PAN, then the entity number, then Z, then the check digit — "
      + "e.g. 27AAPFU0939F1ZV.";
  }
  if (!VALID_STATE_CODES.has(g.slice(0, 2))) {
    return `${g.slice(0, 2)} is not a GST state code. They run 01 to 38, plus 97 `
      + "(Other Territory) and 99 (Centre Jurisdiction).";
  }
  const expected = checksumChar(g.slice(0, 14));
  if (g[14] !== expected) {
    return `The check digit does not match: this GSTIN ends in ${g[14]}, and the `
      + `first 14 characters compute to ${expected}. Usually two characters have `
      + "been swapped — check the PAN.";
  }
  return null;
}

/** Well-formed AND the check digit agrees. Blank is valid: not registered is
 *  different from wrongly registered. */
export function isValidGstin(gstin: string | null | undefined): boolean {
  return gstinProblem(gstin) === null;
}

/** The two-digit state code, which decides place of supply and therefore
 *  whether a supply is inter-State (IGST Act §7) or intra-State (§8). */
export function gstinStateCode(gstin: string): string | null {
  const g = (gstin || "").trim().toUpperCase();
  return g && isValidGstin(g) ? g.slice(0, 2) : null;
}

/** The PAN embedded in a GSTIN — characters 3 to 12. */
export function gstinPan(gstin: string): string | null {
  const g = (gstin || "").trim().toUpperCase();
  return g && isValidGstin(g) ? g.slice(2, 12) : null;
}
