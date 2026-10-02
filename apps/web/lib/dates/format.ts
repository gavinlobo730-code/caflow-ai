/**
 * THE ONE WAY A DATE IS WRITTEN FOR A PERSON (frontend_ux-20).
 *
 * Before this module a date read three different ways depending on which screen
 * a CA happened to be on, and none of the three was a decision:
 *
 *   `toLocaleDateString("en-IN")`        -> "5/9/2026"   (47 call sites; NOT
 *                                           zero-padded, and day-first only by
 *                                           the grace of the locale — a reader
 *                                           used to month-first sees 9 May)
 *   `lib/services/formatting.formatDate` -> "05 Sept 2026" (35 importers; the
 *                                           month abbreviation is whatever the
 *                                           browser's ICU says — "Sept" on a
 *                                           current Node and Chrome, "Sep" on
 *                                           an older one)
 *   22 locally defined fmtDate / formatDate helpers, each with its own options
 *   and its own idea of what to print for an absent value.
 *
 * and the CA-facing money tables printed the raw `YYYY-MM-DD` the API sent.
 *
 * ── THE CHOICE: `dd MMM yyyy` ("05 Sep 2026") ───────────────────────────────
 *
 *   A numeric date is only unambiguous to a reader who shares the writer's
 *   convention, and an Indian practice does not: a client abroad, a bank's
 *   statement and an accounting package each write 05/09/2026 and mean a
 *   different day. A month NAME cannot be misread as month-first or day-first,
 *   which is the property the money screens need — a due date, an invoice date
 *   and a filing date are exactly the figures somebody acts on. The day is
 *   zero-padded so a column of them lines up, and the month comes from a FIXED
 *   TABLE, never from ICU, so "Sep" is "Sep" in every browser and on every
 *   build machine (`Intl` says "Sept" for en-IN today and said "Sep" before).
 *   The year is always printed: a due date without one reads the same in
 *   December and in January.
 *
 *   ISO (`2026-09-05`) is also unambiguous and is what inputs, URLs, exports and
 *   the API carry; it is a machine form, and a ledger a CA reads aloud to a
 *   client is not where it belongs.
 *
 * ── TWO KINDS OF INPUT, AND THEY ARE NOT THE SAME THING ──────────────────────
 *
 *   A BARE `YYYY-MM-DD` is a calendar DATE (a `date` column: invoice_date,
 *   due_date, entry_date). It has no zone and nothing to convert, so it is read
 *   OUT OF ITS OWN DIGITS and never handed to `new Date()`: `new Date(
 *   "2026-03-31")` is UTC midnight, which `toLocaleDateString` then reads in the
 *   BROWSER's zone — so 31 March became 30 March for anybody west of Greenwich,
 *   and for a CA working abroad that is the day a return falls due. CLAUDE.md's
 *   rule for a stored DATE is the same as lib/dateMath's: stay in one frame.
 *
 *   A TIMESTAMP (`created_at`, `posted_at`, anything with a time part) is an
 *   INSTANT. PostgREST sends a `timestamptz` in UTC, so its date is the Indian
 *   calendar date only after it is converted: from 18:30 to 24:00 UTC (00:00 to
 *   05:30 IST the next day) the UTC date is YESTERDAY. It is converted with an
 *   explicit `Asia/Kolkata` zone, never by adding 5:30 by hand, and a timestamp
 *   with no offset is read as UTC, which is the server's own convention
 *   (`core.auth._instant_epoch` reads a naive `iat` as UTC for the same reason).
 *
 * ── WHAT IS DELIBERATELY NOT HERE ────────────────────────────────────────────
 *
 *   No function takes a `Date` object, because a `Date` in this codebase is one
 *   of two different things and nothing on the object says which: a local-
 *   midnight anchor built from `new Date(y, m, d)` (lib/dateMath) or a real
 *   instant. A caller holding a local-midnight `Date` passes
 *   `toLocalISO(d)`; a caller holding an instant passes `d.toISOString()`. The
 *   conversion is then written down at the call site, where the reader can see
 *   which one was meant.
 *
 *   An absent or unreadable value is never rendered as a date. Every function
 *   takes the text to show instead (default "—"), and a string that is not a
 *   real calendar date — `2026-02-31` rolls over to March in `new Date()` and is
 *   refused here — gets it too, so an unknown never reads as a value.
 *
 *   PDFs and exports format dates on the SERVER and are not touched by this
 *   file; the grouping of a rupee figure has its own pair of modules, and this
 *   is the date twin of them.
 */

