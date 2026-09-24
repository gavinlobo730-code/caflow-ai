// A vendor advance can be put against a bill — the AP mirror of SALES-14.
//
// `PATCH /api/purchase-payments/{id}/allocate` was written at the same time as
// the AR one (`update_allocations_core` calls itself "the AP mirror of
// receipts.py" in its own docstring) and no screen called either. SALES-14
// wired up the AR half; this is the other one, and until 24-09-2026 the
// Purchases screen showed an unallocated figure ONLY while a payment was being
// typed — a running total inside the form — so once saved, a stranded advance
// stopped being mentioned anywhere in the product.
//
// What these hold is narrow on purpose — the modal's copy and colours will
// change with the design pass. What must not change: the two sides' SETTLEMENT
// definitions stay apart, the caps stay shared, the ceiling is the server's
// generated column rather than a subtraction, and the whole allocation set is
// submitted rather than the one line that changed.
//
// Run with: node --experimental-strip-types --test scripts/a-stranded-advance-can-be-applied.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const read = (...p: string[]) =>
  stripComments(fs.readFileSync(path.join(__dirname, "..", ...p), "utf8"));

const MODAL = read("components", "purchases", "AllocatePaymentModal.tsx");
const PAGE = read("app", "clients", "[id]", "purchases", "page.tsx");
const AP = read("lib", "purchases", "paymentAllocation.ts");
const AR = read("lib", "sales", "receiptAllocation.ts");
const SHARED = read("lib", "allocation", "documentAllocation.ts");

test("the endpoint is actually called, which is the whole finding", () => {
  assert.match(MODAL, /api\.purchasePayments\.allocate\(/);
});

test("the screen offers it, and only where there is something to apply", () => {
  assert.match(PAGE, /setAllocateFor\(/, "no way to open the modal");
  assert.match(PAGE, /AllocatePaymentModal/, "the modal is not rendered");
  // Offering "Apply" on a fully-applied payment would open a modal whose only
  // possible outcome is re-submitting what is already there.
  assert.match(PAGE, /unallocatedOf\(p\) > 0 && \(/);
});

test("the unallocated figure is shown on the row, not only inside the form", () => {
  // The defect was not that the arithmetic was wrong — it was that a saved
  // payment stopped mentioning what was left over.
  assert.match(PAGE, /key: "unallocated", header: "Unallocated"/);
});

test("the two settlement rules stay apart, because they genuinely differ", () => {
  // AR adds the TDS the CUSTOMER deducted (§198/§199); AP does not, because
  // the tax the client withheld already came off net_payable_paise. Collapsing
  // them lets a CA type a figure the server answers 422 to.
  assert.match(AR, /amount_paise \?\? 0\) \+ Number\(r\.tds_paise/);
  assert.doesNotMatch(AP, /tds_paise/,
    "the AP settlement must not reach for TDS — it is already off the bill");
  // Deliberately NOT asserted on the comments: `stripComments` runs first, and
  // a guard that pins prose fails on a reword that breaks nothing. The rule is
  // the two functions' BEHAVIOUR, and lib/purchases/paymentAllocation.test.ts
  // holds that directly — it computes both and asserts they differ.
});

test("the caps are shared rather than copied", () => {
  for (const [name, src] of [["AP", AP], ["AR", AR]] as const) {
    assert.match(src, /from "\.\.\/allocation\/documentAllocation\.ts"/,
      `${name} should re-export the shared caps, not hold its own copy`);
  }
  assert.match(SHARED, /export function allocationProblems/);
  assert.match(SHARED, /export function ceilingFor/);
});

test("the ceiling is the generated column, never a subtraction in the browser", () => {
  // migration 278. The note SIGNS are opposite on the two sides — credit notes
  // ADD on a purchase bill and SUBTRACT on a sales invoice — which is exactly
  // why neither side may recompute it.
  assert.match(MODAL, /outstanding_paise/);
  assert.doesNotMatch(MODAL, /net_payable_paise\s*[-+]\s*/,
    "the modal is re-deriving what the column already holds");
});

test("the whole allocation set is submitted, not just the line that changed", () => {
  // The endpoint reverses everything first and re-applies what it is sent, so
  // sending one line silently un-applies the others.
  assert.match(MODAL, /entered\s*\n?\s*\.filter/);
  assert.match(MODAL, /purchase_bill_id: e\.documentId/);
});

test("a bill this payment already cleared is still listed", () => {
  // It has no outstanding left, so a naive `> 0` filter drops it — and then
  // re-allocating away from it is impossible and its line vanishes from the
  // set the modal submits.
  assert.match(MODAL, /outstanding_paise \?\? 0\) > 0 \|\| priorMap\[b\.id\] > 0/);
});

test("a refusal answered as HTTP 200 is checked", () => {
  // The API answers some refusals as 200 with {success: false}; an unchecked
  // call reports an allocation the server declined.
  assert.match(MODAL, /res\?\.success/);
});
