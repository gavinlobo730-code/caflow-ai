/**
 * QuickBooks-style payment terms for customers and sales invoices.
 *
 * Terms are a thin, presentational layer over an integer number of credit days —
 * the canonical value already stored on the customer (default) and snapshotted
 * onto each invoice. A preset like "Net 30" simply means 30 credit days; "Due on
 * Receipt" means 0. Anything that is not a preset is "Custom".
 *
 * Because the label is a pure function of the stored credit_days, persisting
 * credit_days + due_date on an invoice already persists its terms — no schema
 * change, and historical invoices never shift when a customer's default changes
 * later (the invoice keeps its own snapshot).
 */

export interface PaymentTermPreset {
  label: string;
  days: number;
}

/** Presets offered in the Payment Terms dropdowns (order = display order). */
export const PAYMENT_TERM_PRESETS: PaymentTermPreset[] = [
  { label: "Due on Receipt", days: 0 },
  { label: "Net 15", days: 15 },
  { label: "Net 30", days: 30 },
  { label: "Net 45", days: 45 },
  { label: "Net 60", days: 60 },
];

export const CUSTOM_TERM = "Custom";

/** Map a credit-days count to its term label ("Custom" when no preset matches). */
export function termLabelForDays(days: number | null | undefined): string {
  if (days == null || !Number.isFinite(days)) return CUSTOM_TERM;
  const preset = PAYMENT_TERM_PRESETS.find((t) => t.days === days);
  return preset ? preset.label : CUSTOM_TERM;
}

/** Map a term label to its day count; null for "Custom" (caller keeps its own days). */
export function daysForTermLabel(label: string): number | null {
  const preset = PAYMENT_TERM_PRESETS.find((t) => t.label === label);
  return preset ? preset.days : null;
}

/** True when the given day count is not one of the presets. */
export function isCustomDays(days: number | null | undefined): boolean {
  return termLabelForDays(days) === CUSTOM_TERM;
}
