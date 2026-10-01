// market_and_trust-16: the dashboard reads the server's first-run checklist and decides nothing.
//   node --experimental-strip-types --test lib/onboarding/firstRun.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { STEP_ROUTES, hrefFor, readFirstRun, shouldShow } from "./firstRun.ts";

const step = (id: string, done: unknown, extra: Record<string, unknown> = {}) =>
  ({ id, title: `Do ${id}`, why: "because", done, done_at: null, ...extra });

const payload = (over: Record<string, unknown> = {}) => ({
  checks: {},
  first_run: {
    steps: [step("first_client", true, { done_at: "2026-09-01T05:00:00+00:00" }),
            step("first_invoice", false), step("first_statement", null), step("invite_colleague", false)],
    total: 4, done_count: 1, complete: false, next_step: "first_invoice",
    unreadable: ["first_statement"], visible: true, minutes_to_first_invoice: null, ...over,
  },
});

test("a well-formed payload is read as the server sent it", () => {
  const c = readFirstRun(payload());
  assert.ok(c);
  assert.equal(c.steps.length, 4);
  assert.deepEqual(c.steps.map((s) => s.done), [true, false, null, false]);
  assert.equal(c.next_step, "first_invoice");
  assert.deepEqual(c.unreadable, ["first_statement"]);
  assert.equal(shouldShow(c), true);
});

test("an unreadable step stays null and is never turned into false or true", () => {
  const c = readFirstRun(payload({ steps: [step("a", null), step("b", "yes"), step("c", 1), step("d", undefined)] }));
  assert.ok(c);
  assert.deepEqual(c.steps.map((s) => s.done), [null, null, null, null]);
});

test("the browser never works out visibility: absent means hidden", () => {
  const p = payload();
  delete (p.first_run as Record<string, unknown>).visible;
  assert.equal(shouldShow(readFirstRun(p)), false);
  assert.equal(shouldShow(readFirstRun(payload({ visible: false }))), false);
});

test("a complete firm is hidden because the server said so, whatever the steps hold", () => {
  assert.equal(shouldShow(readFirstRun(payload({ complete: true, visible: false }))), false);
});

test("a visible card with no steps to list is not shown", () => {
  assert.equal(shouldShow(readFirstRun(payload({ steps: [] }))), false);
});

test("a payload that is not the right shape is no data and never a crash", () => {
  for (const bad of [null, undefined, [], "oops", 7, {}, { first_run: [] }, { first_run: "x" }, { first_run: null }]) {
    assert.equal(readFirstRun(bad), null, JSON.stringify(bad));
  }
});

test("`steps` that is not a list is read as no steps, and a half-formed step is dropped", () => {
  const c = readFirstRun(payload({ steps: { 0: "x" } }));
  assert.ok(c);
  assert.deepEqual(c.steps, []);
  const d = readFirstRun(payload({ steps: [null, 3, {}, { id: "" }, step("first_client", true)] }));
  assert.ok(d);
  assert.deepEqual(d.steps.map((s) => s.id), ["first_client"]);
});

test("`unreadable` that is not a list of strings is read as none", () => {
  assert.deepEqual(readFirstRun(payload({ unreadable: "first_statement" }))!.unreadable, []);
  assert.deepEqual(readFirstRun(payload({ unreadable: [1, "a", null] }))!.unreadable, ["a"]);
});

test("counts the server did not send are derived from the steps and never from nothing", () => {
  const p = payload();
  delete (p.first_run as Record<string, unknown>).total;
  delete (p.first_run as Record<string, unknown>).done_count;
  const c = readFirstRun(p)!;
  assert.equal(c.total, 4);
  assert.equal(c.done_count, 1);
});

test("each step the server names has a screen to open, and an unknown one has none", () => {
  for (const id of Object.keys(STEP_ROUTES)) {
    const href = hrefFor(id);
    assert.ok(href && href.startsWith("/"), id);
  }
  assert.equal(hrefFor("a_step_the_server_added_tomorrow"), null);
  assert.equal(hrefFor("constructor"), null, "an inherited property is not a route");
});
