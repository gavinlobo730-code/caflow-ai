/**
 * Whether a compliance obligation is OVERDUE — one predicate, for the tile
 * that counts them and the filter that lists them.
 *
 * WHY IT IS DERIVED AND NOT READ. `filing_status` is the stored WORKFLOW state
 * (lib/data/compliance.ts maps the backend's eight onto pending / in_progress /
 * filed / overdue / na), and "Overdue" there is a transition somebody makes by
 * hand — nothing in apps/api sets it when a due date passes. So /deadlines
 * offered Status = "overdue", compared the stored value, and listed nothing,
 * while the Overdue tile above it — which worked the date out — read 14.
 *
 * WHY THE STATUS FILTER WAS NOT REDEFINED INSTEAD. Rewriting the Status
 * column's value to "overdue" whenever the date has passed would take those
 * rows OUT of "pending" and "in_progress", and each of those has a tile of its
 * own counting the STORED status; the filter and its tile would then disagree
 * by exactly the overdue rows. Overdue is a second fact about a row, not a
 * status, so it is its own filter.
 *
 * THE RULE. Due strictly BEFORE today — an obligation due today is not late
 * until the day is out — and not settled: "filed" and "na" (not applicable)
 * owe nothing whatever the date. A row somebody has explicitly moved to
 * "overdue" is overdue, the same reading
 * domain/compliance_record_service._compute_risk_score gives the stored
 * status (`status == "Overdue" or days_until_due < 0`).
 *
 * "Today" is the CA's calendar date from lib/dateMath (never a UTC
 * `toISOString()` slice, which reads yesterday until 05:30 IST); callers that
 * test several rows pass it once so every row is judged against one day.
 */
import type { ComplianceEntry } from "../data/compliance.ts";
import { todayLocalISO } from "../dateMath.ts";

/** Workflow states that owe nothing, however far past the due date. */
export const SETTLED_FILING_STATUSES: ReadonlySet<string> = new Set(["filed", "na"]);

export function isOverdue(
  entry: Pick<ComplianceEntry, "due_date" | "filing_status">,
  todayISO: string = todayLocalISO(),
): boolean {
  if (SETTLED_FILING_STATUSES.has(entry.filing_status)) return false;
  if (entry.filing_status === "overdue") return true;
  // A missing due date cannot be late; `"" < today` would say it is.
  const due = (entry.due_date ?? "").slice(0, 10);
  return due !== "" && due < todayISO;
}
