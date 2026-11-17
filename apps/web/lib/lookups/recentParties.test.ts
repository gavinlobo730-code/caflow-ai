import { test } from "node:test";
import assert from "node:assert/strict";
import { recentFirst } from "./recentParties.ts";

test("the server's order is kept, and an id the list does not hold is left out rather than invented", () => {
  const list = [{ id: "a", name: "A" }, { id: "b", name: "B" }, { id: "c", name: "C" }];
  assert.deepEqual(recentFirst(["c", "x", "a"], list).map((p) => p.id), ["c", "a"]);
  assert.deepEqual(recentFirst([], list), []);
  assert.deepEqual(recentFirst(["a"], []), []);
});
