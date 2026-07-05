/**
 * Pure ISO (YYYY-MM-DD) calendar-date arithmetic for the sales invoice form's
 * payment-terms auto-fill (invoice date + credit days -> due date, and the
 * reverse gap when a due date is edited directly).
 *
 * toLocalISO and diffDaysISO delegate to the platform-wide helpers in
 * lib/dateMath.ts (Phase 3 consolidation — this module used to duplicate them
 * verbatim; verified byte-for-byte identical, including leap-year/month/year
 * boundary and malformed-input behavior, before merging). addDaysISO has no
 * canonical counterpart there and stays here.
 *
 * Dates are parsed AND formatted in LOCAL time throughout — never round-tripped
 * through UTC via Date#toISOString — so the calendar date arithmetic operates
 * on is exactly the calendar date the CA typed into the invoice date field,
 * regardless of the browser's timezone offset. This matters for every India-
 * based user: IST is UTC+5:30, so local midnight is always 18:30 UTC on the
 * PREVIOUS calendar day, and toISOString().slice(0, 10) would silently shift
 * every computed due date back by one day.
 */
import { toLocalISO, daysBetweenLocalISO } from "../dateMath.ts";

/** Add N calendar days to an ISO (YYYY-MM-DD) date; "" on bad input (including
 * a non-finite `days` or a shift landing outside the Date-representable range —
 * both would otherwise silently format as the literal string "NaN-NaN-NaN"). */
export function addDaysISO(dateStr: string, days: number): string {
  if (!dateStr || !Number.isFinite(days)) return "";
  const d = new Date(dateStr + "T00:00:00");
  if (Number.isNaN(d.getTime())) return "";
  d.setDate(d.getDate() + days);
  if (Number.isNaN(d.getTime())) return "";
  return toLocalISO(d);
}

/** Whole-day difference toStr − fromStr; null on bad input. */
export const diffDaysISO = daysBetweenLocalISO;
