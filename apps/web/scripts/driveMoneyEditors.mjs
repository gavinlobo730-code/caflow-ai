#!/usr/bin/env node
/**
 * Drive the editors that move money in a real browser, and fail on what a click really does (PRE-A-015).
 *
 * WHY THIS EXISTS. Every guard written for the money editors (the repeat-click guard, the row keyboard, the
 * unsent drafts, the typed dates) is a SOURCE guard: it reads text and proves the text has a shape. CLAUDE.md
 * says so at each of them ("nothing was clicked, because there is no browser"), and the one time the date field
 * WAS driven, in a scratch script nobody kept, it was on one editor of sixty. So none of the following had ever
 * been observed to work, and the first to find out was going to be a CA:
 *
 *   * two clicks on Post Entry in the same tick make ONE journal (frontend_ux-09, which was eleven);
 *   * the same for Save & Issue, Record Payment, Issue, Receive and the deletes;
 *   * Tab reaches a ledger row, the arrows move between rows and Enter opens one (frontend_ux-16);
 *   * a reload raises the browser's own "leave site?" prompt on a dirty form, the draft is OFFERED and not
 *     applied, Discard really discards, and a successful save really clears it (frontend_ux-23);
 *   * a typed date is read by the one rule in every editor, the unreadable one is refused with the date's own
 *     sentence and sends nothing, and the date that reaches the server is the ISO date typed, in any browser
 *     locale and zone (frontend_ux-19);
 *   * a delete and a prompt are in-app dialogs, never the browser's, and Cancel sends nothing (frontend_ux-21).
 *
 * WHAT IT DOES. Serves the smoke build's `out/` (the same export the walk serves, built by `pnpm smoke:build`)
 * from `scripts/drive/stub.mjs`, which answers rows where the walk answers `[]` and keeps a LOG of every write.
 * Each scenario in `scripts/drive/scenarios/` gets a fresh browser context, a fresh page, fresh storage and a
 * clock pinned to one instant, opens a screen, does what a person does and asserts on the log. A scenario also
 * fails on anything the walk fails a route for (an uncaught exception, a console error, a Content-Security-Policy
 * violation, a request for a host that is not the stub) and on any native alert, confirm or prompt: the product
 * has an in-app dialog for each, and the one native dialog allowed is the browser's own leave-site prompt, which
 * the drive accepts so a reload does not hang.
 *
 *   pnpm smoke:build && node scripts/driveMoneyEditors.mjs
 *   node scripts/driveMoneyEditors.mjs --only dates --report .smoke/drive-report.json
 *
 * --only <text>    run the scenarios whose group or id starts with, or equals, the text
 * --report <file>  also write the verdict as JSON and, under GitHub Actions, a table on the run's summary page
 * --no-tz-matrix   run each date scenario once, not under en-US/Los Angeles, en-IN/Kolkata and en-GB/Kiritimati (the first of them)
 * --zone <which>   which of those zones the date scenarios run under: `all` (the default), `rotate` (ONE zone, the matrix's zones in turn,
 *                  a new one each INDIAN day, with the part below) or the id of one zone (`Asia/Kolkata`). A scenario with no context in the
 *                  chosen zone runs all of its own.
 * --shard <which>  which half of the date group to drive: `all` (the default for a zone that is not `rotate`), `rotate` (the default for
 *                  `--zone rotate`: one half, a new one every third Indian day) or 0 or 1. The other groups run in full whatever the part.
 *                  What the nightly asks for is `--zone rotate`: a zone and a half a night, so a night fits its allowance and over six
 *                  nights every zone sees every date scenario once (`drive/kit.mjs` holds the rule, `the-nightly-drive-...test.ts` the proof).
 * --stop-after <minutes>  a deadline for the drive: after it the runner STARTS NO MORE scenarios, writes its report (`complete: false`, the runs it did not drive named in
 *                  `not_driven`) and exits 1. The workflow's job has an allowance, and a job that runs past it is cancelled WITHOUT running its later steps, the one that uploads
 *                  this report among them: the run of 6 November 2026 ran 55 minutes against 45 and left nothing. A runner that stops itself leaves the report and the job red.
 * --list           print the runs that would be driven, one a line, and exit 0 before any build or browser is needed (what the tests of the rotation read)
 * --now <instant>  read the rotation at this instant (`2026-11-07T00:30:00Z`, with its zone) and not at the real clock, to reproduce a night or to test the runner's own use of it
 * --shots          keep a screenshot of every failed scenario in .smoke/drive/
 * --out <dir>      drive another export than out/ (a build of an earlier commit, a patched copy)
 * --no-headers     drive WITHOUT out/_headers (not the product as it is served)
 *
 * Both spellings of a flag with a value, `--zone rotate` and `--zone=rotate`, are read. NOTHING IS IGNORED: a flag the runner does not know, a value on a flag that takes none
 * (`--shots=1`), a missing or empty value, a flag given twice and a bare word are each refused with exit 2, because a run that ignores what it was given drives something
 * other than what was asked.
 *
 * PROBE_REACHABLE=1  after each four-second wait for a sentence, ask the browser whether the person could reach it (a trial click): a sentence drawn
 *                  BEHIND an overlay (a page's message line under a drawer's backdrop) is "visible" to Playwright and is not where the person is
 *                  looking. A probe, not a check anything waits on: an element with pointer-events off (a toast) fails it though it can be read.
 *
 * ENVIRONMENT. SMOKE_PORT is the port the export was built for (`pnpm smoke:build` bakes 4319 into the bundle,
 * and so does this script by default; the same variable the walk reads). PLAYWRIGHT_MODULE points at a Playwright
 * install kept outside the project; PLAYWRIGHT_BROWSERS_PATH at a directory of Chromium builds.
 *
 * ADDING A SCENARIO. A file in `scripts/drive/scenarios/` exporting `group` and `scenarios` is picked up by
 * name; `kit.mjs` has the helpers (`sameTickDouble`, `expectWrites`, `pick`), `flows.mjs` the ways to a drawer, and
 * a new date field is one more row in `EDITORS` in `scenarios/dates.mjs`. Do not name a file `test-*.mjs` or
 * `*.test.*`: `pnpm test` would run it without a browser.
 *
 * EXIT. 0: every scenario held (or `--list` listed). 1: a scenario failed, or the deadline of `--stop-after` came before the end (the report is written first). 2: it could
 * not tell: no export, an export not built for this port, no Playwright, nothing ran, or an argument it will not guess at.
 *
 * NOT A PULL-REQUEST CHECK AND NOT A REQUIRED ONE, like the walk beside it: it needs the export and a Chromium,
 * so `.github/workflows/smoke-walk.yml` runs it after the walk, nightly and on demand, on the same build.
 *
 * WHAT IT DOES NOT PROVE. A stub is not the server: a write the real API would refuse is answered `success` here
 * unless a scenario says otherwise, and the figures are fixtures. It proves what the BROWSER does with a click,
 * a key and a typed date. The backend's arithmetic is the backend suite's.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { parseRules, resolve as resolveRule, rulesCloudflareKeeps } from "./check-live-redirects.mjs";
import { headersFor, parseHeadersFile } from "./security-headers.mjs";
import { ACCOUNTS, CLIENT_ID, CLIENT_ROW, CUSTOMER, FAKE_FIRM_ROW, FAKE_SESSION, FAKE_USERS_ROW, ITEM, JOURNAL_ENTRIES, NOW, VENDOR } from "./drive/fixtures.mjs";
import {
  SHARDS, contextsFor, deadlinePassed, inShard, installedChromium, loadPlaywright, parseArgs, partOfTheNight, reportOf, resolveNow, resolveShard, resolveStopAfter, resolveZone,
} from "./drive/kit.mjs";
import { createStub, ok } from "./drive/stub.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");
const SHOT_DIR = path.join(WEB, ".smoke", "drive");
const SCENARIO_DIR = path.join(__dirname, "drive", "scenarios");

/** The port `pnpm smoke:build` bakes into the bundle (the walk's `SMOKE_PORT`, the same default). */
const PORT = Number(process.env.SMOKE_PORT || 4319);

