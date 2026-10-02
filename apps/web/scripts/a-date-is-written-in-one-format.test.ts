// A date a person reads is written by ONE module, and that module never moves
// a day. Run with:
//   node --experimental-strip-types --test scripts/a-date-is-written-in-one-format.test.ts
//
// WHAT WAS WRONG (frontend_ux-20)
//     The same date read "5/9/2026" on one screen, "05 Sept 2026" on the next
//     and "2026-09-05" on a ledger. There were 47 `toLocaleDateString` calls
//     (45 of them `en-IN` with no options, which prints D/M/YYYY unpadded),
//     22 locally defined `fmtDate` / `formatDate` helpers each with its own
//     options and its own idea of what an absent value prints, and six private
//     month-name tables. Underneath, two of them were wrong rather than merely
//     different: `new Date("2026-03-31").toLocaleDateString(...)` reads a bare
//     calendar date as UTC midnight in the BROWSER's zone — 30 March west of
//     Greenwich — and `toLocaleString("en-IN")` prints a stored UTC instant in
//     whatever zone the browser is in, which is not the Indian date between
//     18:30 and 24:00 UTC.
//
// THE RULE, IN FOUR PARTS
//   1. NOTHING CALLS THE LOCALE DATE API. `toLocaleDateString`,
//      `toLocaleTimeString`, a date-shaped `toLocaleString` and
//      `Intl.DateTimeFormat` live in `lib/dates/format.ts` and nowhere else.
//      The frozen list is EMPTY, so this is a ban rather than a budget: there
//      is no number to raise. A genuinely different presentation is a function
//      in lib/dates with its reason beside it.
//   2. NOBODY DEFINES A LOCAL DATE HELPER. A function named fmt*/format* + a
//      date noun may not be declared outside lib/dates unless it hands the work
//      to the one module in the same body. An ALIAS (`const fmtDateTime =
//      formatDateTime`) is not a definition and is fine.
//   3. THE MONTH TABLE IS ONE. A literal array of month names is a private
//      formatter. The list below is FROZEN and can only shrink: the five
//      long-name tables are month PICKERS and a calendar heading, not a way of
//      printing a date, and each says why.
//   4. THE FORMATS AGREE. One fixture of ISO dates is pushed through every
//      path that prints one and must come out identically — and must not move
//      under any timezone (the TZ matrix is in lib/dates/format.test.ts).
//
// WHAT THIS CANNOT SEE, AND SAYS SO
//   A date printed RAW — `{inv.invoice_date}` — calls no function at all, so no
//   syntactic rule here can tell it from a reference number. The CA-facing
//   money tables still print the API's `YYYY-MM-DD` that way (frontend_ux-20's
//   own evidence missed it), and converting them is a per-field sweep that
//   needs the column list, not a regex. Nor can it see a Date formatted by a
//   hand-built template (`${d.getDate()}/${d.getMonth()+1}`); the name rule
//   catches the helper such a template usually lives in and nothing else.
//   There is no browser harness, so "the same date on five screens" means the
//   five formatting paths the screens call, not five rendered pages.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";
import { formatDate, formatDateTime } from "../lib/dates/format.ts";
import { formatIst } from "../lib/dates/formatIst.ts";
import { formatRangeLabel } from "../lib/dates/periods.ts";
import { describeChanges } from "../components/accounting/entryHistoryFields.ts";

const WEB = path.resolve(import.meta.dirname, "..");
const AUTHORITY = "lib/dates/format.ts";

function walk(dir: string, out: string[] = []): string[] {
  for (const e of fs.readdirSync(path.join(WEB, dir), { withFileTypes: true })) {
    const rel = path.posix.join(dir, e.name);
    if (e.isDirectory()) {
      if (e.name === "node_modules" || e.name === ".next" || e.name === "out") continue;
      walk(rel, out);
    } else if (/\.(ts|tsx)$/.test(e.name) && !/\.test\.(ts|tsx)$/.test(e.name)) {
      out.push(rel);
    }
  }
  return out;
}

