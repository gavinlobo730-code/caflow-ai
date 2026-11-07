import { test } from "node:test";
import assert from "node:assert/strict";
import { editedText } from "./editedValue.ts";

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
