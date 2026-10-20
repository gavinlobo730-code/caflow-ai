// Run with:
//   node --experimental-strip-types --test lib/health/vocabulary.test.ts
//
// The module's WORDS are pinned to the engine from the Python side
// (apps/api/tests/test_one_health_vocabulary.py). This file pins the two
// functions a screen calls — above all that a server grade wins.
import test from "node:test";
import assert from "node:assert/strict";
import {
  GRADE_BADGE_CLASS, GRADE_BAR_CLASS, GRADE_TEXT_CLASS, HEALTH_GRADES, PORTFOLIO_BAR_LABELS, PORTFOLIO_UNSPLIT_HEALTHY_LABEL,
  dimensionLabel, gradeBadgeClass, gradeForScore, gradeOf, gradeTone, scoreBarClass, scoreTextClass, weightLabel, HEALTH_DIMENSIONS,
} from "./vocabulary.ts";

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

test("a score is coloured as its grade is: the 66 that printed amber beside a Good badge is Good's colour now", () => {
  assert.equal(scoreTextClass(66), GRADE_TEXT_CLASS.Good);
  assert.equal(scoreBarClass(66), GRADE_BAR_CLASS.Good);
  assert.equal(scoreTextClass(45), GRADE_TEXT_CLASS["At Risk"]);
  assert.equal(scoreTextClass(34), GRADE_TEXT_CLASS.Critical);
  assert.equal(scoreTextClass(80), GRADE_TEXT_CLASS.Healthy);
  assert.equal(scoreTextClass(50), GRADE_TEXT_CLASS["Needs Attention"]);
});

test("every score from 0 to 100 has a colour of its grade, and the number and the badge share the severity token", () => {
  for (let score = 0; score <= 100; score++) {
    const grade = gradeForScore(score);
    assert.equal(scoreTextClass(score), GRADE_TEXT_CLASS[grade]);
    assert.equal(scoreBarClass(score), GRADE_BAR_CLASS[grade]);
    const token = /text-sev-\w+$/.exec(gradeBadgeClass(grade));
    assert.equal(token?.[0], scoreTextClass(score), `${score}: the number and the ${grade} badge are two colours`);
  }
});

test("five grades have five different looks", () => {
  for (const table of [GRADE_BADGE_CLASS, GRADE_TEXT_CLASS, GRADE_BAR_CLASS]) {
    assert.equal(new Set(HEALTH_GRADES.map((g) => table[g])).size, 5);
  }
});

test("the three-colour reading: Healthy and Good ready, Needs Attention and At Risk attention, Critical a problem", () => {
  assert.deepEqual(HEALTH_GRADES.map(gradeTone), ["ready", "ready", "attention", "attention", "problem"]);
  assert.equal(gradeTone(gradeForScore(70)), "ready", "the ring used to draw a firm score of 70 amber");
});

test("the portfolio bars are named with the engine's grade words", () => {
  assert.equal(PORTFOLIO_BAR_LABELS.healthy, "Healthy or Good");
  assert.equal(PORTFOLIO_BAR_LABELS.needsAttention, "Needs Attention");
  assert.equal(PORTFOLIO_BAR_LABELS.atRisk, "At Risk");
  assert.equal(PORTFOLIO_BAR_LABELS.critical, "Critical");
  assert.equal(PORTFOLIO_UNSPLIT_HEALTHY_LABEL, "Healthy, Good or Needs Attention");
});

test("a band's range is built from the band table: the text beside a count is the line the engine draws", async () => {
  const { gradeRangeLabel } = await import("./vocabulary.ts");
  assert.equal(gradeRangeLabel("Critical"), "0–34");
  assert.equal(gradeRangeLabel("At Risk"), "35–49");
  assert.equal(gradeRangeLabel("Needs Attention"), "50–64");
  assert.equal(gradeRangeLabel("Good"), "65–79");
  assert.equal(gradeRangeLabel("Healthy"), "80–100");
  assert.equal(gradeRangeLabel("Fine" as never), "", "a word that is not a grade has no range");
});
