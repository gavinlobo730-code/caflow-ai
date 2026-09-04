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
// The employee FORM moved to components/payroll/AddEmployeeModal.tsx on
// 2026-09-04, when the roster became its own screen (/payroll/people). The
// invariants are unchanged and follow the code.
const FORM = "components/payroll/AddEmployeeModal.tsx";
const FILES = [
  FORM,
  "app/payroll/page.tsx",
  "app/payroll/people/page.tsx",
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
  for (const f of FILES) {
    assert.doesNotMatch(code(f), /function rsToP/,
      `rsToP must not come back in ${f}; paiseFromRupeeInput never multiplies`);
  }
});

test("amounts and rates both come from lib/money/rupeeInput", () => {
  const a = src(FORM);
  assert.match(a, /import \{ paiseFromRupeeInput, bpsFromPercentInput \} from "@\/lib\/money\/rupeeInput"/);
  const b = src("app/clients/[id]/payroll/page.tsx");
  assert.match(b, /import \{ paiseFromRupeeInput, bpsFromPercentInput \} from "@\/lib\/money\/rupeeInput"/);
});

test("a field the parser refuses stops the save instead of becoming a number", () => {
  const a = src(FORM);
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

test("no payroll screen keeps a second CSV importer", () => {
  // This test used to assert the BROWSER importer parsed percentages exactly.
  // That importer is gone: the whole file now goes to
  // POST /api/payroll/employees/import, which validates it as a whole, refuses
  // it as a whole, and is idempotent on employee_code.
  //
  // The guarantee did not disappear with it — it MOVED, and moving it found a
  // real gap. domain/payroll/employee_import._percent stripped commas the way
  // the amount parser does, so "1,0" was read as 10% where the browser had
  // always refused it. A percentage is never grouped; only an amount is.
  // apps/api's test_a_comma_in_a_percentage_is_refused_even_though_one_in_an_amount_is_not
  // now holds that, against the importer itself rather than a copy of it.
  //
  // What has to stay true HERE is that no screen grows a second one back.
  for (const f of FILES) {
    assert.doesNotMatch(code(f), /bpsFromPercentInput\(row\./,
      `${f} must not parse import rows itself — the server owns the file`);
    assert.doesNotMatch(code(f), /paiseFromRupeeInput\(row\./,
      `${f} must not parse import rows itself — the server owns the file`);
  }
});
