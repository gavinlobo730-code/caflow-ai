// What the "Book a demo" form does while a slow API makes it wait, driven with a fake clock (market_and_trust-17, POST-A-119).
//   cd apps/marketing && node --experimental-strip-types --test lib/demoRequestWait.test.ts
//
// This half lived in apps/api/tests/test_the_demo_form_does_not_look_dead_while_the_api_wakes.py, which ran this file
// under Node from pytest and SKIPPED wherever the backend job's Node could not strip TypeScript, so whether it ran
// depended on the runner image. It runs here, in Marketing CI, which pins Node 22. The source-level half (one request,
// no resend, the endpoint takes no request id, the page shows the form only with an address) stays on the Python side,
// because it reads the backend's route too.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import {
  GIVE_UP_AFTER_MS, MAILTO_MAX_LENGTH, SLOW_AFTER_MS, buildDemoMailto, watchSlowRequest, type Timers,
} from "./demoRequestWait.ts";

function fakeClock() {
  let now = 0;
  let id = 0;
  const q: { id: number; at: number; fn: () => void; live: boolean }[] = [];
  const timers: Timers = {
    set: (fn, ms) => { const t = { id: ++id, at: now + ms, fn, live: true }; q.push(t); return t.id; },
    clear: (i) => { const t = q.find((x) => x.id === i); if (t) t.live = false; },
  };
  return {
    timers,
    advance(ms: number) {
      const target = now + ms;
      for (;;) {
        const next = q.filter((t) => t.live && t.at <= target).sort((a, b) => a.at - b.at)[0];
        if (!next) break;
        now = next.at; next.live = false; next.fn();
      }
      now = target;
    },
  };
}

/** Each step advances the clock by ms or stops the watch; the events seen after each step. */
function run(steps: (number | "stop")[]): string[][] {
  const c = fakeClock();
  const events: string[] = [];
  const snap: string[][] = [];
  const w = watchSlowRequest({ onSlow: () => events.push("slow"), onGiveUp: () => events.push("giveup") }, c.timers);
  for (const s of steps) { if (s === "stop") w.stop(); else c.advance(s); snap.push(events.slice()); }
  return snap;
}

const fields = {
  name: "CA Priya Raghavan", firm_name: "Raghavan & Associates", email: "priya@raghavan.in",
  phone: "+91 98765 43210", firm_size: "2–5 people", message: "GSTR-1 for 40 clients,\nTally today.",
};
const query = (url: string) => new URL(url.replace("mailto:", "http://x/")).searchParams;

test("with no answer the fallback appears, then the request is abandoned, once each", () => {
  const a = run([SLOW_AFTER_MS - 1, 1, GIVE_UP_AFTER_MS - SLOW_AFTER_MS - 1, 1, 500_000]);
  assert.deepEqual(a[0], [], "nothing may fire a millisecond before the fallback is due");
  assert.deepEqual(a[1], ["slow"], "the email fallback appears at SLOW_AFTER_MS");
  assert.deepEqual(a[2], ["slow"], "and the request is still running a millisecond before it is abandoned");
  assert.deepEqual(a[3], ["slow", "giveup"], "it is abandoned at GIVE_UP_AFTER_MS");
  assert.deepEqual(a[4], ["slow", "giveup"], "each clock fires once, never again");
});

test("a fast answer never sees the fallback or the abandon", () => {
  assert.deepEqual(run([5000, "stop", 500_000]), [[], [], []]);
});

test("a late answer is not abandoned after the fact", () => {
  const c = run([SLOW_AFTER_MS + 1, 28_000, "stop", 500_000]);
  assert.deepEqual(c[0], ["slow"], "the fallback showed");
  assert.deepEqual(c[c.length - 1], ["slow"], "an answer that arrives before the abandon clock cancels it");
});

test("stopping twice is harmless", () => {
  const d = run([100, "stop", "stop", 500_000]);
  assert.deepEqual(d[d.length - 1], []);
});

test("the clocks are in the order the wait needs, and the abandon leaves a margin over the measured 56.55 s cold start", () => {
  assert.ok(SLOW_AFTER_MS < GIVE_UP_AFTER_MS);
  assert.ok(GIVE_UP_AFTER_MS > 56_550);
});

test("the mailto carries every field the visitor typed", () => {
  const url = buildDemoMailto("hello@practicesync.com", fields);
  assert.ok(url.startsWith("mailto:hello@practicesync.com?"));
  const q = query(url);
  assert.equal(q.get("subject"), "Demo request");
  const body = q.get("body") ?? "";
  for (const typed of ["CA Priya Raghavan", "Raghavan & Associates", "priya@raghavan.in", "+91 98765 43210", "2–5 people", "GSTR-1 for 40 clients,", "Tally today."]) {
    assert.ok(body.includes(typed), `${typed} was typed and is missing from the email`);
  }
  assert.ok(body.includes("\r\n"), "RFC 6068 asks for CRLF line breaks in a mailto body");
});

test("an empty optional field is left out, not printed as null", () => {
  const body = query(buildDemoMailto("a@b.c", { ...fields, phone: null, firm_size: null, message: null })).get("body") ?? "";
  for (const absent of ["Phone:", "Practice size:", "What I would like to see", "null", "undefined"]) {
    assert.ok(!body.includes(absent), `${absent} is in the email of a visitor who typed nothing there`);
  }
});

test("a very long message is shortened so the link survives, and says so", () => {
  const long = buildDemoMailto("hello@practicesync.com", { ...fields, message: "word ".repeat(2000) });
  assert.ok(long.length <= MAILTO_MAX_LENGTH, "a mailto URL past about 2,000 characters is cut by mail clients, losing the END");
  const body = query(long).get("body") ?? "";
  assert.ok(body.includes("shortened"));
  assert.ok((body.match(/word/g) ?? []).length > 50, "it is shortened, not discarded");
  assert.ok(body.includes("CA Priya Raghavan"), "the identifying fields are never the ones dropped");
});

test("the module imports nothing through the app's alias, so this runner can load it", () => {
  const src = readFileSync(join(import.meta.dirname, "demoRequestWait.ts"), "utf8");
  assert.doesNotMatch(src, /from\s+["']@\//);
});
