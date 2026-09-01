/**
 * Reading a document line's quantity and rate as they were typed.
 *
 * WHAT THIS REPLACES, AND WHY IT MATTERED
 *     Every line editor in the app gated on
 *
 *         (parseFloat(l.qty) || 0) > 0 && (parseFloat(l.rate) || 0) > 0
 *
 *     and then built its payload with `Math.round(parseFloat(l.rate) * 100)`.
 *     A rate typed the way Indian amounts are grouped passes that gate and
 *     passes it QUIETLY: parseFloat("1,25,000") is 1, so a ₹1,25,000 line was
 *     accepted as a valid ₹1 line, previewed at ₹1, and saved at ₹1. Nothing
 *     anywhere said so.
 *
 *     parseFloat also reads "12abc" as 12 and "1e3" as 1000, and a blank field
 *     as NaN — which `|| 0` then turned into a silent zero.
 *
 * WHAT IT DOES NOT DO
 *     It is not a second implementation of the line arithmetic. The taxable
 *     amount and the GST split stay in lib/money/gstLine.ts, which is pinned to
 *     the Python backend by shared/gst-parity-vectors.json. This only decides
 *     whether the two STRINGS are numbers at all, and hands over the values the
 *     rest of the pipeline then uses — so a string the parity-pinned builders
 *     would coerce never reaches them.
 */
import { paiseFromRupeeInput, parseQuantity } from "./rupeeInput.ts";

export interface ParsedLineAmounts {
  /** As the payload and the NUMERIC(10,3) column carry it. */
  quantity: number;
  /** Integer paise. */
  ratePaise: number;
}

/**
 * The line's quantity and rate, or null if either is not a positive number.
 *
 * Null is the answer for a blank line too. Callers filter those out before
 * asking — a half-typed row is not an error, it is a row the CA has not
 * finished — and the editors keep doing exactly that.
 */
export function parseLineAmounts(qty: string, rate: string): ParsedLineAmounts | null {
  const quantity = parseQuantity(qty ?? "");
  const ratePaise = paiseFromRupeeInput(rate ?? "");
  if (quantity === null || ratePaise === null) return null;
  if (quantity <= 0 || ratePaise <= 0) return null;
  return { quantity, ratePaise };
}

/**
 * Whether a line's quantity and rate are BOTH present and BOTH unreadable-free.
 * Distinguishes "not filled in yet" from "filled in wrongly", which is what
 * lets an editor stay quiet about an empty row and refuse a mistyped one.
 */
export function lineAmountsTyped(qty: string, rate: string): boolean {
  return (qty ?? "").trim() !== "" || (rate ?? "").trim() !== "";
}
