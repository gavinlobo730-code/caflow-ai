/**
 * The Health pages' "At-Risk Clients" and "Critical Clients" are exactly the clients the health engine flags, and say so in words
 * (POST-A-285).
 *
 * WHAT WAS WRONG
 *   The engine stores `is_critical` (score under 35, a hard override clamps the score to 34) and `is_at_risk` (35 to 49) beside every
 *   score. The at-risk page asked for `is_at_risk` and then dropped everything under 40 in the browser, under a subtitle that said
 *   "Health score 40–59"; the critical page said "below 40" and "all scores are 40 or above". A client scoring 38 was at risk on the
 *   Health page, the dashboard and the assistant and was on neither list here.
 *
 * THE RULE, NOT THE SPELLINGS
 *   1. A list page asks the database for the flag and draws what comes back: no numeric comparison of `overall_score` in the page.
 *   2. The at-risk list is the at-risk flag and NOT the critical flag, as `/api/health/dashboard` subtracts.
 *   3. Neither page states a score threshold of its own in words; the engine owns the lines (`domain/health/scoring`).
 *
 * Run with:
 *   node --experimental-strip-types --test scripts/the-health-lists-are-the-engines-flags.test.ts
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");

function code(rel: string): string {
  return fs.readFileSync(path.join(WEB, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:])\/\/[^\n]*/g, "$1");
}

const PAGES = { "at-risk": "app/health/at-risk/page.tsx", critical: "app/health/critical/page.tsx" } as const;

test("the scan reads two real pages", () => {
  for (const rel of Object.values(PAGES)) {
    assert.ok(code(rel).includes("getSupabaseClient") && code(rel).length > 1500, `${rel} is not the page the guard means`);
  }
});

test("neither list page compares a score in the browser", () => {
  for (const [name, rel] of Object.entries(PAGES)) {
    const compares = [...code(rel).matchAll(/overall_score\s*(?:>=|<=|>|<)\s*\d+/g)].map((m) => m[0]);
    assert.deepEqual(compares, [], `the ${name} page compares a score with a threshold of its own instead of the engine's flag`);
  }
});

test("the lists ask for the engine's flags: at risk and not critical; critical", () => {
  const atRisk = code(PAGES["at-risk"]);
  assert.ok(/\.eq\("is_at_risk",\s*true\)/.test(atRisk), "the at-risk list does not ask for is_at_risk");
  assert.ok(/\.eq\("is_critical",\s*false\)/.test(atRisk), "the at-risk list does not leave out the critical clients");
  assert.ok(/\.eq\("is_critical",\s*true\)/.test(code(PAGES.critical)), "the critical list does not ask for is_critical");
});

test("neither page states a score threshold of its own in words", () => {
  for (const [name, rel] of Object.entries(PAGES)) {
    const words = [...code(rel).matchAll(/(?:below|under|above|over)\s+\d{2}\b|\b\d{2}\s*[–-]\s*\d{2}\b|\b\d{2} or above\b/gi)].map((m) => m[0]);
    assert.deepEqual(words, [], `the ${name} page states a threshold in words; the engine owns the lines`);
  }
});
