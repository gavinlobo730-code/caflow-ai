// node --experimental-strip-types --test lib/auth/browserSessionGlue.test.ts
//
// POST-A-483, driven the way the page runs it: a module that captures what it finds when it first runs, writers that do nothing
// until the decision is made, and a sign-out that really happens. The independent review ran the real sign-in library against the
// first version and found it ended nothing, for two reasons these tests keep shut: the sign-in service's announcement of a
// session recovered from storage marked the tab before the decision read the marker, and the heartbeat was written a moment before
// the decision read it.
import test, { before } from "node:test";
import assert from "node:assert/strict";
import { ALIVE_KEY, ALIVE_LOCK_NAME, KEEP_KEY, MARKER_KEY, keepFlag } from "./browserSession.ts";

class Store {
  m = new Map<string, string>();
  getItem(k: string) { return this.m.has(k) ? this.m.get(k)! : null; }
  setItem(k: string, v: string) { this.m.set(k, String(v)); }
  removeItem(k: string) { this.m.delete(k); }
}

let NOW = 0;                           // read when the tests start, not when the file loads
before(() => { NOW = Date.now(); });
const DAY = 86_400_000;

interface World {
  local?: Record<string, string>; session?: Record<string, string>;
  hash?: string; search?: string;
  locksHeld?: string[]; pong?: boolean; stored?: boolean; userId?: string;
}

let n = 0;
type Glue = { markBrowserSession(): void; beat(): void };
type LooseGlobal = Record<string, unknown>;

async function run(w: World, during?: (g: Glue) => void) {
  const local = new Store(), session = new Store();
  Object.entries(w.local ?? {}).forEach(([k, v]) => local.setItem(k, v));
  Object.entries(w.session ?? {}).forEach(([k, v]) => session.setItem(k, v));
  const g = globalThis as unknown as LooseGlobal;
  g.window = { localStorage: local, sessionStorage: session, location: { hash: w.hash ?? "", search: w.search ?? "" } };
  Object.defineProperty(g, "navigator", {
    configurable: true,
    value: { locks: w.locksHeld === undefined ? undefined : {
      query: async () => ({ held: w.locksHeld!.map((name) => ({ name })) }),
      request: async () => undefined,
    } },
  });
  g.BroadcastChannel = class {
    onmessage: ((ev: { data: unknown }) => void) | null = null;
    postMessage(msg: unknown) { if (msg === "ping" && w.pong) setTimeout(() => this.onmessage?.({ data: "pong" }), 5); }
    close() {}
  };
  const signedOut: unknown[] = [];
  const client = {
    auth: {
      getSession: async () => ({ data: { session: w.stored === false ? null : { user: { id: w.userId ?? "u1" } } } }),
      signOut: async (opts: unknown) => { signedOut.push(opts); },
    },
  };
  const glue = await import(`./browserSessionGlue.ts?case=${++n}`);
  const pending = glue.enforceBrowserSession(client);
  during?.(glue);                       // what the page does while the decision is still out: the library's SIGNED_IN, the heartbeat
  const outcome = await pending;
  return { outcome, signedOut, local, session, glue };
}

test("a stored session with nothing to say the browser stayed open is ended, here only", async () => {
  const r = await run({ local: { [ALIVE_KEY]: String(NOW - DAY) } });
  assert.equal(r.outcome, "ended");
  assert.deepEqual(r.signedOut, [{ scope: "local" }]);
  assert.equal(r.session.getItem(MARKER_KEY), null);
});

test("the library's announcement of a recovered session and the first heartbeat, both before the decision, change nothing about it", async () => {
  const r = await run({ local: { [ALIVE_KEY]: String(NOW - DAY) } }, (g) => { g.markBrowserSession(); g.beat(); });
  assert.equal(r.outcome, "ended", "a marker or a heartbeat written before the decision read it kept the session");
  assert.equal(r.glue.browserSessionDecided(), true);
  assert.equal(r.local.getItem(ALIVE_KEY), String(NOW - DAY), "a heartbeat was written before the decision");
  assert.equal(r.session.getItem(MARKER_KEY), null);
});

