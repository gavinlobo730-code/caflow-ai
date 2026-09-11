/**
 * The Schedule III mapping screen must not carry its own caption list, and must
 * be able to save the decision it is named after.
 *
 * WHAT WAS WRONG, measured on production on 11-09-2026.
 *
 * The screen held a hardcoded SCHEDULE_III_SECTIONS array that had drifted from
 * the backend classifier in BOTH directions at once:
 *
 *   - it offered five captions the engine had never heard of (Capital Work in
 *     Progress, Goodwill & Intangibles, Long-term Provisions, Short-term
 *     Provisions, Deferred Tax Asset), so a CA could pick one and the statement
 *     would ignore it; and
 *   - it spelled five others differently ("Employee Benefits Expense" here,
 *     "Employee Benefit Expense" there), which is how NINE of the fifty mapped
 *     accounts in the live database were being silently discarded — the CA
 *     chose, the choice was saved, and the financial statements went back to
 *     guessing from the account's subtype.
 *
 * It was also READ-ONLY: the only way to set a mapping was to re-import the
 * whole chart of accounts. A screen named after a decision that cannot be made
 * on it is a report.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.join(import.meta.dirname, "..");
const SCREEN = "app/accounting/schedule-iii-mapping/page.tsx";

function code(rel: string): string {
  return fs.readFileSync(path.join(ROOT, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
}

test("the screen holds no caption list of its own", () => {
  const src = code(SCREEN);
  // The RULE, not one spelling of it: no array literal in this file may be a
  // run of Schedule III caption strings. The old bug was a const named
  // SCHEDULE_III_SECTIONS, and the next one will be named something else.
  const captionish = /"(?:Share Capital|Reserves & Surplus|Trade Payables|Trade Receivables|Inventories|Revenue from Operations|Other Income|Finance Costs|Other Expenses|Cash & Cash Equivalents)"/g;
  const hits = src.match(captionish) ?? [];
  assert.equal(hits.length, 0,
    `${SCREEN} names Schedule III captions directly (${hits.join(", ")}) — the list ` +
    "must come from the module that does the classifying, or the two drift and " +
    "the CA's choice is discarded");
});

test("the screen fetches the vocabulary from the backend", () => {
  const src = code(SCREEN);
  assert.match(src, /scheduleIiiCaptions\(\)/,
    "the captions must be served by the engine that honours them");
});

test("the screen can save a mapping, through the API rather than PostgREST", () => {
  const src = code(SCREEN);
  assert.match(src, /updateAccount\(/,
    "a screen named after a decision must be able to record it");
  assert.doesNotMatch(src, /\.from\("chart_of_accounts"\)[\s\S]{0,400}\.update\(/,
    "writes go through the API so rbac() runs and the caption is validated; a " +
    "direct PostgREST update skips both");
});

test("a refusal is not shown as a saved mapping", () => {
  const src = code(SCREEN);
  // This router answers a refusal as HTTP 200 with {success:false}. The GST
  // filing path had exactly this bug: an unchecked call displayed "Filed" for a
  // request the server had declined.
  assert.match(src, /!res\.success/,
    "the response must be checked, not assumed");
  assert.match(src, /schedule_iii_mapping: previous/,
    "and an optimistic update must be reverted when the server says no");
});

test("an unrecognised stored mapping is reported, not shown as blank", () => {
  const src = code(SCREEN);
  assert.match(src, /unrecognised/,
    "an account carrying a caption this version does not present is NOT the " +
    "same as an unmapped one: somebody decided, and the decision is not being " +
    "honoured. Showing it as blank hides that");
});
