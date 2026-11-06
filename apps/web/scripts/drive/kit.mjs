/**
 * The small things every scenario needs: finding Playwright, finding a Chromium, pressing a button twice before
 * the page can draw, choosing from one of the product's own pickers, and saying "this URL was written exactly
 * N times".
 *
 * PLAYWRIGHT IS NOT A DEPENDENCY OF THIS PACKAGE, for the reason the walk's header gives: it is a ~40 MB install
 * the frontend job every pull request runs does not need. The workflow that runs the drive installs it in its
 * own job (it is the walk's job; the drive runs after the walk, on the same install and the same build), and
 * `loadPlaywright` below looks for it in the three places it can be: the package the workflow added, a plain
 * `playwright`, and a path in `PLAYWRIGHT_MODULE` for a machine that keeps it outside the project.
 */
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import assert from "node:assert/strict";

export async function loadPlaywright() {
  const tries = [
    () => import("@playwright/test"),
    () => import("playwright"),
    () => (process.env.PLAYWRIGHT_MODULE ? import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href) : Promise.reject(new Error("unset"))),
  ];
  for (const attempt of tries) {
    try {
      const pw = await attempt();
      const chromium = pw.chromium ?? pw.default?.chromium;
      if (chromium) return chromium;
    } catch { /* try the next place */ }
  }
  console.error(
    "Playwright is not installed.\n" +
    "  cd apps/web && pnpm add -D @playwright/test      (and remove it again before committing: it is not a\n" +
    "  project dependency, see scripts/smoke-walk.mjs above loadChromium() for why)\n" +
    "or point PLAYWRIGHT_MODULE at an install, e.g. /opt/node-tools/node_modules/playwright/index.mjs.");
  process.exit(2);
}

/** The Chromium already on disk, when there is one (the walk's rule: Playwright's own download is disabled in
 *  some environments and the installed build may not be the one this version expects). Undefined lets Playwright
 *  use its own, which is what a CI runner has after `playwright install`. */
export function installedChromium() {
  const root = process.env.PLAYWRIGHT_BROWSERS_PATH || "/opt/pw-browsers";
  if (!fs.existsSync(root)) return undefined;
  for (const dir of fs.readdirSync(root).filter((d) => d.startsWith("chromium-")).sort().reverse()) {
    for (const rel of ["chrome-linux/chrome", "chrome-linux64/chrome"]) {
      const p = path.join(root, dir, rel);
      if (fs.existsSync(p)) return p;
    }
  }
  return undefined;
}

/**
 * Click every one of `locators` before the page gets a turn to render.
 *
 * THIS IS THE DEFECT, REPRODUCED. A person's double-click is two click events a few milliseconds apart, and
 * React commits the first click's `setSaving(true)` only after both have run; a guard held in React state
 * (`disabled={saving}`) therefore reads `false` twice. `element.click()` called twice inside ONE evaluate is the
 * same thing with the timing removed: no render can sit between the two. Playwright's own `dblclick()` is not
 * this, since it waits for the page to settle between the events and so tests a slower person than the one who
 * posted eleven journals.
 */
export async function sameTick(...locators) {
  const handles = [];
  for (const locator of locators) {
    // `elementHandle` waits for the element to exist and be attached, with the locator's own timeout.
    handles.push(await locator.elementHandle());
  }
  const page = locators[0].page();
  await page.evaluate((els) => { for (const el of els) el.click(); }, handles);
}

/** The same button pressed twice in one tick: the double-click. */
export async function sameTickDouble(locator) {
  const handle = await locator.elementHandle();
  await locator.page().evaluate((el) => { el.click(); el.click(); }, handle);
}

/** Pick an option in one of the product's own comboboxes. Scoped to the open listbox: an unscoped
 *  `getByRole("option")` also matches an ordinary `<select>`'s options elsewhere on the same screen. */
export async function pick(page, trigger, optionText) {
  await trigger.click();
  await page.locator("[role=listbox] [role=option]", { hasText: optionText }).first().click();
}

