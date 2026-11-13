// A FIRM'S DAY IS INDIA'S, AND NO SCREEN READS THE BROWSER'S OWN CALENDAR FOR IT (POST-A-404). Run with:
//   node --experimental-strip-types --test scripts/a-firms-day-is-indias-and-not-the-browsers.test.ts
//
// THE DEFECT
//   `todayLocalISO()` (lib/dateMath) was the BROWSER's calendar day. It is right for a CA whose browser is set to India's zone and a day out, for part of every day, for one whose browser is set to
//   another (five and a half hours of every day for a browser on UTC, more across the Americas, and on 1 April it is the other financial year). It had 94 call sites in 52 files: the starting value
//   of a box a person then reads as today, the blank state of a form, a day SENT STRAIGHT TO A WRITE (a reversal date, a capital work in progress date), and every comparison with a stored date
//   (overdue, days since, due soon), mixed in one file with `todayIstISO()` (lib/dates/format), which is India's day, in several. A firm's day is India's whatever zone the screen is opened in.
//   The helper is deleted and every site reads `todayIstISO()`; `currentFinancialYearLabel()` with no date reads it too.
//
// THE RULE, NOT A SPELLING OF IT (the defect has as many spellings as there are ways to ask a clock for a day)
//   1. `todayLocalISO` is named nowhere in `app/`, `components/` or `lib/`.
//   2. `toLocalISO(new Date())` is nowhere (it is `todayLocalISO` written out).
//   3. A bare `new Date()` or a `new Date(Date.now() + n)` (an instant turned into a calendar day, in the browser's frame) that is not read as an instant (`.getTime()`, `.toISOString()`, `.valueOf()`, `.getTimezoneOffset()`) is a read of the browser's calendar when
//      its `getMonth()` or `getFullYear()` is asked next. They are counted per file and held on a map that may only shrink, in BOTH directions: a new one fails, and so does a conversion that leaves its
//      entry behind (each is listed with the reason the browser's clock is the right one). `Date.now()` and `new Date(value)` are not counted: the first is an instant, the second is a given date.
//
// WHAT IT DOES NOT SEE
//   A day read through a Date built from other parts, or a clock handed in from a parent; the comparison of a stored date with a local one is the day-count guard's (a-day-count-comes-from-the-one-helper).
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");
const ROOTS = ["app", "components", "lib"];

function sources(): string[] {
  const out: string[] = [];
  const walk = (dir: string) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      if (entry.name === "node_modules" || entry.name.startsWith(".")) continue;
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (/\.(ts|tsx)$/.test(entry.name) && !/\.test\.(ts|tsx)$/.test(entry.name)) out.push(path.relative(WEB, full).split(path.sep).join("/"));
    }
  };
  for (const root of ROOTS) walk(path.join(WEB, root));
  return out.sort();
}

const code = (rel: string) => stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));

