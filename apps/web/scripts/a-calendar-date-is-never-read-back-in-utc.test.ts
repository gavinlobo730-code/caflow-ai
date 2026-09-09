// A calendar date is produced from LOCAL components, never read back out of a
// UTC instant. Run with:
//   node --experimental-strip-types --test scripts/a-calendar-date-is-never-read-back-in-utc.test.ts
//
// WHAT IS WRONG WITH `new Date().toISOString().slice(0, 10)`
//     It is not a calendar date. It is an instant, formatted in UTC. India is
//     UTC+5:30, so local midnight is 18:30 UTC on the PREVIOUS day: between
//     00:00 and 05:30 IST every one of these returns YESTERDAY.
//
//     Where that landed was not cosmetic. It was the default value of the
//     invoice date, the purchase-bill date, both credit-note dates and both
//     debit-note dates — a Rule 46(b) particular of a tax invoice, and the date
//     that decides which return period the supply falls in. A CA working late,
//     which is the whole of March and most of a quarter end, got a document
//     dated a day early and nothing said so.
//
//     The same shape appears on a locally-BUILT Date: `new Date(y, m, 0)` is
//     local midnight on the last day of the month, and .toISOString() reads it
//     back in UTC as 18:30 the day before — so app/gst/page.tsx computed a
//     filing period that ended one day early.
//
// WHY THIS IS A TEST AND NOT A COMMENT
//     lib/dateMath.ts has existed for a long time. Its header already explains
//     the IST shift in full and already names todayLocalISO() as "the safe
//     replacement for new Date().toISOString().slice(0, 10) / .split("T")[0]".
//     lib/dates/periods.ts says it again. lib/sales/dateMath.ts says it a third
//     time. On 2026-09-09 there were still fifty live sites doing exactly that,
//     across thirty files.
//
//     That is the money-parser lesson in CLAUDE.md, repeated: the correct
//     helper existed, the prose said to use it, and nothing checked. So this
//     states the RULE.
//
// THE RULE, IN TWO DIRECTIONS
//   1. TRUNCATION — a toISOString() result may never be cut down to a date.
//      A full ISO timestamp is fine and is the correct thing to send for a
//      timestamptz column (created_at, updated_at, ca_approved_at); it is the
//      SLICING that turns an instant into the wrong calendar day. Naming the
//      truncation rather than toISOString() itself is what makes the rule
//      precise instead of a ban with thirty exemptions.
//   2. ONE FORMATTER — no module may hand-roll its own
//      `${getFullYear()}-${getMonth()+1}-${getDate()}`. There were four. A
//      fourth copy is correct today and is the thing that drifts.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.join(import.meta.dirname, "..");

/** Source with comments stripped — the assertions are about CODE, and the
 *  notes left behind quote the very forms they replaced. */
