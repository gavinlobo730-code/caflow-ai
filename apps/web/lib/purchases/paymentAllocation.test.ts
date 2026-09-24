// Applying a vendor payment to bills — the AP mirror of SALES-14. Run with:
//   node --experimental-strip-types --test lib/purchases/paymentAllocation.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import {
  allocationProblems, ceilingFor, settlementValue, unallocatedOf,
} from "./paymentAllocation.ts";
import {
  settlementValue as receiptSettlement,
} from "../sales/receiptAllocation.ts";

const L = 1_00_000_00; // one lakh, in paise

// ── THE ASYMMETRY, WHICH IS THE WHOLE REASON THIS FILE EXISTS ──────────────
//
// A RECEIPT settles cash + the TDS the CUSTOMER deducted (§198/§199). A
// PAYMENT settles the cash alone, because the tax the CLIENT withheld has
// already come off `purchase_bills.net_payable_paise` — the figure migration
// 278's generated `outstanding_paise` is built from — and
// `update_allocations_core` caps on `amount_paise`.
//
// Getting this backwards on either side lets a CA type a figure the server
// answers 422 to, which is exactly what these caps exist to prevent.

test("a payment settles the cash and only the cash", () => {
  assert.equal(settlementValue({ amount_paise: 98_000_00 }), 98_000_00);
  assert.equal(settlementValue({ amount_paise: L }), L);
});

test("the two sides disagree about TDS, and each is right about its own", () => {
  // Same shape, different answer. Asserted on the ANSWERS rather than by
  // reading either implementation, so collapsing the two into one function
  // fails here rather than passing quietly.
  const cash = 98_000_00;
  assert.equal(receiptSettlement({ amount_paise: cash, tds_paise: 2_000_00 }), L);
  assert.equal(settlementValue({ amount_paise: cash }), cash);
  assert.notEqual(
    receiptSettlement({ amount_paise: cash, tds_paise: 2_000_00 }),
    settlementValue({ amount_paise: cash }),
  );
});

// ── What is still unallocated ──────────────────────────────────────────────

test("the unallocated figure is the server's own, not a subtraction", () => {
  // A payment the server says has ₹5,000 left, whatever `allocated_paise`
  // happens to hold — the column is written by update_allocations_core at the
  // end of every re-allocation.
  assert.equal(unallocatedOf({
    amount_paise: L, allocated_paise: 90_000_00, unallocated_paise: 5_000_00,
  }), 5_000_00);
});

test("a row written before the column existed falls back to the formula", () => {
  assert.equal(unallocatedOf({ amount_paise: L, allocated_paise: 40_000_00 }), 60_000_00);
  assert.equal(unallocatedOf({ amount_paise: L }), L);
  assert.equal(unallocatedOf({ amount_paise: L, unallocated_paise: null }), L);
});

test("a fully applied payment reads as nil, not as falsy-therefore-missing", () => {
  // 0 is a real answer and must not fall through to the subtraction.
  assert.equal(unallocatedOf({
    amount_paise: L, allocated_paise: L, unallocated_paise: 0,
  }), 0);
});

// ── The ceiling: the bill's own outstanding, plus what this payment had ────

test("the ceiling is the bill's generated outstanding", () => {
  assert.equal(ceilingFor({ id: "b1", outstanding_paise: 30_000_00 }), 30_000_00);
});

test("a bill THIS payment already cleared still has room for it", () => {
  // update_allocations_core reverses this payment's prior allocations before
  // applying the new ones, so its own contribution is added back. Without it,
  // re-allocating an existing payment would be impossible and the line would
  // vanish from the set the modal submits.
  assert.equal(ceilingFor({ id: "b1", outstanding_paise: 0 }, 25_000_00), 25_000_00);
});

// ── The per-line and total checks ──────────────────────────────────────────

test("an allocation above the bill's outstanding is refused", () => {
  const p = allocationProblems(
    [{ documentId: "b1", paise: 40_000_00, ceiling: 30_000_00 }], L);
  assert.equal(p.ok, false);
  assert.equal(p.perLine.length, 1);
  assert.match(p.perLine[0].message, /still owes/);
});

test("a negative allocation is refused — it is not a refund", () => {
  // It would drive the bill's paid_paise DOWN and reopen a bill this payment
  // never touched.
  const p = allocationProblems(
    [{ documentId: "b1", paise: -1_00, ceiling: 30_000_00 }], L);
  assert.equal(p.ok, false);
  assert.match(p.perLine[0].message, /negative/);
});

test("something that is not an amount is refused, not read as nil", () => {
  const p = allocationProblems(
    [{ documentId: "b1", paise: null, ceiling: 30_000_00 }], L);
  assert.equal(p.ok, false);
  assert.match(p.perLine[0].message, /Not an amount/);
});

test("allocating more than the payment settles is an over-run", () => {
  const p = allocationProblems([
    { documentId: "b1", paise: 60_000_00, ceiling: L },
    { documentId: "b2", paise: 60_000_00, ceiling: L },
  ], L);
  assert.equal(p.overRun, true);
  assert.equal(p.ok, false);
  assert.equal(p.total, 1_20_000_00);
});

test("leaving part of a payment unallocated is fine — it is an advance", () => {
  const p = allocationProblems(
    [{ documentId: "b1", paise: 30_000_00, ceiling: 30_000_00 }], L);
  assert.equal(p.ok, true);
  assert.equal(p.overRun, false);
  assert.equal(p.total, 30_000_00);
});
