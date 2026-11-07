import { test } from "node:test";
import assert from "node:assert/strict";
import { itemsKey, namesGoodsFrom } from "./namesGoods.ts";

// POST-A-378. The pure decisions behind the "did the goods come back?" lookup of the two drawer modals (`useNamesGoods`).

test("the same set of items is the same question whichever way the lines list it", () => {
  assert.equal(itemsKey(["b", "a", "b", null, undefined, ""]), "a,b");
  assert.equal(itemsKey(["a", "b"]), itemsKey(["b", "a", "a"]));
});

test("no item is no question", () => {
  assert.equal(itemsKey([]), "");
  assert.equal(itemsKey([null, undefined, ""]), "");
});

test("a set that holds a good names goods, a set of services does not", () => {
  assert.equal(namesGoodsFrom({ data: [{ kind: "service" }, { kind: "good" }], error: null }), true);
  assert.equal(namesGoodsFrom({ data: [{ kind: "service" }], error: null }), false);
});

test("a read that failed is not an answer: it is not 'a good', whatever it carries", () => {
  assert.equal(namesGoodsFrom({ data: [{ kind: "good" }], error: { message: "no answer" } }), false);
  assert.equal(namesGoodsFrom({ data: null, error: { message: "refused" } }), false);
});

test("a read that found nothing, or nothing it could name, is not 'a good'", () => {
  assert.equal(namesGoodsFrom({ data: [], error: null }), false);
  assert.equal(namesGoodsFrom({ data: null, error: null }), false);
  assert.equal(namesGoodsFrom({ data: undefined }), false);
  assert.equal(namesGoodsFrom({ data: [{}, { kind: null }], error: null }), false);
});
