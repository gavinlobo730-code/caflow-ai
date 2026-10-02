/**
 * THE ONE RULE FOR A DATE A PERSON TYPES (frontend_ux-19).
 *
 * `<input type="date">` is a control the BROWSER draws, in the BROWSER's locale:
 * mm/dd/yyyy in a US-locale browser, a segmented mask that cannot be typed into
 * in one go and a calendar popup everywhere, in well over a hundred fields of
 * this product. An Indian clerk types 15/03/2026, or 15/3, or just 15 — and expects the books'
 * own financial year to supply the rest, as Tally does. This module is that
 * reading: text in, an ISO calendar date or an error out, with no React and no
 * clock of its own beyond the two the product already has.
 *
 * ── WHAT IS ACCEPTED ────────────────────────────────────────────────────────
 *
 *   15/03/2026  15-03-2026  15.03.2026  15032026     day, month, four-digit year
 *   15/03/26    150326                               ... or a two-digit year (20yy)
 *   2026-03-15                                       ISO, so a pasted or stored
 *                                                    value reads back unchanged
 *   15/3  15-3  1503                                 day and month: the YEAR is
 *                                                    the financial year's own
 *   15                                               a bare day: the month is the
 *                                                    ANCHOR's, the year the FY's
 *
 *   One separator throughout (15/03-2026 is a typo, not a date), and spaces
 *   around a separator are ignored. Only ASCII digits: `\d` without the `u` flag
 *   is [0-9], so a fullwidth or Devanagari digit is an error, not a guess — the
 *   same trap `str.isdigit` is in Python (CLAUDE.md, HSN digits).
 *
 *   A digit string of 3, 5 or 7 characters is ambiguous (`153` is 15/3 or 1/53)
 *   and is refused. `20260315` is read as ddmmyyyy like every other eight-digit
 *   string, so it is the error "there is no month 26", never 2026-03-15.
 *
 * ── EXPANSION IS THE FINANCIAL YEAR'S, NOT THE CALENDAR'S ───────────────────
 *
 *   `15/1` in FY 2026-27 is 15 January **2027**: April to December belong to the
 *   year the FY starts in and January to March to the year after. That is
 *   `lib/dates/periods.ts`'s clock and is read off it (`fyRangeFor`,
 *   `financialYearOfMonth`), never restated: this file contains no `4`, no `31
 *   March`, and no list of month lengths.
 *
 *   The FY is the caller's `financialYear` where it has one; where it has none
 *   it is the financial year OF THE ANCHOR, and the anchor is, in order, the
 *   caller's `anchor` (the document's own date, so a bare day lands in the
 *   month the document is already in), then today in IST. An anchor outside the
 *   FY is CLAMPED to its nearest end, which is what "today, clamped into the FY"
 *   means for a CA entering last year's books in October: a bare `15` is March,
 *   the last month of that year, and the field shows 15/03/2027 at once.
 *
 * ── NOTHING IS GUESSED ──────────────────────────────────────────────────────
 *
 *   31/02/2026 is an error naming February 2026's 28 days. It is never March
 *   3rd, which is what `new Date(2026, 1, 31)` makes of it and what a native
 *   input's text mode, a spreadsheet and half the ERP packages do silently, and
 *   a wrong day on a voucher is a wrong period on a return. 29/02 is valid in a
 *   leap year and an error in every other one — and `29/02` with no year is
 *   judged in the FY's own February, so it is valid in FY 2027-28 (February
 *   2028) and an error in FY 2026-27 (February 2027). Month 13, day 0 and a
 *   year outside 1900-2999 (the span `lib/dates/periods` already uses as "all
 *   time") each get their own sentence. Anything that is not a date returns an
 *   error and no `iso`.
 *
 *   The text never goes through `new Date(string)`. A bare date is a calendar
 *   day with no zone, and handing it to the Date parser reads it as UTC midnight
 *   (lib/dates/format.ts documents what that did to 31 March west of Greenwich).
 *   Day arithmetic below is `Date.UTC(y, m - 1, d + n)` read back in the UTC
 *   frame, which cannot move a day under any TZ.
 *
 * ── WHAT IS DELIBERATELY NOT HERE ───────────────────────────────────────────
 *
 *   NO PERIOD LOCK, NO FILED-RETURN RULE, NO "IS THIS DATE ALLOWED". Whether a
 *   date falls in a locked year or a period a return has been filed for is the
 *   server's (`period_lock_service`, the posting kernel) and stays there: a
 *   mirror in TypeScript would be a second copy of a statutory rule that
 *   disagrees the day the first moves. `min` and `max` are an INPUT HINT — a
 *   field that knows its financial year can say "this is before 01 Apr 2026" —
 *   and the result still carries the ISO date, so a parent that does not care
 *   is exactly where a native input left it and the server's refusal is shown as
 *   it always was.
 */
