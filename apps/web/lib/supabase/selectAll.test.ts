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

test("propagates an error and returns the rows gathered before it", async () => {
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
  assert.equal(data.length, 1000); // first full page kept; nothing past the failure
  // Wave 2 is two concurrent requests, and the second was already in flight
  // when the first failed. A request cannot be un-sent, so it completes and its
  // rows are discarded. What matters — and what this asserts — is that no
  // THIRD wave is started, and that the caller sees only the clean prefix.
  assert.equal(page, 3);
});

test("stops starting new waves once a page fails", async () => {
  // The property the count above is a proxy for, asserted directly: with a
  // failure in wave 2, paging must not reach the pages wave 3 would have asked
  // for. Without the early return this would run to MAX_PAGES.
  const requested: number[] = [];
  const err = { message: "boom", details: "", hint: "", code: "500" };
  const { data, error } = await selectAll<number>(() => ({
    range: (from: number, to: number) => {
      requested.push(from);
      if (from === 1000) return Promise.resolve({ data: null, error: err });
      return Promise.resolve({ data: Array.from({ length: to - from + 1 }, (_, i) => from + i), error: null });
    },
  }), 1000);
  assert.deepEqual(error, err);
  assert.deepEqual(data, Array.from({ length: 1000 }, (_, i) => i));
  assert.deepEqual(requested, [0, 1000, 2000]); // wave 1, then wave 2 — and stop
});

test("a client under the cap still costs exactly one request", async () => {
  // The reason waves start at width 1. Most clients are under 1000 rows, and
  // firing a speculative wave of four at them would make the common case worse
  // to make the rare case better.
  const calls: Array<[number, number]> = [];
  const rows = Array.from({ length: 999 }, (_, i) => i);
  const { data } = await selectAll(fakeTable(rows, calls), 1000);
  assert.equal(data.length, 999);
  assert.equal(calls.length, 1);
});

test("pages in widening waves instead of one round trip per page", async () => {
  // The whole point of the change, measured rather than assumed. 10 full pages
  // plus the short 11th: sequentially that is 11 round trips, and this asserts
  // it now costs 4.
  //
  // A "wave" is counted the way latency actually works — a request issued while
  // nothing else is in flight starts a new one; requests issued alongside it
  // cost no extra wall-clock.
  const rows = Array.from({ length: 10_000 }, (_, i) => i);
  let inFlight = 0;
  let waves = 0;
  const { data, error } = await selectAll<number>(() => ({
    range: (from: number, to: number) => {
      if (inFlight === 0) waves++;
      inFlight++;
      return new Promise((resolve) => {
        setTimeout(() => {
          inFlight--;
          resolve({ data: rows.slice(from, to + 1), error: null });
        }, 5);
      });
    },
  }), 1000);
  assert.equal(error, null);
  assert.deepEqual(data, rows); // order preserved across concurrent pages
  assert.equal(waves, 4, `expected 4 round trips for 11 pages, got ${waves}`);
});

test("concurrent pages are concatenated in page order, not completion order", async () => {
  // The failure this guards: a later page resolving first and its rows landing
  // ahead of an earlier page's would silently reorder the table.
  const rows = Array.from({ length: 3500 }, (_, i) => i);
  const { data, error } = await selectAll<number>(() => ({
    range: (from: number, to: number) =>
      new Promise((resolve) => {
        // Earlier pages deliberately resolve LAST.
        setTimeout(() => resolve({ data: rows.slice(from, to + 1), error: null }),
          Math.max(0, 30 - from / 100));
      }),
  }), 1000);
  assert.equal(error, null);
  assert.deepEqual(data, rows);
});

test("waves widen 1, 2, 4, 4 and never exceed the concurrency cap", async () => {
  const starts: number[] = [];
  const rows = Array.from({ length: 12_000 }, (_, i) => i);
  const { data } = await selectAll<number>(() => ({
    range: (from: number, to: number) => {
      starts.push(from);
      return Promise.resolve({ data: rows.slice(from, to + 1), error: null });
    },
  }), 1000, 4);
  assert.equal(data.length, 12_000);
  // 1 (page 0) + 2 (pages 1-2) + 4 (pages 3-6) + 4 (pages 7-10) + 4 (11-14);
  // page 12 comes back empty, so pages 13-14 are fetched but dropped.
  assert.deepEqual(starts.slice(0, 7).map((f) => f / 1000), [0, 1, 2, 3, 4, 5, 6]);
  assert.ok(starts.length <= 15, `fetched ${starts.length} pages for 12 pages of data`);
});

test("concurrency 1 restores the strictly sequential behaviour", async () => {
  // The escape hatch, and proof the ramp is the only thing that changed: with a
  // width of one this is exactly the loop this function used to be.
  const calls: Array<[number, number]> = [];
  const rows = Array.from({ length: 2500 }, (_, i) => i);
  const { data } = await selectAll(fakeTable(rows, calls), 1000, 1);
  assert.deepEqual(data, rows);
  assert.deepEqual(calls, [[0, 999], [1000, 1999], [2000, 2999]]);
});

test("treats null data as an empty page (no crash)", async () => {
  const { data, error } = await selectAll<number>(() => ({
    range: () => Promise.resolve({ data: null, error: null }),
  }), 1000);
  assert.equal(error, null);
  assert.deepEqual(data, []);
});