// `parseArgs` (drive/kit.mjs) reads both spellings of a flag with a value and refuses everything it cannot use: a run that ignores a flag it was given drives something other than what was asked.
const parsed = parseArgs(process.argv.slice(2));
if (parsed.problem) {
  console.error(parsed.problem);
  process.exit(2);
}
const flags = parsed.flags;
const only = flags["--only"] ?? null;
const reportPath = flags["--report"] ?? null;
const shots = Boolean(flags["--shots"]);
const noTzMatrix = Boolean(flags["--no-tz-matrix"]);
const noHeaders = Boolean(flags["--no-headers"]);
const listOnly = Boolean(flags["--list"]);
/** The export to drive: `out/`, or another directory of the same shape (a build of an earlier commit, to see a
 *  fix fail without it, or a copy with the guard patched out of the compiled chunks, as a negative control). */
const OUT = path.resolve(flags["--out"] ?? path.join(WEB, "out"));
/** The zone(s) the date scenarios run under: `all`, or the one zone `--zone` chose (`rotate` is chosen by the INDIAN day of this run), and the part of the date group: `all`, or the one shard
 *  `--shard` chose (`rotate`, which a rotating zone implies, is chosen by the same day). The nightly drives one of each. `--now` moves the instant the rotation is read at. */
let zone = "all";
let shard = "all";
let stopAfter = null;
const realNow = Date.now();
let chosenAt = realNow;
try {
  chosenAt = resolveNow(flags["--now"], realNow);
  zone = flags["--zone"] === undefined ? "all" : resolveZone(flags["--zone"], chosenAt);
  shard = resolveShard(flags["--shard"], flags["--zone"] ?? "all", chosenAt);
  stopAfter = resolveStopAfter(flags["--stop-after"]);
} catch (e) {
  console.error(e instanceof Error ? e.message : String(e));
  process.exit(2);
}
const night = partOfTheNight(chosenAt);
console.log(
  `Date scenarios: ${zone === "all" ? "every zone of the matrix" : `${zone} only`}, ${shard === "all" ? "the whole group" : `part ${shard + 1} of ${SHARDS}`}` +
  `${flags["--zone"] === "rotate" ? ` (the Indian day ${night.day}, by --zone rotate${flags["--now"] ? `, read at ${flags["--now"]}` : ""})` : ""}` +
  `${stopAfter === null ? "" : `; a deadline of ${stopAfter} minutes for the drive`}.`);

