// A SCREEN THAT COUNTS OR COLOURS A LATE OBLIGATION ASKS THE ONE RULE (POST-A-280, the screens). Run with:
//   node --experimental-strip-types --test scripts/the-compliance-screens-ask-the-one-overdue-rule.test.ts
//
// WHAT WAS WRONG
//   `lib/compliance/overdue.isOverdue` is the rule: not settled, and either moved to "overdue" by hand or due strictly before the CA's day.
//   Five screens (the client overview, the client Compliance tab, Reports, the income-tax tracker and the calendar) wrote
//   `filing_status !== "filed" && due_date < today` themselves, which is the rule only when nobody has moved an obligation to "overdue" with
//   a date still ahead: such a row was counted as late on the Deadlines screen and as open, not late, on these. The "upcoming" tests
//   (`!== "filed" && due_date >= today`) had the matching fault, so that row was listed as overdue and as upcoming at once.
//
// WHAT THIS HOLDS
//   * no screen or component writes a comparison of a compliance entry's due date with today beside a test of `filing_status !== "filed"`,
//     in either order, on one line or the next: they call `isOverdue` or `isUpcoming`;
//   * the five screens import the rule from `lib/compliance/overdue` and call it;
//   * the helper itself keeps the two lists exclusive (pinned in `lib/compliance/overdue.test.ts`).
// NOT COVERED: `practice/compliance`'s fallback (`o.overdue ?? ...`, kept for the redeploy window in which the backend does not send the
// server's own flag), `lib/compliance/calendarGroups` (an external MCA item has no status, only a date) and `lib/data/compliance.toEntry` (the one place
// the stored word and the date are first combined).
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.join(import.meta.dirname, "..");

function walk(dir: string, out: string[] = []): string[] {
  for (const e of fs.readdirSync(path.join(WEB, dir), { withFileTypes: true })) {
    const rel = path.posix.join(dir, e.name);
    if (e.isDirectory()) { if (e.name !== "node_modules" && e.name !== ".next") walk(rel, out); }
    else if (/\.tsx$/.test(e.name) && !/\.test\.tsx$/.test(e.name)) out.push(rel);
  }
  return out;
}

const SOURCES = [...walk("app"), ...walk("components")];
const read = (rel: string) => stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));

// A test of the filed word and a comparison of a due date with a day, in either order, within one expression (a line and the next).
const FILED_THEN_DATE = /filing_status\s*!==\s*"filed"[^;{}]{0,60}?\bdue_date\s*(?:<|>=|<=|>)(?!=)/;
const DATE_THEN_FILED = /\bdue_date\s*(?:<|>=|<=|>)[^;{}]{0,60}?filing_status\s*!==\s*"filed"/;

test("the walk finds the tree", () => {
  assert.ok(SOURCES.length > 300, `read only ${SOURCES.length} files`);
  assert.ok(SOURCES.includes("app/deadlines/page.tsx"));
});

test("no screen writes the late test of an obligation itself", () => {
  const found: string[] = [];
  for (const f of SOURCES) {
    const flat = read(f).replace(/\s*\n\s*/g, " ");
    for (const re of [FILED_THEN_DATE, DATE_THEN_FILED]) {
      const m = re.exec(flat);
      if (m) found.push(`${f}: ${m[0].slice(0, 90)}`);
    }
  }
  assert.deepEqual(found, [], "a screen decides itself whether an obligation is late: call isOverdue or isUpcoming from lib/compliance/overdue");
});

test("the five screens import the rule and call it", () => {
  for (const f of ["app/clients/[id]/overview/page.tsx", "app/clients/[id]/compliance/page.tsx", "app/reports/page.tsx", "app/income-tax/page.tsx", "app/calendar/page.tsx"]) {
    const src = read(f);
    assert.match(src, /from "@\/lib\/compliance\/overdue"/, `${f} does not import the rule`);
    assert.match(src, /\bisOverdue\(/, `${f} does not call isOverdue`);
  }
  for (const f of ["app/clients/[id]/overview/page.tsx", "app/income-tax/page.tsx"]) {
    assert.match(read(f), /\bisUpcoming\(/, `${f} lists upcoming obligations without isUpcoming`);
  }
});

test("the income-tax tracker gives a not-applicable entry its own label and keeps it out of the total", () => {
  const src = read("app/income-tax/page.tsx");
  assert.match(src, /na: "Not applicable"/, "a not-applicable entry prints as the raw word");
  assert.match(src, /const totalDue = entries\.filter\(\(e\) => e\.filing_status !== "na"\)\.length;/, "the total counts entries that are not due");
});

test("the calendar lists an obligation as upcoming only when it has an open row that is not already late", () => {
  assert.match(read("lib/compliance/calendarGroups.ts").replace(/\s+/g, " "), /g\.open - g\.overdue > 0 && g\.due_date >= todayISO/);
});

test("the patterns see what they are meant to see", () => {
  for (const sample of [
    'c.due_date < today && c.filing_status !== "filed"',
    'e.filing_status !== "filed" && e.due_date < today',
    'c.filing_status !== "filed" && c.due_date >= today',
  ]) assert.ok(FILED_THEN_DATE.test(sample) || DATE_THEN_FILED.test(sample), sample);
  for (const sample of ['t.due_date < today && t.status !== "completed"', 'c.filing_status === "filed"', 'filing_status !== "filed"; due_date = x']) {
    assert.ok(!(FILED_THEN_DATE.test(sample) || DATE_THEN_FILED.test(sample)), sample);
  }
});
