// The marketing quality pass (POST-A-122): what the workflow is allowed to be,
// and what its scripts read and print.
//
// The pass runs Lighthouse and axe on a GitHub runner when a person starts it
// (.github/workflows/marketing-quality.yml). It cannot run here, and this file
// does not pretend it did: it holds the workflow to its shape (started by hand
// only, no `paths:` filter, not a required check, every tool at an exact
// version, nothing installed with apt), and it drives the parts that need no
// browser: the page list read off the app/ tree, the plan's budget read off the
// plan, the figures taken out of a Lighthouse report and an axe result, the
// summary, and the server that stands in for Cloudflare Pages.
//
// Run with: node --experimental-strip-types --test scripts/the-marketing-quality-pass-is-started-by-hand.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import zlib from "node:zlib";
import type { AddressInfo } from "node:net";
import { fileURLToPath } from "node:url";
import {
  AXE_TAGS,
  axeCountsOf,
  metricsOf,
  pagesOf,
  planBudget,
  renderSummary,
  slugOf,
} from "./qualityReport.mjs";
import { createServer, headersFor, parseHeadersFile, resolvePath } from "./serve-out.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const MARKETING = path.resolve(HERE, "..");
const REPO = path.resolve(MARKETING, "..", "..");
const WORKFLOWS = path.join(REPO, ".github", "workflows");
const WORKFLOW = fs.readFileSync(path.join(WORKFLOWS, "marketing-quality.yml"), "utf8");
const PLAN = fs.readFileSync(path.join(REPO, "docs", "marketing", "2026-09-16-website-redesign-plan.md"), "utf8");

/** The workflow with its comment lines removed: the header describes triggers it must not have. */
const CODE = WORKFLOW.split("\n").filter((l) => !l.trimStart().startsWith("#")).join("\n");

const env = (name: string, text = CODE) => text.match(new RegExp(`^\\s+${name}:\\s*"([^"]+)"`, "m"))?.[1];

// ── the workflow ─────────────────────────────────────────────────────────────

test("it is started by hand and by nothing else", () => {
  const on = CODE.match(/^on:\n([\s\S]*?)^\S/m)?.[1] ?? "";
  assert.match(on, /^\s+workflow_dispatch:/m);
  for (const trigger of ["push", "pull_request", "pull_request_target", "schedule", "workflow_run"]) {
    assert.doesNotMatch(on, new RegExp(`^\\s+${trigger}:`, "m"), `the pass must not run on ${trigger}`);
  }
  assert.doesNotMatch(CODE, /^\s+paths(-ignore)?:/m, "a paths filter has no place on a workflow started by hand");
});

test("it is not one of the required checks", () => {
  const backend = fs.readFileSync(path.join(WORKFLOWS, "backend-ci.yml"), "utf8");
  const required = ["pytest — mock mode (Python 3.11)", "migration apply — real Postgres 16"];
  for (const name of required) assert.ok(backend.includes(name), `premise: ${name} is the backend's job`);
  const names = [...CODE.matchAll(/^\s{4}name:\s*(.+)$/gm)].map((m) => m[1].trim());
  assert.ok(names.length >= 1);
  for (const name of names) assert.ok(!required.includes(name), `${name} is a required check's name`);
});

test("every tool it adds is pinned to an exact version, and the axe pair is the smoke walk's", () => {
  const exact = /^\d+\.\d+\.\d+$/;
  for (const name of ["LIGHTHOUSE_VERSION", "PLAYWRIGHT_VERSION", "AXE_PLAYWRIGHT_VERSION"]) {
    assert.match(env(name) ?? "", exact, `${name} is not an exact version`);
  }
  const smoke = fs.readFileSync(path.join(WORKFLOWS, "smoke-walk.yml"), "utf8");
  assert.equal(env("PLAYWRIGHT_VERSION"), env("PLAYWRIGHT_VERSION", smoke));
  assert.equal(env("AXE_PLAYWRIGHT_VERSION"), env("AXE_PLAYWRIGHT_VERSION", smoke));
  assert.match(CODE, /pnpm add --save-dev[\s\S]*?"lighthouse@\$\{LIGHTHOUSE_VERSION\}"/);
  assert.match(CODE, /"@axe-core\/playwright@\$\{AXE_PLAYWRIGHT_VERSION\}"/);
});

test("the site's own install pays for none of them", () => {
  const pkg = JSON.parse(fs.readFileSync(path.join(MARKETING, "package.json"), "utf8"));
  const deps = { ...pkg.dependencies, ...pkg.devDependencies };
  for (const name of ["lighthouse", "playwright", "playwright-core", "@axe-core/playwright", "axe-core"]) {
    assert.ok(!(name in deps), `${name} is in apps/marketing/package.json`);
  }
  const ci = fs.readFileSync(path.join(WORKFLOWS, "marketing-ci.yml"), "utf8").toLowerCase();
  for (const tool of ["lighthouse", "playwright", "axe-core"]) {
    assert.ok(!ci.includes(tool), `Marketing CI mentions ${tool}; the pass's tools are the pass's job's alone`);
  }
});

