// POST-A-468. The attendance Export wrote the editor's seeded 26 of 26 days present for an employee with no attendance row for the month, as if
// it were recorded. The rows now say which of three things they are, and a row nobody entered carries no days.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { toCsv } from "../lib/table/process.ts";
import { ATTENDANCE_STATUS, attendanceExportRows } from "../lib/payroll/attendanceExport.ts";

const seed = { working_days: 26, days_present: 26, casual_leaves: 0, sick_leaves: 0, earned_leaves: 0 };
const saved = { working_days: 26, days_present: 24, casual_leaves: 1, sick_leaves: 0, earned_leaves: 0 };
const figures = (r: typeof seed) => ({ lop: r.working_days - r.days_present - r.casual_leaves, net_pay_days: r.days_present + r.casual_leaves });
const roster = [{ id: "a", name: "Asha" }, { id: "b", name: "Ravi", designation: "Clerk" }, { id: "c", name: "Mira" }];

test("an employee nobody entered goes out with blank days and the status says the run assumes a full month", () => {
  const rows = attendanceExportRows(roster, { a: saved, b: seed, c: seed }, new Set(["a"]), new Set(["c"]), figures);
  const ravi = rows[1];
  assert.equal(ravi.status, ATTENDANCE_STATUS.notEntered);
  assert.match(ravi.status, /full month/);
  for (const key of ["working_days", "days_present", "casual_leaves", "sick_leaves", "earned_leaves", "lop", "net_pay_days"] as const) {
    assert.equal(ravi[key], null, `${key} of a not-entered row is blank, not the seed`);
  }
});

test("a saved row is written as read and marked entered; a typed one is marked as not saved", () => {
  const rows = attendanceExportRows(roster, { a: saved, b: seed, c: { ...seed, days_present: 20 } }, new Set(["a"]), new Set(["c"]), figures);
  assert.equal(rows[0].status, ATTENDANCE_STATUS.entered);
  assert.equal(rows[0].days_present, 24);
  assert.equal(rows[0].lop, 1);
  assert.equal(rows[2].status, ATTENDANCE_STATUS.edited);
  assert.equal(rows[2].days_present, 20);
});

test("an entered row that was then edited says it is not saved", () => {
  const rows = attendanceExportRows(roster.slice(0, 1), { a: saved }, new Set(["a"]), new Set(["a"]), figures);
  assert.equal(rows[0].status, ATTENDANCE_STATUS.edited);
});

test("the file writes a blank cell, never 26, for a not-entered employee", () => {
  const rows = attendanceExportRows(roster.slice(1, 2), { b: seed }, new Set(), new Set(), figures);
  const csv = toCsv(rows, [
    { key: "name", header: "Employee", accessor: (r) => r.name },
    { key: "status", header: "Status", accessor: (r) => r.status },
    { key: "working_days", header: "Working Days", accessor: (r) => r.working_days },
    { key: "days_present", header: "Days Present", accessor: (r) => r.days_present },
  ]);
  const line = csv.split("\n")[1];
  assert.doesNotMatch(line, /26/);
  assert.match(line, /,,$/);
});

test("the attendance page exports through the rule and says what a blank row means beside the button", () => {
  const src = readFileSync(join(import.meta.dirname, "..", "app", "payroll", "attendance", "page.tsx"), "utf8");
  assert.match(src, /attendanceExportRows\(rosterOnScreen, attendance, entered, touched/);
  assert.match(src, /\{ATTENDANCE_EXPORT_NOTE\}/);
  assert.match(src, /header: "Status"/);
});
