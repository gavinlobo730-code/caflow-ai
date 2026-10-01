/**
 * A billing rate as typed, and the three things it can be (practice_management-11).
 *
 * WHY THIS IS NOT JUST `paiseFromRupeeInput`. That parser reads a BLANK field as
 * 0 — right for every amount column in this app, where an empty box means
 * "nothing here" — and a billing rate is the one place that is the wrong answer
 * in the direction a Partner pays for: a blank rate box would store ₹0 an hour,
 * which is a stated decision ("these hours bill at nothing") and takes the time
 * OFF the "no rate" list, where somebody was going to give it a price. So blank
 * is its own answer here, `clear`, and a typed `0` is a rate.
 *
 * The digits are still read by the one parser (`lib/money/rupeeInput.ts`), so
 * "1,25,000" is refused rather than read as ₹1, and "1e3" is not an amount.
 * Negative is refused here as well as by the server: a CHECK and a 422 are
 * where it is enforced, and this is where the person is told why.
 */
import { paiseFromRupeeInput } from "../money/rupeeInput.ts";

export type RateInput =
  | { kind: "clear" }
  | { kind: "rate"; paise: number }
  | { kind: "invalid"; message: string };

export const RATE_INPUT_HINT =
  "A rate is an amount in rupees per hour, e.g. 2500 or 2500.50 — without commas. " +
  "Leave it empty for none; 0 means these hours bill at nothing.";

export function readRateInput(raw: string): RateInput {
  if (raw.trim() === "") return { kind: "clear" };
  const paise = paiseFromRupeeInput(raw);
  if (paise === null || paise < 0) return { kind: "invalid", message: RATE_INPUT_HINT };
  return { kind: "rate", paise };
}
