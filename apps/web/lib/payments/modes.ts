/**
 * The payment modes a form offers, in one place.
 *
 * There were two identical copies — `app/clients/[id]/sales/page.tsx` and
 * `lib/imports/mappers.ts`, the second of which REFUSES an import row whose
 * mode is not in its list. So the receipt form and the importer had to agree
 * by coincidence, and the fixed-asset drawer (FA-07) was about to be a third
 * copy that agreed by coincidence with both.
 *
 * WHAT THIS IS NOT
 *     Not a statutory vocabulary and not a backend contract. `apps/api` does
 *     not constrain `payment_mode` to any list; the only thing it asks of the
 *     value is whether it means physical cash
 *     (`domain/accounting/payment_account.CASH_PAYMENT_MODES` — "cash",
 *     "petty_cash"), which decides whether the leg posts to Cash in Hand or to
 *     a bank ledger. So this list is a UI convenience, and "cash" earning its
 *     place in it is the one entry that changes where money is booked.
 */
export const PAYMENT_MODES = ["bank", "cash", "cheque", "upi", "neft", "rtgs"] as const;

export type PaymentMode = (typeof PAYMENT_MODES)[number];

/** Whether this mode means physical cash — mirrors CASH_PAYMENT_MODES. */
export function isCashMode(mode: string | null | undefined): boolean {
  const m = (mode ?? "").trim().toLowerCase().replace(/[\s_-]+/g, "_");
  return m === "cash" || m === "petty_cash";
}
