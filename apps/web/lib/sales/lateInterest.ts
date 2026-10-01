/**
 * The keystroke half of the interest-terms form (accounting-22).
 *
 * THIS DECIDES NOTHING. Whether a customer owes interest, for how many days and
 * how much is `domain/sales/late_interest.py`, served through the preview. All
 * that lives here is turning what a CA TYPED into the two integers the terms
 * endpoint takes, and turning the stored annual rate back into what a rate box
 * shows. The bounds (a rate above 100% a year is a unit slip, grace is at most a
 * year) are the server's and arrive as its own sentence on a 422.
 *
 * A BLANK RATE IS NOT ZERO. Blank means "no rate on record" and is sent as
 * `null`; a typed 0 means "interest is waived for this customer". The two read
 * differently on the screen and in the preview, so nothing here defaults one to
 * the other.
 */
import { bpsFromPercentInput } from "../money/rupeeInput.ts";

export const BASIS_CHOICES = [
  { value: "due_date", label: "From the due date" },
  { value: "invoice_date", label: "From the invoice date" },
] as const;

export interface TermsText {
  rate: string;
  grace: string;
  basis: string;
}

export type TermsPayload =
  | { ok: true; rate_bps: number | null; grace_days: number; basis: string }
  | { ok: false; error: string };

/** What a rate box shows for a stored annual rate: 1800 -> "18", 1850 -> "18.5",
 *  75 -> "0.75", none -> "". Integer arithmetic only, so it round-trips with
 *  `bpsFromPercentInput` exactly. */
export function ratePercentText(bps: number | null | undefined): string {
  if (bps === null || bps === undefined || !Number.isFinite(bps)) return "";
  const n = Math.trunc(bps);
  const whole = Math.floor(Math.abs(n) / 100);
  const frac = String(Math.abs(n) % 100).padStart(2, "0").replace(/0+$/, "");
  return `${n < 0 ? "-" : ""}${whole}${frac ? `.${frac}` : ""}`;
}

/** What was typed, as the body the terms endpoint takes — or the sentence for
 *  the CA when a box does not hold a number. */
export function termsPayload(t: TermsText): TermsPayload {
  const rawRate = t.rate.trim().replace(/%$/, "").trim();
  let rate_bps: number | null = null;
  if (rawRate !== "") {
    const parsed = bpsFromPercentInput(rawRate);
    if (parsed === null) {
      return { ok: false, error: "The interest rate is not a percentage. Type it like 18 or 18.5." };
    }
    rate_bps = parsed;
  }
  const rawGrace = t.grace.trim();
  if (rawGrace !== "" && !/^\d{1,4}$/.test(rawGrace)) {
    return { ok: false, error: "Grace days is a whole number of days, like 0 or 7." };
  }
  const grace_days = rawGrace === "" ? 0 : Number.parseInt(rawGrace, 10);
  return { ok: true, rate_bps, grace_days, basis: t.basis };
}
