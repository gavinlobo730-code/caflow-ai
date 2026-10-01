/**
 * How the worklist of invoices that need an IRN and have none is WORDED (GST-20).
 *
 * THIS DECIDES NOTHING. Whether an invoice owes an IRN, which of the five window
 * states it is in and how many days are left are `domain/gst/irn_worklist.py`'s
 * answers, carried on each row. What lives here is only the sentence for each
 * state, kept in one place so the panel and any later screen say the same thing —
 * and the one rule worth a test: THE FIVE STATES ARE NOT INTERCHANGEABLE.
 *
 *   * `no_reporting_limit` is an invoice that STILL OWES an IRN and has no clock.
 *     It must never read as "fine", and it must never be given a deadline.
 *   * `past_window` is not "overdue by n days" in the way a filing is: the IRP
 *     will refuse it, and what to do next is the CA's.
 *   * an `assumed` window (turnover unrecorded) says so, because a clock shown as
 *     if it bound, for a client nobody has measured, is a reading and not a fact.
 */
import type { IrnWorklistRow, IrnWorklistWindow } from "@/lib/api";

const plural = (n: number, one: string, many: string) => (n === 1 ? one : many);

/** One line for the "Window" column. Arithmetic is the server's `days_left`;
 *  nothing here counts a day. */
export function windowText(w: IrnWorklistWindow): string {
  const assumed = w.assumed ? " (assumed)" : "";
  switch (w.status) {
    case "within_window": {
      const n = w.days_left ?? 0;
      return `${n} ${plural(n, "day", "days")} left, until ${w.deadline}${assumed}`;
    }
    case "last_day":
      return `Last day to report to the IRP — ${w.deadline}${assumed}`;
    case "past_window": {
      const n = Math.abs(w.days_left ?? 0);
      return `${n} ${plural(n, "day", "days")} past the IRP's ${w.days}-day limit${assumed}`;
    }
    case "no_reporting_limit":
      return "No IRP reporting limit — an IRN is still owed";
    case "not_in_force":
      return "The IRP limit was not yet in force";
    default:
      return "";
  }
}

/** The state of the IRN record for this invoice, in words a CA acts on. */
export function irnStateText(state: IrnWorklistRow["irn_state"]): string {
  switch (state) {
    case "irn_cancelled": return "IRN cancelled";
    case "record_prepared_not_generated": return "Record prepared — no IRN recorded";
    case "none":
    default: return "No IRN recorded";
  }
}

/** True for the rows the CA can still do something about at the IRP. */
export function isActionable(w: IrnWorklistWindow): boolean {
  return w.status === "within_window" || w.status === "last_day"
    || w.status === "no_reporting_limit";
}

/** Tone for a window state: only a lapsed one is a problem, and only today's
 *  last day is attention. No limit is NOT shown as ready — it still owes. */
export function windowTone(w: IrnWorklistWindow): "problem" | "attention" | "neutral" {
  if (w.status === "past_window") return "problem";
  if (w.status === "last_day") return "attention";
  return "neutral";
}
