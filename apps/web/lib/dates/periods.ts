/**
 * Shared period-picker presets and date-range math for transaction list
 * pages (Sales Invoices, Purchase Bills, Bank, ...) and the multi-period
 * comparison columns on P&L / Balance Sheet — one canonical implementation
 * instead of each page hand-rolling its own FY math.
 *
 * Dates are parsed and formatted using LOCAL calendar components throughout
 * — never round-tripped through UTC via Date#toISOString (see lib/dateMath.ts:
 * IST is UTC+5:30, so local midnight is 18:30 UTC on the PREVIOUS calendar
 * day, and toISOString().split("T")[0] silently shifts every date back one
 * day for any browser running in an ahead-of-UTC timezone — i.e. every
 * India-based user of this product).
 */
import { toLocalISO, todayLocalISO, currentFinancialYearLabel } from "../dateMath.ts";

export type PeriodMode =
  | "today"
  | "yesterday"
  | "this_week"
  | "last_3_months"
  | "this_fy"
  | "last_fy"
  | "all_time"
  | "custom";

export interface DateRange {
  start: string; // YYYY-MM-DD
  end: string;   // YYYY-MM-DD
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
  { value: "all_time", label: "All Time" },
  { value: "custom", label: "Custom Range" },
];

/**
 * How a chosen period reads in prose — a table heading, an empty-state line.
 *
 * A financial year is named outright ("FY 2025-26"), matching the dropdown
 * exactly. It used to render as "This Financial Year (FY 2025-26)", which was
 * relative to a year chosen elsewhere on the screen; a heading that says
 * "This" while the header above it says a different year is the disagreement
 * this whole change removes.
 */
export function periodOptionLabel(mode: PeriodMode, financialYear: string): string {
  if (mode === "this_fy") return `FY ${financialYear}`;
  if (mode === "last_fy") return `FY ${shiftFY(financialYear, -1)}`;
  return PERIOD_OPTIONS.find((o) => o.value === mode)?.label ?? mode;
}

// ── Choosing a financial year, on the page rather than above it ─────────────
//
// "This Financial Year" and "Last Financial Year" are relative labels, and
// they were relative to a financial year chosen in a DIFFERENT control — the
// selector that used to sit in the client header. That produced a screen
// showing "FY 2026-27" at the top and "Last Financial Year (FY 2025-26)" in
// the filter directly beneath it, both true, disagreeing, with nothing to say
// which one the rows below belonged to.
//
// The header selector is gone. A period is now chosen entirely within the
// control that scopes the query, and a financial year is named outright —
// "FY 2025-26", not "Last Financial Year" — so the label on the filter and
// the data in the table cannot drift apart.
//
// this_fy / last_fy stay in PeriodMode above rather than being deleted: a
// bookmarked ?period=last_fy, or any state persisted before this change, must
// still resolve to a real range instead of silently falling through to the
// default. Nothing OFFERS them any more.

/** How many financial years back the picker offers. */
export const FY_CHOICE_COUNT = 5;

/**
 * The financial years a picker offers, newest first, ending at the current
 * one. Not centred on "today plus one": a CA works on the year just closed
 * far more often than on one that has not started, and a future FY in the
 * list is a way to file an empty return by accident.
 */
export function financialYearChoices(
  count: number = FY_CHOICE_COUNT,
  today: Date = new Date(),
): string[] {
  const current = currentFinancialYearLabel(today);
  return Array.from({ length: count }, (_, i) => shiftFY(current, -i));
}

/**
 * A single dropdown value covering both halves of the selection.
 *
 * A financial year is TWO pieces of state — the mode and which year — and a
 * `<select>` carries one string. Encoding the year into the value keeps them
 * from being set independently, which is the bug class this whole change is
 * about: two controls, each individually correct, describing different periods.
 */
