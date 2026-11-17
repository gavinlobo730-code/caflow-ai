/**
 * A foreign document's INR total, converted the way the save converts it (POST-A-266, part 3).
 *
 * THIS WAS AN ESTIMATE AND IS NOW THE SERVER'S RULE. The sales invoice and the purchase bill used to multiply the
 * foreign grand total by `parseFloat(rate)` once, in binary floating point, and label the answer "≈". The save does
 * something else: `routers/sales_invoices.py` and `routers/purchase_bills.py` convert EACH tax head (taxable value,
 * CGST, SGST, IGST, cess) with `domain/currency/conversion.to_base_minor`, exact `Decimal` arithmetic rounded HALF_UP
 * to the paisa, and define the INR total as the SUM of the converted heads, so the ledger balances with no FX rounding
 * account. One conversion of the total and five conversions summed can differ by a paisa or two. This module is that
 * rule, in exact integer arithmetic on the rate AS TYPED (the API reads the typed string into a `Decimal`), and
 * `shared/fx-conversion-vectors.json` pins it to the Python function from both suites.
 *
 * What it still cannot know is whether the server will accept the rate or the lines; the screen keeps its sentence
 * that the server confirms on save, and shows nothing for a rate that is not a plain positive decimal or a currency
 * whose minor unit the currency master has not given.
 */
import { pow10 } from "../money/decimalMath.ts";

const B0 = BigInt(0);
const B2 = BigInt(2);

/** A rate typed as a plain positive decimal ("83.25"), as exact (unscaled, scale); anything else is null. */
export function rateParts(text: string): { unscaled: bigint; scale: number } | null {
  const t = text.trim();
  if (!/^\d+(\.\d+)?$/.test(t)) return null;
  const [whole, frac = ""] = t.split(".");
  const unscaled = BigInt(whole + frac);
  if (unscaled <= B0) return null;
  return { unscaled, scale: frac.length };
}

/**
 * `to_base_minor(txn_minor, Decimal(rate), txn_minor_unit)`: round_half_up(txn x rate x 10^(base - txn_unit)).
 * HALF_UP is Python's: a half rounds AWAY from zero, for a negative amount too. Null when the rate is not readable or
 * a unit is not a whole number from 0 to 6.
 */
export function toBaseMinor(txnMinor: number, rateText: string, txnMinorUnit: number, baseMinorUnit = 2): number | null {
  const rate = rateParts(rateText);
  if (!rate || !Number.isSafeInteger(txnMinor)) return null;
  for (const u of [txnMinorUnit, baseMinorUnit]) if (!Number.isInteger(u) || u < 0 || u > 6) return null;
  const shift = baseMinorUnit - txnMinorUnit;
  const negative = txnMinor < 0;
  const num = BigInt(Math.abs(txnMinor)) * rate.unscaled * pow10(Math.max(0, shift));
  const den = pow10(rate.scale + Math.max(0, -shift));
  const rounded = (B2 * num + den) / (B2 * den);   // floor((num + den/2) / den), exact for non-negative num
  const out = Number(rounded);
  return negative && out !== 0 ? -out : out;
}

/** The INR total of a foreign document: each head converted on its own and the results added, as the save does. */
export function baseTotalOfHeads(headsMinor: readonly number[], rateText: string, txnMinorUnit: number | undefined): number | null {
  if (txnMinorUnit === undefined) return null;
  let total = 0;
  for (const h of headsMinor) {
    const b = toBaseMinor(h, rateText, txnMinorUnit);
    if (b === null) return null;
    total += b;
  }
  return total;
}
