/**
 * The GSTR-2B reconciliation's words (PRE-A-001). Run with:
 *   node --experimental-strip-types --test lib/gst/recon2bBuckets.test.ts
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  RECON_2B_BUCKETS,
  reconStatusLabel,
  savedReconciliationBreakdown,
  supplierLines,
} from "./recon2bBuckets.ts";

test("the four answers each have a distinct name the screen uses everywhere", () => {
  assert.deepEqual(RECON_2B_BUCKETS.map((b) => b.status),
    ["matched", "amount_mismatch", "missing_in_2b", "missing_in_books"]);
  const labels = RECON_2B_BUCKETS.map((b) => b.label);
  assert.equal(new Set(labels).size, 4);
  for (const b of RECON_2B_BUCKETS) {
    assert.ok(b.label && b.hint && b.tone, b.status);
    assert.ok(!b.label.includes("_"), `${b.status}: a label is words, not a token`);
  }
});

test("a status is shown by its label, and an unknown one by its own words, never hidden", () => {
  assert.equal(reconStatusLabel("missing_in_2b"), "Supplier has not filed");
  assert.equal(reconStatusLabel("missing_in_books"), "No bill in the books");
  assert.equal(reconStatusLabel("pending_review"), "Pending review");
  assert.equal(reconStatusLabel(""), "Unclassified");
});

test("the saved reconciliation reads in the screen's words and order, with no raw token", () => {
  // The line printed `amount_mismatch: 1, missing_in_books: 3` before.
  const text = savedReconciliationBreakdown({ missing_in_books: 3, amount_mismatch: 1 });
  assert.equal(text, "Amount mismatch 1 · No bill in the books 3");
  assert.ok(!/[a-z]+_[a-z]+/.test(text));
  assert.equal(
    savedReconciliationBreakdown({ matched: 9, amount_mismatch: 1, missing_in_2b: 2, missing_in_books: 3 }),
    "Matched 9 · Amount mismatch 1 · Supplier has not filed 2 · No bill in the books 3");
});

test("a status the map does not know is still counted, after the known ones", () => {
  assert.equal(savedReconciliationBreakdown({ zeta_case: 2, matched: 1, alpha_case: 4 }),
    "Matched 1 · Alpha case 4 · Zeta case 2");
});

test("a zero, a missing or a damaged breakdown says nothing rather than something wrong", () => {
  assert.equal(savedReconciliationBreakdown({ matched: 0 }), "");
  assert.equal(savedReconciliationBreakdown({}), "");
  assert.equal(savedReconciliationBreakdown(null), "");
  assert.equal(savedReconciliationBreakdown(undefined), "");
  assert.equal(savedReconciliationBreakdown({ matched: Number.NaN, missing_in_2b: 2 }), "Supplier has not filed 2");
});

test("a supplier is named once: the name with the GSTIN under it, or the GSTIN alone", () => {
  const G = "27AAPFU0939F1ZV";
  assert.deepEqual(supplierLines("Acme Tools", G), { primary: "Acme Tools", secondary: G });
  // The case the drive found: a book-side row has no name, and the GSTIN was
  // printed on both lines.
  assert.deepEqual(supplierLines(null, G), { primary: G, secondary: null });
  assert.deepEqual(supplierLines("", G), { primary: G, secondary: null });
  assert.deepEqual(supplierLines("  ", G), { primary: G, secondary: null });
  // A name that is the GSTIN is not repeated either.
  assert.deepEqual(supplierLines(G, G), { primary: G, secondary: null });
  // Nothing at all is a dash, not a blank cell.
  assert.deepEqual(supplierLines(null, null), { primary: "—", secondary: null });
  assert.deepEqual(supplierLines("Acme Tools", ""), { primary: "Acme Tools", secondary: null });
});
