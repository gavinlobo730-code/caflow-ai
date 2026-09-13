// A gap the payroll run NAMES has somewhere to be fixed, and the editor opens
// on the roster the gap is about.
//
// Run with:
//   node --experimental-strip-types --test scripts/a-named-attendance-gap-can-be-filled-in.test.ts
//
// WHAT WAS WRONG (PAY-15)
//     The client payroll tab reads `attendance_gaps` off the run and prints
//     them — "Priya Sharma: no attendance entered for this month — paid a full
//     month …" — and then tells the CA to "fix these and create it again".
//     From that tab there was no way to. The editor is at
//     `/payroll/attendance`, nothing pointed at it, and migration 328 REFUSES
//     to finalise a run with an unresolved gap, so the instruction was the only
//     route forward and it was a dead end.
//
//     And the editor itself listed EVERY employee in the firm, unfiltered. A
//     firm running payroll for eight clients showed one roster of everybody,
//     which for a per-client, per-month obligation is a list nobody can work
//     through — and its CSV export carried the whole firm under a filename
//     that named neither.
//
// THE RULE, WHICH IS THE DURABLE HALF
//     THERE IS EXACTLY ONE ATTENDANCE EDITOR. The fix is a link carrying the
//     client and the month, not a second editor on the payroll tab — two
//     editors of one table drift, which is the mistake CLAUDE.md keeps having
//     to record. And whatever the editor SHOWS is what it EXPORTS: a table
//     scoped to one client whose export quietly carried the firm is a leak
//     between clients, not a cosmetic difference.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const EDITOR = "app/payroll/attendance/page.tsx";
const CLIENT_TAB = "app/clients/[id]/payroll/page.tsx";

function read(rel: string): string {
  return fs.readFileSync(path.join(WEB, rel), "utf8");
}
/** Comments blanked, so a note ABOUT a defect is not read as the defect. */
function code(src: string): string {
  return src.replace(/\/\*[\s\S]*?\*\//g, " ").replace(/^\s*\/\/.*$/gm, " ");
}

test("the payroll tab points at the attendance editor, carrying the client and the month", () => {
  const src = code(read(CLIENT_TAB));
  assert.match(
    src,
    /\/payroll\/attendance\?client=\$\{encodeURIComponent\(clientId\)\}&month=\$\{encodeURIComponent\(month\)\}/,
    "the gap panel must link to the editor with THIS client and THIS month — "
    + "a bare /payroll/attendance lands on the whole firm and on today's month, "
    + "which is not the month the run reported",
  );
});

test("the link appears only where an attendance gap was actually named", () => {
  const src = code(read(CLIENT_TAB));
  assert.match(
    src,
    /runGaps\.some\([\s\S]{0,120}?attendance/i,
    "a permanent link would read as a step every run needs; it belongs on the "
    + "panel that named the gap",
  );
});

test("there is exactly one attendance editor", () => {
  // The fix for a dead-end instruction is a link, never a second editor. Two
  // editors of one table drift, and this one enforces an identity
  // (days_present + CL + SL + EL + LOP = working_days) that a copy would not.
  const editors: string[] = [];
  const walk = (dir: string) => {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      if (e.name === "node_modules" || e.name === ".next" || e.name.startsWith(".")) continue;
      const full = path.join(dir, e.name);
      if (e.isDirectory()) { walk(full); continue; }
      if (!/\.tsx$/.test(e.name)) continue;
      const src = code(fs.readFileSync(full, "utf8"));
      // What makes a file an EDITOR rather than a reader: it saves attendance.
      if (/saveAttendance\s*\(/.test(src) || /payload[\s\S]{0,80}casual_leaves/.test(src)) {
        editors.push(path.relative(WEB, full));
      }
    }
  };
  walk(path.join(WEB, "app"));
  walk(path.join(WEB, "components"));
  assert.deepEqual(editors, [EDITOR],
    `attendance is edited in ${editors.length} places — there must be exactly one`);
});

test("the editor hydrates the client and the month from the link", () => {
  const src = code(read(EDITOR));
  assert.match(src, /URLSearchParams\(window\.location\.search\)/,
    "read off window.location: apps/web is a static export and useSearchParams "
    + "forces a Suspense boundary this page otherwise needs none of");
  assert.match(src, /\.get\("client"\)/, "the client must be hydrated");
  assert.match(src, /\.get\("month"\)/, "the month must be hydrated");
  // The YEAR specifically, and matched on the HYDRATION rather than on the
  // name: `setAttYear(` also appears on the year input's own onChange, so a
  // bare name check passes with the hydration half deleted.
  assert.match(src, /setAttYear\(Number\(m\[1\]\)\)/,
    "a month of 2026-04 must set the YEAR too — the editor keeps month and "
    + "year as separate controls, and hydrating only the month lands April "
    + "of whatever year the page opened on");
  assert.match(src, /setAttMonth\(Number\(m\[2\]\)\)/, "and the month");
});

test("the roster on screen is derived once, and the export reads the same list", () => {
  const src = code(read(EDITOR));
  assert.match(src, /const rosterOnScreen =/,
    "one derivation, so the table, the export and the empty state cannot disagree");
  // The three consumers. `employees` may still be read for the client PICKER
  // and for the leave-balance tab, which are firm-wide by nature.
  assert.match(src, /exportRows: AttendanceExportRow\[\] = rosterOnScreen\.map/,
    "the CSV must export what is on screen — an export carrying the whole firm "
    + "while the table shows one client is a leak between clients");
  assert.match(src, /\{rosterOnScreen\.map\(emp => \{/,
    "the table body must render the filtered roster");
  assert.match(src, /\{rosterOnScreen\.length === 0 \?/,
    "the empty state must be about what is on screen");
});

test("a client-scoped export says which client in its filename", () => {
  const src = code(read(EDITOR));
  assert.match(src, /attendance-\$\{attClient/,
    "two clients exported for one month would otherwise be the same filename twice");
});

test("saving still sends only what the CA touched, grouped by its own client", () => {
  // The filter is about what is SHOWN. It must not become a filter on what is
  // SAVED: a CA who edits one client, switches, and edits another must have
  // both saved, and each row goes to its own client's endpoint.
  const src = code(read(EDITOR));
  assert.match(src, /employees\.filter\(e => touched\.has\(e\.id\)/,
    "save reads `employees`, not the filtered roster");
  assert.match(src, /byClient\[emp\.client_id\] \?\?= \[\]/,
    "rows are grouped by their own client before being sent");
});
