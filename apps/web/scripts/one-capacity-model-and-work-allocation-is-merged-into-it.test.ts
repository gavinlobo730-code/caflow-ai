// There is ONE answer to "how loaded is this person", the server's, and the old
// Work Allocation screen is merged into it. Run with:
//   node --experimental-strip-types --test scripts/one-capacity-model-and-work-allocation-is-merged-into-it.test.ts
//
// WHY THIS EXISTS (practice_management-24)
//     `/team/work-allocation` divided a COUNT of open tasks by a constant held in
//     the browser — `CAPACITY = {Partner: 20, Manager: 30, Executive: 40,
//     Reviewer: 20}` — beside `/team/workload`, a real model off each person's
//     configured weekly hours and logged time. Two screens, two answers, one of
//     them a guess by job title, and the guess had its own reassign flow that
//     wrote `tasks` over PostgREST so `rbac()` never saw it and the assignee was
//     told nothing. These are the RULES, not a spelling of that file:
//       * no browser code decides a person's capacity from their ROLE;
//       * the retired URL fetches nothing, writes nothing and decides nothing;
//       * nothing in the browser reassigns a task except through the API;
//       * the figures the merged screen shows are the server's.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.join(import.meta.dirname, "..");
const RETIRED = "app/team/work-allocation/page.tsx";
const WORKLOAD = "app/team/workload/page.tsx";
const PANEL = "components/team/OpenWorkPanel.tsx";

function strip(src: string): string {
  return src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\{\/\*[\s\S]*?\*\/\}/g, "").replace(/^\s*\/\/.*$/gm, "");
}
function code(rel: string): string {
  return strip(fs.readFileSync(path.join(ROOT, rel), "utf8"));
}
function walk(dir: string, out: string[] = []): string[] {
  for (const e of fs.readdirSync(path.join(ROOT, dir), { withFileTypes: true })) {
    const rel = `${dir}/${e.name}`;
    if (e.isDirectory()) { if (e.name !== "node_modules" && e.name !== ".next") walk(rel, out); }
    else if (/\.(ts|tsx)$/.test(e.name) && !/\.test\.(ts|tsx)$/.test(e.name)) out.push(rel);
  }
  return out;
}

const SOURCES = ["app", "components", "lib"].flatMap((d) => walk(d));
const ROLES = ["Partner", "Manager", "Executive", "Reviewer"];

test("no browser code keeps a capacity (or a load, or a quota) keyed by role", () => {
  const offenders: string[] = [];
  for (const rel of SOURCES) {
    const src = code(rel);
    // an object literal with two or more role names as keys, each given a number
    for (const m of src.matchAll(/\{([^{}]*)\}/g)) {
      const hits = ROLES.filter((r) => new RegExp(`\\b${r}\\b["']?\\s*:\\s*\\d+`).test(m[1]));
      if (hits.length >= 2) offenders.push(`${rel}: ${m[0].replace(/\s+/g, " ").slice(0, 100)}`);
    }
  }
  assert.deepEqual(offenders, [],
    "a number of tasks, or hours, a person can carry because of their JOB TITLE is a guess; " +
    "capacity is `weekly_capacity_hours`, configured per person and served by GET /api/workload");
  assert.ok(SOURCES.length > 300, "the scan must actually be reading the tree");
});

test("the retired Work Allocation URL is a redirect that fetches nothing", () => {
  const src = code(RETIRED);
  assert.match(src, /router\.replace\(`\/team\/workload/, "it lands on the merged screen");
  assert.match(src, /window\.location\.hash/, "a #unassigned-tasks deep link survives");
  for (const forbidden of [/\.from\(/, /selectAll/, /api\./, /getSupabaseClient/, /fetch\(/, /useState/]) {
    assert.doesNotMatch(src, forbidden, `the redirect must not use ${forbidden}`);
  }
  assert.ok(src.split("\n").length < 40, "a redirect stub, not a screen");
});

test("nothing links to or lists the retired screen as a place of its own", () => {
  // The two files that legitimately NAME it: the route manifest (every page on
  // disk, generated) and the navigation inventory, where UNLISTED records why the
  // URL is not a screen of its own.
  const offenders = SOURCES
    .filter((rel) => rel !== RETIRED && rel !== "lib/workspace/knownRoutes.generated.ts"
      && rel !== "lib/navigation/screens.ts")
    .filter((rel) => /["'`]\/team\/work-allocation/.test(code(rel)));
  assert.deepEqual(offenders, [], "link to /team/workload (or its #unassigned-tasks / #open-tasks anchors)");
  // ...and the inventory names it ONLY as unlisted, never as a screen in ALL_SCREENS.
  const screens = fs.readFileSync(path.join(ROOT, "lib/navigation/screens.ts"), "utf8");
  assert.doesNotMatch(strip(screens), /firm\(\s*"\/team\/work-allocation"/, "it is not a palette entry");
  assert.match(strip(screens), /"\/team\/work-allocation":/, "it is recorded as unlisted, with a reason");
});

test("the merged screen is the one with the unassigned backlog and the reassign flow", () => {
  const page = code(WORKLOAD);
  assert.match(page, /<OpenWorkPanel\b/);
  assert.match(page, /href="#unassigned-tasks"/, "the backlog link lands on this page");
  const panel = code(PANEL);
  assert.match(panel, /id="unassigned-tasks"/);
  assert.match(panel, /id="open-tasks"/);
});

test("a reassignment goes through the API, never straight over PostgREST", () => {
  const panel = code(PANEL);
  assert.match(panel, /api\.tasks\.update\(/);
  assert.doesNotMatch(panel, /\.from\(\s*["']tasks["']\s*\)/, "a browser write is a write rbac() never saw");
  assert.doesNotMatch(panel, /assignee_id/, "the server moves both assignee columns; the browser names neither");
});

test("the figures on the merged screen are the server's: nothing here divides, averages or multiplies", () => {
  for (const rel of [PANEL, WORKLOAD]) {
    const src = code(rel);
    assert.doesNotMatch(src, /\.reduce\([^)]*(estimated_minutes|active_tasks|open_tasks)/,
      `${rel}: totals come from the payload (estimated_open_minutes, unassigned.estimated_minutes)`);
    assert.doesNotMatch(src, /\bCAPACITY\b/, `${rel}`);
    assert.doesNotMatch(src, /\/\s*cap(acity)?\b/i, `${rel}: no task count is divided by a capacity here`);
  }
  assert.match(code(PANEL), /estimated_open_minutes/);
  assert.match(code(PANEL), /open_tasks_without_estimate/, "tasks with no estimate are counted, not averaged over");
});

test("none of it keeps the user's work in the browser", () => {
  for (const rel of [RETIRED, WORKLOAD, PANEL]) {
    assert.doesNotMatch(code(rel), /localStorage|sessionStorage/, rel);
  }
});
