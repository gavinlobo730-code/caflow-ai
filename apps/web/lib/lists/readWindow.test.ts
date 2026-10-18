// POST-A-259. `readWindow` reads a list the server answered as a window ({ <rows>, has_more, limit, max_limit }).
//   node --experimental-strip-types --test lib/lists/readWindow.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { readWindow } from "./readWindow.ts";

test("a window carries its rows, the server's has_more and its limits", () => {
  const w = readWindow<{ id: string }>({ entities: [{ id: "a" }, { id: "b" }], has_more: true, limit: 100, max_limit: 2000 }, "entities", 50);
  assert.deepEqual(w, { rows: [{ id: "a" }, { id: "b" }], hasMore: true, limit: 100, maxLimit: 2000 });
});

test("more exist only when the server said exactly true", () => {
  for (const v of [false, undefined, null, "true", 1, "yes"]) {
    const w = readWindow({ entities: [], has_more: v, limit: 10, max_limit: 20 }, "entities", 10);
    assert.equal(w?.hasMore, false, `has_more ${String(v)} must not claim more`);
  }
});

test("a count that equals the limit is not a claim: only the server's answer is", () => {
  const rows = Array.from({ length: 100 }, (_, i) => ({ id: String(i) }));
  assert.equal(readWindow({ entities: rows, has_more: false, limit: 100, max_limit: 2000 }, "entities", 100)?.hasMore, false);
  assert.equal(readWindow({ entities: rows.slice(0, 3), has_more: true, limit: 100, max_limit: 2000 }, "entities", 100)?.hasMore, true);
});

test("a rows field that is not a list is read as no rows, never as a thing to map over", () => {
  assert.deepEqual(readWindow({ entities: null, limit: 5, max_limit: 9 }, "entities", 5)?.rows, []);
  assert.deepEqual(readWindow({ entities: "oops", limit: 5, max_limit: 9 }, "entities", 5)?.rows, []);
});

test("limits fall back to what was asked when the server did not echo numbers", () => {
  const w = readWindow({ entities: [], limit: "x", max_limit: Number.NaN }, "entities", 40);
  assert.equal(w?.limit, 40);
  assert.equal(w?.maxLimit, 40);
});

test("a refusal, a scalar or an object without the rows field is not a window", () => {
  assert.equal(readWindow(null, "entities", 10), null);
  assert.equal(readWindow(undefined, "entities", 10), null);
  assert.equal(readWindow("error", "entities", 10), null);
  assert.equal(readWindow({ leads: [] }, "entities", 10), null);
});

test("a bare list, from a server that predates the window, is read as complete", () => {
  const w = readWindow([{ id: "a" }], "entities", 100);
  assert.deepEqual(w, { rows: [{ id: "a" }], hasMore: false, limit: 100, maxLimit: 100 });
});
