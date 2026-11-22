// Run with:
//   node --experimental-strip-types --test lib/ui/rowMenuKeys.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { nextActionIndex } from "./rowMenuKeys.ts";

test("ArrowDown and ArrowUp move by one and wrap round", () => {
  assert.equal(nextActionIndex("ArrowDown", 0, 4), 1);
  assert.equal(nextActionIndex("ArrowDown", 3, 4), 0);
  assert.equal(nextActionIndex("ArrowUp", 2, 4), 1);
  assert.equal(nextActionIndex("ArrowUp", 0, 4), 3);
});

test("Home and End go to the ends, wherever focus is", () => {
  for (const at of [-1, 0, 2, 3]) {
    assert.equal(nextActionIndex("Home", at, 4), 0);
    assert.equal(nextActionIndex("End", at, 4), 3);
  }
});

test("with focus on the menu itself and on no action, ArrowDown takes the first and ArrowUp the last", () => {
  assert.equal(nextActionIndex("ArrowDown", -1, 4), 0);
  assert.equal(nextActionIndex("ArrowUp", -1, 4), 3);
});

test("a menu of one action stays on it", () => {
  assert.equal(nextActionIndex("ArrowDown", 0, 1), 0);
  assert.equal(nextActionIndex("ArrowUp", 0, 1), 0);
});

test("any other key, and a menu with no action, are not the menu's to answer", () => {
  for (const key of ["Enter", " ", "Tab", "Escape", "a", "ArrowLeft", "ArrowRight", "PageDown"]) assert.equal(nextActionIndex(key, 1, 4), null, key);
  for (const key of ["ArrowDown", "ArrowUp", "Home", "End"]) assert.equal(nextActionIndex(key, -1, 0), null, key);
});
