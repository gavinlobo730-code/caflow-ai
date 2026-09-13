// Multi-currency has a screen that switches it on, and the screen decides
// nothing (ACC-19).
//
// Run with:
//   node --experimental-strip-types --test scripts/multi-currency-can-be-switched-on.test.ts
//
// WHAT WAS WRONG
//     All five multi-currency phases are built and none of it could be turned
//     on. `resolve_currency_policy` is `active = L1 AND L2 AND L3`; L2
//     (firms.multi_currency_entitled) and L3 (clients.multi_currency_enabled)
//     were READ by six routers and WRITTEN BY NOTHING — no endpoint, no field,
//     no screen, no seed. Only a manual UPDATE against the database could
//     activate any of it.
//
// THE RULE, WHICH IS THE DURABLE HALF
//     The gates come from the server and so do the refusals. Whether a client
//     may be switched on is a question about the firm's entitlement and the
//     client's functional currency — Capability B, presentation and
//     translation, is not built — and re-deciding either here is the "second
//     implementation" this codebase keeps having to record. The screen renders
//     `gates`, sends a boolean, and shows the sentence that comes back.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const SCREEN = "app/settings/multi-currency/page.tsx";
const INDEX = "app/settings/page.tsx";

function code(rel: string): string {
  return fs.readFileSync(path.join(WEB, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/^\s*\/\/.*$/gm, " ");
}

test("the screen exists and settings links to it", () => {
  assert.ok(fs.existsSync(path.join(WEB, SCREEN)), `${SCREEN} is missing`);
  assert.match(code(INDEX), /href="\/settings\/multi-currency"/,
    "an unreachable settings page is the same as no page");
});

test("both gates are written through the API, never over PostgREST", () => {
  const src = code(SCREEN);
  assert.match(src, /api\.currencies\.setEntitlement\(/, "the firm gate (L2)");
  assert.match(src, /api\.currencies\.setClientPolicy\(/, "the client gate (L3)");
  // rbac() runs only on the API path. These two columns decide what the
  // posting kernel accepts, so a direct .from("firms").update() would be a
  // Partner-only control with no Partner check.
  assert.doesNotMatch(src, /\.from\(["'](firms|clients)["']\)/,
    "these gates are Partner-only and rbac() runs only through /api");
});

test("the screen shows WHICH gate is down, not just the answer", () => {
  // `active: false` alone is what made this unusable — a Partner ticked
  // something and could not tell which of three switches was still down.
  const src = code(SCREEN);
  for (const gate of ["firmGates?.platform", "firmGates?.firm", "gates.client",
                      "gates.functional_currency_supported"]) {
    assert.ok(src.includes(gate), `the screen must render ${gate}`);
  }
});

test("the platform kill switch is shown and never offered", () => {
  const src = code(SCREEN);
  assert.match(src, /firmGates\?\.platform\.why/,
    "the server says WHY the platform gate is down — MULTI_CURRENCY_ENABLED is "
    + "an environment variable, so the sentence is the only actionable part");
  assert.match(src, /Multi-currency is off for this deployment/,
    "…and it is announced, not left to be inferred from every row reading Off");
  assert.doesNotMatch(src, /MULTI_CURRENCY_ENABLED\s*=/, "nothing here sets it");
  assert.doesNotMatch(src, /setPlatform/, "there is no platform setter to call");
});

test("no refusal is re-decided in the browser", () => {
  const src = code(SCREEN);
  // The server refuses turning a client on under an unentitled firm, and
  // turning on a client whose books are kept in a currency the product does
  // not support. Both come back as a sentence, and that sentence is the whole
  // value of the refusal.
  // Both handlers, counted — one of the two swallowing the sentence is the
  // whole defect, and a single match would pass on the other.
  const shown = src.match(/setError\(e instanceof Error \? e\.message/g) ?? [];
  assert.ok(shown.length >= 3,
    `the server's sentence is what the CA is shown on every path (found ${shown.length})`);
  assert.doesNotMatch(src, /functional_currency\s*[!=]==?\s*["']INR["']/,
    "whether a functional currency is supported is the server's answer — it "
    + "carries `functional_currency_supported`");
  assert.doesNotMatch(src, /throw new Error\((["'`])(?!.*\{).*(firm|currency)/i,
    "no refusal is invented here");
});

test("the firm gate is read with no client in the request", () => {
  const src = code(SCREEN);
  // A firm with no clients yet has no policy to read the firm gate off — and
  // that is exactly the firm a Partner is switching this on for. The checkbox
  // would have snapped back to Off after every save.
  assert.match(src, /api\.currencies\.entitlement\(\)/,
    "the firm gate has its own read");
  assert.doesNotMatch(src, /rows\.find\(\w+ => \w+\.policy\)/,
    "the firm gate must not be taken off the first client's policy");
});
