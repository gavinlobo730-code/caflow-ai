// Unit tests for the Multi-Currency UI preview helpers (foreign invoice/bill
// header estimates, and the INR-only TDS-on-a-foreign-bill preview). Run with:
//   node --experimental-strip-types --test lib/services/currencyPreview.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import {
  estimateBaseMinor,
  estimateForeignTds,
  convertBaseToForeignMinor,
} from "./currencyPreview.ts";

test("estimateBaseMinor converts foreign minor units to base paise at the booking rate", () => {
  assert.equal(estimateBaseMinor(10000, 83), 830000);       // $100.00 @ 83 -> Rs 8,300.00
  assert.equal(estimateBaseMinor(0, 83), 0);
  assert.equal(estimateBaseMinor(10000, 83.25), 832500);    // fractional rate
});

test("estimateBaseMinor rounds to the nearest paisa", () => {
  assert.equal(estimateBaseMinor(333, 1.005), 335); // 333 * 1.005 = 334.665 -> 335
});

test("estimateForeignTds applies the vendor's bps rate to an already-base taxable value", () => {
  assert.equal(estimateForeignTds(8_300_000, 200), 166_000); // Rs 83,000 taxable @ 2% -> Rs 1,660.00
  assert.equal(estimateForeignTds(100_000, 0), 0);           // no TDS rate -> nothing withheld
  assert.equal(estimateForeignTds(0, 1000), 0);              // no taxable -> nothing withheld
});

test("estimateForeignTds floors (never rounds up) — matches the backend's TDS engine", () => {
  assert.equal(estimateForeignTds(333, 1000), 33); // 333 * 1000 / 10000 = 33.3 -> 33
});

test("convertBaseToForeignMinor is the inverse of estimateBaseMinor at the same rate", () => {
  const foreign = 10_000;
  const rate = 83;
  const base = estimateBaseMinor(foreign, rate);
  assert.equal(convertBaseToForeignMinor(base, rate), foreign);
});

test("convertBaseToForeignMinor returns 0 for a not-yet-usable rate (still being typed)", () => {
  assert.equal(convertBaseToForeignMinor(830_000, 0), 0);
  assert.equal(convertBaseToForeignMinor(830_000, -5), 0);
});

test("foreign purchase bill preview: TDS must be computed on the base-converted taxable, not the raw foreign figure", () => {
  // $1,000.00 taxable, 18% GST -> $1,180.00 total; vendor is 2% TDS (194C); rate 1 USD = INR 83.
  const foreignTaxable = 100_000; // $1,000.00 in cents
  const foreignTotal = 118_000;   // $1,180.00 in cents
  const rate = 83;
  const tdsRateBps = 200; // 2%

  const estBaseTaxable = estimateBaseMinor(foreignTaxable, rate);
  assert.equal(estBaseTaxable, 8_300_000); // Rs 83,000.00

  const tdsPaise = estimateForeignTds(estBaseTaxable, tdsRateBps);
  assert.equal(tdsPaise, 166_000); // Rs 1,660.00 — always INR, never foreign-denominated

  // Naive (wrong) approach: apply the TDS rate directly to the foreign taxable
  // and treat the result as paise. This is exactly the bug this module exists
  // to prevent — it understates the true INR TDS by the exchange-rate factor.
  const naiveWrongTds = Math.floor((foreignTaxable * tdsRateBps) / 10000);
  assert.notEqual(naiveWrongTds, tdsPaise);
  assert.equal(naiveWrongTds, 2_000); // Rs 20.00 — ~83x too small

  const netPayableForeign = foreignTotal - convertBaseToForeignMinor(tdsPaise, rate);
  assert.equal(netPayableForeign, 116_000); // $1,160.00 actually wired to the vendor
});
