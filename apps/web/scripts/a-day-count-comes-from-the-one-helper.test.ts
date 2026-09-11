// A whole-day count comes from lib/dateMath, and nothing reads the clock once.
// Run with:
//   node --experimental-strip-types --test scripts/a-day-count-comes-from-the-one-helper.test.ts
//
// THIS IS THE SIBLING OF a-calendar-date-is-never-read-back-in-utc.test.ts
//     That one stops a calendar DATE being read out of a UTC instant. This one
//     stops the two things that go wrong when you ask how many DAYS apart two
//     of them are. Same module, same failure, different question — and the
//     helper for it has existed the whole time.
//
// ─────────────────────────────────────────────────────────────────────────────
// RULE 1 — NOTHING DIVIDES BY A DAY IN MILLISECONDS
// ─────────────────────────────────────────────────────────────────────────────
// `lib/dateMath.daysBetweenLocalISO` anchors both sides to local midnight, and
// its own docstring has said since it was written: "never mix a date-only
// string with a live `new Date()` instant (parsing a bare date string yields
// UTC midnight, so diffing it against 'now' produces a result that depends on
// time-of-day, not just the calendar date)".
//
// On 2026-09-11 there were still FOURTEEN sites doing exactly that, in 13
// files. Seven were wrong, and one of them was wrong ALL DAY EVERY DAY rather
// than only overnight:
//
//     app/risks/page.tsx
//       today.setHours(0, 0, 0, 0)                       // local midnight
//       Math.floor((today - new Date(due_date)) / 86400000)   // UTC midnight
//
// Local midnight in IST is 18:30 UTC on the previous day, so the difference is
// always 5½ hours SHORT of a whole number of days and floor() takes the day
// off. A filing ten days overdue read nine, on the figure overdueRiskLevel()
// thresholds at 30 and 15. The same subtraction with Math.ceil, on the same
// page, made a DSC expiring today read "1 day left".
//
// WHY THE RULE IS THE DIVISION AND NOT THE SUBTRACTION
//     Multiplying by a day is fine and common — a TTL (`24 * 60 * 60 * 1000`),
//     or building an instant a week out. It is DIVIDING by one that turns a
//     millisecond difference into a count of calendar days, and that is the
//     operation that has to be anchored. Naming the division rather than
//     banning the constant is what makes this a rule instead of a ban with
//     exemptions.
//
// ─────────────────────────────────────────────────────────────────────────────
// RULE 2 — NO MODULE READS THE CLOCK AT LOAD
// ─────────────────────────────────────────────────────────────────────────────
// A module-scope `const TODAY = new Date()` is evaluated once, when the bundle
// loads, and never again. Everything derived from it is frozen for the life of
// the tab — and a compliance dashboard is precisely the tab somebody leaves
// open.
//
// This rule exists because the first sweep MISSED IT. A scan for
// `^const .*TODAY.* = new Date()` found one file; the defect had four more
// spellings and they were not cosmetic:
//
//   app/mca/page.tsx          "N days remaining" and the amber-under-30 colour
//                             on five statutory MCA deadlines, frozen at load
//   app/gst/page.tsx          the deadline banner AND `currentPeriod`, which
//                             decides which filings count as "this month"
//   app/accounting/loans      daysToDate, plus the default disbursement and
//                             start dates on two forms — open one the next
//                             morning and it defaulted to YESTERDAY
//   app/accounting/msme-...   whether an MSMED §15 payment is late
//   app/accounting/schedule-iii  the FY options on the year-end statements
//
// Only the first of those five was `new Date()`. One was `todayLocalISO()` —
// the CORRECT helper, called in the wrong place — which is the whole reason
// this is stated over "a module-scope binding initialised from a live clock
// read" rather than over any spelling of the clock.
//
// That is the money-parser lesson in CLAUDE.md for the third time: the helper
// existed, the prose said to use it, and nothing checked.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.join(import.meta.dirname, "..");

/** THE one implementation. Everything else delegates to it. */
const THE_HELPER = "lib/dateMath.ts";

/** lib/dateMath.test.ts re-derives the arithmetic on purpose — a test that
 *  proved the helper by calling the helper would prove nothing. It is the
 *  control, not a second implementation. */
const THE_CONTROL = "lib/dateMath.test.ts";

/** Source with comments stripped — the assertions are about CODE, and the
 *  notes left behind (including this file's own) quote the forms they replaced. */
function code(rel: string): string {
  return fs.readFileSync(path.join(ROOT, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "")
    .replace(/\/\/.*$/gm, "");
}

const SKIP = new Set(["node_modules", ".next", "out", ".git", "dist", "coverage"]);

function sources(): string[] {
  const found: string[] = [];
  (function walk(dir: string) {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      if (SKIP.has(e.name)) continue;
      const p = path.join(dir, e.name);
      if (e.isDirectory()) walk(p);
      else if (/\.tsx?$/.test(e.name)) found.push(path.relative(ROOT, p));
    }
  })(ROOT);
  return found.sort();
}

/** Every way of spelling a day in milliseconds that anyone has used or would.
 *  The list is long on purpose: each entry is a SPELLING, and the rule is
 *  stated over the operation (division) so a spelling nobody thought of still
 *  has to get past the division test to matter. */
