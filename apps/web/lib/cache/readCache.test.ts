import { test } from "node:test";
import assert from "node:assert/strict";
import { bindReadCacheToUser, forgetReads, peekRead, readKey, readStale } from "./readCache.ts";

const never = () => assert.fail("no stale answer was expected");

test("the first read has nothing to paint, a second paints the first's answer at once and still reads again", async () => {
  forgetReads();
  let calls = 0;
  const fetcher = async () => ++calls;
  assert.equal(await readStale("fam|a", fetcher, never), 1);
  let painted: number | undefined;
  const slow = () => new Promise<number>((r) => setTimeout(() => r(++calls), 30));
  const real = readStale("fam|a", slow, (d) => { painted = d; });
  assert.equal(painted, 1, "the last answer is painted synchronously, before the real read lands");
  assert.equal(await real, 2, "the real read always runs and is what is returned");
  assert.equal(peekRead("fam|a")?.data, 2, "the real answer replaces the stale one");
});

test("a write's forget clears the family and not another", async () => {
  forgetReads();
  await readStale(readKey(["clients", "active"]), async () => "c", never);
  await readStale(readKey(["clients", "all"]), async () => "c2", never);
  await readStale(readKey(["other", "x"]), async () => "o", never);
  forgetReads("clients");
  assert.equal(peekRead("clients|active"), undefined);
  assert.equal(peekRead("clients|all"), undefined);
  assert.equal(peekRead("other|x")?.data, "o");
});

test("an answer that was in flight when its key was cleared is not stored over the clear", async () => {
  forgetReads();
  const out = readStale("clients|active", () => new Promise<string>((r) => setTimeout(() => r("old"), 20)), never);
  forgetReads("clients");
  assert.equal(await out, "old");
  assert.equal(peekRead("clients|active"), undefined, "a read that began before a write must not be what the next paint shows");
});

test("a different person, or nobody, empties the cache; the same person does not", async () => {
  forgetReads();
  bindReadCacheToUser("u1");
  await readStale("clients|active", async () => "list", never);
  bindReadCacheToUser("u1");
  assert.equal(peekRead("clients|active")?.data, "list");
  bindReadCacheToUser("u2");
  assert.equal(peekRead("clients|active"), undefined);
  await readStale("clients|active", async () => "list2", never);
  bindReadCacheToUser(null);
  assert.equal(peekRead("clients|active"), undefined);
});

test("two callers for one key share one request", async () => {
  forgetReads();
  let calls = 0;
  const f = () => new Promise<number>((r) => setTimeout(() => r(++calls), 10));
  const [a, b] = await Promise.all([readStale("k|1", f), readStale("k|1", f)]);
  assert.equal(calls, 1);
  assert.equal(a, b);
});

test("a failed real read rejects and leaves the stale answer in place", async () => {
  forgetReads();
  await readStale("clients|all", async () => "kept", never);
  await assert.rejects(readStale("clients|all", async () => { throw new Error("down"); }, () => {}), /down/);
  assert.equal(peekRead("clients|all")?.data, "kept");
});
