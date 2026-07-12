/**
 * Shared period-picker presets and date-range math for transaction list
 * pages (Sales Invoices, Purchase Bills, Bank, ...) — one canonical
 * implementation instead of each page hand-rolling its own FY math.
 */

export type PeriodMode =
  | "today"
  | "yesterday"
  | "this_week"
  | "last_3_months"
  | "this_fy"
  | "last_fy"
  | "custom";

export interface DateRange {
  start: string; // YYYY-MM-DD
  end: string;   // YYYY-MM-DD
}

function toIso(d: Date): string {
  return d.toISOString().split("T")[0];
}

function addDays(d: Date, n: number): Date {
  const copy = new Date(d);
  copy.setDate(copy.getDate() + n);
  return copy;
}

/** FY range (April 1 – March 31) for a "YYYY-YY" financial year string — IT Act §3. */
export function fyRangeFor(fy: string): DateRange {
  const [y] = fy.split("-");
  const yr = parseInt(y, 10);
  return { start: `${yr}-04-01`, end: `${yr + 1}-03-31` };
}

/** Shift a "YYYY-YY" financial year string by `delta` years, e.g. ("2026-27", -1) → "2025-26". */
export function shiftFY(fy: string, delta: number): string {
  const [y] = fy.split("-");
  const yr = parseInt(y, 10) + delta;
  return `${yr}-${String(yr + 1).slice(-2)}`;
}

export const PERIOD_OPTIONS: { value: PeriodMode; label: string }[] = [
  { value: "today", label: "Today" },
  { value: "yesterday", label: "Yesterday" },
  { value: "this_week", label: "This Week" },
  { value: "last_3_months", label: "Last 3 Months" },
  { value: "this_fy", label: "This Financial Year" },
  { value: "last_fy", label: "Last Financial Year" },
  { value: "custom", label: "Custom Range" },
];

/** Dropdown option label, with the FY resolved into "This Financial Year (FY 2026-27)" etc. */
export function periodOptionLabel(mode: PeriodMode, financialYear: string): string {
  if (mode === "this_fy") return `This Financial Year (FY ${financialYear})`;
  if (mode === "last_fy") return `Last Financial Year (FY ${shiftFY(financialYear, -1)})`;
  return PERIOD_OPTIONS.find((o) => o.value === mode)?.label ?? mode;
}

/**
 * Resolve a period mode to a concrete [start, end] date range.
 * `todayIso` is injectable for tests; defaults to the real current date.
 */
export function resolvePeriodRange(
  mode: PeriodMode,
  financialYear: string,
  custom: { from: string; to: string },
  todayIso: string = toIso(new Date()),
): DateRange {
  const today = new Date(`${todayIso}T00:00:00`);
  switch (mode) {
    case "today":
      return { start: todayIso, end: todayIso };
    case "yesterday": {
      const y = toIso(addDays(today, -1));
      return { start: y, end: y };
    }
    case "this_week": {
      // Monday–Sunday of the current week.
      const dow = today.getDay(); // 0 = Sunday
      const mondayOffset = dow === 0 ? -6 : 1 - dow;
      const monday = addDays(today, mondayOffset);
      const sunday = addDays(monday, 6);
      return { start: toIso(monday), end: toIso(sunday) };
    }
    case "last_3_months": {
      const start = new Date(today.getFullYear(), today.getMonth() - 2, 1);
      return { start: toIso(start), end: todayIso };
    }
    case "last_fy":
      return fyRangeFor(shiftFY(financialYear, -1));
    case "custom":
      return { start: custom.from || "1900-01-01", end: custom.to || "2999-12-31" };
    case "this_fy":
    default:
      return fyRangeFor(financialYear);
  }
}