test("once the decision is made the writers work", async () => {
  const r = await run({ session: { [MARKER_KEY]: "1" } });
  assert.equal(r.outcome, "kept");
  r.glue.beat();
  assert.notEqual(r.local.getItem(ALIVE_KEY), null);
  r.session.removeItem(MARKER_KEY);
  r.glue.markBrowserSession();
  assert.equal(r.session.getItem(MARKER_KEY), "1");
});

test("a tab that already belongs to the browser session is kept", async () => {
  const r = await run({ session: { [MARKER_KEY]: "1" }, local: { [ALIVE_KEY]: String(NOW - DAY) } });
  assert.equal(r.outcome, "kept");
  assert.deepEqual(r.signedOut, []);
});

test("an address that carries a sign-in (a link, an invitation, a password reset) is a fresh sign-in and is kept and marked", async () => {
  for (const hash of ["#access_token=a&refresh_token=b&type=magiclink", "#access_token=a&type=recovery"]) {
    const r = await run({ hash, local: { [ALIVE_KEY]: String(NOW - DAY) } });
    assert.equal(r.outcome, "kept", hash);
    assert.equal(r.session.getItem(MARKER_KEY), "1");
    assert.deepEqual(r.signedOut, []);
  }
});

test("another tab holding the alive lock keeps the person in, a sleeping tab included, and its absence does not", async () => {
  const kept = await run({ locksHeld: [ALIVE_LOCK_NAME], local: { [ALIVE_KEY]: String(NOW - DAY) } });
  assert.equal(kept.outcome, "kept");
  const ended = await run({ locksHeld: ["some-other-lock"], local: { [ALIVE_KEY]: String(NOW - DAY) } });
  assert.equal(ended.outcome, "ended");
});

test("another tab that answers the ping keeps the person in", async () => {
  const r = await run({ pong: true, local: { [ALIVE_KEY]: String(NOW - DAY) } });
  assert.equal(r.outcome, "kept");
});

test("a heartbeat from a moment ago keeps the person in, an old one does not", async () => {
  assert.equal((await run({ local: { [ALIVE_KEY]: String(NOW - 30_000) } })).outcome, "kept");
  assert.equal((await run({ local: { [ALIVE_KEY]: String(NOW - 10 * 60_000) } })).outcome, "ended");
});

test("the tickbox keeps the person who ticked it, for fourteen days, and nobody else", async () => {
  const stale = { [ALIVE_KEY]: String(NOW - DAY) };
  assert.equal((await run({ local: { ...stale, [KEEP_KEY]: keepFlag(NOW, "u1") }, userId: "u1" })).outcome, "kept");
  assert.equal((await run({ local: { ...stale, [KEEP_KEY]: keepFlag(NOW, "u1") }, userId: "u2" })).outcome, "ended", "inherited by the next person");
  assert.equal((await run({ local: { ...stale, [KEEP_KEY]: JSON.stringify({ until: NOW + 400 * DAY, uid: "u1" }) }, userId: "u1" })).outcome, "ended", "an edited flag outlived its cap");
});

test("no stored session means nothing to end, and the tab is marked", async () => {
  const r = await run({ stored: false });
  assert.equal(r.outcome, "kept");
  assert.equal(r.session.getItem(MARKER_KEY), "1");
  assert.deepEqual(r.signedOut, []);
});

test("a failure to read the session releases the writers and leaves the person signed in", async () => {
  const g = globalThis as unknown as LooseGlobal;
  g.window = { localStorage: new Store(), sessionStorage: new Store(), location: { hash: "", search: "" } };
  g.BroadcastChannel = class { postMessage() {} close() {} };
  const glue = await import(`./browserSessionGlue.ts?case=${++n}`);
  await assert.rejects(glue.enforceBrowserSession({ auth: { getSession: async () => { throw new Error("storage"); } } }));
  assert.equal(glue.browserSessionDecided(), true);
});
