/**
 * The wage months a salary challan may name (POST-A-267): the three months of the quarter it is recorded for, of its financial year.
 *
 * The server decides everything that matters: which sections are salary (it serves `salary` on each challan section), that the
 * month lies inside the challan's own quarter (it refuses one that does not, in words), and what the month closes on the compliance
 * calendar. This only lists the calendar months a quarter of an April-to-March year spans, so the choice offered is never one the
 * server would refuse. A label that is not a financial year or a quarter that is not Q1-Q4 offers nothing.
 */
import { formatMonthYear } from "../dates/format.ts";

const FIRST_MONTH: Record<string, number> = { Q1: 4, Q2: 7, Q3: 10, Q4: 1 };

export interface WageMonthChoice { value: string; label: string }

export function wageMonthsOfQuarter(financialYear: string, quarter: string): WageMonthChoice[] {
  const m = /^(\d{4})-\d{2,4}$/.exec(financialYear.trim());
  const first = FIRST_MONTH[quarter];
  if (!m || first === undefined) return [];
  const year = Number(m[1]) + (quarter === "Q4" ? 1 : 0);
  return [0, 1, 2].map((i) => {
    const value = `${year}-${String(first + i).padStart(2, "0")}`;
    return { value, label: formatMonthYear(value) };
  });
}
