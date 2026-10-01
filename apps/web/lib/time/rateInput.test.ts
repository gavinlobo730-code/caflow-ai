// practice_management-11: a blank billing rate is "none", never ₹0, and a typed 0 is a rate.
//   node --experimental-strip-types --test lib/time/rateInput.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { readRateInput } from "./rateInput.ts";

test("a blank rate box is CLEAR, not zero", () => {
  assert.deepEqual(readRateInput(""), { kind: "clear" });
  assert.deepEqual(readRateInput("   "), { kind: "clear" });
});

test("a typed zero is a stated rate", () => {
  assert.deepEqual(readRateInput("0"), { kind: "rate", paise: 0 });
  assert.deepEqual(readRateInput("0.00"), { kind: "rate", paise: 0 });
});

test("rupees become exact paise", () => {
  assert.deepEqual(readRateInput("2500"), { kind: "rate", paise: 250000 });
  assert.deepEqual(readRateInput("2500.50"), { kind: "rate", paise: 250050 });
  assert.deepEqual(readRateInput(" 99.9 "), { kind: "rate", paise: 9990 });
});

for (const bad of ["1,25,000", "12abc", "1e3", "-5", "-0.01", ".", "abc", "1.2.3"]) {
  test(`${JSON.stringify(bad)} is refused with the sentence, not stored as something else`, () => {
    const r = readRateInput(bad);
    assert.equal(r.kind, "invalid");
    if (r.kind === "invalid") assert.match(r.message, /rupees per hour/);
  });
}
