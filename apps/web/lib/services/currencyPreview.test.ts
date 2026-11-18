// Unit tests for the Multi-Currency UI preview helpers. Run with:
//   node --experimental-strip-types --test lib/services/currencyPreview.test.ts
//
// estimateForeignTds and convertBaseToForeignMinor USED TO LIVE HERE and were
// deleted with their tests when the purchase-bill editor stopped computing TDS
// in the browser (TDS-14). The tests they had were all correct about the
// arithmetic they described — including the good one proving the rate must be
// applied to the BASE-converted taxable and not the raw foreign figure — and
// that was the problem: rate x base is not what the server computes. It
// branches on residency first, then applies a section threshold, the year's
// aggregate and the s.206AA floor, or s.195 with surcharge and cess. A helper
// that cannot see any of those cannot preview the figure that will be saved,
// however well it is tested. lib/purchases/serverTdsPreview.ts asks the server.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { baseTotalOfHeads, rateParts, toBaseMinor } from "./currencyPreview.ts";

// POST-A-266: the preview is the save's conversion, pinned to the Python by the vectors both suites read.
const V = JSON.parse(readFileSync(join(import.meta.dirname, "../../../../shared/fx-conversion-vectors.json"), "utf8")) as {
  conversions: Array<{ txn_minor: number; rate: string; txn_minor_unit: number; base_minor: number }>;
  documents: Array<{ heads: number[]; rate: string; txn_minor_unit: number; base_total: number; one_conversion_of_the_total: number }>;
};

test("every conversion is what to_base_minor computes", () => {
  assert.ok(V.conversions.length >= 15);
  for (const v of V.conversions) assert.equal(toBaseMinor(v.txn_minor, v.rate, v.txn_minor_unit), v.base_minor, JSON.stringify(v));
});

test("a document's INR total is its heads converted one by one and added, as the save does", () => {
  for (const d of V.documents) assert.equal(baseTotalOfHeads(d.heads, d.rate, d.txn_minor_unit), d.base_total, JSON.stringify(d));
  assert.ok(V.documents.some((d) => d.base_total !== d.one_conversion_of_the_total), "a vector shows the old single conversion differs");
});

test("a rate or a unit that cannot be read gives no figure, never a guess", () => {
  for (const r of ["", "0", "0.00", "-83", "83,5", "8e1", "abc", "83.", ".5"]) assert.equal(rateParts(r), null, r);
  assert.equal(toBaseMinor(100, "83", 7), null);
  assert.equal(baseTotalOfHeads([100], "83", undefined), null, "a currency the master has not described");
  assert.equal(baseTotalOfHeads([100, 5], "x", 2), null);
});

test("the editors show the save's conversion and no longer multiply the total once", () => {
  const web = join(import.meta.dirname, "../..");
  for (const f of ["components/invoices/InvoiceEditor.tsx", "components/purchases/PurchaseBillEditor.tsx"]) {
    const src = readFileSync(join(web, f), "utf8");
    assert.match(src, /baseTotalOfHeads\(/, f);
    assert.doesNotMatch(src, /estimateBaseMinor|≈ INR total/, f);
  }
});
