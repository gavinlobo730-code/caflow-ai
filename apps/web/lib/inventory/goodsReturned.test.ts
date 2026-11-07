import { test } from "node:test";
import assert from "node:assert/strict";
import { goodsReturnedQuestion, goodsReturnedWords } from "./goodsReturned.ts";

// POST-A-378. The question is one control (`GoodsReturnedChoice`) used by four screens, and the goods of the two kinds of note do not travel the same way: a credit note's goods COME BACK to the client, a purchase debit
// note's goods GO BACK TO THE SUPPLIER. The server words its own question and its "stock was not moved" sentence with those two verbs (`domain/inventory/note_goods.KINDS`), and the legend must not contradict them.

test("the question is worded for the note's own kind", () => {
  assert.equal(goodsReturnedQuestion("credit_note"), "Did the goods come back?");
  assert.equal(goodsReturnedQuestion("debit_note"), "Did the goods go back to the supplier?");
});

test("a purchase debit note is never asked whether its goods 'came back'", () => {
  assert.doesNotMatch(goodsReturnedQuestion("debit_note"), /come back|came back/);
});

test("the stored answer in words keeps its three states apart", () => {
  assert.equal(goodsReturnedWords(true), "Yes");
  assert.match(goodsReturnedWords(false), /^No \(/);
  assert.equal(goodsReturnedWords(null), "Not stated");
  assert.equal(goodsReturnedWords(undefined), "Not stated");
});
