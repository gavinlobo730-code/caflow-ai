// The employee form collects what the statutory outputs actually need.
//   node --experimental-strip-types --test scripts/employee-form-captures-what-filing-needs.test.ts
//
// WHY THIS EXISTS
//     Three statutory builders in apps/api are finished, careful and correct —
//     domain/payroll/{ecr,esic}.py and the s.192 projection — and none of them
//     could be fed, because no screen collected their inputs:
//
//       * the EPFO ECR refuses a member whose UAN is absent or not 12 digits;
//       * the ESIC return needs the IP number;
//       * s.192 needs the JOINING DATE, or a mid-year joiner's tax is estimated
//         over twelve months instead of the months they actually work. The
//         2026-09-01 audit measured that at Rs 1,46,250 over-deducted on one
//         employee.
//
//     payroll_employees has held every one of these columns for some time, and
//     models/payroll.py::EmployeeIn has always ACCEPTED them. Only the forms
//     never asked. The firm-wide form captured PAN, gender and PT state; the
//     per-client one captured Aadhaar and department and no PAN at all.
//
//     So this is not a schema change or an API change. It is the form catching
//     up with an engine that was already ahead of it — and this test is what
//     stops a field being dropped in a future tidy-up, because nothing else in
//     the build would notice.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

// The FORM, not the page. It moved to components/payroll/AddEmployeeModal.tsx
// on 2026-09-04 when the roster became its own screen (/payroll/people); the
// invariant is unchanged and follows the code.
const FORM = path.join(import.meta.dirname, "..", "components/payroll/AddEmployeeModal.tsx");
const page = () => fs.readFileSync(FORM, "utf8");

// The importable column list the People screen offers. It now MIRRORS the
// server's domain/payroll/employee_import.COLUMNS — a Python parity test holds
// the two identical — so the columns are asserted against that list rather than
// against a second one the browser kept for itself.
const COLUMNS = path.join(import.meta.dirname, "..", "lib/imports/mappers.ts");
const columns = () => fs.readFileSync(COLUMNS, "utf8");

/** The fields a statutory output cannot be produced without. */
const REQUIRED_BY_A_FILING = [
  "uan",             // EPFO ECR
  "esi_number",      // ESIC return
  "joining_date",    // s.192 projection
  "bank_account_no", // salary payment file
  "bank_ifsc",
];

test("the form holds every identifier a filing needs", () => {
  const s = page();
  for (const f of REQUIRED_BY_A_FILING) {
    assert.match(s, new RegExp(`\\b${f}: employee\\?\\.${f} \\?\\? ""`),
      `${f} must be in the form's state`);
    assert.match(s, new RegExp(`form\\.${f}`), `${f} must be bound to an input`);
  }
});

test("every one of them is sent, and blank means null rather than empty string", () => {
  const s = page();
  // An empty string in a uuid- or date-shaped column is a different failure
  // from an absent one, and PostgREST will not coerce it.
  assert.match(s, /uan: form\.uan\.trim\(\) \|\| null/);
  assert.match(s, /esi_number: form\.esi_number\.trim\(\) \|\| null/);
  assert.match(s, /joining_date: form\.joining_date \|\| null/);
  assert.match(s, /bank_ifsc: form\.bank_ifsc\.trim\(\)\.toUpperCase\(\) \|\| null/);
});

test("each field says what cannot be produced without it", () => {
  // "Optional" is what gets a field left blank. The hint has to name the
  // consequence, because the consequence lands months later on a portal.
  const s = page();
  assert.match(s, /cannot go in the EPFO ECR/);
  assert.match(s, /cannot go in the ESIC return/);
  assert.match(s, /over-deducts/);
});

test("the CSV import carries them too", () => {
  // A migration is where a roster actually arrives. An import that could not
  // carry these would produce four hundred employees nobody can file for.
  //
  // The second half of this used to assert `uan: row.uan` — the BROWSER reading
  // each field off the row. That importer is gone: the whole file now goes to
  // POST /api/payroll/employees/import, which validates it as a whole, refuses
  // it as a whole, and is idempotent on employee_code. So what has to be true
  // here is only that the column is OFFERED; that the server reads it is
  // asserted in apps/api's test_the_employee_master_and_its_import.py, against
  // the importer itself rather than against a copy of it.
  const s = columns();
  for (const f of REQUIRED_BY_A_FILING) {
    assert.match(s, new RegExp(`key: "${f}"`), `${f} must be an importable column`);
  }
});