// ── The scenarios: every module in scripts/drive/scenarios/ ─────────────────────────────────────────────
// Discovered, not listed, so a scenario file cannot be written and forgotten. A module exports `group` (a
// word) and `scenarios` (an array of { id, title, run(env), contexts? }). They are read BEFORE the export is looked for, so `--list` needs no build.
const modules = [];
for (const file of fs.readdirSync(SCENARIO_DIR).filter((f) => f.endsWith(".mjs")).sort()) {
  const mod = await import(pathToFileURL(path.join(SCENARIO_DIR, file)).href);
  if (typeof mod.group !== "string" || !Array.isArray(mod.scenarios)) {
    console.error(`scripts/drive/scenarios/${file} must export \`group\` (a string) and \`scenarios\` (an array).`);
    process.exit(2);
  }
  modules.push({ file, group: mod.group, scenarios: mod.scenarios });
}

/** Expand a scenario into the runs it asks for: one, or one per browser context under the matrix. */
function runsOf(group, scenario) {
  const base = { group, id: `${group}/${scenario.id}`, title: scenario.title, run: scenario.run };
  if (!inShard(group, scenario.id, shard)) return [];
  if (!scenario.contexts) return [{ ...base, context: null }];
  const inZone = contextsFor(scenario.contexts, zone);
  const contexts = noTzMatrix ? inZone.slice(0, 1) : inZone;
  return contexts.map((c) => ({ ...base, id: `${base.id} [${c.locale} ${c.timezoneId}]`, context: c }));
}
const selected = modules.flatMap((m) => m.scenarios.flatMap((s) => runsOf(m.group, s)))
  .filter((r) => !only || r.group === only || r.id === only || r.id.startsWith(only));
