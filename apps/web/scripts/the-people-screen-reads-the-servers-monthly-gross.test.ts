// The People screen's monthly figure is the server's. Run with:
//   node --experimental-strip-types --test scripts/the-people-screen-reads-the-servers-monthly-gross.test.ts
//
// WHY THIS EXISTS
//     The roster column added basic, HRA and DA in the browser (`Math.round(basic * pct / 100)`, a floating product) and
//     was headed "Monthly CTC". The slip rounds the same percentage as an exact decimal half-up, so the two part ways
//     by a paisa on some pairs (a basic of Rs 4,46,138.75 with DA at 9.2% is 4104477 on the slip and 4104476 in the
//     browser's formula), and CTC is gross plus the employer's PF, ESI, EDLI and admin charge, which this was not.
//     The server serves `full_month_gross_paise` on each roster row now (apps/api/tests/
//     test_the_people_screen_shows_the_servers_monthly_gross.py holds the number); this holds that the browser
//     neither computes it nor calls it CTC.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.join(import.meta.dirname, "..");
const PEOPLE = "app/payroll/people/page.tsx";
const SHARED = "components/payroll/shared.ts";

function code(rel: string): string {
  return fs.readFileSync(path.join(ROOT, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
}

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of fs.readdirSync(path.join(ROOT, dir), { withFileTypes: true })) {
    const rel = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name !== "node_modules" && entry.name !== ".next") walk(rel, out);
    } else if (/\.(ts|tsx)$/.test(entry.name) && !/\.test\./.test(entry.name)) out.push(rel);
  }
  return out;
}

test("the roster column reads the server's figure and shows a dash when there is none", () => {
  const src = code(PEOPLE);
  assert.match(src, /e\.full_month_gross_paise \?\? null/, "the sort and filter value is the server's, null when absent");
  assert.match(src, /e\.full_month_gross_paise == null \? "—" : formatPaise\(e\.full_month_gross_paise\)/,
    "an absent figure is a dash, never a zero or a recomputed number");
});

test("the column is not headed CTC", () => {
  const src = code(PEOPLE);
  assert.doesNotMatch(src, /header:\s*"Monthly CTC"/, "cost to company includes the employer's contributions; this is gross");
  assert.match(src, /header:\s*"Monthly gross"/);
});

test("nothing in the browser adds an employee's pay up from basic and a percentage", () => {
  const offenders: string[] = [];
  for (const rel of [...walk("app"), ...walk("components"), ...walk("lib")]) {
    const src = code(rel);
    // A percentage of BASIC. Converting a basis-point input to the percent the API takes (`hraBps / 100`) is not one.
    if (/basic\w*\s*\*\s*[\w.?]*(hra|da)_percent|(hra|da)_percent[\w.?]*\s*\*\s*[\w.?()]*basic/i.test(src)) offenders.push(rel);
    if (/employeeGrossPaise/.test(src)) offenders.push(`${rel} (employeeGrossPaise)`);
  }
  assert.deepEqual(offenders, [], "the percentage of basic is the server's: GET /api/payroll/employees serves the gross");
});

test("the Employee type carries the server's field", () => {
  const src = fs.readFileSync(path.join(ROOT, SHARED), "utf8");
  assert.match(src, /full_month_gross_paise\?: number \| null;/);
});