import { MONTH_ABBREVIATIONS, formatDate, todayIstISO } from "./format.ts";
import { financialYearOfMonth, fyRangeFor } from "./periods.ts";

/** The span a typed year may fall in: `lib/dates/periods` already treats
 *  1900-01-01 .. 2999-12-31 as "all time", and a year outside it is a typo for a
 *  books-keeping product, not a date. */
export const MIN_YEAR = 1900;
export const MAX_YEAR = 2999;

/** What to type, in the placeholder and in the unreadable-text sentence. */
export const TYPED_DATE_EXAMPLE = "15/03/2026";
export const TYPED_DATE_PLACEHOLDER = "dd/mm/yyyy";

export type TypedDateProblem =
  | "unreadable"
  | "year_digits"
  | "no_such_month"
  | "no_such_day"
  | "bad_year";

export interface TypedDateContext {
  /** "2026-27". A bare day, or a day and month, is resolved inside it. Where it
   *  is absent or not a real label (`2026-28` is not) the FY of the anchor is
   *  used. */
  financialYear?: string | null;
  /** `YYYY-MM-DD`, or `YYYY-MM` for a month alone: the month a BARE DAY belongs
   *  to. Absent or unreadable, it is today in IST. */
  anchor?: string | null;
  /** `YYYY-MM-DD` bounds, an input hint only (see the header). */
  min?: string | null;
  max?: string | null;
  /** Injectable clock for tests, `YYYY-MM-DD`; defaults to today in IST. */
  today?: string;
}

export type TypedDate =
  /** Nothing but whitespace. Not an error: an optional date is allowed to be blank. */
  | { kind: "empty" }
  | {
      kind: "date";
      /** `YYYY-MM-DD`, the same string `<input type="date">` puts in `.value`. */
      iso: string;
      /** `dd/mm/yyyy`, what the field should show once it has understood. */
      display: string;
      /** Set when the date is real and outside `min`/`max`. */
      outOfRange: "min" | "max" | null;
      /** A sentence for `outOfRange`; null otherwise. */
      message: string | null;
    }
  | { kind: "error"; problem: TypedDateProblem; message: string };

const BARE_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;
const BARE_MONTH = /^(\d{4})-(\d{2})$/;
const FY_LABEL = /^(\d{4})-(\d{2})$/;

function pad(n: number, width = 2): string {
  return String(n).padStart(width, "0");
}

/** Days in month `m` (1-12) of year `y`, in the UTC frame — day 0 of the next
 *  month is the last day of this one, leap years included. */
function daysInMonth(y: number, m: number): number {
  return new Date(Date.UTC(y, m, 0)).getUTCDate();
}

function isRealDay(y: number, m: number, d: number): boolean {
  return m >= 1 && m <= 12 && d >= 1 && d <= daysInMonth(y, m);
}

/** A strictly valid bare date, or null. */
function readIso(text: string | null | undefined): { y: number; m: number; d: number } | null {
  const hit = BARE_DATE.exec((text ?? "").trim());
  if (!hit) return null;
  const [y, m, d] = [Number(hit[1]), Number(hit[2]), Number(hit[3])];
  return y >= MIN_YEAR && y <= MAX_YEAR && isRealDay(y, m, d) ? { y, m, d } : null;
}

const isoOf = (y: number, m: number, d: number) => `${pad(y, 4)}-${pad(m)}-${pad(d)}`;

/** `dd/mm/yyyy` for a valid bare date, "" for anything else — including a
 *  timestamp, which is an instant and not a calendar day (an `<input
 *  type="date">` shows nothing for one either). */
export function typedDateText(iso: string | null | undefined): string {
  const day = readIso(iso);
  return day ? `${pad(day.d)}/${pad(day.m)}/${pad(day.y, 4)}` : "";
}

/** `iso` moved by `n` days, or null when `iso` is not a date or the result would
 *  leave 1900-2999. */
export function addDaysISO(iso: string, n: number): string | null {
  const day = readIso(iso);
  if (!day || !Number.isInteger(n)) return null;
  const t = new Date(Date.UTC(day.y, day.m - 1, day.d + n));
  const [y, m, d] = [t.getUTCFullYear(), t.getUTCMonth() + 1, t.getUTCDate()];
  return y >= MIN_YEAR && y <= MAX_YEAR ? isoOf(y, m, d) : null;
}

interface FinancialYear {
  start: string; // YYYY-MM-DD
  end: string;
  startYear: number;
  startMonth: number;
}

