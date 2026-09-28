// Two payroll screens printed a raw ISO date string instead of a formatted
// one — "Due 2027-11-30" on the Bonus tab, "Joined 2022-01-15" on the
// Employee drawer — where every other date-bearing screen in the app goes
// through `formatDate` ("30 Nov 2027", "15 Jan 2022").
//
// Run with: node --experimental-strip-types --test scripts/payroll-date-formatting.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");

function read(rel: string): string {
  return stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));
}

test("the Bonus tab's due date is formatted, not printed raw", () => {
  const src = read("components/payroll/BonusRegister.tsx");
  assert.match(src, /import \{ formatDate \} from "@\/lib\/services\/formatting";/,
    "BonusRegister no longer imports the shared date formatter");
  assert.match(src, /Due \{formatDate\(data\.due_date\)\}/,
    "the due date is rendered as data.due_date directly, unformatted");
  assert.ok(!src.includes("Due {data.due_date}"),
    "the raw ISO due date is still interpolated straight into the sentence");
});

test("the Employee drawer's joining date is formatted, not printed raw", () => {
  const src = read("components/payroll/EmployeeDrawer.tsx");
  assert.match(src, /import \{ formatDate \} from "@\/lib\/services\/formatting";/,
    "EmployeeDrawer no longer imports the shared date formatter");
  assert.match(src, /Joined \{employee\.joining_date \? formatDate\(employee\.joining_date\) : /,
    "the joining date is not run through formatDate when it is present");
  assert.ok(!src.includes("Joined {employee.joining_date ||"),
    "the raw ISO joining date is still interpolated straight into the sentence");
});
