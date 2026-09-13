// PUR-24, the frontend half. The service can compute the tie-up perfectly and
// the report still not tie, because the screen renders open documents only.
//
// What these hold is narrow on purpose — the panel's copy and colours will
// change with the design pass. What must not change: the advances are READ off
// the response, they are rendered OUTSIDE the buckets, the net figure comes
// from the SERVER rather than being subtracted here, and the discrepancy
// sentences reach the CA.
//
// Run with: node --experimental-strip-types --test scripts/an-advance-is-on-the-ageing-report.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PAGE = path.join(__dirname, "..", "app", "clients", "[id]", "reports", "ageing", "page.tsx");
const code = stripComments(fs.readFileSync(PAGE, "utf8"));

test("the screen reads the advances the endpoints now return", () => {
  assert.match(code, /ar\.data\.advances\b/, "the receivables advances are dropped");
  assert.match(code, /ap\.data\.advances\b/, "the payables advances are dropped");
});

test("the net figure comes from the server, never subtracted here", () => {
  // CLAUDE.md: zero business logic in the frontend. `total − advances` looks
  // harmless and is the first step towards two definitions of one number.
  assert.match(code, /ar\.data\.net_receivable_paise/);
  assert.match(code, /ap\.data\.net_payable_paise/);
  assert.doesNotMatch(
    code,
    /total_outstanding_paise\s*-\s*(section\.)?total_advances_paise/,
    "the tie-up figure is being recomputed in the browser",
  );
});

test("an advance is rendered outside the ageing buckets", () => {
  // The panel is its own <section> ABOVE DocumentList. A supplier advance is
  // an asset and a customer advance a liability; either one inside the buckets
  // misstates the Schedule III note this screen exists to build.
  assert.match(code, /<AdvancesPanel/, "no advances panel is rendered");
  const render = code.slice(code.indexOf('tab === "receivables" || tab === "payables"'));
  assert.ok(
    render.indexOf("<AdvancesPanel") < render.indexOf("<DocumentList"),
    "the advances must be shown before the documents they reconcile",
  );
  // DocumentList still receives only rows — no advances leak into its table.
  assert.doesNotMatch(
    code,
    /<DocumentList[\s\S]{0,400}advances=/,
    "advances are being passed into the document table",
  );
});

test("a discrepancy between the column and the allocation rows reaches the CA", () => {
  assert.match(code, /advance_gaps/, "the server states the difference and the screen swallows it");
  const panel = code.slice(code.indexOf("function AdvancesPanel"));
  assert.match(panel, /section\.gaps\.map/, "the gap sentences are never rendered");
});

test("zero advances says so rather than hiding the section", () => {
  // A missing section and a nil section look identical to a reader, and only
  // one of them means the documents below ARE the control account.
  const panel = code.slice(code.indexOf("function AdvancesPanel"));
  assert.match(panel, /section\.advances\.length === 0/,
    "with no advances the panel must still state the tie-up, not disappear");
  assert.match(panel, /if \(section === null\) return null;/,
    "only a section that has not loaded yet renders nothing");
});

test("changing the as-at date clears the advances with the rows", () => {
  // A stale advances total beside a fresh document total is a tie-up that
  // silently does not tie.
  assert.match(code, /setAsOf\(e\.target\.value\);[\s\S]{0,160}setArAdvances\(null\)/);
  assert.match(code, /setAsOf\(e\.target\.value\);[\s\S]{0,160}setApAdvances\(null\)/);
});
