// Keeping the API awake while somebody looks at the product (frontend_ux-05). Run with:
//   node --experimental-strip-types --test lib/api/keepAwake.test.ts
//
// Everything the browser provides is passed in, so the rules are driven here with a fake clock, a fake tab
// that can be shown and hidden, and a fake store — no timers, no network, no DOM.
import test from "node:test";
import assert from "node:assert/strict";
import {
  FRESH_SHARE, KEEP_AWAKE_INTERVAL_MS, LAST_PING_KEY, createKeepAwake, healthUrl, type KeepAwakeDeps,
} from "./keepAwake.ts";

const TEN_MINUTES = 10 * 60 * 1000;

function rig(over: Partial<KeepAwakeDeps> = {}) {
  let now = 1_000_000;
  let visible = true;
  let listener: (() => void) | null = null;
  let timer: { fn: () => void; ms: number } | null = null;
  const calls: { url: string; init: RequestInit }[] = [];
  let stored: number | null = null;
  const deps: KeepAwakeDeps = {
    apiBase: "https://api.example.test",
    fetch: (url, init) => { calls.push({ url, init }); return Promise.resolve({ ok: true }); },
    now: () => now,
    isVisible: () => visible,
    onVisibilityChange: (l) => { listener = l; return () => { listener = null; }; },
    setInterval: (fn, ms) => { timer = { fn, ms }; return timer; },
    clearInterval: (h) => { if (timer === h) timer = null; },
    store: { get: () => stored, set: (at) => { stored = at; } },
    ...over,
  };
  const awake = createKeepAwake(deps);
  return {
    awake, calls,
    timer: () => timer,
    listening: () => listener !== null,
    now: () => now,
    advance(ms: number) { now += ms; },
    /** The interval fires after `ms` has passed. */
    tick(ms = TEN_MINUTES) { now += ms; timer?.fn(); },
    show() { visible = true; listener?.(); },
    hide() { visible = false; listener?.(); },
    setStored(at: number | null) { stored = at; },
    stored: () => stored,
  };
}

test("the interval is ten minutes and a ping skips when another is younger than 90% of one", () => {
  assert.equal(KEEP_AWAKE_INTERVAL_MS, TEN_MINUTES);
  assert.equal(FRESH_SHARE, 0.9);
  assert.equal(LAST_PING_KEY, "practicesync.keep-awake.last-ping");
});

test("the URL is the base plus /health, and nothing when there is no base", () => {
  assert.equal(healthUrl("https://api.example.test"), "https://api.example.test/health");
  assert.equal(healthUrl("https://api.example.test///"), "https://api.example.test/health");
  assert.equal(healthUrl(""), null);
  assert.equal(healthUrl("   "), null);
  assert.equal(healthUrl(undefined), null);
});

test("warmUp is one GET to /health carrying no credential, header or body", () => {
  const r = rig();
  r.awake.warmUp();
  assert.equal(r.calls.length, 1);
  const { url, init } = r.calls[0];
  assert.equal(url, "https://api.example.test/health");
  assert.equal(init.method, "GET");
  assert.equal(init.credentials, "omit", "a knock on the door must never carry cookies");
  assert.equal(init.headers, undefined, "no Authorization, no identifier");
  assert.equal(init.body, undefined);
  assert.deepEqual(Object.keys(init).sort(), ["cache", "credentials", "method", "mode"], "nothing else is sent");
});

test("warmUp pings whatever the tab is doing, because it runs before anyone has signed in", () => {
  const r = rig();
  r.hide();
  r.awake.warmUp();
  assert.equal(r.calls.length, 1);
});

test("with no API base nothing is ever called", () => {
  const r = rig({ apiBase: "" });
  r.awake.warmUp();
  r.awake.start();
  r.tick();
  assert.equal(r.calls.length, 0);
});

test("start pings nothing at once and then every ten minutes while the tab is visible", () => {
  const r = rig();
  r.awake.start();
  assert.equal(r.calls.length, 0, "the warm-up already ran; start is the REPEAT");
  assert.equal(r.timer()?.ms, TEN_MINUTES);
  r.tick();
  assert.equal(r.calls.length, 1);
  r.tick();
  assert.equal(r.calls.length, 2);
});

