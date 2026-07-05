/**
 * Shared, pure calendar-date helpers used wherever a "today" or a whole-day
 * difference is computed for a business decision (journal/receipt/invoice
 * dates, aging buckets, due-today checks).
 *
 * Dates are parsed AND formatted in LOCAL time throughout — never round-tripped
 * through UTC via Date#toISOString — so the calendar date arithmetic operates
 * on is exactly the calendar date the browser's clock reads, regardless of
 * timezone offset. This matters for every India-based user: IST is UTC+5:30,
 * so local midnight is always 18:30 UTC on the PREVIOUS calendar day, and
 * toISOString().slice(0, 10) would silently shift "today" back by one day
 * from local midnight until 05:30 local time.
 *
 * This module intentionally duplicates the (already-correct) formatting
 * primitive in lib/sales/dateMath.ts rather than importing it — that module
 * is scoped to the sales invoice form's payment-terms math, and consolidating
 * the two is a separate, deliberately out-of-scope cleanup.
 */

/** Format a Date using its LOCAL calendar components as YYYY-MM-DD (never via
 * toISOString, which converts through UTC and can shift the calendar day). */
export function toLocalISO(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/** The current LOCAL calendar date as YYYY-MM-DD — the safe replacement for
 * `new Date().toISOString().slice(0, 10)` / `.split("T")[0]`. */
export function todayLocalISO(): string {
  return toLocalISO(new Date());
}

/** Whole calendar days from `fromStr` to `toStr` (both YYYY-MM-DD), computed
 * entirely on local-midnight-anchored dates — never mix a date-only string
 * with a live `new Date()` instant (parsing a bare date string yields UTC
 * midnight, so diffing it against "now" produces a result that depends on
 * time-of-day, not just the calendar date). "" / malformed input -> null. */
export function daysBetweenLocalISO(fromStr: string, toStr: string): number | null {
  if (!fromStr || !toStr) return null;
  const a = new Date(fromStr + "T00:00:00");
  const b = new Date(toStr + "T00:00:00");
  if (Number.isNaN(a.getTime()) || Number.isNaN(b.getTime())) return null;
  return Math.round((b.getTime() - a.getTime()) / 86_400_000);
}