/** A real financial-year label: `YYYY-YY` whose second half FOLLOWS the first
 *  (`2026-28` passes a shape regex and is not a year — models/fy.py's rule). */
function readFinancialYear(label: string | null | undefined): FinancialYear | null {
  const hit = FY_LABEL.exec((label ?? "").trim());
  if (!hit) return null;
  const y = Number(hit[1]);
  if (y < MIN_YEAR || y >= MAX_YEAR || (y + 1) % 100 !== Number(hit[2])) return null;
  const { start, end } = fyRangeFor(`${hit[1]}-${hit[2]}`);
  return { start, end, startYear: y, startMonth: Number(start.slice(5, 7)) };
}

/** The anchor as a full valid date: a day as given, a month as its first day,
 *  and anything else — or nothing — as today in India. */
function anchorDay(ctx: TypedDateContext): string {
  const anchor = (ctx.anchor ?? "").trim();
  if (readIso(anchor)) return anchor;
  const month = BARE_MONTH.exec(anchor);
  if (month && readIso(`${anchor}-01`)) return `${anchor}-01`;
  return readIso(ctx.today) ? (ctx.today as string) : todayIstISO();
}

function financialYearFor(ctx: TypedDateContext): FinancialYear {
  const stated = readFinancialYear(ctx.financialYear);
  if (stated) return stated;
  // The FY the anchor day belongs to — the periods module's own answer.
  const derived = readFinancialYear(financialYearOfMonth(anchorDay(ctx).slice(0, 7)));
  // Null only for an anchor in the last year this module reads (2999); today's
  // year is the answer then, rather than a throw out of a keystroke handler.
  return derived ?? (readFinancialYear(financialYearOfMonth(todayIstISO().slice(0, 7))) as FinancialYear);
}

/** The anchor day clamped into the FY: before it, its first day; after it, its
 *  last. */
function clampedAnchor(ctx: TypedDateContext, fy: FinancialYear): string {
  const a = anchorDay(ctx);
  return a < fy.start ? fy.start : a > fy.end ? fy.end : a;
}

/** The year January-March or April-December of financial year `fy` falls in. */
function yearInFinancialYear(fy: FinancialYear, month: number): number {
  return month >= fy.startMonth ? fy.startYear : fy.startYear + 1;
}

const unreadable = (): TypedDate => ({
  kind: "error",
  problem: "unreadable",
  message: `Not a date. Type it as dd/mm/yyyy, for example ${TYPED_DATE_EXAMPLE}.`,
});

const yearDigits = (): TypedDate => ({
  kind: "error",
  problem: "year_digits",
  message: "Write the year with 2 or 4 digits, for example 26 or 2026.",
});

interface Shape {
  day: number;
  /** null: the anchor's month. */
  month: number | null;
  /** null: the financial year's own year for the month. Else a FULL year. */
  year: number | null;
}

/** Text shaped into day / month / year, or the error it is. */
function readShape(raw: string): Shape | TypedDate {
  // Spaces around a separator are layout ("15 / 03 / 2026"), not a separator.
  const text = raw.trim().replace(/\s*([/.\-])\s*/g, "$1");

  if (/^\d+$/.test(text)) {
    const n = (from: number, to: number) => Number(text.slice(from, to));
    switch (text.length) {
      case 1:
      case 2: return { day: Number(text), month: null, year: null };
      case 4: return { day: n(0, 2), month: n(2, 4), year: null };
      case 6: return { day: n(0, 2), month: n(2, 4), year: 2000 + n(4, 6) };
      case 8: return { day: n(0, 2), month: n(2, 4), year: n(4, 8) };
      default: return unreadable();
    }
  }

  const hit = /^(\d{1,4})([/.\-])(\d{1,2})(?:\2(\d{1,4}))?$/.exec(text);
  if (!hit) return unreadable();
  const [, first, , second, third] = hit;

  if (third === undefined) {
    // d/m. A four-digit first part is a year-and-month, which is not a date.
    return first.length <= 2
      ? { day: Number(first), month: Number(second), year: null }
      : unreadable();
  }
  if (first.length === 4) {
    // ISO order: yyyy-mm-dd.
    return third.length <= 2
      ? { day: Number(third), month: Number(second), year: Number(first) }
      : unreadable();
  }
  if (first.length > 2) return unreadable();
  if (third.length === 2) return { day: Number(first), month: Number(second), year: 2000 + Number(third) };
  if (third.length === 4) return { day: Number(first), month: Number(second), year: Number(third) };
  return yearDigits();
}

function isShape(x: Shape | TypedDate): x is Shape {
  return "day" in x;
}

