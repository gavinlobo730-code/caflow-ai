// What a person is told while a server that may be asleep answers (frontend_ux-05). Run with:
//   node --experimental-strip-types --test lib/async/slowServer.test.ts
//
// The watch is plain TypeScript with an injectable clock, so every rule is driven here with a fake one stepped
// by hand — no real waiting, no DOM.
import test from "node:test";
import assert from "node:assert/strict";
import {
  RETRY_OFFERED_AFTER_MS, WAKING_NOTICE_AFTER_MS, WAKING_SENTENCE, createSlowWatch, phaseAfter,
  type SlowPhase, type Timers,
} from "./slowServer.ts";

/** A clock that only moves when told to, and fires what has come due in order. */
function fakeClock() {
  let now = 0;
  let nextId = 1;
  const queue = new Map<number, { at: number; fn: () => void }>();
  const timers: Timers = {
    set(fn, ms) { const id = nextId++; queue.set(id, { at: now + ms, fn }); return id; },
    clear(handle) { queue.delete(handle as number); },
  };
  return {
    timers,
    pending: () => queue.size,
    advance(ms: number) {
      const target = now + ms;
      for (;;) {
        const due = [...queue.entries()].filter(([, t]) => t.at <= target).sort((a, b) => a[1].at - b[1].at)[0];
        if (!due) break;
        now = due[1].at;
        queue.delete(due[0]);
        due[1].fn();
      }
      now = target;
    },
  };
}

function region(watch: ReturnType<typeof createSlowWatch>, canRetry = false) {
  const seen: SlowPhase[] = [];
  const handle = watch.start((p) => seen.push(p), { canRetry });
  return { seen, handle, last: () => seen[seen.length - 1] ?? "quiet" };
}

test("the thresholds and the sentence are the audit's, exactly", () => {
  assert.equal(WAKING_NOTICE_AFTER_MS, 3_000);
  assert.equal(RETRY_OFFERED_AFTER_MS, 20_000);
  assert.equal(WAKING_SENTENCE, "The server is waking up. The first screen of the day can take up to a minute.");
});

test("phaseAfter is quiet below three seconds, waking to twenty, stalled from there", () => {
  assert.equal(phaseAfter(0), "quiet");
  assert.equal(phaseAfter(2_999), "quiet");
  assert.equal(phaseAfter(3_000), "waking");
  assert.equal(phaseAfter(19_999), "waking");
  assert.equal(phaseAfter(20_000), "stalled");
  assert.equal(phaseAfter(60_000), "stalled");
  for (const odd of [-1, Number.NaN, Number.POSITIVE_INFINITY]) assert.equal(phaseAfter(odd), "quiet", `${odd} is not a wait`);
});

test("a region says nothing for three seconds, then one sentence, then a retry offer — each once", () => {
  const clock = fakeClock();
  const r = region(createSlowWatch(clock.timers));
  clock.advance(2_999);
  assert.deepEqual(r.seen, [], "a warm server answers in this time and nobody should be told anything");
  clock.advance(1);
  assert.deepEqual(r.seen, ["waking"]);
  clock.advance(16_999);
  assert.deepEqual(r.seen, ["waking"], "the sentence is not rewritten while it waits");
  clock.advance(1);
  assert.deepEqual(r.seen, ["waking", "stalled"]);
  clock.advance(120_000);
  assert.deepEqual(r.seen, ["waking", "stalled"], "nothing repeats");
});

test("a region that finishes before three seconds is never told anything and leaves no timer behind", () => {
  const clock = fakeClock();
  const watch = createSlowWatch(clock.timers);
  const r = region(watch);
  clock.advance(1_200);
  r.handle.stop();
  assert.equal(watch.pendingCount(), 0);
  assert.equal(clock.pending(), 0, "a stopped region cancels both its timers");
  clock.advance(60_000);
  assert.deepEqual(r.seen, []);
});

test("nothing is said to a region after it stops", () => {
  const clock = fakeClock();
  const r = region(createSlowWatch(clock.timers));
  clock.advance(5_000);
  assert.deepEqual(r.seen, ["waking"]);
  r.handle.stop();
  clock.advance(60_000);
  assert.deepEqual(r.seen, ["waking"], "the data arrived: the stale 20-second timer must not fire into a gone region");
  r.handle.stop(); // stopping twice is harmless
});

test("ONE notice at a time: of two waiting regions the one further along speaks", () => {
  const clock = fakeClock();
  const watch = createSlowWatch(clock.timers);
  const first = region(watch);
  clock.advance(10_000);
  const second = region(watch);
  assert.equal(first.last(), "waking");
  clock.advance(3_000); // first: 13 s, second: 3 s — both have something to say
  assert.equal(first.last(), "waking");
  assert.equal(second.last(), "quiet", "the second region must not repeat the first's sentence");
  clock.advance(7_000); // first reaches 20 s
  assert.equal(first.last(), "stalled");
  assert.equal(second.last(), "quiet");
});

test("a region keeps its OWN clock: the next one is quiet for its own three seconds", () => {
  const clock = fakeClock();
  const watch = createSlowWatch(clock.timers);
  const first = region(watch);
  clock.advance(25_000);
  assert.equal(first.last(), "stalled");
  const second = region(watch);
  assert.equal(second.last(), "quiet", "a region that started a moment ago has not been waiting twenty seconds");
  first.handle.stop();
  assert.equal(second.last(), "quiet", "and the first leaving does not make it speak early");
  clock.advance(3_000);
  assert.equal(second.last(), "waking");
});

test("when the speaker leaves, the next one that has something to say takes over at once", () => {
  const clock = fakeClock();
  const watch = createSlowWatch(clock.timers);
  const first = region(watch);
  clock.advance(1_000);
  const second = region(watch);
  clock.advance(5_000); // first 6 s, second 5 s: both waking, the older speaks
  assert.equal(first.last(), "waking");
  assert.equal(second.last(), "quiet");
  first.handle.stop();
  assert.equal(second.last(), "waking", "the screen still has something pending and still says so");
});

test("of two equally far along, the one that can offer a retry speaks", () => {
  const clock = fakeClock();
  const watch = createSlowWatch(clock.timers);
  const skeleton = region(watch, false);
  const table = region(watch, true);
  clock.advance(20_000);
  assert.equal(table.last(), "stalled");
  assert.equal(skeleton.last(), "quiet", "a notice with a Retry is worth more than one without");
});

test("with nothing else to separate them the older region speaks", () => {
  const clock = fakeClock();
  const watch = createSlowWatch(clock.timers);
  const a = region(watch);
  const b = region(watch);
  clock.advance(3_000);
  assert.equal(a.last(), "waking");
  assert.equal(b.last(), "quiet");
});

test("a retry that restarts a region (stop then start) puts it back to quiet and starts its clock again", () => {
  const clock = fakeClock();
  const watch = createSlowWatch(clock.timers);
  const first = region(watch, true);
  clock.advance(21_000);
  assert.equal(first.last(), "stalled");
  first.handle.stop();
  const again = region(watch, true);
  assert.equal(again.last(), "quiet");
  clock.advance(19_999);
  assert.equal(again.last(), "waking", "the offer comes twenty seconds after the NEW request, not the first");
  clock.advance(1);
  assert.equal(again.last(), "stalled");
});