test("it installs nothing with apt and uses the runner's Chrome", () => {
  assert.doesNotMatch(CODE, /apt-get|playwright install/);
  assert.match(CODE, /CHROME_PATH=/);
});

test("it builds and serves this commit, or measures the deployed site, and keeps the reports either way", () => {
  const build = CODE.indexOf("pnpm build");
  const serve = CODE.indexOf("node scripts/serve-out.mjs --root out");
  const measure = CODE.indexOf("node scripts/quality-pass.mjs --base http://127.0.0.1:4173");
  assert.ok(build > 0 && serve > build && measure > serve, "build, then serve, then measure");
  assert.match(CODE, /node scripts\/quality-pass\.mjs --base "\$LIVE_SITE_URL"/);
  const keep = CODE.slice(CODE.indexOf("name: Keep the reports"));
  assert.match(keep, /if: always\(\)/);
  assert.match(keep, /uses: actions\/upload-artifact@v\d+/);
  assert.match(keep, /path: apps\/marketing\/\.qa\//);
});

test("the deployed site it measures is the one the site says it is", () => {
  const site = fs.readFileSync(path.join(MARKETING, "lib", "site.ts"), "utf8");
  const fallback = site.match(/NEXT_PUBLIC_SITE_URL \|\| "([^"]+)"/)?.[1];
  assert.ok(fallback, "premise: lib/site.ts falls back to a literal origin");
  assert.equal(env("LIVE_SITE_URL"), fallback);
});

// ── what it measures and how it reports ──────────────────────────────────────

test("every page of the site is measured, read off the app tree", () => {
  const pages = pagesOf(path.join(MARKETING, "app"));
  for (const p of ["/", "/pricing/", "/products/", "/support/", "/resources/", "/demo/", "/privacy/", "/access/"]) {
    assert.ok(pages.includes(p), `${p} is not measured`);
  }
  assert.equal(pages[0], "/");
  assert.ok(pages.every((p) => !p.includes("(") && p.endsWith("/")), pages.join(" "));
  assert.equal(slugOf("/"), "home");
  assert.equal(slugOf("/pricing/"), "pricing");
});

test("the plan's budget is read word for word from the plan", () => {
  const budget = planBudget(PLAN);
  assert.equal(budget.length, 5, budget.join("\n"));
  assert.ok(budget[0].startsWith("globe capped at 30fps"), budget[0]);
  assert.ok(budget[4].startsWith("the hero's box is reserved so nothing shifts"), budget[4]);
  for (const line of budget) assert.ok(!line.includes("\n") && !line.includes("  "), line);
  assert.deepEqual(planBudget("# no budget here\n"), []);
});

const LHR = {
  requestedUrl: "http://127.0.0.1:4173/",
  finalDisplayedUrl: "http://127.0.0.1:4173/",
  lighthouseVersion: "13.5.0",
  configSettings: { formFactor: "mobile" },
  categories: { performance: { score: 0.91 }, accessibility: { score: 1 }, "best-practices": { score: 0.96 }, seo: { score: null } },
  audits: {
    "largest-contentful-paint": { numericValue: 2345.6, score: 0.93 },
    "cumulative-layout-shift": { numericValue: 0.0123, score: 1 },
    "total-blocking-time": { numericValue: 87.2, score: 0.99 },
  },
  runWarnings: [],
};

test("the figures are taken out of a Lighthouse report, and an absent one stays absent", () => {
  const m = metricsOf(LHR);
  assert.equal(m.performance, 91);
  assert.equal(m.accessibility, 100);
  assert.equal(m.seo, null, "a null score is not zero");
  assert.equal(m.lcpMs, 2345.6);
  assert.equal(m.cls, 0.0123);
  assert.equal(m.fcpMs, null, "a missing audit is not zero");
  assert.equal(m.formFactor, "mobile");
  assert.equal(metricsOf({}).lcpMs, null);
});

test("an axe result is counted by rule and by impact", () => {
  const a = axeCountsOf({
    url: "http://x/",
    violations: [
      { id: "color-contrast", impact: "serious", nodes: [{}, {}, {}] },
      { id: "image-alt", impact: "critical", nodes: [{}] },
    ],
  });
  assert.equal(a.rules.length, 2);
  assert.equal(a.nodes, 4);
  assert.deepEqual(a.byImpact, { critical: 1, serious: 3, moderate: 0, minor: 0 });
  assert.deepEqual(axeCountsOf({}).rules, []);
  assert.deepEqual(AXE_TAGS, ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]);
});