/**
 * Read what was typed.
 *
 * `empty` for blank text, `error` for anything that is not one real calendar day
 * (with the sentence to show), `date` for one — carrying its ISO form, the
 * `dd/mm/yyyy` text to show back, and whether `min`/`max` say it is out of
 * range. A `date` is returned for an out-of-range value: the field warns, the
 * caller decides, and the server still has the last word.
 */
export function parseTypedDate(raw: string | null | undefined, ctx: TypedDateContext = {}): TypedDate {
  if (typeof raw !== "string" || raw.trim() === "") return { kind: "empty" };
  const shape = readShape(raw);
  if (!isShape(shape)) return shape;

  const fy = financialYearFor(ctx);
  let { month, year } = shape;
  const { day } = shape;

  if (month === null) {
    // A bare day: the anchor's month, in the year the clamped anchor is in.
    const a = clampedAnchor(ctx, fy);
    month = Number(a.slice(5, 7));
    year = Number(a.slice(0, 4));
  }
  if (month < 1 || month > 12) {
    return { kind: "error", problem: "no_such_month", message: `There is no month ${month}: months run from 1 to 12.` };
  }
  if (year === null) year = yearInFinancialYear(fy, month);
  if (year < MIN_YEAR || year > MAX_YEAR) {
    return {
      kind: "error", problem: "bad_year",
      message: `${year} is outside the years this field takes, ${MIN_YEAR} to ${MAX_YEAR}.`,
    };
  }
  if (day < 1 || day > 31) {
    return { kind: "error", problem: "no_such_day", message: `There is no day ${day}: days run from 1 to 31.` };
  }
  const last = daysInMonth(year, month);
  if (day > last) {
    const leap = month === 2 && day === 29
      ? ` ${year} is not a leap year.`
      : "";
    return {
      kind: "error", problem: "no_such_day",
      message: `${MONTH_ABBREVIATIONS[month - 1]} ${year} has only ${last} days.${leap}`,
    };
  }

  const iso = isoOf(year, month, day);
  const min = readIso(ctx.min) ? (ctx.min as string).trim() : null;
  const max = readIso(ctx.max) ? (ctx.max as string).trim() : null;
  const outOfRange = min !== null && iso < min ? "min" : max !== null && iso > max ? "max" : null;
  const message = outOfRange === "min"
    ? `${formatDate(iso)} is before ${formatDate(min)}.`
    : outOfRange === "max"
      ? `${formatDate(iso)} is after ${formatDate(max)}.`
      : null;
  return { kind: "date", iso, display: typedDateText(iso), outOfRange, message };
}

/** The day an ArrowUp or ArrowDown on an EMPTY or unreadable field starts from:
 *  the anchor, clamped into the FY — a native date input starts from today in
 *  the same situation. */
export function startingDay(ctx: TypedDateContext = {}): string {
  return clampedAnchor(ctx, financialYearFor(ctx));
}

/**
 * ArrowUp / ArrowDown. A readable date moves by `delta` days (null at the edge of
 * 1900-2999); a blank or unreadable field takes the starting day, whichever
 * arrow it was, rather than moving from a date nobody can see.
 */
export function stepTypedDate(raw: string, delta: number, ctx: TypedDateContext = {}): string | null {
  const read = parseTypedDate(raw, ctx);
  if (read.kind === "date") return addDaysISO(read.iso, delta);
  return startingDay(ctx);
}

/**
 * What a field reports to its parent each time what it holds changes.
 *
 * THREE STATES, because a parent needs to tell them apart and a bare string
 * cannot: `empty` (nothing typed — an optional date may be this), `valid` (one
 * real calendar day; the ISO string is the value the field handed up) and
 * `invalid` (text that is not a date — the field handed up `""`, and a parent
 * that saves anyway would drop what was typed without a word, which is why it
 * is asked to refuse). `outOfRange` is only ever set on a `valid` date: it is a
 * hint, never a reason to refuse.
 */
export interface DateFieldState {
  status: "empty" | "valid" | "invalid";
  /** What is in the box, as typed. */
  text: string;
  /** A sentence for a person: the error when `invalid`, the hint when out of range. */
  message: string | null;
  outOfRange: "min" | "max" | null;
}

export function dateFieldState(text: string, read: TypedDate): DateFieldState {
  if (read.kind === "empty") return { status: "empty", text, message: null, outOfRange: null };
  if (read.kind === "error") return { status: "invalid", text, message: read.message, outOfRange: null };
  return { status: "valid", text, message: read.message, outOfRange: read.outOfRange };
}

/** The ISO string a field hands its parent: the date when there is one, `""`
 *  for blank AND for text that is not a date — never a stale earlier value. */
export function isoFromRead(read: TypedDate): string {
  return read.kind === "date" ? read.iso : "";
}