test("starting twice is one timer and one listener", () => {
  const r = rig();
  r.awake.start();
  const first = r.timer();
  r.awake.start();
  assert.equal(r.timer(), first, "a second start must not arm a second timer");
  assert.equal(r.awake.isRunning(), true);
});

test("a hidden tab pings nothing and its timer is cleared; showing it again wakes the server if it has been quiet", () => {
  const r = rig();
  r.awake.start();
  r.tick();
  assert.equal(r.calls.length, 1);
  r.hide();
  assert.equal(r.timer(), null, "a tab nobody is looking at has no reason to keep a server awake");
  r.advance(TEN_MINUTES * 3);
  assert.equal(r.calls.length, 1);
  r.show();
  assert.equal(r.calls.length, 2, "coming back after a long absence is exactly when the next click would meet a cold server");
  assert.ok(r.timer(), "and the timer is armed again");
});

test("showing the tab again soon after a ping does not ping a second time", () => {
  const r = rig();
  r.awake.start();
  r.tick();
  r.hide();
  r.advance(30_000);
  r.show();
  assert.equal(r.calls.length, 1);
});

test("a tick while hidden does nothing even if a timer somehow fired", () => {
  const r = rig();
  r.awake.start();
  const t = r.timer();
  r.hide();           // clears the timer…
  r.advance(TEN_MINUTES);
  t?.fn();            // …but suppose one already queued still runs
  assert.equal(r.calls.length, 0);
});

test("stop clears the timer and the listener, and a later show does not ping", () => {
  const r = rig();
  r.awake.start();
  r.awake.stop();
  assert.equal(r.timer(), null);
  assert.equal(r.listening(), false);
  assert.equal(r.awake.isRunning(), false);
  r.show();
  assert.equal(r.calls.length, 0, "a signed-out tab keeps nothing awake");
  r.awake.stop(); // safe when not started
});

test("it can be started again after a stop (a second sign-in)", () => {
  const r = rig();
  r.awake.start();
  r.awake.stop();
  r.awake.start();
  r.tick();
  assert.equal(r.calls.length, 1);
});

test("another tab's recent ping is respected: one request a window across tabs", () => {
  const r = rig();
  r.awake.start();
  r.advance(TEN_MINUTES - 30_000);
  r.setStored(r.now());   // another tab pings now…
  r.tick(30_000);         // …and this tab's own timer fires thirty seconds later
  assert.equal(r.calls.length, 0, "two tabs must not make two requests for one window");
});

test("a tab pings when the last ping, its own or another's, is old enough", () => {
  const r = rig();
  r.awake.start();
  r.setStored(1_000_000 - TEN_MINUTES);
  r.tick(1);
  assert.equal(r.calls.length, 1);
  assert.equal(r.stored() !== null, true, "it records when it pinged, for the other tabs");
});

test("a store that throws is ignored and the tab simply pings on its own timer", () => {
  const r = rig({ store: { get: () => { throw new Error("blocked"); }, set: () => { throw new Error("blocked"); } } });
  r.awake.start();
  assert.doesNotThrow(() => r.tick());
  assert.equal(r.calls.length, 1);
  assert.doesNotThrow(() => r.awake.warmUp());
});

test("no store at all (a browser that gives none) still works", () => {
  const r = rig({ store: null });
  r.awake.start();
  r.tick();
  assert.equal(r.calls.length, 1);
  // Its own memory stops it pinging twice inside a window.
  r.tick(60_000);
  assert.equal(r.calls.length, 1);
});

test("a failed ping is silent: no throw, no unhandled rejection", async () => {
  const seen: unknown[] = [];
  const onUnhandled = (e: unknown) => seen.push(e);
  process.on("unhandledRejection", onUnhandled);
  try {
    const rejecting = rig({ fetch: () => Promise.reject(new Error("offline")) });
    rejecting.awake.warmUp();
    const throwing = rig({ fetch: () => { throw new TypeError("Failed to fetch"); } });
    assert.doesNotThrow(() => throwing.awake.warmUp());
    await new Promise((r) => setImmediate(r));
    await new Promise((r) => setImmediate(r));
  } finally {
    process.off("unhandledRejection", onUnhandled);
  }
  assert.deepEqual(seen, [], "a failed ping is not a toast, a console error or an unhandled rejection");
});
