// A gain computed on a provisional Cost Inflation Index must say so. Run with:
//   node --experimental-strip-types --test scripts/a-provisional-cost-inflation-index-is-said-on-the-capital-gains-screen.test.ts
//
// WHY THIS EXISTS (ledger POST-A-077)
//     `capital_gains_engine` stamps `indexation_is_estimated` and `indexation_note` when a transfer falls in a year whose
//     index CBDT has not yet notified (usually until about June) and the newest known index was used instead. The API
//     returned both and the register stored the indexed cost as NULL for exactly that reason, but nothing in apps/web
//     rendered either field, so the calculator showed an estimated-index gain, which OVERSTATES the gain, as though it
//     were computed. No sale date triggers it today (2026-27 is present); the window opens again from 1 April 2027, which
//     is when a screen that has never said it would first be wrong.
//
//     The sentence is the SERVER's. The page holds no wording about which year or why: it shows what it was given.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const read = (rel: string) => fs.readFileSync(path.join(import.meta.dirname, "..", rel), "utf8");
const page = () => read("app/income-tax/capital-gains/page.tsx");

test("the result type carries both fields the engine sends", () => {
  const s = read("lib/data/income-tax.ts");
  assert.match(s, /indexation_is_estimated\?: boolean;/);
  assert.match(s, /indexation_note\?: string \| null;/);
});

test("the calculator shows a notice whenever the index is provisional, with the server's sentence", () => {
  const s = page();
  assert.match(s, /result\.indexation_is_estimated &&/, "the notice must be conditional on the flag");
  assert.match(s, /\{result\.indexation_note\}/, "and must show the server's own sentence");
});

test("the register preview says the indexed cost is provisional and is saved blank", () => {
  const s = page();
  assert.match(s, /regPreview\?\.indexation_is_estimated &&/);
  assert.match(s, /Indexed Cost\{regPreview\.indexation_is_estimated \? " \(provisional\)" : ""\}/);
  assert.match(s, /\{regPreview\.indexation_note\}/);
  assert.match(s, /the indexed cost is saved as blank/);
});

test("the page composes no sentence of its own about which year is missing", () => {
  const s = page();
  assert.doesNotMatch(s, /is not notified/, "the sentence belongs to capital_gains_engine");
  assert.doesNotMatch(s, /understates the indexed cost/, "the browser must not restate the rule it is reporting");
});
