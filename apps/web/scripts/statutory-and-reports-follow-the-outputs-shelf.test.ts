// StatutoryTab and ReportsTab open on the month the Outputs shelf has
// selected, not on the calendar's current month, and a legitimately empty
// answer from the statutory summary reads as such rather than as the
// pre-Load prompt (apex-payroll-yearend-09).
//
// Run with:
//   node --experimental-strip-types --test \
//     scripts/statutory-and-reports-follow-the-outputs-shelf.test.ts
//
// WHAT WAS WRONG
//     Both tabs computed their own `new Date()` default, unrelated to
//     whichever month was actually selected on the Outputs shelf they are
//     rendered from (e.g. "August 2026 - draft"). And `statutory_summary`
//     answers `{success: true, data: null}` for a month with no run — a
//     genuine, loaded answer — which StatutoryTab rendered with the exact
//     same "Select a month and click Load" text as a tab nobody had touched
//     yet.
//
// THE FIX
//     Both components take an `initialMonth` prop, seeding their `month`
//     state on first render only; OutputsTab passes its own selected run's
//     month. StatutoryTab tracks `hasLoaded` separately from `loading` and
//     `loadFailed`, so a loaded-and-empty answer gets its own sentence.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");
const PAGE = "app/clients/[id]/payroll/page.tsx";

function read(): string {
  return fs.readFileSync(path.join(WEB, PAGE), "utf8");
}

/** The source of one top-level `function <name>(` declaration through to the
 *  next top-level `function` — the same extraction the Escape-key guard
 *  (a-modal-closes-on-escape.test.ts) uses for this kind of file. */
function functionBody(src: string, name: string): string {
  const m = new RegExp(`(?:^|\\n)function ${name}\\(`).exec(src);
  assert.ok(m, `function ${name} not found`);
  const start = m.index + m[0].length;
  const rest = src.slice(start);
  const next = rest.search(/\nfunction |\nexport default function /);
  return next === -1 ? rest : rest.slice(0, next);
}

test("StatutoryTab and ReportsTab both accept initialMonth", () => {
  const src = stripComments(read());
  assert.match(
    src,
    /function StatutoryTab\(\{ clientId, initialMonth \}: \{ clientId: string; initialMonth\?: string \}\)/,
  );
  assert.match(
    src,
    /function ReportsTab\(\{ clientId, initialMonth \}: \{ clientId: string; initialMonth\?: string \}\)/,
  );
});

test("initialMonth wins over today's date, and only as the seed", () => {
  for (const name of ["StatutoryTab", "ReportsTab"]) {
    const body = functionBody(stripComments(read()), name);
    assert.match(body, /const defaultMonth = initialMonth\s*\n?\s*\|\|/,
      `${name} must prefer initialMonth over its own new Date() default`);
    assert.match(body, /useState\(defaultMonth\)/,
      `${name} must seed state once, not re-derive the month every render`);
  }
});

test("OutputsTab threads its own selected run's month into both tabs", () => {
  const src = stripComments(read());
  const body = functionBody(src, "OutputsTab");
  assert.match(body, /<StatutoryTab clientId=\{clientId\} initialMonth=\{run\?\.month\} \/>/);
  assert.match(body, /<ReportsTab clientId=\{clientId\} initialMonth=\{run\?\.month\} \/>/);
});

test("StatutoryTab tells a loaded-and-empty month apart from a never-loaded one", () => {
  const body = functionBody(stripComments(read()), "StatutoryTab");
  assert.match(body, /const \[hasLoaded, setHasLoaded\] = useState\(false\)/);
  assert.match(body, /setHasLoaded\(true\)/,
    "hasLoaded must actually be set somewhere in load()");
  assert.match(body, /No payroll run recorded for \{formatMonthYear\(month\)\}/);
  assert.match(body, /hasLoaded \? \(/,
    "the empty-but-loaded branch must be reachable in the render");
  // The pre-Load prompt must still exist for the genuinely untouched case.
  assert.match(body, /Select a month and click Load to view statutory dues/);
});

test("hasLoaded flips on a failed load too, not only a successful empty one", () => {
  // setHasLoaded(true) belongs in `finally`, which runs whether load()
  // threw, returned success:false, or found a genuinely empty month — the
  // loadFailed branch above still takes priority in the render either way.
  const body = functionBody(stripComments(read()), "StatutoryTab");
  const financeIdx = body.indexOf("async function load()");
  assert.ok(financeIdx !== -1, "load() not found");
  const loadBody = body.slice(financeIdx);
  const finallyMatch = /finally\s*\{([^}]*)\}/.exec(loadBody);
  assert.ok(finallyMatch, "load() has no finally block");
  assert.match(finallyMatch[1], /setHasLoaded\(true\)/);
});
