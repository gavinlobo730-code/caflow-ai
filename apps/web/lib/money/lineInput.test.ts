import { test } from "node:test";
import assert from "node:assert/strict";
import { lineAmountsTyped, parseLineAmounts } from "./lineInput.ts";

test("a plain line is read exactly", () => {
  assert.deepEqual(parseLineAmounts("2", "125000"), { quantity: 2, ratePaise: 12_500_000 });
  assert.deepEqual(parseLineAmounts("0.335", "1.00"), { quantity: 0.335, ratePaise: 100 });
});

test("the grouped rate that used to be accepted as one rupee is read as what it says", () => {
  // (parseFloat("1,25,000") || 0) > 0 is TRUE, and the line saved at ₹1. It is now READ as ₹1,25,000 (POST-A-567, the owner's decision of
  // 27-11-2026), by the one reader every line's text goes through, so the preview and the payload agree on it.
  assert.deepEqual(parseLineAmounts("1", "1,25,000"), { quantity: 1, ratePaise: 12_500_000 });
  assert.deepEqual(parseLineAmounts("1,000", "50"), { quantity: 1000, ratePaise: 5000 });
});

test("a comma in a place nobody writes one is still refused", () => {
  assert.equal(parseLineAmounts("1", "1,2,5"), null);
  assert.equal(parseLineAmounts("1", "12,50"), null);
  assert.equal(parseLineAmounts("1,00", "50"), null);
});

test("text that parseFloat reads as a number is refused", () => {
  assert.equal(parseLineAmounts("1", "12abc"), null);   // parseFloat -> 12
  assert.equal(parseLineAmounts("1", "1e3"), null);     // parseFloat -> 1000
  assert.equal(parseLineAmounts("1e3", "50"), null);
});

test("a rate with more precision than paise is refused, not truncated", () => {
  assert.equal(parseLineAmounts("1", "1.005"), null);
});

test("zero and negative are not lines", () => {
  assert.equal(parseLineAmounts("0", "50"), null);
  assert.equal(parseLineAmounts("1", "0"), null);
  assert.equal(parseLineAmounts("-1", "50"), null);
  assert.equal(parseLineAmounts("1", "-50"), null);
});

test("blank is null, so an unfinished row is not an error", () => {
  assert.equal(parseLineAmounts("", ""), null);
  assert.equal(lineAmountsTyped("", ""), false);
  // …but a row with something in it IS one the CA meant to fill.
  assert.equal(lineAmountsTyped("2", ""), true);
  assert.equal(lineAmountsTyped("", "1,25,000"), true);
});