/** The product's own source: screens, components and libraries. Not scripts/
 *  (these tests quote the forms they forbid), not tests. */
const SOURCES = ["app", "components", "lib"].flatMap((d) => walk(d)).sort();

function code(rel: string): string {
  return stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));
}

test("the scan reads the tree it claims to (not vacuous)", () => {
  assert.ok(SOURCES.length > 400, `only ${SOURCES.length} source files were scanned`);
  assert.ok(SOURCES.includes(AUTHORITY), "the authority module is outside the scan");
  assert.ok(SOURCES.includes("lib/services/formatting.ts"));
});

// ── 1. Nothing calls the locale date API ────────────────────────────────────

const DATE_OPTION_KEY = /\b(?:day|month|year|hour|minute|second|weekday|dateStyle|timeStyle|timeZone)\s*:/;

/** Every `.toLocaleString(` whose receiver is a Date constructor or whose own
 *  argument list carries a date option. A number's `toLocaleString("en-IN", {
 *  minimumFractionDigits })` is the rupee formatter's business and is not this. */
function dateShapedToLocaleString(src: string): number {
  let n = 0;
  const re = /\.toLocaleString\s*\(/g;
  for (let m = re.exec(src); m; m = re.exec(src)) {
    // The argument list, brace-aware, up to its closing parenthesis.
    let depth = 1, i = m.index + m[0].length;
    for (; i < src.length && depth > 0; i++) {
      if (src[i] === "(") depth++;
      else if (src[i] === ")") depth--;
    }
    const args = src.slice(m.index + m[0].length, i - 1);
    const before = src.slice(Math.max(0, m.index - 60), m.index);
    if (DATE_OPTION_KEY.test(args) || /new Date\s*\([^)]*\)\s*$/.test(before)) n++;
  }
  return n;
}

// Frozen, and EMPTY: file -> how many calls it may still make.
const FROZEN_LOCALE_DATE_CALLS: Record<string, number> = {};

