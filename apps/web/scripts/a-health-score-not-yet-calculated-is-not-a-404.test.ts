/**
 * sweep-accounting-hub-1-03 / sweep-tds-mca-11 — ClientTopBar
 * (components/shell/ClientTopBar.tsx) calls getLatestHealthScore on mount for
 * EVERY client-workspace page, and GET /api/health/clients/{id} used to 404
 * whenever the client had never been calculated — every brand-new client,
 * and permanently the internal practice client. The browser caught the
 * rejection and rendered nothing, so nothing broke visually, but a failed
 * request was logged on every single navigation.
 *
 * The backend (apps/api/routers/health.py::get_client_health) now answers
 * 200 with data: null for "no score yet" — a real client access refusal
 * still 404s, via assert_client_access, before that lookup ever runs. This
 * pins the frontend half: getLatestHealthScore must treat a null `data` as
 * "none yet" rather than unconditionally spreading it into toClientHealth,
 * which would depend on an exception (thrown on the null spread, caught by
 * the outer try/catch) standing in for an ordinary answer.
 *
 * Run with: node --experimental-strip-types --test scripts/a-health-score-not-yet-calculated-is-not-a-404.test.ts
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");

function code(file: string): string {
  return fs.readFileSync(path.join(WEB, file), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
}

function functionBody(source: string, name: string): string {
  const start = source.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `expected to find a function named ${name}`);
  const braceStart = source.indexOf("{", start);
  let depth = 0;
  for (let i = braceStart; i < source.length; i++) {
    if (source[i] === "{") depth++;
    else if (source[i] === "}") {
      depth--;
      if (depth === 0) return source.slice(braceStart, i + 1);
    }
  }
  throw new Error(`unbalanced braces reading ${name}`);
}

test("getLatestHealthScore treats a null data field as no score yet", () => {
  const body = functionBody(
    code("lib/services/health-score-compute.ts"),
    "getLatestHealthScore",
  );
  // Guards res.data before handing it to toClientHealth, rather than
  // unconditionally spreading a possibly-null value.
  assert.match(body, /res\.data\s*\?\s*toClientHealth\(res\.data\)\s*:\s*null/,
    "a client with no health score yet must resolve to null explicitly, " +
    "not by throwing on the spread and falling into the catch");
  // The unconditional call this replaced must be gone.
  assert.doesNotMatch(body, /return\s+toClientHealth\(res\.data\);/,
    "the old shape called toClientHealth(res.data) unconditionally, which " +
    "only produced null for a not-yet-calculated client by throwing on a " +
    "null spread and being caught below");
});