/** What an absent or unreadable date renders as. */
export const DATE_ABSENT = "—";

/** The fixed month table. NOT `Intl`: ICU's abbreviation moves between versions
 *  ("Sep" -> "Sept" for en-IN), and the same month must be spelled the same way
 *  on every screen and in every browser. */
export const MONTH_ABBREVIATIONS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
] as const;

const WEEKDAY_NAMES = [
  "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
] as const;

const BARE_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;
const BARE_MONTH = /^(\d{4})-(\d{2})$/;
// date, "T" or a space (Postgres' own text form), time, optional fraction,
// optional zone: "Z", "+05:30", "+0530" or Postgres' "+00".
const TIMESTAMP =
  /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?\s*(Z|[+-]\d{2}(?::?\d{2})?)?$/i;

interface CalendarDay { y: number; m: number; d: number }
interface WallClock extends CalendarDay { hh: number; mm: number }

/** Is this a real calendar day? `Date.UTC` rolls 31 February over to March, so
 *  the round trip is the test — and it stays in the UTC frame on both halves. */
function isRealDay(y: number, m: number, d: number): boolean {
  if (m < 1 || m > 12 || d < 1 || d > 31) return false;
  const t = new Date(Date.UTC(y, m - 1, d));
  return t.getUTCFullYear() === y && t.getUTCMonth() === m - 1 && t.getUTCDate() === d;
}

// Built once: constructing an Intl.DateTimeFormat is not cheap and a table of a
// thousand rows would build a thousand of them.
//
// It supplies NUMBERS only (day, month, year, hour, minute in India), never a
// month name or a layout — those are this file's. `hourCycle: "h23"` because
// `hour12: false` makes some engines print midnight as "24".
const IST_WALL_CLOCK = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Asia/Kolkata",
  year: "numeric",
  month: "numeric",
  day: "numeric",
  hour: "numeric",
  minute: "numeric",
  hourCycle: "h23",
});

/** The Indian wall clock at an instant, or null for an instant that is not one. */
function istWallClock(ms: number): WallClock | null {
  if (!Number.isFinite(ms)) return null;
  const out: Record<string, number> = {};
  for (const part of IST_WALL_CLOCK.formatToParts(new Date(ms))) {
    if (part.type === "literal") continue;
    out[part.type] = Number(part.value);
  }
  const { year, month, day, hour, minute } = out;
  if (![year, month, day, hour, minute].every(Number.isFinite)) return null;
  return { y: year, m: month, d: day, hh: hour % 24, mm: minute };
}

/** A timestamp string as an instant (epoch ms), or null. A string with no zone
 *  is UTC. The fraction is cut to milliseconds because engines disagree about
 *  longer ones and PostgREST sends microseconds. */
function instantOf(text: string): number | null {
  const m = TIMESTAMP.exec(text);
  if (!m) return null;
  const [, ys, mos, ds, hs, mis, ss, frac, zone] = m;
  if (!isRealDay(Number(ys), Number(mos), Number(ds))) return null;
  if (Number(hs) > 23 || Number(mis) > 59 || Number(ss ?? "0") > 59) return null;
  let z = "Z";
  if (zone && zone.toUpperCase() !== "Z") {
    const sign = zone[0];
    const digits = zone.slice(1).replace(":", "");
    z = `${sign}${digits.slice(0, 2)}:${digits.length > 2 ? digits.slice(2, 4) : "00"}`;
  }
  const ms = `${(frac ?? "0").padEnd(3, "0").slice(0, 3)}`;
  const t = Date.parse(`${ys}-${mos}-${ds}T${hs}:${mis}:${ss ?? "00"}.${ms}${z}`);
  return Number.isNaN(t) ? null : t;
}

/** The calendar day a string means: a bare date as itself, a timestamp as its
 *  Indian date. Null for anything else. */
function dayOf(value: unknown): CalendarDay | null {
  if (typeof value !== "string") return null;
  const text = value.trim();
  const bare = BARE_DATE.exec(text);
  if (bare) {
    const [y, m, d] = [Number(bare[1]), Number(bare[2]), Number(bare[3])];
    return isRealDay(y, m, d) ? { y, m, d } : null;
  }
  const ms = instantOf(text);
  if (ms === null) return null;
  return istWallClock(ms);
}