if (!selected.length) {
  console.error(only ? `No scenario matches --only ${only}.` : "No scenarios were found under scripts/drive/scenarios/.");
  process.exit(2);
}
if (listOnly) {
  // ONE write, and the exit waits for it: `process.exit` straight after a large `console.log` to a PIPE (which is how a test reads this) drops what the pipe has not yet taken, and through a
  // slow reader the whole drive's list (a thousand lines) came back 218 lines short.
  await new Promise((resolve) => process.stdout.write(`${selected.map((r) => r.id).join("\n")}\n${selected.length} run(s) selected.\n`, resolve));
  process.exit(0);
}

if (!fs.existsSync(OUT)) {
  console.error(`${OUT} does not exist: run \`pnpm smoke:build\` first.`);
  process.exit(2);
}
// A build made for another port (or without the smoke env) calls hosts this server is not, and every screen
// would then fail on an aborted request and read as a product that is broken. Say which it is.
{
  const chunks = path.join(OUT, "_next", "static", "chunks");
  const wanted = `127.0.0.1:${PORT}/__api`;
  const built = fs.existsSync(chunks) && fs.readdirSync(chunks).some(
    (f) => f.endsWith(".js") && fs.readFileSync(path.join(chunks, f), "utf8").includes(wanted));
  if (!built) {
    console.error(
      `This build does not point at ${wanted}, so its calls would not reach the drive's stub.\n` +
      "Rebuild with `pnpm smoke:build` (port 4319), or set SMOKE_PORT to the port the build was made for.");
    process.exit(2);
  }
}

let headerRules = [];
let cspState = "not applied (--no-headers)";
if (noHeaders) {
  console.log("--no-headers: driving WITHOUT out/_headers. This is not the product as it is served.");
} else {
  const headersFile = path.join(OUT, "_headers");
  if (!fs.existsSync(headersFile)) {
    console.error("out/_headers does not exist, so this build is not the product as served.\n" +
      "  pnpm smoke:build     (writes it after `next build`)\nor pass --no-headers to drive without it on purpose.");
    process.exit(2);
  }
  headerRules = parseHeadersFile(fs.readFileSync(headersFile, "utf8"));
  const served = headersFor(headerRules, "/");
  cspState = served["content-security-policy"] ? "enforced"
    : served["content-security-policy-report-only"] ? "REPORT-ONLY" : "ABSENT";
  console.log(`Security headers: ${Object.keys(served).length} applied to every static response; CSP ${cspState}.`);
}

// ── Serving the export the way Cloudflare Pages does ─────────────────────────────────────────────────────
// A static export has one page per route SHAPE (`/clients/_placeholder/…`), and it is `out/_redirects` that
// answers a real id with that page. The walk imitates the rewrite from the route tree. The drive applies the
// FILE ITSELF, with the matcher `check-live-redirects.mjs` holds for exactly this (first match wins, the
// 100-dynamic cap honoured), because a drive follows links: a click that navigates asks for the page AND its
// `index.txt` RSC payload, and a server that knew only the HTML would send Next's router into a hard
// navigation and the drive would be testing a path nobody takes.
const redirectsFile = path.join(OUT, "_redirects");
const redirectRules = fs.existsSync(redirectsFile)
  ? rulesCloudflareKeeps(parseRules(fs.readFileSync(redirectsFile, "utf8")))
  : [];
function resolveBuilt(url) {
  const hit = redirectRules.length ? resolveRule(redirectRules, url) : null;
  const target = hit && hit.rule.status === "200" ? hit.target : url;
  let file = path.join(OUT, target);
  if (!path.extname(file)) file = path.join(file, "index.html");
  return file.startsWith(OUT) && fs.existsSync(file) ? file : null;
}

