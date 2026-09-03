// Payroll amounts and rates go through the exact parsers. Run with:
//   node --experimental-strip-types --test scripts/payroll-money-is-exact.test.ts
//
// WHY THIS EXISTS
//     CLAUDE.md records that all 61 money call sites across 28 files were
//     converted to lib/money/rupeeInput.ts and that "there is no longer a
//     second way". The payroll forms were a second way, and stayed one until
//     2026-09-04:
//
//         basic_paise: rsToP(parseFloat(form.basic_rs) || 0)
//
//     parseFloat("1,25,000") is 1. A CA typing an amount the way Indian
//     amounts are grouped set a basic salary of ONE RUPEE, and everything
//     downstream — HRA, DA, the PF wage, the s.192 projection, the payslip,
//     the ECR — followed it without complaint. parseFloat("") is NaN, which
//     JSON.stringify sends as null.
//
//     The PERCENTAGES were the half that survived the first sweep, on all
//     three payroll forms and in the CSV importer. A rate is not money, but
//     "1,0" read as 1% where the CA meant 10% is money by the time it reaches
//     the payslip — and HRA feeds s.10(13A) and Annexure II.
//
//     The parsers REFUSE (null) rather than coerce. That is the point: a
//     rejected field is a question for the CA; a coerced one is a wrong number
//     nobody sees.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.join(import.meta.dirname, "..");
const FILES = [
  "app/payroll/page.tsx",
  "app/clients/[id]/payroll/page.tsx",
];

/** A file with its comments stripped — the assertions are about CODE, and the
 *  notes left behind quote the very forms they replaced. */
function code(rel: string): string {
  return fs.readFileSync(path.join(ROOT, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
}
const src = (rel: string) => fs.readFileSync(path.join(ROOT, rel), "utf8");

test("no payroll form parses a number with parseFloat", () => {
  for (const f of FILES) {
    assert.doesNotMatch(code(f), /parseFloat\s*\(/,
      `${f} must use the exact parsers, not parseFloat`);
  }
});

test("the float-multiplying helper is gone with its last caller", () => {
  // rsToP was Math.round(rs * 100) — the second half of the forbidden form.
  assert.doesNotMatch(code("app/payroll/page.tsx"), /function rsToP/,
    "rsToP must not come back; paiseFromRupeeInput never multiplies");
});

test("amounts and rates both come from lib/money/rupeeInput", () => {
  const a = src("app/payroll/page.tsx");
  assert.match(a, /import \{ paiseFromRupeeInput, bpsFromPercentInput \} from "@\/lib\/money\/rupeeInput"/);
  const b = src("app/clients/[id]/payroll/page.tsx");
  assert.match(b, /import \{ paiseFromRupeeInput, bpsFromPercentInput \} from "@\/lib\/money\/rupeeInput"/);
});

test("a field the parser refuses stops the save instead of becoming a number", () => {
  const a = src("app/payroll/page.tsx");
  // The employee form: all four fields checked, and the save returns.
  assert.match(a, /if \(basicPaise === null \|\| otherPaise === null \|\| hraBps === null \|\| daBps === null\)/,
    "every parsed field must be checked before the payload is built");
  assert.match(a, /is not a number|are not numbers/,
    "and the CA must be told which field");

  const b = src("app/clients/[id]/payroll/page.tsx");
  assert.match(b, /const hraBps = bpsFromPercentInput\(form\.hra_percent\);\s*\n\s*if \(hraBps === null\)/,
    "the per-client employee form must refuse a bad HRA percentage");
  assert.match(b, /if \(basicBps === null \|\| hraBps === null\)/,
    "a salary STRUCTURE is applied to a whole roster; a bad percentage there is wrong every month");
});

test("the CSV importer rejects a bad percentage the way it rejects a bad amount", () => {
  const a = src("app/payroll/page.tsx");
  // Amounts already skipped the row and reported. Percentages did not.
  assert.match(a, /const hraBps = bpsFromPercentInput\(row\.hra_percent \?\? "40"\);/,
    "the importer must parse the percentage exactly");
  assert.match(a, /must be plain percentages, without commas/,
    "a refused percentage must reject the ROW, not silently take a default");
  assert.match(a, /if \(row\.hra_percent && bpsFromPercentInput\(row\.hra_percent\) === null\)/,
    "validateRow must show it before the import runs, as it does for amounts");
});
