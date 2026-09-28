// Run with:
//   node --experimental-strip-types --test lib/health/vocabulary.test.ts
//
// The module's WORDS are pinned to the engine from the Python side
// (apps/api/tests/test_one_health_vocabulary.py). This file pins the two
// functions a screen calls — above all that a server grade wins.
import test from "node:test";
import assert from "node:assert/strict";
import { dimensionLabel, gradeForScore, gradeOf, weightLabel, HEALTH_DIMENSIONS } from "./vocabulary.ts";

test("73 is Good — the badge used to say Fair (sweep-client-purchases-05)", () => {
  assert.equal(gradeForScore(73), "Good");
  assert.equal(gradeForScore(64), "Needs Attention");
  assert.equal(gradeForScore(34), "Critical");
});

test("the server's grade wins over the score's band", () => {
  // A hard override caps the composite, so these agree in practice — but the
  // screen must show what the server SAID, not re-derive it.
  assert.equal(gradeOf("At Risk", 90), "At Risk");
});

test("a legacy letter or a missing grade reads as the score's band, never as a grade", () => {
  assert.equal(gradeOf("B", 73), "Good");
  assert.equal(gradeOf(null, 81), "Healthy");
  assert.equal(gradeOf(undefined, 10), "Critical");
});

test("an unknown dimension key is shown as itself, a missing one as Overall", () => {
  assert.equal(dimensionLabel("open_notices"), "Open Notices");
  assert.equal(dimensionLabel("relationship_risk"), "relationship_risk");
  assert.equal(dimensionLabel(null), "Overall");
});

test("weights sum to 100% and render as whole percentages", () => {
  assert.equal(HEALTH_DIMENSIONS.reduce((a, d) => a + d.weightBp, 0), 10000);
  assert.equal(weightLabel(2500), "25%");
  assert.equal(weightLabel(500), "5%");
});