// ── The tables every scenario starts from ───────────────────────────────────────────────────────────────
function baseline() {
  return {
    users: [FAKE_USERS_ROW],
    firms: [FAKE_FIRM_ROW],
    clients: [CLIENT_ROW],
    chart_of_accounts: ACCOUNTS,
    customers: [CUSTOMER],
    vendors: [VENDOR],
    journal_entries: JOURNAL_ENTRIES,
  };
}

const stub = createStub({ root: OUT, port: PORT, headerRules, resolveBuilt });
await stub.start();
const chromium = await loadPlaywright();
// `--disable-background-networking` keeps Chromium itself (component updates, safe browsing) from calling out
// during a run: the page's own requests are sealed off below, and a browser that phones home would be noise in
// an environment whose egress is policed.
const browser = await chromium.launch({
  executablePath: installedChromium(),
  args: ["--disable-background-networking"],
});
if (shots) fs.mkdirSync(SHOT_DIR, { recursive: true });

const SESSION_SCRIPT = `(() => { try {
  for (const ref of ["127", "localhost", "placeholder"])
    localStorage.setItem("sb-" + ref + "-auth-token", ${JSON.stringify(JSON.stringify(FAKE_SESSION))});
} catch {} })();`;

/** A policy violation is an event, and a report-only policy raises it with no console error at all. */
const CSP_SCRIPT = `document.addEventListener("securitypolicyviolation", (e) => {
  (window.__cspViolations = window.__cspViolations || []).push(
    e.effectiveDirective + " blocked " + (e.blockedURI || "inline") + " (" + e.disposition + ")");
});`;

const SCENARIO_TIMEOUT_MS = 90_000;
const results = [];
const escaped = new Set();
const started = Date.now();

/** The report, as it stands (`reportOf` in drive/kit.mjs builds it). It is written as the run goes (at most every 20 seconds) and again at the end. This alone does NOT save the report of a run that
 *  the JOB cancels: a job that times out is cancelled and its later steps, the upload among them, never run (the run of 6 November 2026 ran 55 minutes against 45, and the step after the drive was
 *  still `pending` when it ended). What saves it is the DEADLINE below, which ends the drive before the job's allowance and leaves the job to upload what was written. The file written as the
 *  run goes is the report of a drive that is killed in any other way (a machine that is lost, a Ctrl-C). `final` is the write at the end, which the 20-second throttle does not apply to. */
let reportWrittenAt = 0;
let stoppedAtDeadline = false;
function writeReport(complete, final = false) {
  if (!reportPath) return;
  if (!final && Date.now() - reportWrittenAt < 20_000) return;
  reportWrittenAt = Date.now();
  const report = reportOf({
    complete, stoppedAtDeadline, only, tzMatrix: !noTzMatrix, zone, shard, stopAfter, chosenAtMs: chosenAt, csp: cspState, pinnedClock: NOW,
    commit: process.env.GITHUB_SHA || null, selected, results, escaped: [...escaped], startedMs: started, nowMs: Date.now(),
  });
  fs.mkdirSync(path.dirname(path.resolve(reportPath)), { recursive: true });
  fs.writeFileSync(reportPath, JSON.stringify(report, null, 2) + "\n");
}

