import { test } from "node:test";
import assert from "node:assert/strict";
import {
  bpsFromPercentInput, paiseFromRupeeInput, parseQuantity, rupeeInputFromPaise,
} from "./rupeeInput.ts";

test("whole rupees become paise", () => {
  assert.equal(paiseFromRupeeInput("0"), 0);
  assert.equal(paiseFromRupeeInput("1"), 100);
  assert.equal(paiseFromRupeeInput("100000"), 10_000_000);
});

test("one and two decimal places are read exactly", () => {
  assert.equal(paiseFromRupeeInput("12.3"), 1230);
  assert.equal(paiseFromRupeeInput("12.34"), 1234);
  assert.equal(paiseFromRupeeInput("0.05"), 5);
  assert.equal(paiseFromRupeeInput(".50"), 50);
  assert.equal(paiseFromRupeeInput("12."), 1200);
});

test("the values float arithmetic gets wrong", () => {
  // Math.round(parseFloat(s) * 100) for each of these: the double nearest the
  // decimal lands just under the .5 boundary, so the old form silently lost a
  // paise. These are the whole reason this module exists.
  for (const [typed, paise] of [["1.005", null], ["8.165", null], ["1.115", null]] as const) {
    assert.equal(paiseFromRupeeInput(typed), paise, `${typed} must be refused, not silently truncated`);
  }
  // And the ones it happens to get right must still be right here.
  assert.equal(paiseFromRupeeInput("1.01"), 101);
  assert.equal(paiseFromRupeeInput("8.17"), 817);
});

test("text that is not an amount is refused rather than coerced", () => {
  for (const bad of ["1e3", "12abc", "abc", "Infinity", "NaN", "1,000", "1 000", "--1", ".", "-", "1.2.3", "₹5"]) {
    assert.equal(paiseFromRupeeInput(bad), null, `${bad} should not parse`);
  }
});

test("blank is zero, because an empty amount column means nothing here", () => {
  assert.equal(paiseFromRupeeInput(""), 0);
  assert.equal(paiseFromRupeeInput("   "), 0);
});

test("surrounding whitespace is tolerated", () => {
  assert.equal(paiseFromRupeeInput("  12.34  "), 1234);
});

test("negatives keep their sign", () => {
  assert.equal(paiseFromRupeeInput("-12.34"), -1234);
  assert.equal(paiseFromRupeeInput("-0.01"), -1);
});

test("amounts beyond exact integer range are refused, not silently rounded", () => {
  assert.equal(paiseFromRupeeInput("999999999999999999"), null);
});

test("paise render back to a two-decimal string", () => {
  assert.equal(rupeeInputFromPaise(0), "0.00");
  assert.equal(rupeeInputFromPaise(5), "0.05");
  assert.equal(rupeeInputFromPaise(1234), "12.34");
  assert.equal(rupeeInputFromPaise(10_000_000), "100000.00");
  assert.equal(rupeeInputFromPaise(-1234), "-12.34");
});

test("round trip is exact across the range a CA can type", () => {
  for (const paise of [0, 1, 5, 99, 100, 1234, 99_999, 10_000_000, 123_456_789, -1, -1234]) {
    assert.equal(
      paiseFromRupeeInput(rupeeInputFromPaise(paise)), paise,
      `${paise} did not survive the round trip`,
    );
  }
});

test("percentages become basis points exactly", () => {
  assert.equal(bpsFromPercentInput("18"), 1800);
  assert.equal(bpsFromPercentInput("0.75"), 75);
  assert.equal(bpsFromPercentInput("10"), 1000);
  assert.equal(bpsFromPercentInput(""), 0);
  // The failures that matter: a grouped or partial number must be refused, not
  // read as a tenth of what was meant.
  assert.equal(bpsFromPercentInput("1,0"), null);
  assert.equal(bpsFromPercentInput("10%"), null);
  assert.equal(bpsFromPercentInput("abc"), null);
});

test("quantities are read exactly to three decimal places", () => {
  assert.equal(parseQuantity("1"), 1);
  assert.equal(parseQuantity("2.5"), 2.5);
  assert.equal(parseQuantity("0.335"), 0.335);
  assert.equal(parseQuantity("10.125"), 10.125);
});

test("a quantity that is not a quantity is refused, not coerced", () => {
  // Each of these is what parseFloat(x) || 0 silently produced instead.
  assert.equal(parseQuantity("1,000"), null);   // parseFloat -> 1
  assert.equal(parseQuantity("12abc"), null);   // parseFloat -> 12
  assert.equal(parseQuantity("1e3"), null);     // parseFloat -> 1000
  assert.equal(parseQuantity("2.5001"), null);  // more than NUMERIC(10,3) holds
  assert.equal(parseQuantity("."), null);
});

test("a blank quantity is a question, not a one", () => {
  // The call sites defaulted a blank to 1, which invents a line nobody typed.
  assert.equal(parseQuantity(""), null);
  assert.equal(parseQuantity("   "), null);
});
