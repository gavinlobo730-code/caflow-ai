// market_and_trust-16: the dashboard reads the server's first-run checklist and decides nothing.
//   node --experimental-strip-types --test lib/onboarding/firstRun.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { PRACTICE_STEP_ROUTES, STEP_ROUTES, hrefFor, practiceHrefFor, progressOf, readFirstRun, shouldShow, startHere } from "./firstRun.ts";

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

// POST-A-002: a person can dismiss the card for good, and the server says whether this person did.
test("dismissed is read as exactly true or false, and anything else is 'could not tell'", () => {
  const read = (v: unknown) => readFirstRun(payload({ dismissed: v }))!.dismissed;
  assert.equal(read(true), true);
  assert.equal(read(false), false);
  assert.equal(read(null), null);
  assert.equal(read("yes"), null);
  assert.equal(read(1), null);
  const p = payload();
  assert.equal(readFirstRun(p)!.dismissed, null, "a backend that does not send the key yet is not a dismissal");
});

test("a card the server says is not visible stays hidden whatever else it says", () => {
  assert.equal(shouldShow(readFirstRun(payload({ visible: false, dismissed: true }))), false);
  assert.equal(shouldShow(readFirstRun(payload({ visible: true, dismissed: false }))), true);
  assert.equal(shouldShow(readFirstRun(payload({ visible: true, dismissed: null }))), true, "an unreadable dismissal leaves the card");
});

// ── the firm's own practice: a second list, in a Partner's answer only (POST-A-533) ─────────────────────────────────────────

const practice = (over: Record<string, unknown> = {}) => ({
  steps: [step("practice_identity", true), step("practice_books", false), step("practice_statement", null), step("practice_fee_bill", false)],
  total: 4, done_count: 1, complete: false, next_step: "practice_books", unreadable: ["practice_statement"], client_id: "p-1", ...over,
});

test("the practice's list is read when the server sends one, and is absent for everybody else", () => {
  assert.equal(readFirstRun(payload())!.practice, null, "a payload with no practice list invented one");
  assert.equal(readFirstRun(payload({ practice: null }))!.practice, null);
  for (const bad of ["yes", 1, [], {}, { steps: [] }, { steps: "four" }]) {
    assert.equal(readFirstRun(payload({ practice: bad }))!.practice, null, JSON.stringify(bad));
  }
  const p = readFirstRun(payload({ practice: practice() }))!.practice!;
  assert.deepEqual(p.steps.map((s) => s.done), [true, false, null, false]);
  assert.equal(p.client_id, "p-1");
  assert.equal(readFirstRun(payload({ practice: practice({ client_id: "" }) }))!.practice!.client_id, null, "an empty id is not an id");
});

test("the card counts both lists for a Partner and the four steps for everybody else", () => {
  assert.deepEqual(progressOf(readFirstRun(payload())!), { done: 1, total: 4 });
  assert.deepEqual(progressOf(readFirstRun(payload({ practice: practice() }))!), { done: 2, total: 8 });
});

test("one step is marked to start with: the clients' next, and the practice's only when the clients have none", () => {
  assert.equal(startHere(readFirstRun(payload({ practice: practice() }))!), "first_invoice");
  assert.equal(startHere(readFirstRun(payload({ next_step: null, practice: practice() }))!), "practice_books");
  assert.equal(startHere(readFirstRun(payload({ next_step: null }))!), null);
});

test("a practice step opens a screen of My practice, and Practice home while the practice is not set up", () => {
  assert.equal(practiceHrefFor("practice_identity", "p-1"), "/practice");
  assert.equal(practiceHrefFor("practice_books", "p-1"), "/clients/p-1/accounting?tab=opening-balances");
  assert.equal(practiceHrefFor("practice_statement", "p-1"), "/clients/p-1/bank");
  assert.equal(practiceHrefFor("practice_fee_bill", "p-1"), "/practice/billing");
  for (const id of Object.keys(PRACTICE_STEP_ROUTES)) {
    const href = practiceHrefFor(id, null)!;
    assert.ok(href === "/practice" || href.startsWith("/practice/"), `${id} leads into a workspace that does not exist: ${href}`);
    assert.doesNotMatch(href, /null|undefined/);
  }
  assert.equal(practiceHrefFor("something_else", "p-1"), null);
  assert.equal(hrefFor("practice_books"), null, "a practice step is routed as a client step");
  assert.ok(Object.keys(STEP_ROUTES).every((id) => !id.startsWith("practice_")));
});

