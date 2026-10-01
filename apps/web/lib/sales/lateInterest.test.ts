// Unit tests for the interest-terms keystroke helper (accounting-22). Run with:
//   node --experimental-strip-types --test lib/sales/lateInterest.test.ts
import test from "node:test";
import assert from "node:assert/strict";

import { ratePercentText, termsPayload } from "./lateInterest.ts";

test("a stored annual rate reads back as the percentage that was typed", () => {
  assert.equal(ratePercentText(1800), "18");
  assert.equal(ratePercentText(1850), "18.5");
  assert.equal(ratePercentText(75), "0.75");
  assert.equal(ratePercentText(5), "0.05");
  assert.equal(ratePercentText(0), "0");
});

test("no rate on record shows an empty box, not a zero", () => {
  assert.equal(ratePercentText(null), "");
  assert.equal(ratePercentText(undefined), "");
});

test("a rate round-trips through the box without a float in between", () => {
  for (const bps of [1, 5, 75, 100, 1250, 1800, 1899, 9999, 10000]) {
    const out = termsPayload({ rate: ratePercentText(bps), grace: "0", basis: "due_date" });
    assert.deepEqual(out, { ok: true, rate_bps: bps, grace_days: 0, basis: "due_date" });
  }
});

test("a blank rate clears the rate and a typed zero waives it: two different facts", () => {
  const blank = termsPayload({ rate: "  ", grace: "", basis: "due_date" });
  const zero = termsPayload({ rate: "0", grace: "", basis: "due_date" });
  assert.deepEqual(blank, { ok: true, rate_bps: null, grace_days: 0, basis: "due_date" });
  assert.deepEqual(zero, { ok: true, rate_bps: 0, grace_days: 0, basis: "due_date" });
});

test("a percent sign is allowed and a thing that is not a percentage is refused in words", () => {
  assert.deepEqual(termsPayload({ rate: "18%", grace: "0", basis: "due_date" }),
    { ok: true, rate_bps: 1800, grace_days: 0, basis: "due_date" });
  for (const bad of ["abc", "1e3", "18abc", "1.2.3"]) {
    const out = termsPayload({ rate: bad, grace: "0", basis: "due_date" });
    assert.equal(out.ok, false, bad);
    if (!out.ok) assert.match(out.error, /percentage/);
  }
});

test("Indian-grouped or float-looking text is never coerced into a rate", () => {
  // parseFloat("1,8") is 1: a rate of 1% where 18% was meant.
  const out = termsPayload({ rate: "1,8", grace: "0", basis: "due_date" });
  assert.equal(out.ok, false);
});

test("grace is a whole number of days and anything else is refused", () => {
  assert.deepEqual(termsPayload({ rate: "18", grace: "7", basis: "invoice_date" }),
    { ok: true, rate_bps: 1800, grace_days: 7, basis: "invoice_date" });
  for (const bad of ["7.5", "-1", "a week", "1e2"]) {
    const out = termsPayload({ rate: "18", grace: bad, basis: "due_date" });
    assert.equal(out.ok, false, bad);
    if (!out.ok) assert.match(out.error, /whole number of days/);
  }
});

test("the bounds are the server's: this helper does not carry a second copy of them", () => {
  // 150% a year and 999 grace days are accepted here so the server's own
  // sentence is what the CA reads, instead of two places deciding what a unit
  // slip is.
  const out = termsPayload({ rate: "150", grace: "999", basis: "due_date" });
  assert.deepEqual(out, { ok: true, rate_bps: 15000, grace_days: 999, basis: "due_date" });
});
