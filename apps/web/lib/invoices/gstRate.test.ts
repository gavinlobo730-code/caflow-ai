// node --experimental-strip-types --test lib/invoices/gstRate.test.ts
//
// A stored GST rate must reopen as itself. The six line editors loaded it with
// Math.round(gst_rate_bps / 100), so 150 bps reopened as 2%, 750 as 8% and 10 or
// 25 as 0% — and because saving deletes and re-inserts every line, the wrong tax
// was written back into GSTR-1 and GSTR-3B (CGST Act §9: the rate notified for
// the supply is the rate charged). The rate list also stopped at 28 a year after
// the 40% slab began (IGST Act §5(1) allows up to 40%).
import test from "node:test";
import assert from "node:assert/strict";
import {
  GST_RATES,
  gstRateOptions,
  gstRateToPercent,
  gstRatePercentFromSelect,
} from "./gst.ts";
import { gstRateBpsFromPercent } from "../money/gstLine.ts";

test("a stored fractional rate reopens as itself, never rounded", () => {
  assert.equal(gstRateToPercent(150), 1.5, "150 bps used to reopen as 2%");
  assert.equal(gstRateToPercent(750), 7.5, "750 bps used to reopen as 8%");
  assert.equal(gstRateToPercent(10), 0.1, "10 bps used to reopen as 0%");
  assert.equal(gstRateToPercent(25), 0.25, "25 bps used to reopen as 0%");
  assert.equal(gstRateToPercent(4000), 40);
});

test("every whole number of basis points survives reopen and save unchanged", () => {
  // The editors save with gstRateBpsFromPercent; reopen then save must be the identity.
  for (let bps = 0; bps <= 10000; bps++) {
    assert.equal(gstRateBpsFromPercent(gstRateToPercent(bps)), bps, `${bps} bps changed on a re-save`);
  }
});

test("an absent or garbage stored rate reads as 0, and PostgREST's string bigint is accepted", () => {
  assert.equal(gstRateToPercent(null), 0);
  assert.equal(gstRateToPercent(undefined), 0);
  assert.equal(gstRateToPercent("750"), 7.5);
  assert.equal(gstRateToPercent("abc"), 0);
});

test("the rate select's value is parsed as a decimal, not truncated to an integer", () => {
  assert.equal(gstRatePercentFromSelect("7.5"), 7.5, "parseInt made this 7");
  assert.equal(gstRatePercentFromSelect("1.5"), 1.5);
  assert.equal(gstRatePercentFromSelect("0.25"), 0.25);
  assert.equal(gstRatePercentFromSelect("0.1"), 0.1);
  assert.equal(gstRatePercentFromSelect("40"), 40);
  assert.equal(gstRatePercentFromSelect(""), 0);
  assert.equal(gstRatePercentFromSelect("x"), 0);
});

test("the 40% slab can be chosen, and the historical slabs stay", () => {
  assert.ok(GST_RATES.includes(40), "40% must be offered");
  assert.ok(GST_RATES.includes(12) && GST_RATES.includes(28), "a pre-22-09-2025 document must still open at 12 or 28");
  for (const r of GST_RATES) {
    assert.equal(gstRatePercentFromSelect(String(r)), r, `${r}% does not survive the select`);
  }
});

test("a stored rate that is not a standard slab is shown, not hidden", () => {
  assert.equal(gstRateOptions(18), GST_RATES, "a standard slab changes nothing");
  assert.equal(gstRateOptions(null), GST_RATES);
  assert.equal(gstRateOptions(Number.NaN), GST_RATES);
  const odd = gstRateOptions(3.5);
  assert.ok(odd.includes(3.5), "the line's own 3.5% must have an option");
  assert.deepEqual(odd, [...odd].sort((a, b) => a - b), "and the options stay in order");
  assert.equal(odd.length, GST_RATES.length + 1);
});
