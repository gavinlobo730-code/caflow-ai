// The firm Calendar shows the dates the compliance engine computed for each client
// and records a done tick on the server. Run with:
//   node --experimental-strip-types --test scripts/the-calendar-reads-the-obligations-the-engine-computed.test.ts
//
// WHY THIS EXISTS (practice_management-17)
//     `/calendar` generated deadlines in the browser: the 11th and the 20th for
//     EVERY client, advance-tax dates, AOC-4 and MGT-7 a day off the engine, no
//     QRMP or state-group rule, every deadline attached to all clients, and a done
//     tick in component state that vanished on refresh and was recorded nowhere.
//     `a-statutory-due-date-is-never-a-literal.test.ts` listed it as a KNOWN
//     DEFECT. These are the RULES, not a spelling of the old code: the screen
//     states no date, a tick is a server write, the read is bounded to what is on
//     screen, and a failed read is not shown as a quiet month.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.join(import.meta.dirname, "..");
const PAGE = "app/calendar/page.tsx";
const GROUPS = "lib/compliance/calendarGroups.ts";
const DATA = "lib/data/compliance.ts";
const GUARD = "scripts/a-statutory-due-date-is-never-a-literal.test.ts";

function code(rel: string): string {
  return fs.readFileSync(path.join(ROOT, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, "")
    .replace(/^\s*\/\/.*$/gm, "");
}

test("the calendar states no date of its own: no deadline is built from a literal month and day", () => {
  for (const rel of [PAGE, GROUPS]) {
    const src = code(rel);
    assert.doesNotMatch(src, /new Date\([^,()]+,\s*\d+,\s*\d+\)/,
      `${rel}: new Date(y, <month>, <day>) with both literal is a deadline written into a screen`);
    assert.doesNotMatch(src, /\bgenerateDeadlines\b|\bdone:\s*false\b/, `${rel}: the browser generator is gone`);
    assert.doesNotMatch(src, /\b(GSTR-?1|GSTR-?3B|GSTR-?9|Advance Tax|DIR-3 KYC)\b[^\n]*\b(11th|20th|31 (Dec|Jul|Oct|Jan|May)|15 (Jun|Sep|Dec|Mar)|30 Sep)\b/,
      `${rel}: a statutory date beside the name of a return`);
  }
});

test("it reads the obligation calendar, bounded to a window, through the data layer", () => {
  const src = code(PAGE);
  assert.match(src, /getObligationCalendar\(/);
  assert.match(src, /dateFrom/); assert.match(src, /dateTo/);
  const data = code(DATA);
  assert.match(data, /api\.complianceOps\.calendar\(/, "the endpoint that had no screen caller");
  assert.match(data, /date_from/); assert.match(data, /date_to/);
});

test("the page no longer reads clients straight over PostgREST", () => {
  const src = code(PAGE);
  assert.doesNotMatch(src, /getSupabaseClient|\.from\(\s*["']clients["']/);
  assert.match(src, /getClients\(/);
});

test("a tick is a server write through the one prompt, and not component state", () => {
  const src = code(PAGE);
  assert.match(src, /<MarkFiledModal\b/, "the same prompt as Deadlines: it asks the date the return was filed on");
  assert.match(src, /markObligationFiled\(/);
  assert.match(src, /describeFilingOutcome\(/, "what the server did about the period is shown, not discarded");
  assert.doesNotMatch(src, /toggleDone|setDeadlines/, "a done toggle held in state is the defect");
  assert.doesNotMatch(src, /localStorage|sessionStorage/);
  // the list is re-read after a tick, so what is shown is what the server holds
  assert.match(src, /await Promise\.all\(\[loadMonth\(\), loadAhead\(\)\]\)/);
});

test("a failed read is said to be one, and is not shown as a month with nothing due", () => {
  const src = code(PAGE);
  assert.match(src, /role="alert"/);
  assert.match(src, /Nothing below is a statement that no deadline falls in this month/);
  assert.match(src, /setMonth\(null\)/, "a failure clears the month rather than leaving the last one up");
});

test("the overdue panel is never narrowed to the month on screen", () => {
  const src = code(PAGE);
  // overdue comes from the today-anchored read, whose bucket the server never windows
  assert.match(src, /overdueGroups\(aheadGroups\)/);
  assert.doesNotMatch(src, /overdueGroups\(monthGroups\)/);
});

test("the MCA annual forms come from the company's own AGM, and the generated rows for them are left out", () => {
  const src = code(PAGE);
  assert.match(src, /api\.mca\.firmCalendar\(/);
  assert.match(src, /categoryOf\(e\.compliance_type\)\s*!==\s*"MCA"/,
    "a generated AOC-4/MGT-7 row carries a date counted from an AGM nobody recorded");
  assert.match(src, /without_agm_date/, "a company with no AGM date is named, not given a plausible one");
});

test("an obligation is named by the engine's own label, and the browser keeps no table of labels", () => {
  const groups = code(GROUPS);
  assert.match(groups, /period_label/);
  assert.doesNotMatch(groups, /["']GSTR-?3B["']\s*:\s*["']GSTR/, "no type -> label table");
});

test("the guard that listed the calendar as a known defect no longer lists it", () => {
  const guard = code(GUARD);
  assert.doesNotMatch(guard, /["']app\/calendar\/page\.tsx["']\s*:/,
    "the allowlist has no entry for app/calendar/page.tsx");
});

test("no route was added under /clients/[id] for it (decision D10)", () => {
  assert.equal(fs.existsSync(path.join(ROOT, "app/clients/[id]/calendar")), false);
});
