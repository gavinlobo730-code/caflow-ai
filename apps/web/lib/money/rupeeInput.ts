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
