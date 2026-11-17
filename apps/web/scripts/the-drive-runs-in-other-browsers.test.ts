// The browser drive can run in Firefox and WebKit and at a phone's width, weekly, and nothing waits on it (POST-A-387).
// Run with: node --experimental-strip-types --test scripts/the-drive-runs-in-other-browsers.test.ts
//
// WHAT THIS HOLDS, AND WHAT IT CANNOT. The runner takes `--browser` and `--width`, `--only` takes several groups, and a workflow runs the
// dates, double-click, keyboard and dialog groups in Firefox, in WebKit and in Chromium at 390 pixels. Whether the drive PASSES in those
// browsers is not known: the container this was written in could not install them, and the first run's triage is the ledger's. A difference
// in how a browser draws a focus ring or a date is not a defect of the product; one in what is sent or shown is.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { BROWSERS, matchesOnly, parseArgs, reportOf, resolveBrowser, resolveWidth, viewportFor } from "./drive/kit.mjs";

const WEB = path.resolve(import.meta.dirname, "..");
const WORKFLOWS = path.resolve(WEB, "..", "..", ".github", "workflows");
const OTHER = fs.readFileSync(path.join(WORKFLOWS, "drive-other-browsers.yml"), "utf8");
const NIGHTLY = fs.readFileSync(path.join(WORKFLOWS, "smoke-walk.yml"), "utf8");

test("--browser and --width are read, defaulted and refused in words", () => {
  assert.deepEqual(BROWSERS, ["chromium", "firefox", "webkit"]);
  assert.equal(resolveBrowser(undefined), "chromium");
  assert.equal(resolveBrowser("webkit"), "webkit");
  assert.throws(() => resolveBrowser("safari"), /not a browser the drive runs in \(chromium, firefox, webkit\)/);
  assert.equal(resolveWidth(undefined), 1440);
  assert.equal(resolveWidth("390"), 390);
  for (const bad of ["abc", "100", "3000", "390.5"]) assert.throws(() => resolveWidth(bad), /--width/, bad);
  assert.deepEqual(viewportFor(390, undefined), { width: 390, height: 844 });
  assert.deepEqual(viewportFor(1440, undefined), { width: 1440, height: 900 });
  assert.deepEqual(viewportFor(390, "720"), { width: 390, height: 720 });
  assert.equal(parseArgs(["--browser", "firefox", "--width=390"]).problem, null);
  assert.match(parseArgs(["--browser"]).problem ?? "", /chromium, firefox or webkit/);
});

test("--only takes several groups, and one group or id still means what it meant", () => {
  const run = (group: string, id: string) => ({ group, id: `${group}/${id}` });
  assert.ok(matchesOnly(run("dates", "x [en-US]"), null));
  assert.ok(matchesOnly(run("dates", "x"), "dates"));
  assert.ok(matchesOnly(run("keyboard", "x"), "dates,keyboard"));
  assert.ok(matchesOnly(run("dialogs", "a-b"), "dialogs/a"));
  assert.ok(!matchesOnly(run("amounts", "x"), "dates,keyboard"));
  assert.ok(!matchesOnly(run("amounts", "x"), "date"), "a group is matched whole, an id by its start");
});

test("the report says which browser and width it was driven in", () => {
  const r = reportOf({ complete: true, zone: "all", shard: "all", chosenAtMs: 0, csp: "REPORT-ONLY", pinnedClock: "x", selected: [], results: [], startedMs: 0, nowMs: 1, browser: "webkit", width: 390 });
  assert.equal(r.mode.browser, "webkit");
  assert.equal(r.mode.width, 390);
  assert.equal(reportOf({ complete: true, zone: "all", shard: "all", chosenAtMs: 0, csp: "", pinnedClock: "", selected: [], results: [], startedMs: 0, nowMs: 1 }).mode.browser, "chromium");
});

test("every group the workflow names exists, and the list can be asked for in another browser without one installed", () => {
  const only = /--only ([\w,-]+)/.exec(OTHER)?.[1];
  assert.ok(only, "the workflow does not say which groups it drives");
  const listed = execFileSync("node", ["scripts/driveMoneyEditors.mjs", "--list", "--only", only, "--browser", "firefox", "--width", "390"], { cwd: WEB, encoding: "utf8" });
  const groups = new Set(listed.split("\n").filter((l) => l.includes("/")).map((l) => l.split("/")[0]));
  for (const g of only.split(",")) assert.ok(groups.has(g), `--only ${g}: no scenario of that group`);
});

test("the workflow is weekly and on demand, never a pull-request check, and covers Firefox, WebKit and a phone", () => {
  assert.doesNotMatch(OTHER, /^\s*pull_request:/m, "a workflow with a pull_request trigger can become a required check that is pending forever");
  assert.doesNotMatch(OTHER, /^\s*push:/m);
  assert.doesNotMatch(OTHER, /^\s*paths:/m);
  assert.match(OTHER, /schedule:\s*\n\s*- cron: "[^"]+"/);
  assert.match(OTHER, /workflow_dispatch:/);
  for (const m of ["{ browser: firefox, width: 1440 }", "{ browser: webkit, width: 1440 }", "{ browser: chromium, width: 390 }"]) assert.ok(OTHER.includes(m), m);
  assert.match(OTHER, /playwright install --with-deps \$\{\{ matrix\.browser \}\}/);
  assert.match(OTHER, /--stop-after 24/, "the drive stops itself inside the job's allowance");
  assert.match(OTHER, /timeout-minutes: 45/);
});

test("the Playwright version is the nightly's, so the two are bumped together", () => {
  const v = (s: string) => /PLAYWRIGHT_VERSION: "([\d.]+)"/.exec(s)?.[1];
  assert.ok(v(OTHER));
  assert.equal(v(OTHER), v(NIGHTLY));
});

test("the nightly drive is still Chromium at the desktop width, and does not take these flags", () => {
  const line = /node scripts\/driveMoneyEditors\.mjs --zone[^\n]*/.exec(NIGHTLY)?.[0] ?? "";
  assert.ok(line, "the nightly drive step was not found");
  assert.doesNotMatch(line, /--browser|--width/);
});
