import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { checksumChar, gstinPan, gstinProblem, gstinStateCode, isValidGstin } from "./gstin.ts";

/**
 * The browser mirror of apps/api/domain/gst/gstin.py, exercised on the SAME
 * cases the Python authority is — apps/api/tests/fixtures/gstin.json, read by
 * both suites. Changing one implementation without the other fails here.
 */
const SHARED = JSON.parse(
  readFileSync(new URL("../../../api/tests/fixtures/gstin.json", import.meta.url), "utf8"),
) as {
  valid: string[];
  invalid: { gstin: string; fragment: string }[];
};

test("every shared valid case passes", () => {
  for (const g of SHARED.valid) {
    assert.equal(gstinProblem(g), null, `${JSON.stringify(g)} should be valid`);
  }
});

test("every shared invalid case fails, for the stated reason", () => {
  for (const c of SHARED.invalid) {
    const problem = gstinProblem(c.gstin);
    assert.ok(problem, `${c.gstin} should be rejected`);
    assert.ok(problem.includes(c.fragment),
      `${c.gstin}: expected a message containing "${c.fragment}", got "${problem}"`);
  }
});

test("the message is identical to the Python authority's, word for word", () => {
  // Not merely "contains the fragment": a CA reads this sentence, and two
  // implementations drifting into two different explanations of the same
  // problem is the thing the shared fixture exists to prevent.
  assert.equal(
    gstinProblem("27AAPFU0939F1ZW"),
    "The check digit does not match: this GSTIN ends in W, and the first 14 "
    + "characters compute to V. Usually two characters have been swapped — check the PAN.",
  );
});

test("a transposition inside the PAN is caught, though the shape accepts it", () => {
  const shape = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/;
  const swapped = "27AAPFU0399F1ZV";
  assert.ok(shape.test(swapped), "the shape regex still accepts it — that is the point");
  assert.equal(isValidGstin(swapped), false);
});

test("blank is not wrong", () => {
  // A person who is not registered has no GSTIN. That is different from having
  // a wrong one, and an unregistered supplier must stay saveable.
  for (const blank of [null, undefined, "", "   "]) {
    assert.equal(isValidGstin(blank), true);
    assert.equal(gstinProblem(blank), null);
  }
});

test("case and surrounding whitespace are forgiven", () => {
  assert.equal(isValidGstin("  27aapfu0939f1zv  "), true);
});

test("the state code and PAN can be read off a valid GSTIN, and only a valid one", () => {
  assert.equal(gstinStateCode("27AAPFU0939F1ZV"), "27");
  assert.equal(gstinPan("27AAPFU0939F1ZV"), "AAPFU0939F");
  // Place of supply follows the state code (IGST Act §7/§8), so reading one out
  // of a number that failed its own check digit would silently decide whether
  // IGST or CGST+SGST is charged.
  assert.equal(gstinStateCode("27AAPFU0939F1ZW"), null);
  assert.equal(gstinPan("27AAPFU0939F1ZW"), null);
});

test("checksumChar refuses anything but fourteen GSTIN characters", () => {
  assert.throws(() => checksumChar("27AAPFU0939F1"), /14 characters/);
  assert.throws(() => checksumChar("27AAPFU0939F1-"), /not a GSTIN character/);
});

test("every check digit the algorithm produces validates", () => {
  // Round trip across the entity-number position, so a wrong weight or modulus
  // shows up rather than happening to work for the three real numbers.
  for (const ch of "ABCDEFGHIJKLMNOPQRSTUVWXYZ") {
    const body = `27AAPFU0939F${ch}Z`;
    assert.equal(isValidGstin(body + checksumChar(body)), true, body);
  }
});