export function encodePeriodChoice(mode: PeriodMode, financialYear: string): string {
  if (mode === "this_fy") return `fy:${financialYear}`;
  if (mode === "last_fy") return `fy:${shiftFY(financialYear, -1)}`;
  return mode;
}

export function decodePeriodChoice(
  value: string,
  fallbackFY: string,
): { mode: PeriodMode; financialYear: string } {
  if (value.startsWith("fy:")) {
    return { mode: "this_fy", financialYear: value.slice(3) };
  }
  return { mode: value as PeriodMode, financialYear: fallbackFY };
}

/**
 * Every option a period dropdown shows, in order: the fixed relative windows,
 * then each financial year by name, then All Time and Custom Range.
 */
export function periodChoices(
  count: number = FY_CHOICE_COUNT,
  today: Date = new Date(),
): { value: string; label: string }[] {
  return [
    { value: "today", label: "Today" },
    { value: "yesterday", label: "Yesterday" },
    { value: "this_week", label: "This Week" },
    { value: "last_3_months", label: "Last 3 Months" },
    ...financialYearChoices(count, today).map((fy) => ({
      value: `fy:${fy}`,
      label: `FY ${fy}`,
    })),
    { value: "all_time", label: "All Time" },
    { value: "custom", label: "Custom Range" },
  ];
}

/**
 * Resolve a period mode to a concrete [start, end] date range.
 * `todayIso` is injectable for tests; defaults to the real current LOCAL date.
 */
export function resolvePeriodRange(
  mode: PeriodMode,
  financialYear: string,
  custom: { from: string; to: string },
  todayIso: string = todayLocalISO(),
): DateRange {
  const today = new Date(`${todayIso}T00:00:00`);
  switch (mode) {
    case "today":
      return { start: todayIso, end: todayIso };
    case "yesterday": {
      const y = toLocalISO(addDays(today, -1));
      return { start: y, end: y };
    }
    case "this_week": {
      // Monday–Sunday of the current week.
      const dow = today.getDay(); // 0 = Sunday
      const mondayOffset = dow === 0 ? -6 : 1 - dow;
      const monday = addDays(today, mondayOffset);
      const sunday = addDays(monday, 6);
      return { start: toLocalISO(monday), end: toLocalISO(sunday) };
    }
    case "last_3_months": {
      const start = new Date(today.getFullYear(), today.getMonth() - 2, 1);
      return { start: toLocalISO(start), end: todayIso };
    }
    case "last_fy":
      return fyRangeFor(shiftFY(financialYear, -1));
    case "all_time":
      return { start: "1900-01-01", end: "2999-12-31" };
    case "custom":
      return { start: custom.from || "1900-01-01", end: custom.to || "2999-12-31" };
    case "this_fy":
    default:
      return fyRangeFor(financialYear);
  }
}

// ── Multi-period comparison columns (P&L / Balance Sheet) ──────────────────
// QuickBooks' "Display columns by" — pick a period (PeriodMode above), then
// split it into Monthly/Quarterly/Yearly columns instead of one lump sum, so
// a CA can eyeball a trend across a financial year without exporting to Excel.

export type Granularity = "total" | "month" | "quarter" | "year";

export const GRANULARITY_OPTIONS: { value: Granularity; label: string }[] = [
  { value: "total", label: "Total" },
  { value: "month", label: "Monthly" },
  { value: "quarter", label: "Quarterly" },
  { value: "year", label: "Yearly" },
];

export interface PeriodColumn {
  label: string;
  start: string;
  end: string;
}

/**
 * The client's real posted-ledger bounds, from GET /api/accounting/ledger-span.
 * null when the ledger is empty — which is NOT the same as "unknown", and is
 * why All Time falls back to the placeholder span rather than inventing a
 * range around today.
 */
export type LedgerSpan = { first: string; last: string } | null;

/**
 * Most columns a split may produce before it collapses to a single total.
 * 60 is chosen to comfortably clear the cases a CA actually asks for — a
 * financial year monthly (12), five years monthly (60), fifteen years
 * quarterly (60) — while stopping a decade-deep ledger split by month from
 * rendering a table nobody can read.
 */
