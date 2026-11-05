// A stored TIMESTAMP is shown as the Indian day it fell on, never cut to its first ten characters. Run with:
//   node --experimental-strip-types --test scripts/a-stored-stamp-is-shown-as-the-indian-day-never-cut-to-its-first-ten-characters.test.ts
//
// WHAT WAS WRONG
//     A `timestamptz` comes back from PostgREST in UTC, so `stamp.slice(0, 10)` is the UTC calendar date. Between 00:00 and 05:30 IST it is the
//     PREVIOUS day, and a screen that prints it says a bank reconciliation was completed, a firm was created, a rule was trusted or an article
//     was changed a day before it was. CLAUDE.md names this ("the Indian day is never read off the UTC clock") and the Python rule that holds it
//     cannot see a browser. `formatDate` (lib/dates/format) prints a timestamp as its date in IST and a bare date from its own digits, so it is
//     the one way to write either.
//
// THE RULE (stated by what is cut, not by a list of files)
//     A value whose last name ends in `_at` (`completed_at`, `created_at`, `trusted_at`, `changed_at`, `superseded_at`, `reopened_at`) is never
//     handed to `.slice(0, 10)`, directly or through `String(...)`. A column named `…_on` or `…_date` holds a calendar date and is not read here.
//
// WHAT THIS CANNOT SEE, AND SAYS SO
//     A stamp held in a variable with another name first (`const d = row.created_at; d.slice(0, 10)`), `.substring(0, 10)` or `.split("T")[0]`
//     spellings, and a stamp built in a template literal. It reads the field name, so a field named `…_at` that holds a date would be flagged.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");

function* walk(dir: string): Generator<string> {
  for (const e of fs.readdirSync(path.join(WEB, dir), { withFileTypes: true })) {
    const rel = path.posix.join(dir, e.name);
    if (e.isDirectory()) {
      if (["node_modules", ".next", "out"].includes(e.name)) continue;
      yield* walk(rel);
    } else if (/\.(ts|tsx)$/.test(e.name) && !/\.test\./.test(e.name) && !/\.d\.ts$/.test(e.name)) {
      yield rel;
    }
  }
}

/** `x.created_at.slice(0, 10)`, `x.created_at?.slice(0, 10)`, `String(x.created_at ?? "").slice(0, 10)` and `String(x.created_at).slice(0, 10)`. */
const STAMP_CUT = [
  /\b[A-Za-z_$][\w$]*_at\b\s*\??\.\s*slice\(\s*0\s*,\s*10\s*\)/g,
  /String\(\s*[^()]*\b[A-Za-z_$][\w$]*_at\b[^()]*\)\s*\.\s*slice\(\s*0\s*,\s*10\s*\)/g,
];

/** Cuts that are NOT a timestamp shown to a person. Frozen: it may only shrink, and each says why. */
const NOT_A_SHOWN_STAMP: Record<string, string> = {};

function cuts(src: string): string[] {
  const code = stripComments(src);
  return STAMP_CUT.flatMap((re) => [...code.matchAll(re)].map((m) => m[0]));
}

test("no screen cuts a stored timestamp to its first ten characters", () => {
  const offenders: string[] = [];
  let scanned = 0;
  for (const dir of ["app", "components", "lib"]) {
    for (const rel of walk(dir)) {
      scanned += 1;
      if (NOT_A_SHOWN_STAMP[rel]) continue;
      for (const c of cuts(fs.readFileSync(path.join(WEB, rel), "utf8"))) offenders.push(`${rel}: ${c}`);
    }
  }
  assert.ok(scanned > 400, `the scan saw only ${scanned} files, so it held nothing`);
  assert.deepEqual(offenders, [], "a stored timestamp cut to ten characters is the UTC day: show it with formatDate (lib/dates/format)");
});

test("the scan finds the spellings it is written for", () => {
  const seen = (s: string) => cuts(s).length;
  assert.equal(seen("{row.created_at.slice(0, 10)}"), 1);
  assert.equal(seen("{row.created_at?.slice(0,10)}"), 1);
  assert.equal(seen('{String(report.reconciliation.completed_at ?? "").slice(0, 10)}'), 1);
  assert.equal(seen("{String(h.superseded_at).slice(0, 10)}"), 1);
  // …and leaves a calendar date alone.
  assert.equal(seen("{row.invoice_date.slice(0, 10)}"), 0);
  assert.equal(seen("{formatDate(row.created_at)}"), 0);
});

test("the NOT_A_SHOWN_STAMP list is empty and only shrinks", () => {
  assert.deepEqual(Object.keys(NOT_A_SHOWN_STAMP), []);
});
