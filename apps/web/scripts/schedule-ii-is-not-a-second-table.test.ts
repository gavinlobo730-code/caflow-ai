// The Schedule II table lives in apps/api, and this page holds no copy of it.
// Run with:
//   node --experimental-strip-types --test scripts/schedule-ii-is-not-a-second-table.test.ts
//
// WHY THIS EXISTS
//     The fixed-assets page carried a WDV_RATES literal — nine categories and
//     a percentage each — and routers/fixed_assets.py carried an identical
//     one, its comment saying in as many words that the values "mirror the
//     frontend's own WDV_RATES table exactly". Both were wrong the same way:
//     mostly INCOME TAX ACT block rates (Furniture 10.00%, Intangibles 25.00%)
//     under a form label that read "Companies Act 2013 Sch II rate", with the
//     correct TEN-year figure (25.89%) sitting against Vehicles, which
//     Schedule II gives eight years. Only Building was right.
//
//     Two copies is how that survives a review: whoever checks one finds it
//     agrees with the other. So the rates are now DERIVED from the Schedule II
//     useful lives in apps/api and served from there, and this test is what
//     stops the literal coming back — including "just the categories", since
//     the category list is half of the same table.
//
//     The depreciation tab had a second copy of a different rule: it computed
//     each asset's annual charge in the browser from the LIVE written-down
//     value, while the backend computes it from the financial year's OPENING
//     value (task #232). The screen and the Post button disagreed, and the
//     screen was the one the CA read.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const PAGE = path.join(import.meta.dirname, "..", "app/clients/[id]/fixed-assets/page.tsx");
const page = () => fs.readFileSync(PAGE, "utf8");

test("the page holds no rate table of its own", () => {
  const s = page();
  // The declaration, not the name: the comment above the fetch explains what
  // WDV_RATES was and why it went, which is worth keeping.
  assert.doesNotMatch(s, /WDV_RATES\s*[:=]/, "the rate table belongs to apps/api");
  assert.doesNotMatch(s, /const CATEGORIES\s*=/,
    "the category list is half of the same statutory table — it comes from the same place");
  // The retired numbers by name: a re-added literal is likeliest to be one of
  // these, copied back off an old branch or a screenshot.
  for (const wrong of ["31.67", "15.33", "13.91", "25.89", "10.0,", "25.0,"]) {
    assert.ok(!s.includes(wrong), `${wrong} is a retired rate literal and must not be back`);
  }
  // And the CORRECT ones must not be here either. They are just as wrong to
  // hold: a second copy of a right number drifts as easily as a wrong one.
  for (const derived of ["63.16", "45.07", "31.23", "18.10", "39.30", "4.87"]) {
    assert.ok(!s.includes(derived), `${derived} is derived in apps/api — do not restate it here`);
  }
});

test("the categories and their lives are fetched", () => {
  const s = page();
  assert.match(s, /\/api\/fixed-assets\/categories\?client_id=/,
    "the create form reads the served Schedule II table");
  assert.match(s, /interface ScheduleIIClass/, "and types what it receives");
  assert.match(s, /useful_life_years: number \| null/,
    "the LIFE is what Schedule II prescribes and what the form must show");
});

test("both Schedule II lives for computers reach the CA", () => {
  const s = page();
  assert.match(s, /selected\.classes\.length > 1/,
    "a category with more than one prescribed life must offer the choice — servers " +
    "are six years and end user devices three, and picking is the CA's job");
  assert.match(s, /schedule_ii_class/, "and the chosen class must be part of the form state");
});

test("where Schedule II prescribes nothing, the field is left blank", () => {
  const s = page();
  // Intangibles are amortised under AS 26 / Ind AS 38 — a judgement, not a
  // table lookup. The old form pre-filled 25.00% (the Income-tax Act's answer)
  // and the CA had no way to tell it was invented.
  assert.match(s, /wdv_rate_percent:\s+cls\?\.wdv_rate_percent != null \? String\(cls\.wdv_rate_percent\) : ""/,
    "a class with no prescribed rate must leave the field empty, not guess");
  assert.match(s, /=== "" \? undefined :/,
    "and a blank field must be sent as absent, so the backend decides — default or refuse");
});

test("the depreciation tab shows what the backend will post", () => {
  const s = page();
  assert.match(s, /\/api\/fixed-assets\/depreciation-schedule\?client_id=/,
    "the charge comes from the schedule endpoint");
  assert.doesNotMatch(s, /function annualDepn/,
    "the browser must not compute the annual charge — that rule is task #232's, in apps/api");
  assert.doesNotMatch(s, /wdv \* \(a\.wdv_rate_percent/,
    "and must not apply a rate to a written-down value at all");
});

test("a refusal reaches the screen instead of being swallowed", () => {
  const s = page();
  // "Depreciation for 2026-09 has not been posted" is the sentence that tells
  // a CA a month was skipped. The old catch was empty: the Post button simply
  // did nothing and the register did not move.
  assert.doesNotMatch(s, /catch \{ \/\* ignore \*\/ \}/,
    "a failed posting must not be discarded");
  assert.match(s, /function refusalMessage/, "the detail out of the response is read");
  assert.match(s, /errors\[r\.asset_id\]/, "and rendered against the row it belongs to");
});

test("an asset with no statutory basis is shown as a named gap", () => {
  const s = page();
  assert.match(s, /statutory_gap/,
    "the server's reason must be rendered — a zero charge with no reason reads as " +
    "'nothing to depreciate', which is a different statement");
});
