// Applying a receipt to invoices (SALES-14). Run with:
//   node --experimental-strip-types --test lib/sales/receiptAllocation.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import {
  allocationProblems, ceilingFor, settlementValue, unallocatedOf,
} from "./receiptAllocation.ts";

const L = 1_00_000_00; // one lakh, in paise

// ── The TDS case, which is where every one of these went wrong ──────────────
//
// A §194J receipt of ₹98,000 cash and ₹2,000 customer-deducted TDS SETTLES
// ₹1,00,000 of invoices. routers/receipts.py caps allocations on amount + TDS
// for exactly that reason.

test("the settlement value is the cash plus the TDS the customer deducted", () => {
  assert.equal(settlementValue({ amount_paise: 98_000_00, tds_paise: 2_000_00 }), L);
  assert.equal(settlementValue({ amount_paise: L }), L);
  assert.equal(settlementValue({ amount_paise: L, tds_paise: null }), L);
});

test("a fully applied TDS receipt is not shown as owing money back", () => {
  // The receipts table computed `amount − allocated`, so this read −₹2,000 and
  // sat under the "Unallocated only" filter for ever.
  const r = { amount_paise: 98_000_00, tds_paise: 2_000_00,
              allocated_paise: L, unallocated_paise: 0 };
  assert.equal(unallocatedOf(r), 0);
  assert.equal(r.amount_paise - r.allocated_paise, -2_000_00,
               "the old formula, kept here so the fix cannot be undone quietly");
});

test("the server's own figure wins over any subtraction done here", () => {
  // They can legitimately differ mid-flight — allocated_paise is maintained on
  // the invoice side — and the stored one is what the endpoint wrote.
  assert.equal(unallocatedOf({ amount_paise: L, allocated_paise: 0,
                               unallocated_paise: 25_000_00 }), 25_000_00);
});

test("a row written before the column was populated falls back to the same formula", () => {
  assert.equal(unallocatedOf({ amount_paise: 98_000_00, tds_paise: 2_000_00,
                               allocated_paise: 60_000_00 }), 40_000_00);
  assert.equal(unallocatedOf({ amount_paise: L }), L);
});

// ── The per-invoice ceiling ────────────────────────────────────────────────

test("an invoice this receipt already paid can still be re-allocated", () => {
  // The endpoint REVERSES this receipt's prior allocations before applying the
  // new ones, so its own contribution is available again. Omitting the add-back
  // makes editing an existing allocation impossible — the field would refuse
  // the figure already in it.
  assert.equal(ceilingFor({ id: "I1", outstanding_paise: 0 }, 50_000_00), 50_000_00);
  assert.equal(ceilingFor({ id: "I1", outstanding_paise: 30_000_00 }, 20_000_00), 50_000_00);
});

test("another receipt's allocation is NOT added back", () => {
  // Only THIS receipt's prior lines are reversed. outstanding_paise already
  // has everybody else's payments in it (migration 278: total + debit notes −
  // paid − credited), and adding them again would let two receipts each pay
  // the invoice in full.
  assert.equal(ceilingFor({ id: "I1", outstanding_paise: 30_000_00 }), 30_000_00);
});

// ── Validation ─────────────────────────────────────────────────────────────

test("an allocation over the invoice's ceiling is refused", () => {
  const p = allocationProblems(
    [{ invoiceId: "I1", paise: 60_000_00, ceiling: 50_000_00 }], L);
  assert.equal(p.ok, false);
  assert.equal(p.perLine.length, 1);
  assert.match(p.perLine[0].message, /still owes/);
});

test("a total over what the receipt settles is refused", () => {
  const p = allocationProblems([
    { invoiceId: "I1", paise: 60_000_00, ceiling: L },
    { invoiceId: "I2", paise: 60_000_00, ceiling: L },
  ], L);
  assert.equal(p.overRun, true);
  assert.equal(p.ok, false);
  assert.equal(p.perLine.length, 0, "neither line is individually wrong");
  assert.equal(p.total, 1_20_000_00);
});

test("a negative allocation is refused rather than treated as a refund", () => {
  // It would drive the invoice's paid_paise DOWN and reopen an invoice this
  // receipt never touched.
  const p = allocationProblems([{ invoiceId: "I1", paise: -1000, ceiling: L }], L);
  assert.equal(p.ok, false);
  assert.match(p.perLine[0].message, /negative/i);
  assert.equal(p.total, 0, "a refused line contributes nothing to the total");
});

test("what is not an amount at all is refused, not coerced", () => {
  // `paise: null` is what lib/money/rupeeInput returns for "1,25,000" and
  // "12abc". The old parseFloat form would have made the first ₹1.
  const p = allocationProblems([{ invoiceId: "I1", paise: null, ceiling: L }], L);
  assert.equal(p.ok, false);
  assert.match(p.perLine[0].message, /Not an amount/);
});

test("leaving part of the receipt unapplied is fine", () => {
  // A customer may genuinely have paid ahead of an invoice not yet raised.
  const p = allocationProblems([{ invoiceId: "I1", paise: 40_000_00, ceiling: L }], L);
  assert.equal(p.ok, true);
  assert.equal(p.total, 40_000_00);
});

test("applying the whole receipt across several invoices is fine", () => {
  const p = allocationProblems([
    { invoiceId: "I1", paise: 30_000_00, ceiling: 30_000_00 },
    { invoiceId: "I2", paise: 70_000_00, ceiling: 80_000_00 },
  ], L);
  assert.equal(p.ok, true);
  assert.equal(p.total, L);
});

test("allocating nothing is allowed — it un-applies the receipt", () => {
  // The endpoint replaces the whole set, so an empty one is how a CA takes a
  // receipt back off the invoices it was wrongly put on.
  const p = allocationProblems([{ invoiceId: "I1", paise: 0, ceiling: L }], L);
  assert.equal(p.ok, true);
  assert.equal(p.total, 0);
});
