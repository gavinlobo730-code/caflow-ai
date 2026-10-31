// POST-A-073 — recording a return as filed writes what it used of each brought-forward loss back to the loss records on the
// server; the screen only reports the cases a person should hear about.
//
// Run with:
//   node --experimental-strip-types --test lib/tax/lossRecordNote.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { lossRecordAnswer, lossRecordNote } from "./lossRecordNote.ts";

const answer = (state: string, message = "A sentence.") => ({ id: "f1", status: "filed", brought_forward_losses: { state, message, losses: [] } });

for (const state of ["written", "not_written"]) {
  test(`the server's own sentence is shown (${state})`, () => {
    assert.equal(lossRecordNote(answer(state, "Two records now show it.")), "Two records now show it.");
  });
}

for (const state of ["unchanged", "no_losses"]) {
  test(`nothing is said when there is nothing to hear (${state})`, () => {
    assert.equal(lossRecordNote(answer(state)), null);
  });
}

test("a blank sentence is not shown", () => {
  assert.equal(lossRecordNote(answer("written", "   ")), null);
});

test("an answer without the block, or a payload that is not an object, says nothing", () => {
  for (const data of [null, undefined, "x", 3, [], {}, { brought_forward_losses: null }, { brought_forward_losses: "x" }, { brought_forward_losses: { state: 3 } }]) {
    assert.equal(lossRecordNote(data), null);
  }
});

for (const state of ["written", "not_written", "unchanged", "no_losses"]) {
  test(`when the CA asked, the server's sentence is shown whatever the state (${state})`, () => {
    assert.equal(lossRecordAnswer(answer(state, "The server's sentence.")), "The server's sentence.");
  });
}

test("a click is not answered with a blank or a payload that is not the answer", () => {
  for (const data of [null, undefined, "x", 3, [], {}, { brought_forward_losses: null }, answer("written", "  ")]) {
    assert.equal(lossRecordAnswer(data), null);
  }
});
