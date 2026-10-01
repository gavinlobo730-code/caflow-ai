// GST-20 — the worklist of invoices that need an IRN and have none reaches the CA.
//
// Run with:
//   node --experimental-strip-types --test scripts/the-invoices-that-need-an-irn-are-listed-where-the-ca-looks.test.ts
//
// WHAT WAS WRONG
//     `irn_scope` decides, for the invoice somebody has open, whether CGST Rule
//     48(4) reaches it. Nothing listed the in-scope invoices that have no IRN —
//     and under Rule 48(5) such an invoice is not an invoice, so the recipient's
//     credit goes with it. The endpoint exists now; a screen that never calls it
//     is the same defect one layer up.
//
// THE RULES, NOT SPELLINGS
//     * the practice-wide screen the CA already opens (deadlines) and the screen
//       where an IRN is recorded (e-invoice) both render the panel;
//     * the panel SAYS when it could not check — an empty panel means "none do",
//       so a silent failure is a false clean result;
//     * the panel decides nothing: no day arithmetic, no threshold, no figure for
//       the IRP's window of its own — they are the server's, [S]-graded there;
//     * the server's caveats and the prepare-only sentence are rendered, not
//       dropped.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const PANEL = path.join("components", "gst", "MissingIrnPanel.tsx");

function code(rel: string): string {
  return fs.readFileSync(path.join(WEB, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/^\s*\/\/.*$/gm, " ");
}

test("both screens render the panel", () => {
  for (const rel of [path.join("app", "deadlines", "page.tsx"),
                     path.join("app", "einvoice", "page.tsx")]) {
    assert.match(code(rel), /<MissingIrnPanel\b/, `${rel} does not render the worklist`);
  }
});

test("the panel reads the server's endpoint and nothing else", () => {
  const src = code(PANEL);
  assert.match(src, /api\.einvoice\.missingIrn\(/);
  assert.doesNotMatch(src, /supabase|\.from\(/, "no second data path");
});

test("a failed read is said in words, never rendered as an empty list", () => {
  const src = code(PANEL);
  assert.match(src, /Couldn(&apos;|')t check which invoices still need an IRN/);
  assert.match(src, /role="alert"/);
  // Both the rejected promise and a not-success response reach that sentence.
  assert.match(src, /catch \{[\s\S]{0,80}setFailed\(true\)/);
  assert.match(src, /setFailed\(got === null\)/);
});

test("lists are read through objectWithLists, not trusted", () => {
  const src = code(PANEL);
  assert.match(src, /objectWithLists<IrnWorklist>\([^)]*"invoices"[^)]*"caveats"[^)]*"clients_not_assessed"/);
});

test("the panel decides nothing about the window", () => {
  const src = code(PANEL) + code(path.join("lib", "gst", "irnWorklist.ts"));
  // No day arithmetic, no turnover figure, no 30 or ₹10 crore of its own.
  assert.doesNotMatch(src, /new Date\(|Date\.now\(|getTime\(|86_?400/,
    "counting days here would be a second implementation of the clock");
  assert.doesNotMatch(src, /\b30\b|10_?00_?00_?000|1000000000/,
    "the window's figures are [S]-graded constants on the server");
  assert.match(src, /w\.days_left/);
});

test("the server's caveats and the prepare-only sentence are rendered", () => {
  const src = code(PANEL);
  assert.match(src, /<StatutoryNotes caveats=\{list\.caveats\}/);
  assert.match(src, /does not reach the IRP/);
});

test("clients that could not be assessed are named, not folded into a clean list", () => {
  const src = code(PANEL);
  assert.match(src, /could not be assessed/);
  assert.match(src, /notAssessed\.map/);
});

test("the panel is written once", () => {
  const owners: string[] = [];
  const walk = (dir: string) => {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      if (e.name === "node_modules" || e.name === ".next" || e.name.startsWith(".")) continue;
      const p = path.join(dir, e.name);
      if (e.isDirectory()) walk(p);
      else if (/\.tsx?$/.test(e.name)
               && code(path.relative(WEB, p)).includes("Invoices that need an IRN and have none")) {
        owners.push(path.relative(WEB, p));
      }
    }
  };
  for (const d of ["app", "components"]) walk(path.join(WEB, d));
  assert.deepEqual(owners, [PANEL]);
});