const DAY_MS = [
  String.raw`86[_ ]?400[_ ]?000`,
  String.raw`1000\s*\*\s*60\s*\*\s*60\s*\*\s*24`,
  String.raw`24\s*\*\s*60\s*\*\s*60\s*\*\s*1000`,
  String.raw`60\s*\*\s*60\s*\*\s*24\s*\*\s*1000`,
  String.raw`1000\s*\*\s*3600\s*\*\s*24`,
  String.raw`3600\s*\*\s*1000\s*\*\s*24`,
  String.raw`24\s*\*\s*3600\s*\*\s*1000`,
  String.raw`3600\s*\*\s*24\s*\*\s*1000`,
  String.raw`86[_ ]?400\s*\*\s*1000`,
  String.raw`1000\s*\*\s*86[_ ]?400`,
].join("|");

/** Whole-file, not line-by-line: app/accounting/loans/page.tsx put the divisor
 *  on its own line, and a line scan reported it clean. */
const DIVIDES_BY_A_DAY = new RegExp(String.raw`\/\s*\(?\s*(?:${DAY_MS})\s*\)?`);

test("nothing outside lib/dateMath turns milliseconds into a count of days", () => {
  const offenders = sources()
    .filter((f) => f !== THE_HELPER && f !== THE_CONTROL)
    .filter((f) => DIVIDES_BY_A_DAY.test(code(f)));

  assert.deepEqual(offenders, [],
    "these divide a millisecond difference by a day, which is a calendar-day "
    + "count computed without anchoring either side to local midnight:\n  "
    + offenders.join("\n  ")
    + "\n\nUse daysBetweenLocalISO(fromISO, toISO) from lib/dateMath. It takes "
    + "YYYY-MM-DD on both sides, so a live instant cannot be passed by mistake.");
});

test("the helper it delegates to is still there and still exported", () => {
  const src = code(THE_HELPER);
  for (const fn of ["daysBetweenLocalISO", "todayLocalISO", "toLocalISO", "dueDateUrgency"]) {
    assert.ok(new RegExp(String.raw`export function ${fn}\b`).test(src),
      `${THE_HELPER} must export ${fn} — this guard sends every caller to it, `
      + "so a rename here silently makes the rule unenforceable.");
  }
});

/** A module-scope binding (column 0 — no leading whitespace, so not inside a
 *  function or a class) initialised from a live clock read. */
const CLOCK_AT_MODULE_SCOPE = new RegExp(
  String.raw`^(?:export\s+)?(?:const|let|var)\s+[A-Za-z_$][\w$]*\s*(?::[^=]+)?=`
  + String.raw`\s*[^;\n]*(?:new Date\(\s*\)|Date\.now\(\s*\)|todayLocalISO\(\s*\)`
  + String.raw`|currentFinancialYearLabel\(\s*\))`,
  "m");

test("no module reads the clock when it loads", () => {
  const offenders = sources()
    .filter((f) => f !== THE_CONTROL)
    .filter((f) => CLOCK_AT_MODULE_SCOPE.test(code(f)));

  assert.deepEqual(offenders, [],
    "these read the clock at module scope, so everything derived from it is "
    + "frozen for the life of the tab:\n  "
    + offenders.join("\n  ")
    + "\n\nMove the read inside the function that needs it. A countdown, a "
    + "filing period, an \"is this late\" test and a form's default date all "
    + "have to be the value NOW, not the value when the bundle loaded.");
});

test("both rules are stated over the operation, not over a name", () => {
  // A regression guard for the guard. The first version of the money-parser
  // check named three SPELLINGS of its defect and passed on sixteen files that
  // used a fourth; CLAUDE.md records it. These assertions pin the two things
  // that make this check a rule: it is the DIVISION that is banned (so a
  // multiplication by a day survives), and it is ANY clock read at module
  // scope (so the correct helper called in the wrong place is still caught).
  assert.ok(!DIVIDES_BY_A_DAY.test("const TTL = 24 * 60 * 60 * 1000;"),
    "building a duration by MULTIPLYING is not a day count and must stay legal");
  assert.ok(!DIVIDES_BY_A_DAY.test("new Date(Date.now() + 7 * 86400000)"),
    "an instant a week out is not a day count and must stay legal");
  assert.ok(DIVIDES_BY_A_DAY.test("Math.ceil((a - b) /\n  (24 * 60 * 60 * 1000))"),
    "a divisor on the next line must still be caught — loans/page.tsx was");

  assert.ok(CLOCK_AT_MODULE_SCOPE.test("const TODAY = new Date();"),
    "the spelling the first sweep found");
  assert.ok(CLOCK_AT_MODULE_SCOPE.test("const TODAY_ISO = todayLocalISO();"),
    "the CORRECT helper called in the wrong place — the spelling it missed");
  assert.ok(CLOCK_AT_MODULE_SCOPE.test('const X = new Date(todayLocalISO() + "T00:00:00");'),
    "wrapped in a Date — app/gst/page.tsx");
  assert.ok(!CLOCK_AT_MODULE_SCOPE.test("  const today = new Date();"),
    "inside a function is the whole point and must stay legal");
  assert.ok(!CLOCK_AT_MODULE_SCOPE.test("const PARSED = new Date(row.created_at);"),
    "parsing a stored instant is not reading the clock");
});