function code(rel: string): string {
  return fs.readFileSync(path.join(ROOT, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "")
    .replace(/\/\/.*$/gm, "");
}

/** Every .ts/.tsx under apps/web, excluding node_modules, build output and
 *  scripts/ (these tests quote the forms they forbid). */
function sources(): string[] {
  const out: string[] = [];
  const skip = new Set(["node_modules", ".next", "out", "scripts", ".turbo"]);
  (function walk(dir: string) {
    for (const e of fs.readdirSync(path.join(ROOT, dir), { withFileTypes: true })) {
      const rel = path.join(dir, e.name);
      if (e.isDirectory()) { if (!skip.has(e.name)) walk(rel); continue; }
      if (e.name.endsWith(".ts") || e.name.endsWith(".tsx")) out.push(rel);
    }
  })(".");
  return out.map((p) => p.replace(/^\.\//, ""))
            .filter((p) => !p.endsWith(".test.ts") && !p.endsWith(".test.tsx"));
}

// The ONE deliberate exception. lib/gst/rule37Period.ts builds its date with
// Date.UTC(...) and reads it back with toISOString(), so both halves are in the
// same frame and the answer is right in every timezone. That is a different
// thing from mixing frames, and it is the shape this rule is protecting: pick a
// frame and stay in it.
const UTC_BY_CONSTRUCTION = new Set(["lib/gst/rule37Period.ts"]);

// The modules that ARE the formatter. lib/sales/dateMath.ts is a deliberate
// duplicate of lib/dateMath.ts — its own header says so and says consolidating
// them is a separate cleanup — so it is listed rather than quietly tolerated.
const FORMATTER_MODULES = new Set(["lib/dateMath.ts", "lib/sales/dateMath.ts"]);

// ── 1. A toISOString() result is never truncated to a date ──────────────────

// Every spelling of "cut this instant down to YYYY-MM-DD", not one of them.
const TRUNCATED = new RegExp(
  String.raw`toISOString\s*\(\s*\)\s*\.\s*(?:` +
  String.raw`slice\s*\(\s*0\s*,\s*10\s*\)` + "|" +
  String.raw`substring\s*\(\s*0\s*,\s*10\s*\)` + "|" +
  String.raw`substr\s*\(\s*0\s*,\s*10\s*\)` + "|" +
  String.raw`split\s*\(\s*["'\x60]T["'\x60]\s*\)\s*\[\s*0\s*\]` +
  ")");

test("no calendar date is cut out of a UTC instant", () => {
  const offenders: string[] = [];
  for (const rel of sources()) {
    if (UTC_BY_CONSTRUCTION.has(rel)) continue;
    if (TRUNCATED.test(code(rel))) offenders.push(rel);
  }
  assert.deepEqual(offenders, [],
    "these read a calendar date out of a UTC instant — in IST that is " +
    "yesterday between 00:00 and 05:30. Use todayLocalISO() for today, or " +
    "toLocalISO(d) for a Date you built from local components " +
    "(lib/dateMath.ts).");
});

test("the one exception is genuinely UTC on both halves", () => {
  // If it ever stops constructing in UTC, the exemption stops being true and
  // this test says so rather than the allowlist silently covering a new bug.
  for (const rel of UTC_BY_CONSTRUCTION) {
    const src = code(rel);
    assert.match(src, /Date\.UTC\s*\(/,
      `${rel} is exempted because it builds its date with Date.UTC and reads ` +
      `it back in UTC. It no longer does, so the exemption is wrong.`);
  }
});

// ── 2. There is one local-date formatter ────────────────────────────────────

// `${d.getFullYear()}-${...getMonth() + 1...}-${...getDate()...}` in any
// spacing — a hand-rolled toLocalISO.
const HAND_ROLLED = /getFullYear\s*\(\s*\)[\s\S]{0,120}?getMonth\s*\(\s*\)\s*\+\s*1[\s\S]{0,120}?getDate\s*\(\s*\)/;

test("nobody writes their own local YYYY-MM-DD formatter", () => {
  const offenders: string[] = [];
  for (const rel of sources()) {
    if (FORMATTER_MODULES.has(rel)) continue;
    if (HAND_ROLLED.test(code(rel))) offenders.push(rel);
  }
  assert.deepEqual(offenders, [],
    "import toLocalISO from lib/dateMath instead of writing a fourth copy of " +
    "it. A copy is correct on the day it is written; that is what makes it " +
    "hard to notice when the original changes.");
});

// ── 3. The helper still does what the rule assumes ──────────────────────────

test("toLocalISO reads local components, not UTC", async () => {
  const { toLocalISO, todayLocalISO } = await import("../lib/dateMath.ts");
  // 31 May 2026 at local midnight. In IST this instant is 30 May 18:30 UTC, so
  // toISOString().slice(0, 10) would say "2026-05-30" — the exact defect.
  const lastDayOfMay = new Date(2026, 4, 31);
  assert.equal(toLocalISO(lastDayOfMay), "2026-05-31");
  // And the month-end idiom the GST period picker uses: day 0 of the next month.
  assert.equal(toLocalISO(new Date(2026, 5, 0)), "2026-05-31");
  assert.equal(toLocalISO(new Date(2026, 2, 0)), "2026-02-28");   // non-leap
  assert.equal(toLocalISO(new Date(2024, 2, 0)), "2024-02-29");   // leap
  assert.match(todayLocalISO(), /^\d{4}-\d{2}-\d{2}$/);
});