function localeDateCalls(src: string): number {
  const direct = (src.match(/\.toLocale(?:Date|Time)String\s*\(/g) ?? []).length;
  const intl = (src.match(/\bIntl\s*\.\s*DateTimeFormat\b/g) ?? []).length;
  return direct + intl + dateShapedToLocaleString(src);
}

test("no screen, component or library calls the locale date API itself", () => {
  const found: Record<string, number> = {};
  for (const rel of SOURCES) {
    if (rel === AUTHORITY) continue;
    const n = localeDateCalls(code(rel));
    if (n > 0) found[rel] = n;
  }
  assert.deepEqual(found, FROZEN_LOCALE_DATE_CALLS,
    "a date is formatted by lib/dates/format.ts (formatDate, formatDateTime, " +
    "formatTime, formatMonthYear, formatWeekdayDate). `toLocaleDateString` reads a " +
    "bare date as UTC midnight in the browser's zone and prints D/M/YYYY unpadded; " +
    "`toLocaleString` prints a UTC instant in the browser's zone. If a presentation " +
    "is genuinely different, add a function to lib/dates with the reason beside it — " +
    "do not add an entry here.");
});

test("the detector sees each spelling it is meant to ban", () => {
  assert.equal(localeDateCalls(`d.toLocaleDateString("en-IN")`), 1);
  assert.equal(localeDateCalls(`d.toLocaleTimeString("en-IN", { hour: "2-digit" })`), 1);
  assert.equal(localeDateCalls(`new Intl.DateTimeFormat("en-IN").format(d)`), 1);
  assert.equal(localeDateCalls(`d.toLocaleString("en-IN", { month: "long", year: "numeric" })`), 1);
  assert.equal(localeDateCalls(`new Date(x).toLocaleString("en-IN")`), 1);
  assert.equal(localeDateCalls(`d.toLocaleString("default", { month: "short" })`), 1);
  // A number is not a date.
  assert.equal(localeDateCalls(`(paise / 100).toLocaleString("en-IN", { minimumFractionDigits: 2 })`), 0);
  assert.equal(localeDateCalls(`rupees.toLocaleString("en-IN")`), 0);
  assert.equal(localeDateCalls(`n.toLocaleString("en-IN", { maximumFractionDigits: 2 })`), 0);
});

// ── 2. Nobody defines a local date helper ───────────────────────────────────

const DATE_NOUN = "(?:Date|Day|Month|Stamp|Time|Clock)";
const HELPER_NAME = new RegExp(`^(?:fmt|format)(?:[A-Z][A-Za-z]*)?${DATE_NOUN}[A-Za-z]*$`);
// `function name(`, or `const name = (`/`async`/`function`/`x =>` — and NOT
// `const name = otherName;`, which is an alias and defines nothing.
const DEFINITION =
  /(?:\bfunction\s+([A-Za-z_$][\w$]*)\s*[<(]|\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=;]+)?=\s*(?:async\s*)?(?:function\b|\(|[A-Za-z_$][\w$]*\s*=>))/g;
const AUTHORITY_CALL =
  /\b(?:formatDate|formatDateTime|formatTime|formatMonthYear|formatWeekdayDate|formatDateAuthority|formatDateTimeAuthority|formatIst|formatIstLabelled)\s*\(/;

function localDateHelpers(src: string): string[] {
  const out: string[] = [];
  for (let m = DEFINITION.exec(src); m; m = DEFINITION.exec(src)) {
    const name = m[1] ?? m[2];
    if (!name || !HELPER_NAME.test(name)) continue;
    // Hands the work to the one module within the next stretch of its own body.
    const body = src.slice(m.index, m.index + 700);
    if (AUTHORITY_CALL.test(body.slice(m[0].length))) continue;
    out.push(name);
  }
  return out;
}

// Frozen: file -> the helper names it may still define. EMPTY.
const FROZEN_LOCAL_DATE_HELPERS: Record<string, string[]> = {};

test("nobody writes a local date helper", () => {
  const found: Record<string, string[]> = {};
  for (const rel of SOURCES) {
    if (rel === AUTHORITY) continue;
    const names = localDateHelpers(code(rel));
    if (names.length) found[rel] = names;
  }
  assert.deepEqual(found, FROZEN_LOCAL_DATE_HELPERS,
    "import formatDate / formatDateTime / formatMonthYear from lib/dates/format " +
    "instead of defining fmtDate in a screen. A local helper is correct on the day " +
    "it is written and that is what makes it hard to notice when the original moves.");
});

test("the helper detector sees a definition, a delegate and an alias for what they are", () => {
  assert.deepEqual(localDateHelpers(`function fmtDate(iso: string) { return iso; }`), ["fmtDate"]);
  assert.deepEqual(localDateHelpers(`const formatDate = (d: string) => d.slice(0, 10);`), ["formatDate"]);
  assert.deepEqual(localDateHelpers(`const fmtMonth = function (m: string) { return m; };`), ["fmtMonth"]);
  assert.deepEqual(localDateHelpers(`function fmtTime(s: string) { return s; }`), ["fmtTime"]);
  // Hands off to the authority: allowed.
  assert.deepEqual(localDateHelpers(`function formatDate(d) { return formatDateAuthority(d); }`), []);
  // An alias defines nothing.
  assert.deepEqual(localDateHelpers(`const fmtDateTime = formatDateTime;`), []);
  // Not date nouns.
  assert.deepEqual(localDateHelpers(`function formatPaise(p: number) { return String(p); }`), []);
  assert.deepEqual(localDateHelpers(`function formatDuration(s: number) { return String(s); }`), []);
});

test("the legacy shared entry point still delegates, in both functions", () => {
  const src = code("lib/services/formatting.ts");
  assert.match(src, /export function formatDate\([^)]*\)[^{]*\{\s*return formatDateAuthority\(/,
    "services/formatting.formatDate no longer delegates to lib/dates/format");
  assert.match(src, /export function formatDateTime\([^)]*\)[^{]*\{\s*return formatDateTimeAuthority\(/,
    "services/formatting.formatDateTime no longer delegates to lib/dates/format");
  assert.match(src, /from "@\/lib\/dates\/format"/);
});

// ── 3. The month table is one ───────────────────────────────────────────────

const MONTH_TABLE =
  /["']Jan(?:uary)?["']\s*,\s*["']Feb(?:ruary)?["']\s*,\s*["']Mar(?:ch)?["']/;

// Frozen, and can only shrink. file -> why a month table is still there.
const FROZEN_MONTH_TABLES: Record<string, string> = {
  "app/payroll/attendance/page.tsx": "long month names for the attendance month picker",
  "app/payroll/statutory/page.tsx": "long month names for the statutory month picker",
  "app/calendar/page.tsx": "the calendar's own heading — a calendar names its month in full",
  "components/gst/IffPanel.tsx": "long month names for the IFF month picker",
  "lib/gst/period.ts": "GSTN's MMYYYY period label in long form, pinned by period.test.ts",
};

test("the only month-name tables left are the frozen pickers and headings", () => {
  const found = SOURCES
    .filter((rel) => rel !== AUTHORITY && MONTH_TABLE.test(code(rel)))
    .sort();
  assert.deepEqual(found, Object.keys(FROZEN_MONTH_TABLES).sort(),
    "a literal list of month names is a private date formatter. Import " +
    "MONTH_ABBREVIATIONS (or call formatMonthYear) from lib/dates/format. If a table " +
    "was REMOVED, delete its entry — this list only shrinks.");
});

test("each frozen month table still says why", () => {
  for (const [file, why] of Object.entries(FROZEN_MONTH_TABLES)) {
    assert.ok(why.length > 20, `${file} has no reason`);
  }
});

// ── 4. The formats agree ────────────────────────────────────────────────────

// One fixture: an ISO calendar date and what every path must print for it.
const FIXTURE: ReadonlyArray<{ iso: string; text: string }> = [
  { iso: "2026-09-05", text: "05 Sep 2026" },   // a month ICU spells "Sept"
  { iso: "2026-03-31", text: "31 Mar 2026" },   // the last day of the FY
  { iso: "2026-04-01", text: "01 Apr 2026" },   // the first, single-digit day
  { iso: "2026-12-31", text: "31 Dec 2026" },   // a year end
  { iso: "2024-02-29", text: "29 Feb 2024" },   // a leap day
];

test("one fixture of ISO dates reads the same through every path that prints a date", () => {
  for (const { iso, text } of FIXTURE) {
    // 1. the authority
    assert.equal(formatDate(iso), text, `formatDate(${iso})`);
    // 2. a timestamp at Indian noon on that day
    assert.equal(formatDate(`${iso}T06:30:00Z`), text, `formatDate(${iso}T06:30Z)`);
    assert.equal(formatDateTime(`${iso}T06:30:00Z`), `${text}, 12:00 pm`, `formatDateTime(${iso})`);
    // 3. the IST stamp the Approvals and Verify Books screens use
    assert.equal(formatIst(`${iso}T06:30:00Z`), `${text}, 12:00 pm`, `formatIst(${iso})`);
    // 4. a period or filing-window label
    assert.equal(formatRangeLabel(iso, iso), text, `formatRangeLabel(${iso})`);
    assert.equal(formatRangeLabel(iso, "2027-03-31"), `${text} – 31 Mar 2027`, `formatRangeLabel(${iso}, …)`);
    // 5. the journal edit log's Date column
    const [change] = describeChanges({
      action: "UPDATE",
      old_data: { entry_date: "2000-01-01" },
      new_data: { entry_date: iso },
    });
    assert.equal(change.after, text, `describeChanges entry_date ${iso}`);
  }
});