export const MAX_SPLIT_COLUMNS = 60;

const MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

function ymd(y: number, m: number, d: number): string {
  return `${y}-${pad2(m)}-${pad2(d)}`;
}

/** Last day-of-month for 1-indexed month `m` (e.g. m=4 → 30 for April). */
function lastDayOfMonth(y: number, m: number): number {
  return new Date(y, m, 0).getDate();
}

function formatOneDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return `${d} ${MONTH_ABBR[m - 1]} ${y}`;
}

export function formatRangeLabel(start: string, end: string): string {
  return start === end ? formatOneDate(start) : `${formatOneDate(start)} – ${formatOneDate(end)}`;
}

function totalColumnLabel(mode: PeriodMode, financialYear: string, start: string, end: string): string {
  if (mode === "this_fy") return `FY ${financialYear}`;
  if (mode === "last_fy") return `FY ${shiftFY(financialYear, -1)}`;
  if (mode === "all_time") return "All Time";
  return formatRangeLabel(start, end);
}

function splitByMonth(start: string, end: string): PeriodColumn[] {
  const cols: PeriodColumn[] = [];
  let [y, m] = start.split("-").map(Number);
  for (;;) {
    const monthStart = ymd(y, m, 1);
    const monthEnd = ymd(y, m, lastDayOfMonth(y, m));
    cols.push({
      label: `${MONTH_ABBR[m - 1]} ${y}`,
      start: monthStart < start ? start : monthStart,
      end: monthEnd > end ? end : monthEnd,
    });
    if (monthEnd >= end) break;
    m += 1;
    if (m > 12) { m = 1; y += 1; }
  }
  return cols;
}

/** Indian FY quarter start month (1/4/7/10) containing calendar month `m`. */
function quarterStartMonth(m: number): number {
  if (m >= 4 && m <= 6) return 4;
  if (m >= 7 && m <= 9) return 7;
  if (m >= 10 && m <= 12) return 10;
  return 1;
}

function splitByQuarter(start: string, end: string): PeriodColumn[] {
  const cols: PeriodColumn[] = [];
  const [y0, m0] = start.split("-").map(Number);
  let y = y0;
  let qm = quarterStartMonth(m0);
  for (;;) {
    const qStart = ymd(y, qm, 1);
    let endM = qm + 2, endY = y;
    if (endM > 12) { endM -= 12; endY += 1; }
    const qEnd = ymd(endY, endM, lastDayOfMonth(endY, endM));
    cols.push({
      label: `${MONTH_ABBR[qm - 1]}–${MONTH_ABBR[endM - 1]} ${y}`,
      start: qStart < start ? start : qStart,
      end: qEnd > end ? end : qEnd,
    });
    if (qEnd >= end) break;
    qm += 3;
    if (qm > 12) { qm -= 12; y += 1; }
  }
  return cols;
}

function splitByYear(start: string, end: string): PeriodColumn[] {
  const cols: PeriodColumn[] = [];
  const [y0, m0] = start.split("-").map(Number);
  let fyStartYear = m0 >= 4 ? y0 : y0 - 1;
  for (;;) {
    const fyStart = ymd(fyStartYear, 4, 1);
    const fyEnd = ymd(fyStartYear + 1, 3, 31);
    cols.push({
      label: `FY ${fyStartYear}-${String(fyStartYear + 1).slice(-2)}`,
      start: fyStart < start ? start : fyStart,
      end: fyEnd > end ? end : fyEnd,
    });
    if (fyEnd >= end) break;
    fyStartYear += 1;
  }
  return cols;
}

/**
 * The range a split actually runs over.
 *
 * Differs from resolvePeriodRange in one case: "All Time" resolves there to a
 * 1900–2999 placeholder, because that function is used to SCOPE A QUERY and an
 * unbounded window is the correct scope for "everything". For SPLITTING, that
 * placeholder is useless — eleven centuries by quarter is ~4,400 columns — so
 * here it is replaced by the client's real first and last posted entry dates
 * when the caller has them.
 */