for (const run of selected) {
  // THE DEADLINE (`--stop-after`): no scenario is STARTED after it. One that is running finishes (or times out, at most SCENARIO_TIMEOUT_MS), so the drive ends at most that much past it.
  if (deadlinePassed(started, Date.now(), stopAfter)) { stoppedAtDeadline = true; break; }
  const t0 = Date.now();
  stub.reset(baseline());
  stub.route({ method: "GET", re: /service-catalogue/, reply: () => ok([ITEM]) });
  const context = await browser.newContext({
    // 1440 by 900 unless DRIVE_VIEWPORT_HEIGHT says otherwise: the probe `PROBE_DIALOG_FIT=1` is run at a shorter screen (768, 720) to find
    // the dialogs whose Save button is out of reach on a smaller laptop.
    viewport: { width: 1440, height: Number(process.env.DRIVE_VIEWPORT_HEIGHT) || 900 },
    ...(run.context ?? {}),
  });
  await context.clock.setFixedTime(new Date(NOW));
  await context.addInitScript(SESSION_SCRIPT);
  await context.addInitScript(CSP_SCRIPT);
  // Anything that is not this server is refused and recorded, as in the walk: a screen that reaches for a real
  // host in a drive is a defect, and a drive that quietly reached one would be touching production.
  await context.route("**/*", (route) => {
    const url = route.request().url();
    if (url.startsWith(`http://127.0.0.1:${PORT}`) || url.startsWith("data:") || url.startsWith("blob:")) return route.continue();
    try { escaped.add(new URL(url).host); } catch { escaped.add(url.slice(0, 40)); }
    return route.abort();
  });
  const page = await context.newPage();
  // PROBE_REACHABLE=1: a sentence a scenario waits for must also be one the person can reach, not one drawn BEHIND an overlay (a message line under a full-screen
  // dialog is "visible" to Playwright and unseen by the person). Every four-second wait for a locator is followed by a trial click, which asks the browser whether
  // the element would receive the click. A probe and not a rule: an element with pointer-events off (a toast) fails it though a person can read it.
  if (process.env.PROBE_REACHABLE) {
    const proto = Object.getPrototypeOf(page.locator("body"));
    if (!proto.__reachableProbe) {
      const waitFor = proto.waitFor;
      proto.waitFor = async function (options) {
        await waitFor.call(this, options);
        if (options && options.timeout === 4000 && (options.state === undefined || options.state === "visible")) {
          await this.click({ trial: true, timeout: 1500 }).catch((e) => {
            console.log(`PROBE-UNREACHABLE ${this}: ${String(e.message).split("\n").slice(0, 4).join(" | ").slice(0, 260)}`);
            throw e;
          });
        }
      };
      proto.__reachableProbe = true;
    }
  }
  page.setDefaultTimeout(10_000);

  const problems = [];
  const natives = [];
  page.on("pageerror", (e) => problems.push(`threw: ${e.message}`));
  // Chromium writes a "Failed to load resource" console error for every non-2xx response, a refusal the stub
  // sent on purpose included. Those are counted apart and judged against the refusals the stub says it sent
  // (below): one more than that is a request that failed for a reason nobody planned.
  const networkErrors = [];
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    if (/^Failed to load resource: the server responded with a status of [45]\d\d/.test(m.text())) networkErrors.push(m.text().slice(0, 200));
    else problems.push(`console.error: ${m.text().slice(0, 200)}`);
  });
  page.on("dialog", (d) => {
    // The browser's own leave-site prompt is accepted so a reload does not hang. Any other native dialog is
    // the product asking with the browser's voice, which it has an in-app dialog for.
    if (d.type() === "beforeunload") { natives.push("beforeunload"); d.accept(); return; }
    problems.push(`a native ${d.type()} dialog was shown: ${JSON.stringify(d.message()).slice(0, 120)}`);
    d.dismiss();
  });

  const env = {
    page, context, stub, natives,
    clientId: CLIENT_ID,
    /** A URL inside the client workspace, trailing slash on the path as the export serves it. */
    at: (rest) => {
      const [p, q = ""] = rest.split("?");
      return `http://127.0.0.1:${PORT}/clients/${CLIENT_ID}${p.endsWith("/") ? p : p + "/"}${q ? "?" + q : ""}`;
    },
    base: `http://127.0.0.1:${PORT}`,
    /** Open a fresh page in the same context (storage shared), for a scenario that needs a second tab. */
    newPage: () => context.newPage(),
  };

  let error = null;
  try {
    await Promise.race([
      run.run(env),
      new Promise((_, reject) => setTimeout(() => reject(new Error(`timed out after ${SCENARIO_TIMEOUT_MS / 1000} s`)), SCENARIO_TIMEOUT_MS)),
    ]);
    if (networkErrors.length > stub.refusalsServed()) {
      problems.push(`console.error: ${networkErrors.length - stub.refusalsServed()} request(s) failed that the stub did not refuse on purpose (${networkErrors[networkErrors.length - 1]})`);
    }
    const violations = await page.evaluate(() => window.__cspViolations || []).catch(() => []);
    for (const v of violations) problems.push(`CSP violation: ${String(v).slice(0, 200)}`);
  } catch (e) {
    error = (e && e.message ? e.message : String(e)).split("\n").slice(0, 6).join(" | ").slice(0, 700);
    if (shots) {
      await page.screenshot({ path: path.join(SHOT_DIR, run.id.replace(/[^A-Za-z0-9._-]+/g, "_") + ".png"), fullPage: true }).catch(() => {});
    }
  }
  await context.close().catch(() => {});

  const good = !error && problems.length === 0;
  results.push({ id: run.id, group: run.group, title: run.title, ok: good, ms: Date.now() - t0, error, problems: [...new Set(problems)] });
  console.log(`${good ? "ok  " : "FAIL"} ${run.id}  (${Date.now() - t0} ms)`);
  if (!good) {
    if (error) console.log(`       ${error}`);
    for (const p of [...new Set(problems)].slice(0, 4)) console.log(`       ${p}`);
  }
  writeReport(false);
}

