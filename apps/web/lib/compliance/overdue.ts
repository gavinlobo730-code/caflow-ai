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
import { todayLocalISO } from "../dateMath.ts";

/** Workflow states that owe nothing, however far past the due date. */
export const SETTLED_FILING_STATUSES: ReadonlySet<string> = new Set(["filed", "na"]);

export function isOverdue(
  entry: { due_date?: string | null; filing_status: string },
  todayISO: string = todayLocalISO(),
): boolean {
  if (SETTLED_FILING_STATUSES.has(entry.filing_status)) return false;
  if (entry.filing_status === "overdue") return true;
  // A missing due date cannot be late; `"" < today` would say it is.
  const due = (entry.due_date ?? "").slice(0, 10);
  return due !== "" && due < todayISO;
}

/**
 * Whether an obligation is OPEN AND NOT YET LATE: not settled, not moved to "overdue" by hand, and due today or later. The complement of
 * `isOverdue` among the open ones, so a screen that lists "overdue" and "upcoming" side by side puts each obligation in exactly one list
 * (an obligation somebody moved to "overdue" with a date ahead used to be in both, because the upcoming test asked the date alone).
 */
export function isUpcoming(
  entry: { due_date?: string | null; filing_status: string },
  todayISO: string = todayLocalISO(),
): boolean {
  if (SETTLED_FILING_STATUSES.has(entry.filing_status) || isOverdue(entry, todayISO)) return false;
  const due = (entry.due_date ?? "").slice(0, 10);
  return due !== "" && due >= todayISO;
}

/** What the GST and MCA filing trackers print against a filing. */
export type FilingTrackerStatus = "Pending" | "Filed" | "Overdue" | "Not applicable";

/**
 * The word a filing tracker prints, from the ONE rule (POST-A-280). Those two screens used to work it out themselves from the due date and the
 * filed date alone (`computeOverdueStatus`), which is the rule only when nobody has recorded anything else: an obligation recorded as NOT
 * APPLICABLE with a past date read Overdue there, and one moved to Overdue by hand with a date ahead read Pending. A filed date or the filed
 * word is a filing, whatever else is stored; "na" owes nothing and says so rather than reading Pending; every other word is `isOverdue`'s.
 * `filing_status` is the compliance vocabulary (pending, in_progress, filed, overdue, na); a table that spells it otherwise maps first.
 */
export function filingTrackerStatus(
  entry: { due_date?: string | null; filing_status?: string | null; filed_date?: string | null },
  todayISO: string = todayLocalISO(),
): FilingTrackerStatus {
  const word = entry.filing_status ?? "";
  if (word === "filed" || (entry.filed_date ?? "") !== "") return "Filed";
  if (word === "na") return "Not applicable";
  return isOverdue({ due_date: entry.due_date, filing_status: word || "pending" }, todayISO) ? "Overdue" : "Pending";
}

/**
 * The compliance calendar's word for a stored `mca_filings.status` (written as not_started | in_progress | filed | overdue; migration 038's
 * CHECK also names not_applicable and pending). Anything that is not one of the words with a meaning of its own is "pending", the open state.
 * Read from the STORED word, in any case, before a page overwrites the row's status with the word it prints.
 */
export function calendarWordForMcaStatus(stored: string | null | undefined): string {
  const word = String(stored ?? "").toLowerCase();
  if (word === "filed") return "filed";
  if (word === "overdue") return "overdue";
  if (word === "not_applicable" || word === "na") return "na";
  return "pending";
}
