// A crash in a CA's browser reaches the team, and nothing from the screen goes with it (ops-09).
//
// Run with:
//   node --experimental-strip-types --test scripts/the-browser-reports-crashes-without-recording-screens.test.ts
//
// WHAT WAS WRONG
//     `sentry.client.config.ts` and `sentry.edge.config.ts` sat in apps/web and NOTHING IMPORTED EITHER.
//     `@sentry/nextjs` loads them through `withSentryConfig` in next.config.mjs and there was none, so
//     the browser reported nothing while looking wired — a CA's broken screen was known only if the CA
//     phoned. They also set `tracesSampleRate: 1.0` and a 10% session replay: a quota spent on every page
//     view, and a recording of screens that hold PAN, payroll and bank figures.
//
// THE RULES IT STATES, each over the tree rather than a list of today's files
//     1. A Sentry config file the SDK only loads through a build plugin may not exist unless that plugin
//        is configured — an unreachable control reads as a working one.
//     2. One module imports the SDK. What is sent, and what is scrubbed before it is, is decided in one place.
//     3. No tracing and no replay anywhere in app code. Replay is a decision for the owner, not a default,
//        and enabling it means naming the routes that must be blocked (payroll, bank, the client portal).
//     4. The DSN is never a literal: it is a build-time variable, because this is a static export.
//     5. A crash an error BOUNDARY caught is reported — the half an SDK install alone misses, because a
//        boundary swallows the throw before any global handler sees it. There are 65 error.tsx files and
//        they all render one component, so the rule is that they keep doing so and that it reports.
//     6. The tracker is started from the root layout, and the release is the commit that was built.
//
// WHAT THIS CANNOT PROVE is that an event reaches a Sentry project: that needs a DSN. The same wiring was
// exercised end to end against a local stand-in for the ingest host on the day it was written, and what
// arrived is described in docs/operations/error-tracking.md.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");

function read(rel: string): string {
  return fs.readFileSync(path.join(WEB, rel), "utf8");
}

/** Every non-test source file under the app's own code directories. */
function sources(): string[] {
  const out: string[] = [];
  const walk = (dir: string) => {
    for (const entry of fs.readdirSync(path.join(WEB, dir), { withFileTypes: true })) {
      const rel = path.posix.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (entry.name === "node_modules" || entry.name === ".next" || entry.name === "out") continue;
        walk(rel);
      } else if (/\.(ts|tsx|mjs|js)$/.test(entry.name) && !/\.test\.(ts|tsx)$/.test(entry.name)) {
        out.push(rel);
      }
    }
  };
  for (const dir of ["app", "components", "lib"]) walk(dir);
  return out;
}

test("the tree has the code this file is about (a vacuity floor)", () => {
  const files = sources();
  assert.ok(files.length > 300, `only ${files.length} source files found — the walk is broken`);
  assert.ok(files.includes("lib/monitoring/index.ts"));
  assert.ok(files.includes("lib/monitoring/options.ts"));
  assert.ok(files.includes("lib/monitoring/scrub.ts"));
});

// ── 1 ──────────────────────────────────────────────────────────────────────────

test("no Sentry config file sits where only a build plugin would load it", () => {
  const strays = fs.readdirSync(WEB).filter((f) => /^sentry\.(client|server|edge)\.config\./.test(f));
  const config = stripComments(read("next.config.mjs"));
  const pluginConfigured = /withSentryConfig/.test(config);
  assert.ok(
    strays.length === 0 || pluginConfigured,
    `${strays.join(", ")} would be loaded by nothing: next.config.mjs does not use withSentryConfig`,
  );
  // And the two that were there stay gone even if the plugin is added later: their options were the defect.
  for (const gone of ["sentry.client.config.ts", "sentry.edge.config.ts"]) {
    assert.ok(!fs.existsSync(path.join(WEB, gone)), `${gone} is back`);
  }
});

// ── 2 ──────────────────────────────────────────────────────────────────────────

