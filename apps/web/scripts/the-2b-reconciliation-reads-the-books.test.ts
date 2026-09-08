// The GSTR-2B screen asks for the portal file and nothing else. Run with:
//   node --experimental-strip-types --test scripts/the-2b-reconciliation-reads-the-books.test.ts
//
// WHY THIS EXISTS
//     The tab's own placeholder said "Paste GSTR-2B JSON here (include
//     book_invoices array for reconciliation)". The BOOKS side came out of the
//     same pasted JSON, and the endpoint looked for `data.docDetails[]` keyed
//     on `sgstin` — a shape the portal never produces. So a CA who pasted a
//     genuine download got "Matched 0, Mismatched 0, Missing 0": a clean
//     result from comparing nothing against nothing.
//
//     Asking a screen to supply the purchase register it is reconciling is
//     asking it to supply the answer.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.join(import.meta.dirname, "..");
const GST_TAB = "app/clients/[id]/compliance/gst/page.tsx";
const PURCHASES = "app/clients/[id]/purchases/page.tsx";
const OLD_SCREEN = "app/gst/reconciliation/page.tsx";

function code(rel: string): string {
  return fs.readFileSync(path.join(ROOT, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
}

test("the screen no longer asks the CA to paste their own purchase register", () => {
  const src = code(GST_TAB);
  assert.doesNotMatch(src, /book_invoices/,
    "the books are read server-side from purchase_bills; a screen that supplies " +
    "them is a screen that supplies the answer");
  assert.match(src, /downloaded from the portal/,
    "and the placeholder must say what to paste");
});

test("the result that comes back is the real one, and it reloads", () => {
  const src = code(GST_TAB);
  assert.match(src, /gstr2b\/reconciliation\?client_id=/,
    "the persisted answer must be read back — the reconciliation this replaces " +
    "started from zero every time it was reopened");
  assert.match(src, /itc_at_risk_paise/,
    '"Matched 12" is not an answer to "how much credit may I take this month"');
  assert.match(src, /defaulters/,
    "and the CA needs the list of suppliers to chase");
});

test("a parse that failed is not shown as a clean reconciliation", () => {
  const src = code(GST_TAB);
  assert.match(src, /!result\.persisted/,
    "a result of zero from a file that would not read must say so");
  assert.match(src, /result\.problems/,
    "and name what was wrong with it");
});

test("the four buckets are four, and each says which party to chase", () => {
  const src = code(GST_TAB);
  for (const s of ["matched", "amount_mismatch", "missing_in_2b", "missing_in_books"]) {
    assert.match(src, new RegExp(s), `${s} must be its own bucket`);
  }
  assert.match(src, /Chase the SUPPLIER/);
  assert.match(src, /Chase the DOCUMENT/);
});

test("the Purchases tab can say whether a bill's supplier filed it", () => {
  // PUR-11's other half: there was no way to see, from the Purchases tab, that
  // a specific bill was unmatched.
  const src = code(PURCHASES);
  assert.match(src, /from\("gstr2a_records"\)/,
    "the tab has to read the persisted reconciliation");
  assert.match(src, /key: "gstr2b", header: "GSTR-2B"/,
    "and show it as a column");
  assert.match(src, /function recon2BLabel/,
    "with one label function, so the column and the filter cannot disagree");
});

test('"not reconciled" and "supplier has not filed" are different words', () => {
  // A bill the supplier did not file has NO 2B document, so it has no row —
  // the absence IS the finding, but only once somebody reconciled the period.
  // Before that the same absence means nobody checked, and telling a CA a
  // supplier defaulted on that basis is a phone call that costs them their
  // credibility.
  const src = code(PURCHASES);
  assert.match(src, /reconciledPeriods/,
    "the tab must know WHICH periods were reconciled to tell the two apart");
  assert.match(src, /supplier has not filed/);
  assert.match(src, /not reconciled/);
});

test("the browser-side reconciliation says what it is", () => {
  // Two screens doing one job drift. Until the owner decides which to keep, a
  // CA must not discover the difference by losing an evening to a refresh.
  const src = code(OLD_SCREEN);
  assert.match(src, /does not read your client&apos;s books, and it does not save anything/,
    "the old screen must say plainly that it persists nothing");
  assert.match(src, /GSTR-2B Recon/,
    "and point at the one that does");
});
