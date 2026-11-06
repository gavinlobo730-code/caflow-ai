// POST-A-388: a date on file is replaced and not emptied on an edit, and the screen says so instead of saying it saved.
// Run with: node --experimental-strip-types --test lib/dates/removedDate.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { removedDateProblem } from "./removedDate.ts";

test("a date on file and a blank box is refused in the box's own words", () => {
  assert.equal(removedDateProblem("The shipping bill date", "2026-07-15", ""),
    "The shipping bill date on file can be corrected but not removed: enter the corrected date.");
});

test("the other way out is said when the screen has one", () => {
  assert.equal(removedDateProblem("The no-PE declaration date", "2026-07-15", "", "untick the declaration if there is none"),
    "The no-PE declaration date on file can be corrected but not removed: enter the corrected date, or untick the declaration if there is none.");
});

test("a date in the box is no problem, whether it is the one on file or a corrected one", () => {
  assert.equal(removedDateProblem("The Form 15CA date", "2026-07-15", "2026-07-15"), null);
  assert.equal(removedDateProblem("The Form 15CA date", "2026-07-15", "2026-07-16"), null);
});

test("nothing on file is no problem: a new record and a box that was never filled are not this rule's", () => {
  assert.equal(removedDateProblem("The opening balance date", "", ""), null);
  assert.equal(removedDateProblem("The opening balance date", null, ""), null);
  assert.equal(removedDateProblem("The opening balance date", undefined, ""), null);
  assert.equal(removedDateProblem("The opening balance date", "   ", ""), null, "blank space is not a date on file");
});

test("blank space in the box is a blank box", () => {
  assert.equal(removedDateProblem("The shipping bill date", "2026-07-15", "  ") !== null, true);
});

test("the sentence names the date it is about, so two forms cannot be mistaken for each other", () => {
  const a = removedDateProblem("The shipping bill date", "2026-07-15", "");
  const b = removedDateProblem("The opening balance date", "2026-07-15", "");
  assert.notEqual(a, b);
});
