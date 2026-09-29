/**
 * Two near-simultaneous callers for the same report key used to issue two
 * backend requests (apex-accounting-reports-12): `cachedReport` only cached
 * the SETTLED value, so a second caller arriving while the first fetch was
 * still outstanding missed the (not-yet-populated) cache and started its own
 * fetch. `cachedReport` now also caches the in-flight PROMISE, so the second
 * caller awaits the first one's request instead.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { cachedReport, clearReports } from "./reportCache.ts";

test("two concurrent callers for the same key share one fetch", async () => {
  const key = "single-flight-test-" + Math.random();
  let calls = 0;
  const fetcher = () => {
    calls++;
    return new Promise<string>((resolve) => setTimeout(() => resolve("data-" + calls), 10));
  };

  const [a, b] = await Promise.all([
    cachedReport(key, fetcher),
    cachedReport(key, fetcher),
  ]);

  assert.equal(calls, 1, "two concurrent callers for the same key must share one fetch");
  assert.equal(a, "data-1");
  assert.equal(b, "data-1", "the second caller must resolve to the SAME value as the first");
  clearReports();
});

test("a caller after the fetch has settled gets the fresh cached value, not a new fetch", async () => {
  const key = "single-flight-settled-" + Math.random();
  let calls = 0;
  const fetcher = () => { calls++; return Promise.resolve("data-" + calls); };

  await cachedReport(key, fetcher);
  const second = await cachedReport(key, fetcher);

  assert.equal(calls, 1, "a second call after the first has resolved should read the settled cache, not refetch");
  assert.equal(second, "data-1");
  clearReports();
});

test("a failed in-flight fetch does not wedge later callers", async () => {
  const key = "single-flight-failure-" + Math.random();
  let calls = 0;
  const failingFetcher = () => { calls++; return Promise.reject(new Error("boom")); };
  const okFetcher = () => { calls++; return Promise.resolve("recovered"); };

  await assert.rejects(() => cachedReport(key, failingFetcher));
  const after = await cachedReport(key, okFetcher);

  assert.equal(calls, 2, "a rejected fetch must be removed from the in-flight map so the next caller can retry");
  assert.equal(after, "recovered");
  clearReports();
});

test("three concurrent callers for DIFFERENT keys each get their own fetch", async () => {
  const prefix = "single-flight-distinct-" + Math.random() + "-";
  let calls = 0;
  const fetcher = () => { calls++; return Promise.resolve(calls); };

  await Promise.all([
    cachedReport(prefix + "a", fetcher),
    cachedReport(prefix + "b", fetcher),
    cachedReport(prefix + "c", fetcher),
  ]);

  assert.equal(calls, 3, "distinct keys must never share a single-flight promise");
  clearReports();
});
