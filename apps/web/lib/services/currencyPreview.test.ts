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
import { estimateBaseMinor } from "./currencyPreview.ts";

test("estimateBaseMinor converts foreign minor units to base paise at the booking rate", () => {
  assert.equal(estimateBaseMinor(10000, 83), 830000);       // $100.00 @ 83 -> Rs 8,300.00
  assert.equal(estimateBaseMinor(0, 83), 0);
  assert.equal(estimateBaseMinor(10000, 83.25), 832500);    // fractional rate
});

test("estimateBaseMinor rounds to the nearest paisa", () => {
  assert.equal(estimateBaseMinor(333, 1.005), 335); // 333 * 1.005 = 334.665 -> 335
});