/** Wait for a fact a click causes, by polling it. `waitForLoadState("networkidle")` resolves AT ONCE for a document that has
 *  already been idle, so it cannot wait for a read a click starts afterwards: on a fast machine the read has landed by the time the
 *  next line looks, on a slower runner it has not, and a scenario written that way passes in one place and fails in the other
 *  (POST-A-262's and POST-A-263's window scenarios did exactly that, and the nightly walk was red from the night they merged).
 *  A scenario waits for the request itself, or for the page to show the answer, never for "quiet". 10 seconds, polled every 50 ms. */
export async function until(condition, what, timeoutMs = 10_000) {
  const stop = Date.now() + timeoutMs;
  while (Date.now() < stop) {
    if (await condition()) return;
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  assert.fail(`timed out waiting for ${what}`);
}

/** Assert `re` was written exactly `n` times. The message names what WAS written, because "expected 1, got 2"
 *  does not say which two. */
export async function expectWrites(stub, re, n, what, method) {
  await stub.quiet();
  const seen = stub.writesTo(re, method);
  assert.equal(seen.length, n,
    `${what}: expected ${n} write(s) to ${re}, saw ${seen.length}` +
    (seen.length ? ` (${seen.map((w) => `${w.method} ${w.path}`).join(", ")})` : "") +
    `. All writes: ${stub.allWrites().map((w) => `${w.method} ${w.path}`).join(", ") || "none"}`);
}

/** The three browser contexts the date scenarios run under. A date is a calendar day and the two usual ways of
 *  getting it wrong are mirror images: `new Date("2026-03-31")` is UTC midnight, which is the PREVIOUS day in a
 *  zone behind UTC (Los Angeles), and `new Date(2026, 2, 31).toISOString()` is local midnight, which is the
 *  previous day in any zone AHEAD of it (Kolkata at +5:30, Kiritimati at +14). Kolkata is the product's own zone,
 *  so it is the one a developer sees; Los Angeles and Kiritimati are the two ends. A field that goes through
 *  either of those routes is wrong in at least one of the three. */
export const TZ_MATRIX = [
  { locale: "en-US", timezoneId: "America/Los_Angeles" },
  { locale: "en-IN", timezoneId: "Asia/Kolkata" },
  { locale: "en-GB", timezoneId: "Pacific/Kiritimati" },
];

// ── Which part of the drive a run drives (`--zone`, `--shard`) ────────────────────────────────────────────────────────────────────
// The date scenarios run under all three zones of the matrix, which is two thirds of the drive's length and more than a night's allowance
// on a GitHub runner (the run of 6 November 2026 was cancelled at its limit, 28 minutes into the drive). The NIGHTLY run therefore drives
// ONE zone and ONE half of the date group, taken in turn, so that over any six consecutive nights every zone sees every date scenario
// once and none is ever left out; the other groups (they run in no zone) run in full every night. An on-demand run says `all`. The rule
// is here, pure, so a test holds it: a rotation written in the workflow's shell could not be tried. THE ALLOWANCE IS NOT RAISED: it is
// the owner's money, so the drive was cut to fit it.

/** How many parts the date group is cut into for a night. */
export const SHARDS = 2;

const DAY_MS = 86_400_000;
/** Five hours thirty minutes: the Indian day starts at 18:30 UTC. */
const IST_OFFSET_MS = 19_800_000;

/** The number of the INDIAN day an instant falls on. The rotation is keyed on this and not on the UTC day because the nightly is scheduled
 *  for 02:00 IST but GitHub runs it hours late (its drive step began between 05:10 and 08:08 IST in the eight nights before this was written), which straddles UTC
 *  midnight (05:30 IST): keyed on the UTC day, those eight nights drove one zone twice running and left another undriven for five.
 *  A job that belongs to the Indian day is read by the Indian day, as everything else in this product is. */
export function indianDayNumber(epochMs) {
  return Math.floor((epochMs + IST_OFFSET_MS) / DAY_MS);
}

/** What the run of the given instant drives when it drives a part: a zone and a shard. The zone changes every day and the shard every
 *  three, so six consecutive days cover each (zone, shard) pair exactly once. */
export function partOfTheNight(epochMs) {
  const day = indianDayNumber(epochMs);
  return { zone: TZ_MATRIX[day % TZ_MATRIX.length].timezoneId, shard: Math.floor(day / TZ_MATRIX.length) % SHARDS, day };
}

/** The zone of a night (kept for the callers that ask only for it). */
export function zoneOfTheDay(epochMs) {
  return partOfTheNight(epochMs).zone;
}

/** What `--zone` means: `all` (every context a scenario asks for), `rotate` (the zone of the day) or the id of one of the matrix's zones.
 *  Anything else is a mistake of the caller's and is refused, because a zone nobody drives would read as a drive that passed. */
export function resolveZone(value, epochMs) {
  if (value === "all") return "all";
  if (value === "rotate") return zoneOfTheDay(epochMs);
  if (TZ_MATRIX.some((c) => c.timezoneId === value)) return value;
  throw new Error(`--zone ${value}: not a zone of the matrix. Use all, rotate or one of ${TZ_MATRIX.map((c) => c.timezoneId).join(", ")}.`);
}

/** What `--shard` means: `all` (the whole date group), `rotate` (the night's part) or a number from 0 to SHARDS - 1. With no `--shard` at all
 *  (undefined), a rotating zone rotates the part too and any other zone drives the whole group. An EMPTY value is not "no flag": it is refused. */
export function resolveShard(value, zoneValue, epochMs) {
  if (value === undefined || value === null) return zoneValue === "rotate" ? partOfTheNight(epochMs).shard : "all";
  if (value === "all") return "all";
  if (value === "rotate") return partOfTheNight(epochMs).shard;
  if (/^\d+$/.test(value) && Number(value) < SHARDS) return Number(value);
  throw new Error(`--shard ${value}: not a part of the date group. Use all, rotate or a number from 0 to ${SHARDS - 1}.`);
}

/** The shard a scenario belongs to: a stable hash of its id (FNV-1a), so adding or removing a scenario moves no other one. */
export function shardOf(id) {
  let h = 0x811c9dc5;
  for (let i = 0; i < id.length; i++) {
    h ^= id.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h % SHARDS;
}

/** Whether a scenario of the given group is driven for a shard: only the date group is cut. */
export function inShard(group, id, shard) {
  return shard === "all" || group !== "dates" || shardOf(id) === shard;
}

/** The contexts one scenario runs under for a resolved zone. A scenario that asks for none of its own (no `contexts`) runs once, as before.
 *  One that asks for a set with no context in the chosen zone is NOT dropped: it runs all of its own, so choosing a zone never removes a
 *  scenario from the run. */
export function contextsFor(contexts, zone) {
  if (!zone || zone === "all") return contexts;
  const wanted = contexts.filter((c) => c.timezoneId === zone);
  return wanted.length ? wanted : contexts;
}

// ── The runner's arguments, its deadline, its clock and its report ─────────────────────────────────────────────────────────────────
// These are here, pure, and not in `driveMoneyEditors.mjs` (which is a script with a browser in it), so that a test can call them: the first
// version of the rotation was tried only through the functions above, and a review showed that deleting the runner's own use of them left
// every test green.

/** Every flag the runner knows. A "value" flag takes one, spelled `--zone rotate` or `--zone=rotate`; a "bare" flag takes none. */
export const FLAGS = {
  "--only": "value", "--report": "value", "--out": "value", "--zone": "value", "--shard": "value", "--stop-after": "value", "--now": "value",
  "--shots": "bare", "--no-tz-matrix": "bare", "--no-headers": "bare", "--list": "bare",
};
/** What a value flag says it needs when it is not given one (the first two keep the words they always had). */
const NEEDS = {
  "--only": "a group or scenario id, e.g. --only dates",
  "--report": "a file path, e.g. --report .smoke/drive-report.json",
  "--out": "a directory, e.g. --out ../wt-18/apps/web/out",
  "--zone": "all, rotate or the id of a zone, e.g. --zone Asia/Kolkata",
  "--shard": "all, rotate or a number, e.g. --shard 0",
  "--stop-after": "a number of minutes, e.g. --stop-after 24",
  "--now": "an instant with its zone, e.g. --now 2026-11-07T00:30:00Z",
};

/** Read the runner's arguments into `{ flags, problem }`. It never throws: a problem is the sentence the caller prints before it exits 2. NOTHING IS IGNORED, because a run that
 *  ignores a flag it was given drives something other than what was asked: an unknown flag, a value on a flag that takes none, a missing, empty or flag-like value, a flag given
 *  twice and a bare word are each refused. */
export function parseArgs(argv) {
  const flags = {};
  const known = Object.keys(FLAGS).join(", ");
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (!a.startsWith("--")) return { flags, problem: `${a}: the runner takes flags only (${known}).` };
    const eq = a.indexOf("=");
    const name = eq === -1 ? a : a.slice(0, eq);
    const kind = FLAGS[name];
    if (!kind) return { flags, problem: `${a}: not a flag of this runner (${known}). A flag it ignores would drive something other than what was asked.` };
    if (name in flags) return { flags, problem: `${name} is given twice: the run would use one of the two and drive something other than what was asked.` };
    if (kind === "bare") {
      if (eq !== -1) return { flags, problem: `${name} takes no value (${a}).` };
      flags[name] = true;
      continue;
    }
    let value;
    if (eq !== -1) value = a.slice(eq + 1);
    else { value = argv[i + 1]; i++; }
    if (!value || value.startsWith("--")) return { flags, problem: `${name} needs ${NEEDS[name]}` };
    flags[name] = value;
  }
  return { flags, problem: null };
}

/** The most minutes a deadline may be. */
export const MAX_STOP_AFTER_MINUTES = 600;

/** What `--stop-after` means: a number of minutes (more than 0, at most MAX_STOP_AFTER_MINUTES), or undefined for no deadline. Anything else is refused. */
export function resolveStopAfter(value) {
  if (value === undefined || value === null) return null;
  const minutes = /^\d+(\.\d+)?$/.test(value) ? Number(value) : NaN;
  if (!(minutes > 0 && minutes <= MAX_STOP_AFTER_MINUTES)) {
    throw new Error(`--stop-after ${value}: not a number of minutes (more than 0, at most ${MAX_STOP_AFTER_MINUTES}).`);
  }
  return minutes;
}

/** Whether the drive's deadline has passed: a run STOPS STARTING scenarios when it has. The deadline is the runner's own because a job that times out is cancelled and its later
 *  steps, the one that uploads the report among them, never run (the run of 6 November 2026 ran 55 minutes against a 45-minute allowance and its upload step never started). */
export function deadlinePassed(startedMs, nowMs, minutes) {
  return minutes !== null && minutes !== undefined && nowMs - startedMs >= minutes * 60_000;
}

/** What `--now` means: the instant the rotation is read at. Absent, it is the real clock. It exists so a test can drive the runner's own use of the rotation
 *  (a runner that read a frozen clock would drive one part forever); an instant has to carry its zone, because a bare date-time is read in the machine's. */
export function resolveNow(value, realNowMs) {
  if (value === undefined || value === null) return realNowMs;
  const ms = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$/.test(value) ? Date.parse(value) : NaN;
  if (!Number.isFinite(ms)) throw new Error(`--now ${value}: not an instant with its zone, e.g. 2026-11-07T00:30:00Z.`);
  return ms;
}

/** The drive's report, as it stands at `nowMs`. `ok` needs the end to have been reached: a report written part-way is not a pass, however little had failed. `not_driven` is what had
 *  not run, named, so a cancelled or stopped run still says what it did not drive. */
export function reportOf({ complete, stoppedAtDeadline = false, only = null, tzMatrix = true, zone, shard, stopAfter = null, chosenAtMs, csp, pinnedClock, commit = null,
  selected, results, escaped = [], startedMs, nowMs }) {
  const failed = results.filter((r) => !r.ok);
  return {
    generated_at: new Date(nowMs).toISOString(),
    commit,
    mode: { only, tz_matrix: tzMatrix, zone, shard, stop_after_minutes: stopAfter, chosen_at: new Date(chosenAtMs).toISOString() },
    csp,
    pinned_clock: pinnedClock,
    complete,
    stopped_at_deadline: stoppedAtDeadline,
    ok: complete && failed.length === 0 && escaped.length === 0,
    scenarios_selected: selected.length,
    scenarios_driven: results.length,
    not_driven: complete ? [] : selected.slice(results.length).map((r) => r.id),
    failed: failed.map((f) => ({ id: f.id, error: f.error, problems: f.problems })),
    scenarios: results,
    blocked_hosts: [...escaped],
    duration_ms: nowMs - startedMs,
  };
}
