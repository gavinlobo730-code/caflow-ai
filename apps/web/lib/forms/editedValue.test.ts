import { test } from "node:test";
import assert from "node:assert/strict";
import { editedChoice, editedText, removedIdentifierProblem } from "./editedValue.ts";

test("a box with text sends the text, trimmed, whatever was on file", () => {
  assert.equal(editedText("  Pay by cheque ", "Pay by NEFT"), "Pay by cheque");
  assert.equal(editedText("Pay by cheque", ""), "Pay by cheque");
  assert.equal(editedText("PO-77", "PO-76"), "PO-77");
});

test("an emptied box that had a value on file sends null, so the server clears it", () => {
  assert.equal(editedText("", "Pay by cheque"), null);
  assert.equal(editedText("   ", "Pay by cheque"), null);
  assert.equal(editedText("", "PO-77"), null);
});

test("an empty box with nothing on file says nothing: a field the screen never showed is not erased", () => {
  assert.equal(editedText("", ""), undefined);
  assert.equal(editedText("", null), undefined);
  assert.equal(editedText("", undefined), undefined);
  assert.equal(editedText(null, undefined), undefined);
  assert.equal(editedText("  ", "   "), undefined, "blanks on both sides are nothing on both sides");
});

test("what a request carries: null survives JSON and undefined does not, which is the whole point", () => {
  const body = JSON.parse(JSON.stringify({ notes: editedText("", "was here"), reference_no: editedText("", ""), our_reference: editedText("OUR-2", "OUR-1") }));
  assert.deepEqual(body, { notes: null, our_reference: "OUR-2" }, "a cleared note is sent; an untouched empty reference is left out");
});

test("a box on file that is cleared and then put back sends the text, not a clear", () => {
  assert.equal(editedText("Pay by cheque", "Pay by cheque"), "Pay by cheque");
});

test("editedChoice: a figure or a picked answer follows the same three cases, and a zero is a value, not an empty box", () => {
  assert.equal(editedChoice(500000, 9000000), 500000);
  assert.equal(editedChoice(0, 9000000), 0, "a credit limit of 0 is cash only, a real answer");
  assert.equal(editedChoice(null, 9000000), null, "emptied over a limit on file: cleared");
  assert.equal(editedChoice(null, 0), null, "emptied over a limit of 0: cleared");
  assert.equal(editedChoice(null, null), undefined);
  assert.equal(editedChoice("", "registered"), null);
  assert.equal(editedChoice(" non_resident ", null), "non_resident");
  assert.equal(editedChoice("", undefined), undefined);
});

test("removedIdentifierProblem: refuses only an identifier on file that the box no longer holds", () => {
  assert.equal(removedIdentifierProblem("GSTIN", "27AAPFU0939F1ZV", "27AAPFU0939F1ZV"), null);
  assert.equal(removedIdentifierProblem("GSTIN", "27AAPFU0939F1ZV", "29AAGCB7383J1Z4"), null, "a correction is not a removal");
  assert.equal(removedIdentifierProblem("GSTIN", null, ""), null, "nothing on file, nothing removed");
  assert.equal(removedIdentifierProblem("GSTIN", "  ", ""), null);
  assert.equal(removedIdentifierProblem("PAN", "AAPFU0939F", "  "),
    "The PAN on file can be corrected but not removed: enter the corrected PAN. Every return not yet filed reads it for the documents already issued to this party.");
});
