// The Tax Audit tracker offers "Completed" and "Filed" only to someone who may approve income tax work, and it counts
// the rows an update reached.
// Run with:
//   node --experimental-strip-types --test scripts/the-tax-audit-screen-asks-who-may-close-an-audit.test.ts
//
// WHY THIS EXISTS (POST-A-226, migration 496)
//     The tracker writes `tax_audits` straight from the browser, including `status = 'completed'` or `'filed'` with a
//     UDIN, an acknowledgement number and a filing date. That is a statement that the auditor has signed and the report
//     is on the portal, and the matching ITR filing record is a Manager's (it goes through the API's mark-filed door).
//     Migration 496 makes the database refuse both statuses, and any change to an audit already in either, to anyone who
//     may not approve (`income_tax:approve`). A policy that refuses an UPDATE finds no row to change and raises no
//     error, so two things have to be true of the screen or it would show a save that did not happen:
//       * a person who may not close an audit is not OFFERED the two statuses and is told, in words, why;
//       * the update asks for the ids it reached and treats none as "not saved".
//
// WHAT THIS DOES NOT DO
//     It reads source. The database half is `apps/api/tests/test_496_..._pg.py`, run against a real Postgres.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const PAGE = "app/income-tax/tax-audit/page.tsx";

function read(rel: string): string {
  return fs.readFileSync(path.join(WEB, rel), "utf8");
}

/** Code only: the notes in these files quote the very writes they replaced. */
function code(src: string): string {
  return src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
}

function walk(dir: string, out: string[] = []): string[] {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name === "node_modules" || e.name === ".next" || e.name.startsWith(".")) continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, out);
    else if (/\.(ts|tsx)$/.test(e.name) && !p.includes(`${path.sep}scripts${path.sep}`)) out.push(p);
  }
  return out;
}

test("the screen asks the permission the database asks, once the person is known", () => {
  const src = code(read(PAGE));
  assert.match(src, /usePermissions\(\)/, "the screen no longer asks what the person may do");
  assert.match(src, /can\(\s*"income_tax"\s*,\s*"approve"\s*\)/, "the permission asked is not income_tax:approve");
  assert.match(src, /!resolved\s*\|\|/, "until the map loads the form must not be narrowed (a gate that waited would never open)");
});

test("a person who may not close an audit is not offered the two statuses", () => {
  const src = code(read(PAGE));
  assert.match(src, /FINISHED_STATUSES\s*:\s*AuditStatus\[\]\s*=\s*\["completed",\s*"filed"\]/);
  assert.match(src, /STATUS_OPTIONS\.filter\(s => !FINISHED_STATUSES\.includes\(s\)\)/,
    "the status choices are not narrowed for a person who may not approve");
  assert.match(src, /statusChoices\.map\(/, "the select must render the narrowed list, not STATUS_OPTIONS");
});

test("an audit already completed or filed is read-only to a person who may not approve", () => {
  const src = code(read(PAGE));
  assert.match(src, /lockedForYou/);
  assert.match(src, /disabled=\{saving \|\| lockedForYou\}/, "Save must be disabled for a locked audit");
  assert.match(src, /disabled=\{lockedForYou\}/, "the status select must be disabled for a locked audit");
});

test("the update counts the rows it reached, because a refused update raises no error", () => {
  const src = code(read(PAGE));
  const at = src.indexOf('.from("tax_audits").update(');
  assert.notEqual(at, -1, "the update is gone — has the save moved?");
  const stmt = src.slice(at, src.indexOf(";", at));
  assert.match(stmt, /\.select\("id"\)/, "the update must ask for the ids it reached");
  assert.match(src.slice(at, at + 600), /reached\.length === 0/, "no row reached must be reported, not shown as saved");
});

test("a found record counts only while the form still names its client and year", () => {
  const src = code(read(PAGE));
  assert.match(src, /existingMatch\.client_id === form\.clientId/, "the match is not tied to the form's client");
  assert.match(src, /existingMatch\.financial_year === form\.financialYear/, "the match is not tied to the form's year");
  assert.match(src, /const target = editAudit \?\? \(matchIsForThisForm \? existingMatch : null\)/,
    "the save target must be the match only while it is for this form (an update keyed on a stale id rewrites the wrong audit)");
});

test("the fields copied from a found record are cleared when the pair no longer has one", () => {
  const src = code(read(PAGE));
  const at = src.indexOf("copiedFromMatch");
  assert.notEqual(at, -1, "the reset is gone");
  const eff = src.slice(at, at + 1100);
  for (const field of ["status: BLANK.status", 'udin: ""', 'ackNumber: ""', 'filingDate: ""']) {
    assert.ok(eff.includes(field), `the reset does not clear ${field}`);
  }
});

test("row security's refusal of a new row is worded, not quoted", () => {
  const src = code(read(PAGE));
  assert.match(src, /code === "42501"/, "a 42501 from the database would be shown as Postgres wrote it");
});

test("no other file writes the tax_audits table from the browser", () => {
  const writers: string[] = [];
  let seen = 0;
  for (const f of walk(WEB)) {
    const src = code(fs.readFileSync(f, "utf8"));
    if (!/\.from\(\s*["']tax_audits["']\s*\)/.test(src)) continue;
    seen++;
    if (/\.from\(\s*["']tax_audits["']\s*\)\s*\.(insert|update|upsert|delete)\(/.test(src)) {
      writers.push(path.relative(WEB, f));
    }
  }
  assert.ok(seen >= 1, "vacuity: no file reads tax_audits at all — has the scan broken?");
  assert.deepEqual(writers, [PAGE], "another file writes tax_audits: it needs the same rule, or the API");
});
