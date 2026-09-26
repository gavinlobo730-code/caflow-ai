/**
 * GSTR-9C (GST-25, part 4) — the browser must not decide eligibility, and
 * must not derive what `domain/gst/gstr9c.py` refuses to derive.
 *
 * Almost every figure on this form is CA-recorded because the audited
 * financial statements are not this product's own books. The one thing the
 * screen must never do is place a client in a threshold band — that is
 * reference data, served by the server, never decided here.
 */
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const PANEL = "components/gst/Gstr9cWorking.tsx";
const PAGE = "app/clients/[id]/compliance/gst/page.tsx";
const API = "lib/api/index.ts";

function code(rel: string): string {
  return fs.readFileSync(path.join(WEB, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/^\s*\/\/.*$/gm, " ");
}

test("the panel never decides which band a client is in", () => {
  const src = code(PANEL);
  // No hardcoded crore figures, no comparison against a turnover to gate the
  // form's own visibility — the threshold table is rendered as reference only.
  assert.doesNotMatch(src, /\b2_00_00_000_00\b|\b5_00_00_000_00\b/,
    "threshold figures are the server's, never re-typed here");
  assert.doesNotMatch(src, /turnover\s*[<>]=?\s*\d/,
    "no turnover comparison decides anything client-side");
  assert.match(src, /threshold_table/, "the reference table is rendered");
  assert.match(src, /never decided by this screen/i);
});

test("5R, 7G, 12F and 14T are read off the statement, never re-derived", () => {
  /* domain/gst/gstr9c.py computes these; the panel must render them, not
     recompute a subtraction the server already refused or performed. */
  const src = code(PANEL);
  assert.match(src, /statement\.table5\.unreconciled_paise/);
  assert.match(src, /statement\.table7\.unreconciled_paise/);
  assert.match(src, /statement\.table12\.unreconciled_paise/);
  assert.match(src, /statement\.table14\.unreconciled_paise/);
  // No hand-rolled subtraction combining two _paise fields into a new figure.
  assert.doesNotMatch(src, /\.audited_adjusted_paise\s*-\s*.*itc_claim_paise/,
    "12F is the server's own subtraction, not repeated here");
});

test("the two [S]-graded bindings are shown, not silently substituted", () => {
  const src = code(PANEL);
  assert.match(src, /GSTR-9 Table 6O/);
  assert.match(src, /GSTR-9 Table 7J \(Net ITC available\)/);
  assert.match(src, /row 9d/);
});

test("gaps reach a renderer", () => {
  const src = code(PANEL);
  assert.match(src, /gaps=\{statement\.gaps\}/);
});

test("the e-commerce row only appears from FY 2024-25 onward", () => {
  const src = code(PANEL);
  assert.match(src, /isEcommerceYear/);
  assert.match(src, />= 2024/);
});

test("rate-wise and expense rows are refused until the reconciliation is saved", () => {
  /* The child rows carry a foreign key to the reconciliation row — there is
     nothing to attach them to until it exists. */
  const src = code(PANEL);
  assert.match(src, /Save the reconciliation above first/);
});

test("money is parsed through the one parser, never a hand-rolled multiply", () => {
  const src = code(PANEL);
  assert.match(src, /paiseFromRupeeInput/);
  assert.doesNotMatch(src, /Math\.round\([^)]*\*\s*100\)/);
  assert.doesNotMatch(src, /parseFloat\([^)]*\)\s*\*\s*100/);
});

test("the panel is reachable from the GSTR-9 tab", () => {
  const src = code(PAGE);
  assert.match(src, /import Gstr9cWorking from "@\/components\/gst\/Gstr9cWorking"/);
  assert.match(src, /<Gstr9cWorking clientId=\{clientId\} financialYear=\{fy\} \/>/);
});

test("the api layer carries every endpoint this panel calls", () => {
  const src = code(API);
  const start = src.indexOf("gstr9c: {");
  assert.ok(start > 0, "the gstr9c namespace exists");
  const ns = src.slice(start, start + 4500);
  assert.match(ns, /\/api\/gst-workspace\/gstr9c\/compute/);
  assert.match(ns, /\/api\/gstr9c\/reconciliation/);
  assert.match(ns, /\/api\/gstr9c\/rate-wise-lines/);
  assert.match(ns, /\/api\/gstr9c\/expense-lines/);
});