function resolveSplitRange(
  mode: PeriodMode,
  financialYear: string,
  custom: { from: string; to: string },
  todayIso?: string,
  ledgerSpan?: LedgerSpan,
): DateRange {
  if (mode === "all_time" && ledgerSpan) {
    return { start: ledgerSpan.first, end: ledgerSpan.last };
  }
  return resolvePeriodRange(mode, financialYear, custom, todayIso);
}

function splitBy(granularity: Granularity, start: string, end: string): PeriodColumn[] {
  switch (granularity) {
    case "month": return splitByMonth(start, end);
    case "quarter": return splitByQuarter(start, end);
    case "year": return splitByYear(start, end);
    default: return [];
  }
}

/**
 * Resolve a period mode to its overall [start, end], then split it into
 * display columns per `granularity`. "total" (the default) always returns
 * exactly one column spanning the whole range — identical to today's single-
 * period statements, so existing call sites are unaffected until they opt in
 * to a finer granularity.
 *
 * Pass `ledgerSpan` so "All Time" means the client's actual books rather than
 * the 1900–2999 placeholder; without it, All Time can only ever be one column.
 */
export function splitPeriodColumns(
  mode: PeriodMode,
  financialYear: string,
  custom: { from: string; to: string },
  granularity: Granularity,
  todayIso?: string,
  ledgerSpan?: LedgerSpan,
): PeriodColumn[] {
  const { start, end } = resolveSplitRange(mode, financialYear, custom, todayIso, ledgerSpan);
  const totalColumn = () =>
    [{ label: totalColumnLabel(mode, financialYear, start, end), start, end }];

  // "total" and an inverted range both mean one column. Checked BEFORE
  // splitBy, which returns [] for "total" — falling through would hand every
  // existing single-period call site an empty report rather than a total.
  if (granularity === "total" || start > end) return totalColumn();

  const split = splitBy(granularity, start, end);
  // Guard against a column count nobody can read and no browser enjoys
  // laying out. With a real ledger span this is rarely reached — it takes ~5
  // years of books to hit it monthly — but "All Time" on a decade-old ledger
  // split by month legitimately produces 120+ columns, and a table that wide
  // is not the report the user was asking for. Collapsing is the honest
  // fallback; periodSplitNotice() below is what makes it visible rather than
  // silent, which is the failure this whole path used to have.
  if (split.length > MAX_SPLIT_COLUMNS) return totalColumn();
  return split;
}

/**
 * Why a requested split did not happen, or null when it did.
 *
 * This exists because the previous behaviour was to collapse silently: the
 * "Display columns by" control stayed on "Quarterly" while rendering a single
 * Total column, which reads as a broken control rather than a deliberate
 * limit. Anything that refuses a user's explicit choice has to say so.
 */
export function periodSplitNotice(
  mode: PeriodMode,
  financialYear: string,
  custom: { from: string; to: string },
  granularity: Granularity,
  todayIso?: string,
  ledgerSpan?: LedgerSpan,
): string | null {
  if (granularity === "total") return null;

  if (mode === "all_time" && !ledgerSpan) {
    return "No posted entries yet — pick a financial year to split into columns.";
  }
  const { start, end } = resolveSplitRange(mode, financialYear, custom, todayIso, ledgerSpan);
  if (start > end) return "That date range ends before it starts.";

  const count = splitBy(granularity, start, end).length;
  if (count > MAX_SPLIT_COLUMNS) {
    const label = GRANULARITY_OPTIONS.find((o) => o.value === granularity)?.label ?? granularity;
    return `${label} columns would need ${count} columns for this range (limit ${MAX_SPLIT_COLUMNS}) — showing a single total. Narrow the period or pick a coarser split.`;
  }
  return null;
}