test("the summary puts the plan's words beside what was measured and marks nothing as passing", () => {
  const budget = planBudget(PLAN);
  const md = renderSummary({
    base: "http://127.0.0.1:4173",
    commit: "abc1234",
    budget,
    lighthouse: [{ page: "/", ...metricsOf(LHR) }],
    axe: [{ page: "/", viewport: "desktop", ...axeCountsOf({ violations: [{ id: "color-contrast", impact: "serious", nodes: [{}] }] }) }],
    failures: ["Lighthouse on /demo/ (desktop) exited 1: boom"],
  });
  for (const line of budget) assert.ok(md.includes(`- ${line}`), `the budget line is not quoted: ${line}`);
  assert.match(md, /\| \/ \| mobile \| 91 \| 2\.35 s \| 0\.93 \| 0\.012 \| 1\.00 \| 87 ms \| 100 \| 96 \| — \|/);
  assert.match(md, /color-contrast \(serious, 1\)/);
  assert.match(md, /## Measurements that did not happen\n\n- Lighthouse on \/demo\/ \(desktop\) exited 1: boom/);
  assert.match(md, /The plan states no LCP or CLS figure/);
  assert.doesNotMatch(md, /\b(PASS|FAIL|within budget|over budget)\b/i);
});

// ── the server that stands in for Cloudflare Pages ───────────────────────────

test("the server answers as Pages does for a trailing-slash export", async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "serve-out-"));
  fs.writeFileSync(path.join(root, "index.html"), "<!doctype html><title>home</title>" + "x".repeat(2000));
  fs.mkdirSync(path.join(root, "pricing"));
  fs.writeFileSync(path.join(root, "pricing", "index.html"), "<title>pricing</title>");
  fs.writeFileSync(path.join(root, "404.html"), "<title>not found</title>");
  fs.writeFileSync(path.join(root, "hero.webp"), Buffer.from([1, 2, 3]));
  fs.writeFileSync(path.join(root, "_headers"), "# generated\n/*\n  X-Frame-Options: DENY\n  Referrer-Policy: strict-origin-when-cross-origin\n");
  fs.writeFileSync(path.join(path.dirname(root), "outside-the-root.txt"), "secret");

  const server = createServer(root);
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const origin = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  try {
    const home = await fetch(`${origin}/`, { headers: { "accept-encoding": "gzip" } });
    assert.equal(home.status, 200);
    assert.equal(home.headers.get("content-type"), "text/html; charset=utf-8");
    assert.equal(home.headers.get("x-frame-options"), "DENY", "out/_headers is applied");
    assert.match(await home.text(), /<title>home<\/title>/, "fetch undoes the gzip it asked for");

    // fetch undoes a gzip it asked for, so the bytes on the wire are read with a plain request.
    const gzipGet = (p: string) =>
      new Promise<{ encoding: string | undefined; body: Buffer }>((resolve, reject) => {
        http
          .get(`${origin}${p}`, { headers: { "accept-encoding": "gzip" } }, (res) => {
            const chunks: Buffer[] = [];
            res.on("data", (c: Buffer) => chunks.push(c));
            res.on("end", () => resolve({ encoding: res.headers["content-encoding"], body: Buffer.concat(chunks) }));
          })
          .on("error", reject);
      });
    const raw = await gzipGet("/");
    assert.equal(raw.encoding, "gzip");
    assert.match(zlib.gunzipSync(raw.body).toString(), /<title>home<\/title>/);
    // A rebuild under a running server is served as built: the first version of
    // this server cached the compressed page by its path alone and went on
    // sending the last build's HTML, whose stylesheet no longer existed.
    fs.writeFileSync(path.join(root, "index.html"), "<!doctype html><title>rebuilt</title>" + "y".repeat(3000));
    assert.match(zlib.gunzipSync((await gzipGet("/")).body).toString(), /<title>rebuilt<\/title>/);

    const bare = await fetch(`${origin}/pricing`, { redirect: "manual" });
    assert.equal(bare.status, 308);
    assert.equal(bare.headers.get("location"), "/pricing/");
    assert.equal((await fetch(`${origin}/pricing/`)).status, 200);

    const picture = await fetch(`${origin}/hero.webp`, { headers: { "accept-encoding": "gzip" } });
    assert.equal(picture.headers.get("content-type"), "image/webp");
    assert.equal(picture.headers.get("content-encoding"), null, "a picture is not gzipped");

    const missing = await fetch(`${origin}/no-such-page/`);
    assert.equal(missing.status, 404);
    assert.match(await missing.text(), /not found/);

    assert.equal((await fetch(`${origin}/`, { method: "POST" })).status, 405);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }

  for (const climb of ["/../outside-the-root.txt", "/%2e%2e/outside-the-root.txt", "/pricing/../../outside-the-root.txt"]) {
    const answer = resolvePath(root, climb);
    assert.ok(!answer.file || answer.file.startsWith(root), `${climb} reached ${answer.file}`);
  }
  assert.equal(resolvePath(root, "/%E0%A4%A").status, 400, "a malformed escape is refused, not thrown");
});

test("a _headers rule applies to the paths it names", () => {
  const rules = parseHeadersFile("/*\n  A: 1\n/pricing/\n  B: 2\n# note\n");
  assert.deepEqual(headersFor(rules, "/"), [["A", "1"]]);
  assert.deepEqual(headersFor(rules, "/pricing/"), [["A", "1"], ["B", "2"]]);
});
