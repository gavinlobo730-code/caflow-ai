// Tests for selectAll() paging past PostgREST's row cap. Run with:
//   node --experimental-strip-types --test lib/supabase/selectAll.test.ts
// selectAll.ts has only a type-import, so it strips to dependency-free JS.
import test from "node:test";
import assert from "node:assert/strict";
import { selectAll } from "./selectAll.ts";

/**
 * Build a fake Rangeable over a backing array that honours `.range(from,to)`
 * inclusively, exactly like PostgREST. Records every requested range so tests
 * can assert the paging behaviour.
 */
function fakeTable<T>(rows: T[], calls: Array<[number, number]> = []) {
  return () => ({
    range: (from: number, to: number) => {
      calls.push([from, to]);
      return Promise.resolve({ data: rows.slice(from, to + 1), error: null });
    },
  });
}

test("returns everything in a single page when under the page size", async () => {
  const calls: Array<[number, number]> = [];
  const { data, error } = await selectAll(fakeTable([1, 2, 3], calls), 1000);
  assert.equal(error, null);
  assert.deepEqual(data, [1, 2, 3]);
  assert.equal(calls.length, 1); // one request, no needless second page
  assert.deepEqual(calls[0], [0, 999]);
});

test("pages past the cap and concatenates in order", async () => {
  const rows = Array.from({ length: 2500 }, (_, i) => i); // > 2 full pages
  const calls: Array<[number, number]> = [];
  const { data, error } = await selectAll(fakeTable(rows, calls), 1000);
  assert.equal(error, null);
  assert.equal(data.length, 2500);
  assert.deepEqual(data, rows); // order preserved across pages
  assert.equal(calls.length, 3); // 1000 + 1000 + 500(short → stop)
  assert.deepEqual(calls, [[0, 999], [1000, 1999], [2000, 2999]]);
});

test("fetches an extra empty page when total is an exact multiple of pageSize", async () => {
  const rows = Array.from({ length: 4 }, (_, i) => i);
  const calls: Array<[number, number]> = [];
  const { data } = await selectAll(fakeTable(rows, calls), 2);
  assert.deepEqual(data, [0, 1, 2, 3]);
  // 2 full pages look full, so a 3rd (empty) page is needed to confirm the end.
  assert.deepEqual(calls, [[0, 1], [2, 3], [4, 5]]);
});

test("empty table returns [] after one request", async () => {
  const calls: Array<[number, number]> = [];
  const { data, error } = await selectAll(fakeTable([], calls), 1000);
  assert.equal(error, null);
  assert.deepEqual(data, []);
  assert.equal(calls.length, 1);
});

test("propagates an error and returns rows gathered so far, stopping immediately", async () => {
  let page = 0;
  const err = { message: "boom", details: "", hint: "", code: "500" };
  const { data, error } = await selectAll<number>(() => ({
    range: (from: number, to: number) => {
      page++;
      if (page === 2) return Promise.resolve({ data: null, error: err });
      return Promise.resolve({ data: Array.from({ length: to - from + 1 }, (_, i) => from + i), error: null });
    },
  }), 1000);
  assert.deepEqual(error, err);
  assert.equal(data.length, 1000); // first full page kept; stopped on the failing second
  assert.equal(page, 2); // did not keep paging after the error
});

test("treats null data as an empty page (no crash)", async () => {
  const { data, error } = await selectAll<number>(() => ({
    range: () => Promise.resolve({ data: null, error: null }),
  }), 1000);
  assert.equal(error, null);
  assert.deepEqual(data, []);
});