test("one module imports the SDK", () => {
  const importers = sources().filter((f) => /from\s+["']@sentry\/|import\(\s*["']@sentry\/|require\(\s*["']@sentry\//.test(stripComments(read(f))));
  assert.deepEqual(importers, ["lib/monitoring/index.ts"]);
});

// ── 3 ──────────────────────────────────────────────────────────────────────────

test("no app code turns on tracing, replay, profiling or user feedback", () => {
  const banned = /\b(tracesSampleRate|tracesSampler|tracePropagationTargets|enableTracing|browserTracingIntegration|replayIntegration|replayCanvasIntegration|replaysSessionSampleRate|replaysOnErrorSampleRate|feedbackIntegration|browserProfilingIntegration|withSentryConfig)\b/;
  const hits = sources().flatMap((f) => {
    const lines = stripComments(read(f)).split("\n");
    return lines.flatMap((l, i) => (banned.test(l) ? [`${f}:${i + 1}: ${l.trim()}`] : []));
  });
  assert.deepEqual(hits, [], "the browser tracker is an error-reporting install and records no screens:\n  " + hits.join("\n  "));
});

// ── 4 ──────────────────────────────────────────────────────────────────────────

test("the DSN is a build-time variable and never a literal in app code", () => {
  const hits = sources().filter((f) => /ingest(\.[a-z]+)?\.sentry\.io|@o\d+\./.test(stripComments(read(f))));
  assert.deepEqual(hits, []);
  assert.match(stripComments(read("lib/monitoring/index.ts")), /process\.env\.NEXT_PUBLIC_SENTRY_DSN/);
});

test("the monitoring code reads NEXT_PUBLIC values only, and no auth token exists in the source", () => {
  for (const f of sources().filter((f) => f.startsWith("lib/monitoring/") || f.startsWith("components/monitoring/"))) {
    const code = stripComments(read(f));
    for (const m of code.matchAll(/process\.env\.([A-Z0-9_]+)/g)) {
      assert.match(m[1], /^NEXT_PUBLIC_/, `${f} reads ${m[1]}, which a static export cannot hold and must not publish`);
    }
  }
  const all = sources().map((f) => stripComments(read(f))).join("\n");
  assert.ok(!/SENTRY_AUTH_TOKEN/.test(all), "a Sentry auth token in a static export would be published");
});

// ── 5 ──────────────────────────────────────────────────────────────────────────

function errorBoundaries(): string[] {
  const out: string[] = [];
  const walk = (dir: string) => {
    for (const entry of fs.readdirSync(path.join(WEB, dir), { withFileTypes: true })) {
      const rel = path.posix.join(dir, entry.name);
      if (entry.isDirectory()) walk(rel);
      else if (entry.name === "error.tsx") out.push(rel);
    }
  };
  walk("app");
  return out;
}

test("every error.tsx renders the one boundary, so one call reports them all", () => {
  const files = errorBoundaries();
  assert.ok(files.length >= 60, `found ${files.length} error.tsx files — the walk is broken or they were deleted`);
  const stray = files.filter((f) => !/ModuleErrorBoundary/.test(stripComments(read(f))) && !/reportClientError/.test(stripComments(read(f))));
  assert.deepEqual(stray, [], "an error.tsx that renders its own UI swallows a crash without telling anybody");
});

test("the shared boundary reports what it catches, from an effect", () => {
  const src = stripComments(read("components/ModuleErrorBoundary.tsx"));
  assert.match(src, /import\s*\{\s*reportClientError\s*\}\s*from\s*"@\/lib\/monitoring"/);
  const effect = src.match(/useEffect\(\(\)\s*=>\s*\{([\s\S]*?)\},\s*\[/);
  assert.ok(effect, "the boundary has no effect");
  assert.match(effect[1], /reportClientError\(\s*error\s*,/);
});

test("the root-layout boundary reports too, and starts the tracker itself", () => {
  const src = stripComments(read("app/global-error.tsx"));
  assert.match(src, /reportClientError\(\s*error\s*,\s*"root layout"\s*\)/);
  assert.match(src, /useEffect/);
});

// ── 6 ──────────────────────────────────────────────────────────────────────────

test("the tracker starts from the root layout, outside the auth providers", () => {
  const src = stripComments(read("app/layout.tsx"));
  assert.match(src, /<MonitoringInit\s*\/>/);
  assert.ok(src.indexOf("<MonitoringInit") < src.indexOf("<AuthProvider"), "a crash while signing in must be reportable");
});

test("the release is the commit Cloudflare built, carried in by next.config.mjs", () => {
  const config = stripComments(read("next.config.mjs"));
  assert.match(config, /NEXT_PUBLIC_SENTRY_RELEASE:[\s\S]*CF_PAGES_COMMIT_SHA/);
  assert.match(config, /NEXT_PUBLIC_SENTRY_ENVIRONMENT:[\s\S]*CF_PAGES_BRANCH/);
  // The environment must say a PREVIEW is not production, or a preview's crashes page someone for prod.
  assert.match(config, /"preview"/);
});

test("the DSN is never defaulted: with none built in nothing starts", () => {
  const src = stripComments(read("lib/monitoring/options.ts"));
  assert.match(src, /if\s*\(!dsn\)\s*return null/);
  assert.ok(!/NEXT_PUBLIC_SENTRY_DSN\s*\|\|/.test(stripComments(read("next.config.mjs"))), "next.config must not invent a DSN");
});
