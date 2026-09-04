// The attendance page saves what the CA touched, through the API. Run with:
//   node --experimental-strip-types --test scripts/attendance-is-not-a-default.test.ts
//
// WHY THIS EXISTS
//     This page was the only writer of public.attendance and it wrote straight
//     through PostgREST:
//
//         const rows = Object.values(attendance).map(...)
//         await sb.from("attendance").upsert(rows, {...})
//
//     `attendance` is the editor's state, and the editor SEEDS a default row —
//     26 working days, 26 present, no leave — for every employee in the firm
//     that has none. So one press of Save wrote a confident, explicit full
//     month for the entire roster, touched or not.
//
//     Migration 324 had just added payroll_slips.attendance_entered so a run
//     could name the people nobody had entered anything for, and PR #410 put
//     those gaps on screen. After one Save a row existed for everybody, the
//     flag read true for everybody, and it asserted that a human had confirmed
//     something no human looked at. There was never a gap to report again.
//
//     The shape is pinned here rather than left to whoever next touches the
//     file, because the regression is invisible: it produces MORE saved data,
//     not less, and nothing on the screen looks wrong.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.join(import.meta.dirname, "..");
const PAGE = "app/payroll/attendance/page.tsx";
const src = fs.readFileSync(path.join(ROOT, PAGE), "utf8");

/** Comments stripped — these assertions are about CODE, and the notes in this
 *  file quote the very forms they replaced. */
const code = src
  .replace(/\/\*[\s\S]*?\*\//g, "")
  .replace(/^\s*\/\/.*$/gm, "");

test("the page no longer writes public.attendance directly", () => {
  assert.doesNotMatch(code, /from\("attendance"\)\s*\.upsert/,
    "attendance goes through the API, where the identity is enforced");
  assert.match(code, /api\.payroll\.saveAttendance\(/);
});

test("a save sends only the employees the CA touched", () => {
  assert.doesNotMatch(code, /Object\.values\(attendance\)\.map/,
    "saving the whole editor is what wrote a full month for the entire firm");
  assert.match(code, /employees\.filter\(e => touched\.has\(e\.id\)/);
});

test("editing a row is what marks it savable", () => {
  // Without this the save has to guess, and the old guess was "everything".
  assert.match(code, /setTouched\(prev => new Set\(prev\)\.add\(empId\)\)/);
});

test("an imported CSV row is marked touched too", () => {
  // An import that did not mark them would silently save nothing.
  const importBlock = code.slice(code.indexOf("onImport"));
  assert.match(importBlock, /setTouched\(prev => new Set\(prev\)\.add\(empId\)\)/);
});

test("the importer rejects a day count that is not a number", () => {
  // `parseInt(row.working_days ?? "26") || 26` turned an unparseable value into
  // a confident 26 — the seeded-row fault, one column down.
  assert.doesNotMatch(code, /parseInt\(row\.working_days \?\? "26"\) \|\| 26/);
  assert.match(code, /is not a whole number of days/);
});

test("loss of pay is NOT sent — the server derives it", () => {
  // A sent value that contradicts the others is refused rather than corrected,
  // so sending the floored one would make every over-count a 422 the CA cannot
  // explain from what is on screen.
  const saveBlock = code.slice(code.indexOf("async function saveAttendance"),
                               code.indexOf("async function saveLeaveBalance"));
  assert.doesNotMatch(saveBlock, /lop_days/);
  assert.match(saveBlock, /earned_leaves: row\.earned_leaves/);
});

test("a row with no saved attendance says so on the row", () => {
  assert.match(code, /const \[entered, setEntered\] = useState<Set<string>>/);
  assert.match(src, /Not entered — the run will assume a full month/);
});

test("days that add up to more than the month are shown, not floored", () => {
  // calcLOP's Math.max(0, …) is what made 26 present + 4 days' leave a free
  // full month. The raw remainder is now rendered as the contradiction it is.
  assert.match(code, /function rawLOP\(row: AttendanceRow\): number/);
  assert.match(code, /const remainder = rawLOP\(row\)/);
  assert.match(src, /days\s*\n?\s*entered vs \{row\.working_days\} working/);
});

test("the server's refusal reaches the CA verbatim", () => {
  // The 422 names the employee and the field. A generic "couldn't save" throws
  // away the only useful part of it.
  assert.match(code, /failures\.push\(res\.error \|\| res\.detail \|\|/);
});

test("the save is client-scoped, as every other write is", () => {
  assert.match(code, /byClient\[emp\.client_id\]/);
  assert.match(code, /client_id: clientId, month, rows/);
});