/** `todayLocalISO`, by name. */
export const BROWSER_DAY_HELPER = /\btodayLocalISO\b/;
/** `toLocalISO(new Date())`, the same thing written out. */
export const BROWSER_DAY_WRITTEN_OUT = /\btoLocalISO\s*\(\s*new\s+Date\s*\(\s*\)\s*\)/;
/** A bare `new Date()` not read as an instant on the spot. */
export const BARE_CLOCK = /\bnew\s+Date\s*\(\s*\)(?!\s*\.\s*(?:getTime|toISOString|valueOf|getTimezoneOffset)\s*\()/g;

/** A Date built from the instant (\`new Date(Date.now() + n)\`): turned into a calendar day it is the BROWSER's day plus n, in a different frame from India's day beside it (found in the deadlines screen's week window). */
export const INSTANT_AS_A_DATE = /\bnew\s+Date\s*\(\s*Date\.now\s*\(\s*\)/g;

export const bareClockReads = (src: string): number => (src.match(BARE_CLOCK) ?? []).length + (src.match(INSTANT_AS_A_DATE) ?? []).length;

/**
 * The files that read the browser's clock on purpose, how many times, and why. A conversion removes an entry; a new read cannot be added without saying here why the browser's own clock is the right
 * one. There are three, and none is a firm's day: a greeting is the reader's own hour, and two fallbacks answer an unreadable ISO string with a Date that is never shown as a day.
 */
const BARE_CLOCK_READS: Record<string, { count: number; why: string }> = {
  "app/DashboardContent.tsx": { count: 1, why: "the greeting (good morning/afternoon) is the reader's own hour, not the firm's day" },
  "app/calendar/page.tsx": { count: 2, why: "the fallback when an ISO string cannot be read; a day that does not exist is never drawn from it" },
};

test("todayLocalISO is named nowhere, and toLocalISO(new Date()) is not its spelling", () => {
  const offenders: string[] = [];
  for (const rel of sources()) {
    const src = code(rel);
    if (BROWSER_DAY_HELPER.test(src)) offenders.push(`${rel}: names todayLocalISO`);
    if (BROWSER_DAY_WRITTEN_OUT.test(src)) offenders.push(`${rel}: toLocalISO(new Date())`);
  }
  assert.deepEqual(offenders, [],
    "a firm's day is India's: use todayIstISO() from lib/dates/format (the browser's own calendar is a day out for part of every day in another zone):\n  " + offenders.join("\n  "));
});

test("the bare browser-clock reads are held on a map that only shrinks, in both directions", () => {
  const found: Record<string, number> = {};
  for (const rel of sources()) {
    const n = bareClockReads(code(rel));
    if (n) found[rel] = n;
  }
  const grew: string[] = [];
  const shrank: string[] = [];
  for (const rel of Object.keys({ ...found, ...BARE_CLOCK_READS }).sort()) {
    const have = found[rel] ?? 0, held = BARE_CLOCK_READS[rel]?.count ?? 0;
    if (have > held) grew.push(`${rel}: ${have} read(s), ${held} held`);
    if (have < held) shrank.push(`${rel}: ${have} read(s), ${held} held (lower its entry)`);
  }
  assert.deepEqual(grew, [], "a screen reads the browser's clock for a day: use todayIstISO() (lib/dates/format) and do not add an entry:\n  " + grew.join("\n  "));
  assert.deepEqual(shrank, [], "these are converted: lower or delete their entries in BARE_CLOCK_READS:\n  " + shrank.join("\n  "));
});

test("the detector sees the spellings it says it sees", () => {
  assert.ok(BROWSER_DAY_HELPER.test("import { todayLocalISO } from '@/lib/dateMath'") && BROWSER_DAY_HELPER.test("x = todayLocalISO()"));
  assert.ok(!BROWSER_DAY_HELPER.test("todayLocalISOs") && !BROWSER_DAY_HELPER.test("todayIstISO()"));
  assert.ok(BROWSER_DAY_WRITTEN_OUT.test("toLocalISO(new Date())") && BROWSER_DAY_WRITTEN_OUT.test("toLocalISO( new  Date( ) ).slice(0, 7)"));
  assert.ok(!BROWSER_DAY_WRITTEN_OUT.test("toLocalISO(new Date(2026, 3, 1))") && !BROWSER_DAY_WRITTEN_OUT.test("toLocalISO(d)"));
  assert.equal(bareClockReads("const now = new Date(); const m = now.getMonth();"), 1);
  assert.equal(bareClockReads("function f(today: Date = new Date()) {}"), 1);
  assert.equal(bareClockReads("new Date().getFullYear() + new Date().getMonth()"), 2);
  assert.equal(bareClockReads("new Date().getTime() + new Date().toISOString() + Date.now() + new Date(value) + new Date(2026, 3, 1) + new Date().valueOf()"), 0);
  assert.equal(bareClockReads("toLocalISO(new Date(Date.now() + 7 * 86400000))"), 1, "an instant turned into the browser's calendar day is a clock read");
  assert.equal(bareClockReads("new Date( Date.now( ) - 1000 )"), 1);
});

test("the helper is gone from lib/dateMath and todayIstISO is exported from lib/dates/format", () => {
  assert.ok(!/export function todayLocalISO\b/.test(code("lib/dateMath.ts")));
  assert.ok(/export function todayIstISO\b/.test(code("lib/dates/format.ts")));
  assert.ok(/currentFinancialYearLabel\(d\?: Date\)/.test(code("lib/dateMath.ts")) && /todayIstISO\(\)/.test(code("lib/dateMath.ts")),
    "currentFinancialYearLabel() with no date must read India's day");
});