function dd(n: number): string {
  return String(n).padStart(2, "0");
}

function dayText({ y, m, d }: CalendarDay): string {
  return `${dd(d)} ${MONTH_ABBREVIATIONS[m - 1]} ${y}`;
}

function clockText({ hh, mm }: WallClock): string {
  const h12 = hh % 12 === 0 ? 12 : hh % 12;
  return `${h12}:${dd(mm)} ${hh < 12 ? "am" : "pm"}`;
}

/**
 * A calendar date: `05 Sep 2026`.
 *
 * A bare `YYYY-MM-DD` is printed from its own digits; a timestamp is printed as
 * its date in IST. Anything else — absent, not a string, not a real day — is
 * `fallback`.
 */
export function formatDate(value: string | null | undefined, fallback: string = DATE_ABSENT): string {
  const day = dayOf(value);
  return day ? dayText(day) : fallback;
}

/**
 * A moment: `05 Sep 2026, 3:30 pm`, in IST.
 *
 * The time of day is only meaningful for an instant, so a BARE DATE is printed
 * as the date alone — never with a midnight nobody recorded. Unlabelled, since
 * every time in this product is IST; `formatIstLabelled` appends the zone for a
 * screen (an audit trail, a posting stamp) where the label is part of the claim.
 */
export function formatDateTime(value: string | null | undefined, fallback: string = DATE_ABSENT): string {
  if (typeof value !== "string") return fallback;
  const text = value.trim();
  if (BARE_DATE.test(text)) return formatDate(text, fallback);
  const ms = instantOf(text);
  const wall = ms === null ? null : istWallClock(ms);
  return wall ? `${dayText(wall)}, ${clockText(wall)}` : fallback;
}

/** The time of day alone, `3:30 pm`, in IST. A bare date has none, so it is
 *  `fallback` rather than an invented 12:00 am. */
export function formatTime(value: string | null | undefined, fallback: string = DATE_ABSENT): string {
  if (typeof value !== "string") return fallback;
  const ms = instantOf(value.trim());
  const wall = ms === null ? null : istWallClock(ms);
  return wall ? clockText(wall) : fallback;
}

/**
 * A month as a period label: `Sep 2026`. Takes `YYYY-MM`, `YYYY-MM-DD` or a
 * timestamp, so a return period, a payroll month and a period start all go
 * through the one spelling. A period is not a date, and it is not printed as one.
 */
export function formatMonthYear(value: string | null | undefined, fallback: string = DATE_ABSENT): string {
  if (typeof value === "string") {
    const ym = BARE_MONTH.exec(value.trim());
    if (ym) {
      const [y, m] = [Number(ym[1]), Number(ym[2])];
      if (m >= 1 && m <= 12) return `${MONTH_ABBREVIATIONS[m - 1]} ${y}`;
      return fallback;
    }
  }
  const day = dayOf(value);
  return day ? `${MONTH_ABBREVIATIONS[day.m - 1]} ${day.y}` : fallback;
}

/**
 * TODAY IN INDIA as `YYYY-MM-DD` — the one screen that compares a stored due
 * date with "now" and must not use the browser's own midnight for it
 * (`lib/dateMath.todayLocalISO` is the browser's calendar day, which is right
 * for a form default and wrong for "is this return overdue" when the reader is
 * abroad). A key, not a display value: print it through `formatDate`.
 */
export function todayIstISO(now: number = Date.now()): string {
  const wall = istWallClock(now);
  // Unreachable for a finite `now`; an unreadable clock must not read as a date.
  return wall ? `${wall.y}-${dd(wall.m)}-${dd(wall.d)}` : "";
}

/**
 * A date with its weekday, `Thursday, 01 Oct 2026` — for a screen that greets
 * the reader with today's date. The weekday is arithmetic on the calendar day in
 * the UTC frame, so no zone can move it.
 */
export function formatWeekdayDate(value: string | null | undefined, fallback: string = DATE_ABSENT): string {
  const day = dayOf(value);
  if (!day) return fallback;
  const weekday = new Date(Date.UTC(day.y, day.m - 1, day.d)).getUTCDay();
  return `${WEEKDAY_NAMES[weekday]}, ${dayText(day)}`;
}
