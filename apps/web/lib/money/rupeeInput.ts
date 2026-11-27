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
 * THE WHOLE-RUPEE PART, GROUPED THE WAY A PERSON TYPES IT (POST-A-567).
 *
 * Either the Indian way (1,25,000: groups of two, the last of three) or the Western way (1,250,000: groups of three), and nothing else.
 * Both name the same digits, so there is no reading in which the two disagree about the value; what is refused is a comma in a place
 * neither puts one (1,2,5 and 12,50 and ,500 and 1,,250), because a comma there is a typing mistake and not a grouping. A group that starts
 * with a zero (0,500 and 01,250) is refused for the same reason: nobody writes a grouped amount that way, and a leading zero there is far
 * likelier a slipped key than a rupee figure.
 */
const GROUPED_WHOLE = /^(?:[1-9]\d{0,2}(?:,\d{3})+|[1-9]\d?(?:,\d{2})*,\d{3})$/;

/**
 * The text as a plain decimal: the commas of a properly grouped whole part taken out, anything else as it was.
 *
 * Returns null only for a comma in a wrong place, or one in the decimals. Text with no comma is returned unchanged, so the readers below
 * judge it exactly as they always did. This is the ONE place that decides what a grouped amount is: a reader that took the commas out by
 * itself would accept 1,2,5 as 125.
 *
 * WHY THIS HAD TO BE ONE FUNCTION AND NOT ONE READER. `gstLine.ratePaiseFromRupees` and `quantityFromInput` still read a string with
 * `parseFloat`, which reads "1,25,000" as 1. They are pinned to the backend by shared/gst-parity-vectors.json and are handed the same text
 * a line editor's reader has already accepted, so a reader that accepted grouping while they did not would put the original defect back
 * (a line of ₹1,25,000 saved at ₹1). Both now take their text through here first.
 */
export function plainDecimalText(raw: string): string | null {
  const s = raw.trim();
  if (!s.includes(",")) return s;
  const m = /^(-?)([\d,]*)((?:\.\d*)?)$/.exec(s);
  if (!m) return null;
  const [, sign, whole, frac] = m;
  if (!GROUPED_WHOLE.test(whole)) return null;
  return `${sign}${whole.replace(/,/g, "")}${frac}`;
}

/**
 * A typed amount or quantity as a JS number, for the parity-pinned arithmetic that takes RUPEES and not paise: the text through the one
 * grouping reader, then parseFloat as before. A text with no comma is judged exactly as parseFloat judged it; properly grouped text is the
 * number it names; text with a comma in a wrong place is NaN (not what parseFloat reads up to the comma), so the callers that already treat
 * a non-number as nothing or as a refusal keep doing so. Use it wherever a screen turns a typed amount or quantity into a
 * number after a reader here has accepted the text; a bare parseFloat or Number on that text reads "1,25,000" as 1 or NaN (POST-A-567).
 */
export function typedNumber(raw: string): number {
  const s = plainDecimalText(raw);
  // A comma in a wrong place is NOT a number: NaN, never what parseFloat would read up to the first comma (1,2,5 as 1; 12,50 as 12).
  return s === null ? Number.NaN : parseFloat(s);
}

/** What an amount box may look like, in the words a refusal uses. One sentence, so every box that refuses an amount says the same thing. */
export const AMOUNT_MAY_LOOK_LIKE = "Type the amount in rupees, for example 1250, 1250.50 or 1,25,000, with commas only where they are usually written.";

/**
 * Parse a rupee amount as typed. Returns integer paise, or null if the text is
 * not an amount. Blank is 0 — an empty field means "nothing here", which is
 * how every amount column in this app already reads.
 */
export function paiseFromRupeeInput(raw: string): number | null {
  const typed = raw.trim();
  if (typed === "") return 0;
  const s = plainDecimalText(typed);
  if (s === null) return null;

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
 * Several rupee-input strings, summed into the rupee string an amount field
 * shows — or "" when the sum is nil, since blank is how this app already
 * reads a zero amount column.
 *
 * Anything that does not parse as an amount contributes nothing to the sum
 * rather than stopping it: this exists to keep a "Total" box in step with the
 * boxes that make it up WHILE they are still being typed into, and those
 * boxes are validated for real (refused, not coerced) at submit time by
 * paiseFromRupeeInput itself.
 */
export function sumRupeeInputs(values: readonly string[]): string {
  const totalPaise = values.reduce((sum, v) => {
    const paise = paiseFromRupeeInput(v || "0");
    return paise === null ? sum : sum + paise;
  }, 0);
  return totalPaise === 0 ? "" : rupeeInputFromPaise(totalPaise);
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
  // A percentage has no grouping: "1,0" there is a typing mistake or somebody's decimal comma, and "1,000" would be a thousand per cent.
  if (raw.includes(",")) return null;
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
  const typed = raw.trim();
  if (typed === "") return null;
  const s = plainDecimalText(typed);
  if (s === null) return null;

  const m = QUANTITY.exec(s);
  if (!m) return null;
  const [, sign, whole, frac = ""] = m;
  if (whole === "" && frac === "") return null;

  const n = Number(`${sign}${whole || "0"}.${frac || "0"}`);
  return Number.isFinite(n) ? n : null;
}
