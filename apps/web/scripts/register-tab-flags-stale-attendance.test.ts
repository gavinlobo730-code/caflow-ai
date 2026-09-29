// The Register (RunsTab) slip view surfaces a "Recompute recommended" banner
// when the server says an employee's attendance changed after their slip was
// generated (apex-payroll-yearend-04, the code half).
//
// Run with:
//   node --experimental-strip-types --test \
//     scripts/register-tab-flags-stale-attendance.test.ts
//
// WHAT WAS WRONG
//     Attendance staleness was invisible: an employee's `attendance` row
//     could be entered or updated AFTER their `payroll_slips` row was
//     already generated for that wage month, and the Register tab kept
//     showing the stale slip figure with no indication anything had changed.
//     recomputeRun() was a manual button with no staleness prompt at all.
//
// THE FIX
//     The Slip type carries `attendance_changed_since_compute` (served by
//     GET /api/payroll/runs/{id}/slips), and the slip table renders a banner
//     naming how many employees are affected, pointing at the existing
//     Recompute action, plus a per-row marker on the affected employee(s).
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");
const PAGE = "app/clients/[id]/payroll/page.tsx";

function read(): string {
  return stripComments(fs.readFileSync(path.join(WEB, PAGE), "utf8"));
}

test("the Slip type carries the staleness flag", () => {
  const src = read();
  const m = /interface Slip \{[\s\S]*?\n\}/.exec(src);
  assert.ok(m, "interface Slip not found");
  assert.match(m[0], /attendance_changed_since_compute\?: boolean/);
});

test("a banner appears when any loaded slip is stale, naming Recompute", () => {
  const src = read();
  assert.match(src, /slips\.some\(s => s\.attendance_changed_since_compute\)/);
  assert.match(src, /Recompute recommended/);
  assert.match(src, /Use Recompute above to rebuild this month/);
});

test("the affected employee(s) are named, not just counted silently", () => {
  const src = read();
  assert.match(
    src,
    /slips\.filter\(s => s\.attendance_changed_since_compute\)\.length/,
  );
});

test("the per-row marker is scoped to the affected slip only", () => {
  const src = read();
  assert.match(src, /\{s\.attendance_changed_since_compute && \(/);
  assert.match(src, /title="Attendance changed since this slip was generated"/);
});
