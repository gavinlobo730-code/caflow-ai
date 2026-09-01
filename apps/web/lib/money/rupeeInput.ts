/**
 * Rupees typed into a form field → integer paise, without floating point.
 *
 * WHY NOT `Math.round(parseFloat(s) * 100)`
 *     That is what the journal entry form did, and it is the one arithmetic
 *     style CLAUDE.md forbids for money. It is *usually* right, which is worse
 *     than being wrong: parseFloat("12.345") * 100 is 1234.4999999999998, so
 *     Math.round silently drops the half paise and the CA is never told. It
 *     also quietly accepts things that are not amounts at all — "1e3" parses
 *     as 1000, "12abc" as 12, "Infinity" as Infinity.
 *
 *     Concatenating the digits instead is exact by construction: "12" and "34"
 *     become the string "1234", and Number() on an integer string is exact to
 *     2^53. No multiplication by 100 ever happens, so there is nothing to round.
 *
 * WHY IT RETURNS null RATHER THAN 0
 *     A field that cannot be parsed is a question for the CA, not a zero to
 *     post. Returning null lets the editor refuse to save and say which line is
 *     wrong; silently coercing to 0 would let an unbalanced entry look balanced.
 *
 * This deliberately does not touch lib/money/gstLine.ts's ratePaiseFromRupees.
 * That one converts a GST RATE and is pinned by a parity fixture against the
 * backend's own rounding; changing it is a separate question from how a plain
 * amount field is read.
 */

/** Optional sign, digits, optional decimal point and up to two more digits. */
const AMOUNT = /^(-?)(\d*)(?:\.(\d{0,2}))?$/;

/**
 * Parse a rupee amount as typed. Returns integer paise, or null if the text is
 * not an amount. Blank is 0 — an empty field means "nothing here", which is
 * how every amount column in this app already reads.
 */
export function paiseFromRupeeInput(raw: string): number | null {
  const s = raw.trim();
  if (s === "") return 0;

  const m = AMOUNT.exec(s);
  if (!m) return null;

  const [, sign, whole, frac = ""] = m;
  // "." and "-" on their own match the shape but carry no digits.
  if (whole === "" && frac === "") return null;

  // The exact step: build the paise digit string, never multiply by 100.
  const digits = (whole || "0") + (frac + "00").slice(0, 2);
  const paise = Number(digits);
  if (!Number.isSafeInteger(paise)) return null;

  return sign === "-" ? -paise : paise;
}

/**
 * Integer paise → the string an amount field shows. Integer arithmetic only,
 * so it round-trips with paiseFromRupeeInput exactly.
 */
export function rupeeInputFromPaise(paise: number): string {
  if (!Number.isFinite(paise)) return "";
  const n = Math.trunc(paise);
  const sign = n < 0 ? "-" : "";
  const abs = Math.abs(n);
  return `${sign}${Math.floor(abs / 100)}.${String(abs % 100).padStart(2, "0")}`;
}

/**
 * A percentage as typed → basis points, exactly. 18 → 1800, 0.75 → 75.
 *
 * The same digit concatenation as paiseFromRupeeInput and for the same reason:
 * `Math.round(parseFloat(s) * 100)` reads "1,0" as 1 and produces 100 bps where
 * the CA meant 1000, and reads a blank field as NaN. A rate is not money, but a
 * TDS rate typed wrong is money by the time it reaches the challan.
 *
 * Deliberately NOT used for the GST rate on an invoice line: that comes from a
 * fixed slab list rather than a text field, and gstLine.gstRateBpsFromPercent
 * is pinned to the backend's own rounding by shared/gst-parity-vectors.json.
 */
export function bpsFromPercentInput(raw: string): number | null {
  return paiseFromRupeeInput(raw);
}

/** Up to three decimal places, matching NUMERIC(10,3) on the line tables. */
const QUANTITY = /^(-?)(\d*)(?:\.(\d{0,3}))?$/;

/**
 * A quantity as typed → the number an invoice line payload carries, or null if
 * the text is not a quantity.
 *
 * Unlike an amount this stays a JS number, because that is what the payload and
 * the NUMERIC(10,3) column take. What it adds over `parseFloat(x) || 0` is the
 * REFUSAL: parseFloat("1,000") is 1, parseFloat("12abc") is 12, and a blank
 * field is NaN — each of which silently becomes a line quantity nobody typed.
 * Blank is null rather than 0 here: a line with no quantity is a question for
 * the CA, and defaulting it to 1 is what the call sites used to do.
 *
 * NOT the same function as gstLine.quantityFromInput, and deliberately named
 * differently so the two cannot be confused. That one COERCES to 0 and is
 * pinned to the backend by shared/gst-parity-vectors.json; it is the payload
 * builder. This one REFUSES, and belongs at the form, before a string the
 * payload builder would silently coerce ever reaches it.
 */
export function parseQuantity(raw: string): number | null {
  const s = raw.trim();
  if (s === "") return null;

  const m = QUANTITY.exec(s);
  if (!m) return null;
  const [, sign, whole, frac = ""] = m;
  if (whole === "" && frac === "") return null;

  const n = Number(`${sign}${whole || "0"}.${frac || "0"}`);
  return Number.isFinite(n) ? n : null;
}
