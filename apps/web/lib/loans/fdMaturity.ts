/**
 * What a fixed-deposit row stores as its maturity amount, and whether that is an estimate.
 *
 * THE RECEIPT IS THE DOCUMENT OF RECORD. A bank states the maturity amount on the deposit receipt, and it depends on how that
 * bank compounds (usually quarterly for a cumulative deposit, not at all for a payout one). The register used to compute the
 * figure here as annual compounding and store it as though it were the bank's; it now stores either the amount a CA typed from
 * the receipt (`isEstimate` false) or this estimate, flagged (`isEstimate` true), and every screen that shows the figure says
 * which. The estimate stays a browser calculation, labelled as one, in the way `lib/services/currencyPreview` is; moving it to
 * the server is the remaining part of POST-A-266 (which replaced POST-A-134 after its triage).
 */
import { paiseFromRupeeInput } from "../money/rupeeInput.ts";
import { daysBetweenLocalISO } from "../dateMath.ts";

/** P x (1 + r/100)^(days/365), annual compounding, in whole paise. A missing or reversed date range is the principal. */
export function estimateFDMaturityPaise(
  principalPaise: number,
  annualRatePercent: number,
  startDate: string,
  maturityDate: string,
): number {
  if (!startDate || !maturityDate) return principalPaise;
  const days = daysBetweenLocalISO(startDate, maturityDate) ?? 0;
  if (days <= 0) return principalPaise;
  const factor = Math.pow(1 + annualRatePercent / 100, days / 365);
  return Math.round(principalPaise * factor);
}

export type MaturityChoice =
  | { ok: true; paise: number; isEstimate: boolean }
  | { ok: false; error: string };

/**
 * The amount to store. Blank receipt box -> the estimate, flagged. A typed amount -> that amount, not flagged, provided it
 * is an amount and is not below the principal (a deposit that returns less than was placed was closed early or is a mistake,
 * and is not a maturity amount).
 */
export function chooseMaturity(receiptText: string, principalPaise: number, estimatePaise: number): MaturityChoice {
  const typed = receiptText.replace(/[,\s₹]/g, "");
  if (typed === "") return { ok: true, paise: estimatePaise, isEstimate: true };
  const paise = paiseFromRupeeInput(typed);
  if (paise === null || paise <= 0) {
    return { ok: false, error: "The maturity amount on the receipt must be an amount in rupees, e.g. 107186.50." };
  }
  if (paise < principalPaise) {
    return {
      ok: false,
      error: "The maturity amount is below the principal. If the deposit was closed early, leave this box blank and mark it broken.",
    };
  }
  return { ok: true, paise, isEstimate: false };
}

/** A stored row whose flag is absent (a read from an API or database that predates it) is an estimate, never a receipt figure. */
export function isEstimate(row: { maturity_amount_is_estimate?: boolean | null }): boolean {
  return row.maturity_amount_is_estimate !== false;
}
