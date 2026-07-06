// Batch 2 — dirty-state comparator for the invoice editor. Run with:
//   node --experimental-strip-types --test lib/invoices/dirtyState.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { hasChanges } from "./dirtyState.ts";

test("identical snapshots are not dirty (key order insensitive)", () => {
  assert.equal(hasChanges({ a: 1, b: 2 }, { b: 2, a: 1 }), false);
  assert.equal(hasChanges({ customerId: "c1", lines: [{ qty: "1", rate: "100" }] },
                          { customerId: "c1", lines: [{ rate: "100", qty: "1" }] }), false);
});

test("any field change is dirty", () => {
  assert.equal(hasChanges({ customerId: "c1" }, { customerId: "c2" }), true);
  assert.equal(hasChanges({ lines: [{ qty: "1" }] }, { lines: [{ qty: "2" }] }), true);
  assert.equal(hasChanges({ notes: "" }, { notes: "hi" }), true);
});

test("array order is significant (line reordering is a real change)", () => {
  assert.equal(hasChanges({ lines: ["a", "b"] }, { lines: ["b", "a"] }), true);
});
