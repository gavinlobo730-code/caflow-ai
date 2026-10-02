// The repeat-click guard under it all (frontend_ux-09). Run with:
//   node --experimental-strip-types --test lib/async/singleFlight.test.ts
//
// What is held here is the RULE, not a spelling: a call while another is
// unresolved is ignored (not queued), the guard is released when the promise
// settles either way, and a rejection is not swallowed on the way through.
import test from "node:test";
import assert from "node:assert/strict";
import { createSingleFlight } from "./singleFlight.ts";

/** A promise a test settles by hand. */
function deferred<T = void>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}
const tick = () => new Promise<void>((r) => setImmediate(r));

test("a second call on the same tick is ignored — the handler is not even called", () => {
  const flight = createSingleFlight();
  let calls = 0;
  const d = deferred();
  const first = flight.run(() => { calls++; return d.promise; });
  // No await between the two: this is the double-click, and no render has
  // happened in between to flip any React state.
  const second = flight.run(() => { calls++; return d.promise; });
  assert.equal(first.started, true);
  assert.equal(second.started, false);
  assert.equal(calls, 1, "ignored means the handler never ran, not that it ran and was discarded");
  assert.equal(flight.busy(), true, "busy() is a synchronous read — it is what a handler asks");
  d.resolve();
});

test("an ignored call is NOT queued: once the first settles, nothing runs on its behalf", async () => {
  const flight = createSingleFlight();
  let calls = 0;
  const d = deferred();
  flight.run(() => { calls++; return d.promise; });
  flight.run(() => { calls++; return Promise.resolve(); });
  flight.run(() => { calls++; return Promise.resolve(); });
  d.resolve();
  await tick();
  assert.equal(calls, 1, "a queued second Post would write the same voucher after the first");
});

test("the guard is released when the promise RESOLVES", async () => {
  const flight = createSingleFlight();
  const d = deferred<string>();
  const r = flight.run(() => d.promise);
  assert.equal(r.started, true);
  d.resolve("ok");
  assert.equal(await (r as { result: Promise<string> }).result, "ok", "the value passes through");
  assert.equal(flight.busy(), false);
  assert.equal(flight.run(() => "again").started, true);
});

test("the guard is released when the promise REJECTS, so a failed save can be retried", async () => {
  const flight = createSingleFlight();
  const d = deferred();
  const r = flight.run(() => d.promise);
  d.reject(new Error("server refused"));
  await assert.rejects(() => (r as { result: Promise<void> }).result, /server refused/);
  assert.equal(flight.busy(), false, "an error must not leave the button dead");
  assert.equal(flight.getState().busy, false);
  assert.equal(flight.run(() => Promise.resolve()).started, true);
});

test("a rejection is not swallowed: the caller still gets it", async () => {
  // Releasing the guard by attaching a handler to the handler's promise would
  // mark it as handled and silence an unhandled rejection that a raw async
  // onClick always raised. `result` is the outcome, rejection included.
  const flight = createSingleFlight();
  const r = flight.run(async () => { throw new Error("boom"); });
  assert.equal(r.started, true);
  await assert.rejects(() => (r as { result: Promise<never> }).result, /boom/);
});

test("a handler that THROWS before returning a promise releases the guard", () => {
  const flight = createSingleFlight();
  assert.throws(() => flight.run(() => { throw new Error("sync boom"); }), /sync boom/);
  assert.equal(flight.busy(), false, "or the button would be dead until the page reloads");
  assert.equal(flight.run(() => 1).started, true);
});

test("a handler that returns a plain value is not an async action and is never held", () => {
  const flight = createSingleFlight();
  let calls = 0;
  assert.equal(flight.run(() => { calls++; }).started, true);
  assert.equal(flight.busy(), false);
  assert.equal(flight.run(() => { calls++; }).started, true);
  assert.equal(calls, 2, "two ordinary synchronous clicks both run");
});

test("a handler that DROPS its promise is not held either — which is why the conversion guard exists", () => {
  // `() => { save(); }` returns undefined. The flight sees a synchronous handler
  // and releases at once; the second click goes through. The screen has to
  // return the promise (`() => save()`), and a source guard asserts it does.
  const flight = createSingleFlight();
  let saves = 0;
  const save = () => { saves++; return new Promise<void>(() => {}); };
  flight.run(() => { save(); });
  flight.run(() => { save(); });
  assert.equal(saves, 2);
});

test("one flight guards several controls: a click on a sibling while one is working is ignored", () => {
  const flight = createSingleFlight();
  const d = deferred();
  const draft = flight.run(() => d.promise, "draft");
  const post = flight.run(() => d.promise, "post");
  assert.equal(draft.started, true);
  assert.equal(post.started, false, "Save Draft and Post Entry are two controls over one action");
  assert.equal(flight.getState().owner, "draft", "only the control that was pressed is the one working");
  d.resolve();
});

test("state is the SAME object until it changes, and subscribers hear busy then idle", async () => {
  const flight = createSingleFlight();
  const seen: Array<{ busy: boolean; owner: string | null }> = [];
  const unsubscribe = flight.subscribe(() => seen.push({ ...flight.getState() }));
  const idle = flight.getState();
  assert.equal(flight.getState(), idle, "a stable snapshot is what useSyncExternalStore needs");

  const d = deferred();
  flight.run(() => d.promise, "a");
  assert.notEqual(flight.getState(), idle);
  d.resolve();
  await tick();
  assert.deepEqual(seen, [{ busy: true, owner: "a" }, { busy: false, owner: null }]);

  unsubscribe();
  flight.run(() => Promise.resolve());
  await tick();
  assert.equal(seen.length, 2, "an unsubscribed listener hears nothing more");
});

test("a synchronous run announces nothing", () => {
  const flight = createSingleFlight();
  let heard = 0;
  flight.subscribe(() => { heard++; });
  flight.run(() => 1);
  assert.equal(heard, 0, "no re-render for a click that held nothing");
});

test("a listener that unsubscribes while being notified does not break the others", async () => {
  const flight = createSingleFlight();
  const calls: string[] = [];
  const stopA = flight.subscribe(() => { calls.push("a"); stopA(); });
  flight.subscribe(() => { calls.push("b"); });
  const d = deferred();
  flight.run(() => d.promise);
  d.resolve();
  await tick();
  assert.deepEqual(calls, ["a", "b", "b"]);
});
