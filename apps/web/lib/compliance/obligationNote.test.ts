// POST-A-254 — a return recorded as filed in the GST workspace closes its compliance obligation on the server; the
// screen only reports the cases where it did not.
//
// Run with:
//   node --experimental-strip-types --test lib/compliance/obligationNote.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { obligationNote } from "./obligationNote.ts";

const answer = (state: string, closed: boolean, message = "A sentence.") =>
  ({ id: "r1", status: "submitted", compliance_obligation: { state, closed, message } });

test("a closed obligation says nothing", () => {
  assert.equal(obligationNote(answer("closed", true)), null);
});

test("an obligation that was already filed says nothing: that is the state the CA wanted", () => {
  assert.equal(obligationNote(answer("already_filed", false)), null);
});

for (const state of ["waiting_for_other_registrations", "not_on_the_calendar", "not_allowed", "not_closed"]) {
  test(`the server's own sentence is shown when the calendar was left open (${state})`, () => {
    assert.equal(obligationNote(answer(state, false, "Left open because.")), "Left open because.");
  });
}

test("an answer without the block, or a payload that is not an object, says nothing", () => {
  for (const data of [null, undefined, "x", 3, [], {}, { compliance_obligation: null }, { compliance_obligation: "x" }]) {
    assert.equal(obligationNote(data), null);
  }
});

test("a missing or blank message is not invented", () => {
  assert.equal(obligationNote({ compliance_obligation: { state: "not_closed", closed: false } }), null);
  assert.equal(obligationNote(answer("not_closed", false, "   ")), null);
});