await browser.close();
await stub.stop();

const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length} scenario(s) driven, ${failed.length} failed. CSP ${cspState}.`);
if (stoppedAtDeadline) {
  console.log(`STOPPED AT ITS DEADLINE (--stop-after ${stopAfter} minutes): ${results.length} of ${selected.length} run(s) driven; the ${selected.length - results.length} not driven are named in the report.`);
}
if (escaped.size) {
  console.log(`BLOCKED: a screen reached for a host that is not the stub: ${[...escaped].join(", ")}. Nothing was contacted.`);
}
if (process.env.GITHUB_ACTIONS === "true") {
  if (stoppedAtDeadline) {
    console.log(`::error title=Money-editor drive stopped at its deadline::${results.length} of ${selected.length} run(s) were driven in ${stopAfter} minutes; the rest are named in the report. The drive has outgrown its allowance: see the-nightly-drive-fits-its-allowance-and-visits-each-zone-in-turn.test.ts.`);
  }
  for (const f of failed.slice(0, 10)) {
    const first = (f.error ?? f.problems[0] ?? "failed").replace(/%/g, "%25").replace(/\r/g, "%0D").replace(/\n/g, "%0A");
    console.log(`::error title=Money-editor drive: ${f.id.replace(/[,:]/g, " ")} failed::${first.slice(0, 300)}`);
  }
}

if (reportPath) {
  writeReport(!stoppedAtDeadline, true);
  console.log(`report written to ${reportPath}`);
  if (process.env.GITHUB_STEP_SUMMARY) {
    const lines = [
      `### Money-editor drive: ${stoppedAtDeadline ? "STOPPED AT ITS DEADLINE" : failed.length ? "FAILED" : "clean"}`,
      "",
      `${results.length} of ${selected.length} scenarios driven in Chromium against the smoke build, ${failed.length} failed. Date scenarios: ${zone === "all" ? "every zone of the matrix" : `${zone} only`}, ${shard === "all" ? "the whole group" : `part ${shard + 1} of ${SHARDS}`}.` +
        `${stoppedAtDeadline ? ` It was stopped at its deadline of ${stopAfter} minutes: ${selected.length - results.length} not driven (named in the report).` : ""}`,
      "",
    ];
    if (failed.length) {
      lines.push("| scenario | what went wrong |", "|---|---|");
      for (const f of failed) {
        lines.push(`| \`${f.id}\` | ${(f.error ?? f.problems[0] ?? "").replace(/\|/g, "\\|").replace(/\s+/g, " ")} |`);
      }
      lines.push("");
    }
    fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY, lines.join("\n") + "\n");
  }
}

process.exit(failed.length || escaped.size || stoppedAtDeadline ? 1 : 0);
