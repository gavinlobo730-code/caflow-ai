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
 * --no-tz-matrix   run each date scenario once, not under en-US/Los Angeles, en-IN/Kolkata and en-GB/Kiritimati
 * --shots          keep a screenshot of every failed scenario in .smoke/drive/
 * --out <dir>      drive another export than out/ (a build of an earlier commit, a patched copy)
 * --no-headers     drive WITHOUT out/_headers (not the product as it is served)
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
 * EXIT. 0: every scenario held. 1: a scenario failed (the report is written first). 2: it could not tell: no
 * export, an export not built for this port, no Playwright, or nothing ran.
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
import { installedChromium, loadPlaywright } from "./drive/kit.mjs";
import { createStub, ok } from "./drive/stub.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");
const SHOT_DIR = path.join(WEB, ".smoke", "drive");
const SCENARIO_DIR = path.join(__dirname, "drive", "scenarios");

/** The port `pnpm smoke:build` bakes into the bundle (the walk's `SMOKE_PORT`, the same default). */
const PORT = Number(process.env.SMOKE_PORT || 4319);

const args = process.argv.slice(2);
const valueOf = (flag) => (args.includes(flag) ? args[args.indexOf(flag) + 1] : null);
const only = valueOf("--only");
const reportPath = valueOf("--report");
const shots = args.includes("--shots");
const noTzMatrix = args.includes("--no-tz-matrix");
/** The export to drive: `out/`, or another directory of the same shape (a build of an earlier commit, to see a
 *  fix fail without it, or a copy with the guard patched out of the compiled chunks, as a negative control). */
const OUT = path.resolve(valueOf("--out") ?? path.join(WEB, "out"));
if (args.includes("--report") && (!reportPath || reportPath.startsWith("--"))) {
  console.error("--report needs a file path, e.g. --report .smoke/drive-report.json");
  process.exit(2);
}
if (args.includes("--only") && (!only || only.startsWith("--"))) {
  console.error("--only needs a group or scenario id, e.g. --only dates");
  process.exit(2);
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
if (args.includes("--no-headers")) {
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

// ── The scenarios: every module in scripts/drive/scenarios/ ─────────────────────────────────────────────
// Discovered, not listed, so a scenario file cannot be written and forgotten. A module exports `group` (a
// word) and `scenarios` (an array of { id, title, run(env), contexts? }).
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
  if (!scenario.contexts) return [{ ...base, context: null }];
  const contexts = noTzMatrix ? scenario.contexts.slice(0, 1) : scenario.contexts;
  return contexts.map((c) => ({ ...base, id: `${base.id} [${c.locale} ${c.timezoneId}]`, context: c }));
}
const selected = modules.flatMap((m) => m.scenarios.flatMap((s) => runsOf(m.group, s)))
  .filter((r) => !only || r.group === only || r.id === only || r.id.startsWith(only));
if (!selected.length) {
  console.error(only ? `No scenario matches --only ${only}.` : "No scenarios were found under scripts/drive/scenarios/.");
  process.exit(2);
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

for (const run of selected) {
  const t0 = Date.now();
  stub.reset(baseline());
  stub.route({ method: "GET", re: /service-catalogue/, reply: () => ok([ITEM]) });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
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
}

await browser.close();
await stub.stop();

const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length} scenario(s) driven, ${failed.length} failed. CSP ${cspState}.`);
if (escaped.size) {
  console.log(`BLOCKED: a screen reached for a host that is not the stub: ${[...escaped].join(", ")}. Nothing was contacted.`);
}
if (process.env.GITHUB_ACTIONS === "true") {
  for (const f of failed.slice(0, 10)) {
    const first = (f.error ?? f.problems[0] ?? "failed").replace(/%/g, "%25").replace(/\r/g, "%0D").replace(/\n/g, "%0A");
    console.log(`::error title=Money-editor drive: ${f.id.replace(/[,:]/g, " ")} failed::${first.slice(0, 300)}`);
  }
}

if (reportPath) {
  const report = {
    generated_at: new Date().toISOString(),
    commit: process.env.GITHUB_SHA || null,
    mode: { only, tz_matrix: !noTzMatrix },
    csp: cspState,
    pinned_clock: NOW,
    ok: failed.length === 0 && escaped.size === 0,
    scenarios_driven: results.length,
    failed: failed.map((f) => ({ id: f.id, error: f.error, problems: f.problems })),
    scenarios: results,
    blocked_hosts: [...escaped],
    duration_ms: Date.now() - started,
  };
  fs.mkdirSync(path.dirname(path.resolve(reportPath)), { recursive: true });
  fs.writeFileSync(reportPath, JSON.stringify(report, null, 2) + "\n");
  console.log(`report written to ${reportPath}`);
  if (process.env.GITHUB_STEP_SUMMARY) {
    const lines = [
      `### Money-editor drive: ${failed.length ? "FAILED" : "clean"}`,
      "",
      `${results.length} scenarios driven in Chromium against the smoke build, ${failed.length} failed.`,
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

process.exit(failed.length || escaped.size ? 1 : 0);
