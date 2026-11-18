import { test } from "node:test";
import assert from "node:assert/strict";
import { recentFirst } from "./recentParties.ts";

test("the server's order is kept, and an id the list does not hold is left out rather than invented", () => {
  const list = [{ id: "a", name: "A" }, { id: "b", name: "B" }, { id: "c", name: "C" }];
  assert.deepEqual(recentFirst(["c", "x", "a"], list).map((p) => p.id), ["c", "a"]);
  assert.deepEqual(recentFirst([], list), []);
  assert.deepEqual(recentFirst(["a"], []), []);
});

test("an account with no id (a screen that keys by code) is never put at the top, and accounts are ordered like parties", () => {
  const accounts = [{ id: "a1", account_name: "Rent" }, { id: null, account_code: "4000" }, { id: "a2", account_name: "Power" }];
  assert.deepEqual(recentFirst(["a2", "a1"], accounts).map((a) => a.id), ["a2", "a1"]);
  assert.deepEqual(recentFirst([""], accounts), []);
});
