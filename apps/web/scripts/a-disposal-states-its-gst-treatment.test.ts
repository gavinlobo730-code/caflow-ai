// A fixed-asset disposal asks the three questions only the CA can answer, and
// shows the CGST s.18(6) working the server computed (FA-08b).
//
// Run with:
//   node --experimental-strip-types --test scripts/a-disposal-states-its-gst-treatment.test.ts
//
// WHAT WAS WRONG
//     The disposal journal posted no tax line and DisposalIn had no field to
//     drive one, so the sale of a capital asset — a supply — was never
//     declared. The panel also showed a P&L computed on the GROSS proceeds,
//     which the moment a disposal carries GST is wrong by the tax.
//
// THE RULE, WHICH IS THE DURABLE HALF
//     The three facts are STATED, never inferred: whether the disposal is a
//     supply, the rate on the sale, and the head. And the s.18(6) working is
//     the SERVER's — two Rules prescribe the reduction and give different
//     figures, which is a statutory judgement, and CLAUDE.md keeps those in
//     apps/api. This screen renders them and derives nothing.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const SCREEN = "app/clients/[id]/fixed-assets/page.tsx";

function code(rel: string): string {
  return fs.readFileSync(path.join(WEB, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/^\s*\/\/.*$/gm, " ");
}

test("the disposal panel asks all three, and sends them", () => {
  const src = code(SCREEN);
  for (const [name, why] of [
    ["is_supply", "a scrapping for nothing is not a supply, and no ledger says which this is"],
    ["gst_rate_bps", "the rate on the sale is not the rate the asset was bought at"],
    ["is_interstate", "an asset bought locally may be sold across a state border"],
  ] as const) {
    assert.match(src, new RegExp(`${name}:\\s`), `the payload must carry ${name} — ${why}`);
  }
  // Unstated goes as null, not as a default. Defaulting either way decides a
  // statutory question by omission.
  assert.match(src, /is_supply:\s+isSupply === "" \? null :/,
    "an unstated supply is sent as null so the server can name the gap");
});

test("the s.18(6) working comes off the server", () => {
  const src = code(SCREEN);
  assert.match(src, /disposal-preview\?/,
    "the panel must ask, so the CA sees the figure before confirming");
  assert.match(src, /preview\?\.section_18_6\?\.applies/,
    "…and render what came back");
  assert.match(src, /section_18_6\.readings\.map/,
    "BOTH readings are rendered — Rule 40(2) and Rule 44(6) give different "
    + "figures and neither is chosen");
});

test("the browser works out no part of the tax", () => {
  const src = code(SCREEN);
  // The inclusive back-out lives in domain/gst/section_18_6 and
  // domain/banking/charge_gst. A copy here would be a statutory calculation in
  // the browser, and it would drift.
  assert.doesNotMatch(src, /10000\s*\+\s*(rate|gst)/i, "no inclusive back-out here");
  // Matched on a PAISE value being scaled, which is what the reduction is —
  // a bare "/ 60" also appears in Tailwind's `bg-[#0F172A]/60` opacity suffix,
  // and forbidding that would be forbidding a colour.
  assert.doesNotMatch(src, /_paise[\w.]*\s*[*/]\s*\d+\s*\/\s*(60|100)/,
    "no reduction arithmetic here — Rule 40(2)'s five points and Rule "
    + "44(6)'s sixtieths are the server's");
});

test("the P&L shown is the server's wherever it has answered", () => {
  // The panel used to compute proceeds − WDV. That figure is wrong by the tax
  // the moment a disposal carries GST, because the buyer's tax is not the
  // seller's proceeds.
  const src = code(SCREEN);
  assert.match(src, /preview\s*\n?\s*\?\s*preview\.gain_loss_paise/,
    "the gain must come from the preview when there is one");
});
