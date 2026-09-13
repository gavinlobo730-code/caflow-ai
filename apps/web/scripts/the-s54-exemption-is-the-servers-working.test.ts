// The s.54 family exemption is the SERVER's working, and the screen decides
// none of it (IT-19).
//
// Run with:
//   node --experimental-strip-types --test scripts/the-s54-exemption-is-the-servers-working.test.ts
//
// WHAT WAS WRONG
//     capital_gains_engine computed the gain, the holding period and the rate
//     and stopped, and there was nowhere to record that the money had gone
//     back into a new asset. On a house sale the whole of that gain is
//     routinely exempt under s.54, so the register showed the tax on a gain
//     the client may not owe tax on at all.
//
// THE RULE, WHICH IS THE DURABLE HALF
//     The four sections differ in ways that decide the figure — s.54F
//     apportions on net consideration where s.54 takes the lower of two
//     amounts, s.54EC's Rs 50 lakh spans two financial years, s.54B reaches a
//     short-term gain — and domain/income_tax/reinvestment_exemption.py is the
//     one place that knows it. Every figure and every refusal on this screen
//     comes off the wire.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const SCREEN = "app/income-tax/capital-gains/page.tsx";
const DATA = "lib/data/income-tax.ts";

function code(rel: string): string {
  return fs.readFileSync(path.join(WEB, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/^\s*\/\/.*$/gm, " ");
}

test("the register asks what was SOLD, which asset_type cannot say", () => {
  const src = code(SCREEN);
  assert.match(src, /transferred_asset_nature/,
    "s.54 reaches a residential house and s.54F an asset that is not one — "
    + "'Immovable property' covers both");
  // Unstated goes as null, never as a default. Defaulting decides which
  // section reaches the transfer by omission.
  assert.match(src, /transferred_asset_nature: regForm\.transferred_asset_nature \|\| null/,
    "an unstated nature must be sent as null so the server can name the gap");
});

test("the exemption panel renders the server's claims and computes nothing", () => {
  const src = code(SCREEN);
  assert.match(src, /getCapitalGainExemption\(/, "the working is fetched");
  assert.match(src, /exemption\?\.claims\.map/, "…and rendered claim by claim");
  assert.match(src, /c\.exemption_paise/, "the figure is the server's");
  // No apportionment, no cap, no window arithmetic in the browser.
  assert.doesNotMatch(src, /gain[\w.]*\s*\*\s*cost/i, "no s.54F fraction here");
  assert.doesNotMatch(src, /5000000|50_00_000|10000000000/,
    "no Rs 50 lakh cap and no Rs 10 crore ceiling here — both move by Finance Act");
  assert.doesNotMatch(src, /Math\.min\(\s*gain/i, "no lower-of rule here");
});

test("every refusal shown is a sentence that came off the wire", () => {
  const src = code(SCREEN);
  assert.match(src, /c\.gaps\.map/, "a claim's own gaps");
  assert.match(src, /exemption\.gaps\.map/, "and the transfer-level ones");
  assert.match(src, /c\.caveats\.map/, "…and the caveats, which say what was not tested");
  // The screen must not invent its own version of a statutory refusal.
  assert.doesNotMatch(src, /does not reach/i, "the server says which section reaches what");
});

test("blank is a third state on both facts no ledger holds", () => {
  const src = code(SCREEN);
  // s.54F's other-houses count and s.54B's agricultural use. A 0 or a false
  // here would ASSERT something the CA has not established.
  assert.match(src, /other_houses === "" \? null : Number/,
    "an unrecorded house count goes as null, never as zero");
  assert.match(src, /agri_use === "" \? null : claimForm\.agri_use === "yes"/,
    "an unestablished agricultural use goes as null, never as false");
});

test("the section vocabulary is served, not hardcoded as the source", () => {
  const src = code(SCREEN);
  assert.match(src, /getReinvestmentSections\(\)/,
    "the four sections and the four natures come from the engine");
  // A fallback array is allowed for the redeploy window — the Schedule III
  // caption shape — but only behind the server's answer.
  assert.match(src, /sectionInfo\.length\s*\n?\s*\?/,
    "the hardcoded list must be a FALLBACK, reached only when the server has "
    + "not answered");
});

test("every call goes through the API, never over PostgREST", () => {
  const src = code(DATA);
  for (const fn of ["getCapitalGainExemption", "addReinvestment", "deleteReinvestment",
                    "getReinvestmentSections"]) {
    assert.ok(src.includes(`export async function ${fn}`), `${fn} is missing`);
  }
  assert.doesNotMatch(src, /\.from\("capital_gain_reinvestments"\)/,
    "the claim table is SELECT-only to the browser and the exemption is "
    + "computed server-side — rbac() runs only through /api");
});

test("the screen says its figures were not read off the Act", () => {
  const src = code(SCREEN);
  assert.match(src, /incometax\.gov\.in/,
    "every window and cap here is [S]-graded; a CA relying on one must be told");
});
