// POST-A-399, the sixth slice: evidence in text that is on file is corrected and not removed on an edit, and the screen says so instead of saying it saved.
// Run with: node --experimental-strip-types --test lib/forms/removedEvidence.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { removedEvidenceProblem } from "./removedEvidence.ts";

test("evidence on file and a blank box is refused in the box's own words", () => {
  assert.equal(removedEvidenceProblem("The shipping bill number", "SB-4471", "", "number"),
    "The shipping bill number on file can be corrected but not removed: enter the corrected number.");
  assert.equal(removedEvidenceProblem("The Form 15CB UDIN", "24012345ABCDEF1234", "   ", "UDIN"),
    "The Form 15CB UDIN on file can be corrected but not removed: enter the corrected UDIN.");
});

test("text in the box is no problem, whether it is what is on file or a correction", () => {
  assert.equal(removedEvidenceProblem("The port code", "INNSA1", "INNSA1", "code"), null);
  assert.equal(removedEvidenceProblem("The port code", "INNSA1", "INBOM4", "code"), null);
});

test("nothing on file is no problem: a new document and a box that was never filled are not this rule's", () => {
  for (const onFile of ["", "  ", null, undefined]) {
    assert.equal(removedEvidenceProblem("The vendor invoice number", onFile, "", "number"), null);
  }
});
