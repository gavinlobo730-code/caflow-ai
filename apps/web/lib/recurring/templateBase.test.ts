import { test } from "node:test";
import assert from "node:assert/strict";
import { templateBasePaise } from "./templateBase.ts";

test("a line is valued by exact decimal multiplication and truncation, as the server values it", () => {
  // 0.335 x Rs 1.00 is 33.5 paise exactly: the server stores 33. Math.round(0.335 * 100) is 34.
  assert.equal(templateBasePaise([{ quantity: 0.335, rate_paise: 100 }]), 33);
  // 2.335 x Rs 1.00 is 233.5 paise exactly: truncation gives 233, rounding would give 234.
  assert.equal(templateBasePaise([{ quantity: 2.335, rate_paise: 100 }]), 233);
  // Binary floating point puts 1.005 x 100 at 100.49999999999999, and the exact product is 100.5: truncated, 100.
  assert.equal(templateBasePaise([{ quantity: 1.005, rate_paise: 100 }]), 100);
});

test("the lines are valued one at a time and then added, never added and then valued", () => {
  // Two lines of 0.335 x Rs 1.00: 33 + 33 = 66, not trunc(0.67 x 100) = 67.
  assert.equal(templateBasePaise([{ quantity: 0.335, rate_paise: 100 }, { quantity: 0.335, rate_paise: 100 }]), 66);
});

test("whole quantities and ordinary rates are plain multiplication", () => {
  assert.equal(templateBasePaise([{ quantity: 3, rate_paise: 125000 }]), 375000);
  assert.equal(templateBasePaise([{ quantity: 12, rate_paise: 99900 }, { quantity: 1, rate_paise: 50000 }]), 1248800);
});

test("a missing rate or quantity counts as nil, and an empty template is nil", () => {
  assert.equal(templateBasePaise([]), 0);
  assert.equal(templateBasePaise([{ quantity: null, rate_paise: 100 }, { quantity: 2, rate_paise: undefined }, {}]), 0);
});

test("a product just under a whole paisa is truncated, not rounded up to it", () => {
  // 0.001 units x 99,999,999 paise is exactly 99,999.999 paise: the server stores 99,999, rounding would say 1,00,000.
  assert.equal(templateBasePaise([{ quantity: 0.001, rate_paise: 99_999_999 }]), 99_999);
  assert.equal(Math.round(0.001 * 99_999_999), 100_000, "the formula this replaces");
});
