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

test("every payroll screen takes its numbers from lib/money/rupeeInput", () => {
  // THE RULE, NOT A FILE'S IMPORT LINE. This used to require BOTH parsers in
  // BOTH files. The per-client payroll page stopped importing
  // paiseFromRupeeInput on 18-09-2026 -- not because it started coercing, but
  // because its employee form was DELETED (PAY-13: there were two employee
  // forms and they disagreed about what an employee is). A guard that names a
  // file's imports breaks on a move that does not break its rule, which is the
  // shape this repository keeps having to restate.
  //
  // What matters is that a screen parsing a typed number reaches for these and
  // nothing else. So: whatever each file parses, it parses exactly.
  for (const f of [FORM, "app/clients/[id]/payroll/page.tsx"]) {
    const body = src(f);
    const parsesRupees = /paiseFromRupeeInput\(/.test(body);
    const parsesPercent = /bpsFromPercentInput\(/.test(body);
    assert.ok(parsesRupees || parsesPercent,
      `${f} parses no typed number at all -- if that is right, take it off this list`);
    if (parsesRupees) {
      assert.match(body, /import \{[^}]*paiseFromRupeeInput[^}]*\} from "@\/lib\/money\/rupeeInput"/,
        `${f} must take paiseFromRupeeInput from the one module`);
    }
    if (parsesPercent) {
      assert.match(body, /import \{[^}]*bpsFromPercentInput[^}]*\} from "@\/lib\/money\/rupeeInput"/,
        `${f} must take bpsFromPercentInput from the one module`);
    }
  }
});

test("a field the parser refuses stops the save instead of becoming a number", () => {
  // THE EMPLOYEE FORM, wherever it lives. There is exactly one now, and these
  // assertions follow it rather than naming the screen it used to sit on.
  const a = src(FORM);
  assert.match(a, /if \(basicPaise === null \|\| otherPaise === null \|\| hraBps === null \|\| daBps === null\)/,
    "every parsed field must be checked before the payload is built");
  assert.match(a, /is not a number|are not numbers/,
    "and the CA must be told which field");
  // Aadhaar came across with the merge and is a refusal too: the backend only
  // ever sees four digits and cannot tell a truncated eleven from a right one.
  assert.match(a, /aadhaarDigits\.length !== 12/,
    "twelve digits or nothing, checked before the request");

  // THE SALARY STRUCTURE is a different form on a different screen, and it is
  // applied to a WHOLE ROSTER -- a bad percentage there is wrong every month.
  const b = src("app/clients/[id]/payroll/page.tsx");
  assert.match(b, /if \(basicBps === null \|\| hraBps === null\)/,
    "a salary structure must refuse a percentage the parser rejected");
});

test("there is exactly one employee form", () => {
  // PAY-13's own rule. Two forms meant which screen a CA happened to use
  // decided whether the employee had a UAN (domain/payroll/ecr.py REFUSES a
  // member without one), a PAN (s.206AA's 20% floor without it) or a joining
  // date (the s.192 projection annualises a mid-year joiner as a full year --
  // measured at Rs 1,46,250 on one employee).
  const page = src("app/clients/[id]/payroll/page.tsx");
  assert.match(page, /AddEmployeeModal/,
    "the client workspace must open the shared form");
  assert.doesNotMatch(page, /\/api\/payroll\/employees"/,
    "a second create path here is the defect coming back");
  // And the shared form carries what the deleted one held, or the merge lost
  // it. ASSERTED ON THE PAYLOAD, not on the file. The first version matched
  // each field name anywhere in the source and PASSED its own negative control
  // — deleting `employee_code` from the payload leaves the name in the form
  // state and on the input, so a field can be collected from the CA and then
  // silently dropped on the way to the server, which is the worst of both.
  const payload = src(FORM).match(/const payload = \{[\s\S]*?\n      \};/);
  assert.ok(payload, "the employee form must build one payload object");
  for (const field of ["employee_code", "date_of_birth", "aadhaar_last4"]) {
    assert.match(payload[0], new RegExp(`\\b${field}:`),
      `${field} was on the deleted form and must reach the SERVER, not just the form`);
  }
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
