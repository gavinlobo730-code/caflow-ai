/**
 * The Executive Dashboard renders an unknown as "No data", and labels as AI only
 * what an AI wrote (ai-08).
 *
 * WHAT WAS WRONG
 *   The page was headed "AI-powered firm intelligence" and rendered, as figures,
 *   three literal zeroes from the server (outstanding invoices, outstanding
 *   amount, average collection days), a utilisation percentage computed as
 *   `overdue * 5 + 50`, a health score of 75 for a firm with none, and an
 *   "Estimated: ₹…" on two growth opportunities whose value was a constant per
 *   head. And when a block of the payload was missing it rendered the block with
 *   every figure 0 — `objectOrNull(...) ?? { critical_clients: 0, … }` — which
 *   reads as "nothing is wrong".
 *
 * THE RULE, NOT THE SPELLINGS
 *   1. A payload block that is absent is NO DATA. The way a zero got onto this
 *      screen was a literal-object fallback after `objectOrNull`, so no such
 *      fallback may come back — whatever keys it carries.
 *   2. The AI label is conditional on the server's own `summary_source`. A
 *      sentence written by the application is not an AI's and says so.
 *   3. No figure on this page is a server-side estimate: `estimated_value_paise`
 *      is not read, because the server no longer computes one.
 *
 * Run with:
 *   node --experimental-strip-types --test scripts/the-executive-dashboard-renders-no-unknown-as-a-value.test.ts
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const PAGE = path.join(WEB, "app/executive-dashboard/page.tsx");

function code(): string {
  // Comments carry the history of these defects in the very words the checks
  // below forbid, so they are stripped before anything is matched.
  return fs.readFileSync(PAGE, "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:])\/\/[^\n]*/g, "$1");
}

test("the scan reads a real page", () => {
  const src = code();
  assert.ok(src.length > 4000 && src.includes("ExecutiveDashboardPage"),
    "the guard is not looking at the dashboard page — did it move?");
});

test("a payload block that is absent is never replaced by an object of zeroes", () => {
  const src = code();
  const fallbacks = [...src.matchAll(/objectOrNull\s*(?:<[^>]*>)?\s*\([^)]*\)\s*\?\?\s*\{/g)];
  assert.deepEqual(fallbacks.map((m) => m[0]), [],
    "a literal-object fallback after objectOrNull puts zeroes on screen for a block that was never read");
});

test("no figure is defaulted to a number where the payload gave none", () => {
  const src = code();
  // `?? 0` is how an unknown becomes a figure. The two surviving reads of a
  // count already known to exist (a list's length) carry no default at all.
  const zeroDefaults = [...src.matchAll(/\?\?\s*0\b/g)].map((m) => m[0]);
  assert.ok(zeroDefaults.length <= 1,
    `the page defaults ${zeroDefaults.length} figures to 0 — an unknown must render as No data`);
});

test("the page says No data in several places and not by accident", () => {
  const src = code();
  assert.ok(/const NO_DATA = "No data"/.test(src));
  assert.ok((src.match(/NO_DATA/g) ?? []).length >= 8,
    "the unknown state is rendered in too few places for it to be the rule");
});

test("the AI label is conditional on the server saying a model wrote the summary", () => {
  const src = code();
  assert.ok(src.includes('data.summary_source === "model"'),
    "the page no longer reads summary_source");
  const labelled = [...src.matchAll(/AI Executive Summary/g)];
  assert.equal(labelled.length, 1);
  const at = labelled[0].index ?? 0;
  const before = src.slice(Math.max(0, at - 160), at);
  assert.ok(/summaryIsModel/.test(before),
    "'AI Executive Summary' is rendered without checking summaryIsModel");
});

test("the header no longer sells the whole page as AI-powered", () => {
  const src = code();
  assert.ok(!/AI-powered/i.test(src));
});

test("no server-side estimate is read or shown", () => {
  const src = code();
  assert.ok(!src.includes("estimated_value_paise"));
  assert.ok(!/Estimated:/.test(src));
  assert.ok(!src.includes("team_utilisation_percent"));
  assert.ok(!src.includes("avg_tasks_per_staff"));
});
