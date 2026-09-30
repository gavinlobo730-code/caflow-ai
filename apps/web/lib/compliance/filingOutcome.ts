/**
 * What to tell the CA after they mark an obligation filed — composed from what
 * the SERVER answered, deciding nothing.
 *
 * The obligation path (`POST /api/compliance/obligations/{id}/mark-filed`)
 * answers whether the filing was RECORDED — which is the same thing as whether
 * the period is now locked against new entries — and, where it was not, why not
 * per obligation type. Mark Filed on /deadlines and on a client's Compliance tab
 * used to discard that answer (the data layer returned void), so a GSTR-3B tick
 * that closed nothing looked identical to one that closed the month.
 *
 * Three cases, told apart by what the server said and not by the obligation's
 * name — the browser holds no list of which returns close a period, the
 * Schedule III caption lesson:
 *   * `filing_recorded === true`  → the period is locked, say from when to when;
 *   * `filing_recorded === false` → nothing was locked, say the server's reason;
 *   * the key is ABSENT           → a backend one deploy behind, which answers
 *     nothing about a lock. That is NOT rendered as "nothing was locked": it
 *     says it could not confirm, because an unknown is never shown as a value.
 */
import type { ObligationFilingResult } from "../api/index.ts";
import { formatRangeLabel } from "../dates/periods.ts";

export interface FilingOutcome {
  title: string;
  description: string;
  /** True only where the server said the period is now closed. */
  locked: boolean;
}

export function describeFilingOutcome(
  result: ObligationFilingResult | null | undefined,
  what: string,
): FilingOutcome {
  const recorded = result?.filing_recorded;
  if (recorded === true) {
    const from = result?.period_locked_from;
    const to = result?.period_locked_to;
    const window = from && to ? ` for ${formatRangeLabel(from, to)}` : "";
    return {
      title: `${what} marked filed — period locked`,
      description: `New entries${window} are now blocked, because a return covering it is on record as filed.`,
      locked: true,
    };
  }
  if (recorded === false) {
    return {
      title: `${what} marked filed`,
      description: result?.filing_not_recorded_reason
        ?? "No period was locked by this.",
      locked: false,
    };
  }
  return {
    title: `${what} marked filed`,
    description: "The server did not say whether a period was locked. Check the books before relying on it.",
    locked: false,
  };
}
