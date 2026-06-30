// Unit tests for the QuickBooks-style Payment Terms mapping (customer & invoice
// terms ⇄ credit days). Run with:
//   node --experimental-strip-types --test lib/sales/paymentTerms.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import {
  PAYMENT_TERM_PRESETS,
  CUSTOM_TERM,
  termLabelForDays,
  daysForTermLabel,
  isCustomDays,
} from "./paymentTerms.ts";

test("termLabelForDays maps each preset day-count to its label", () => {
  assert.equal(termLabelForDays(0), "Due on Receipt");
  assert.equal(termLabelForDays(15), "Net 15");
  assert.equal(termLabelForDays(30), "Net 30");
  assert.equal(termLabelForDays(45), "Net 45");
  assert.equal(termLabelForDays(60), "Net 60");
});

test("termLabelForDays returns Custom for non-preset / unknown values", () => {
  assert.equal(termLabelForDays(7), CUSTOM_TERM);
  assert.equal(termLabelForDays(90), CUSTOM_TERM);
  assert.equal(termLabelForDays(null), CUSTOM_TERM);
  assert.equal(termLabelForDays(undefined), CUSTOM_TERM);
  assert.equal(termLabelForDays(NaN), CUSTOM_TERM);
});

test("daysForTermLabel maps preset labels to day-counts; Custom is null", () => {
  assert.equal(daysForTermLabel("Due on Receipt"), 0);
  assert.equal(daysForTermLabel("Net 15"), 15);
  assert.equal(daysForTermLabel("Net 30"), 30);
  assert.equal(daysForTermLabel("Net 45"), 45);
  assert.equal(daysForTermLabel("Net 60"), 60);
  assert.equal(daysForTermLabel(CUSTOM_TERM), null);
  assert.equal(daysForTermLabel("nonsense"), null);
});

test("preset label ⇄ days round-trips for every preset", () => {
  for (const p of PAYMENT_TERM_PRESETS) {
    assert.equal(daysForTermLabel(p.label), p.days);
    assert.equal(termLabelForDays(p.days), p.label);
  }
});

test("isCustomDays is true only for non-preset values", () => {
  assert.equal(isCustomDays(30), false);
  assert.equal(isCustomDays(0), false);
  assert.equal(isCustomDays(7), true);
  assert.equal(isCustomDays(null), true);
});
