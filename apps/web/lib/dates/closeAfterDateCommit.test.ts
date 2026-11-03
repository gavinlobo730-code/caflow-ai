// POST-A-126 (item 5): Escape over a date box that has not committed yet.
// Run with: node --experimental-strip-types --test lib/dates/closeAfterDateCommit.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { closeAfterTheFocusedDateCommits, type FocusedElement } from "./closeAfterDateCommit.ts";
import { TYPED_DATE_MARKER } from "./typedDate.ts";

/** A stand-in for the focused element, recording the order of what happens to it and to the close. */
function stand(attrs: string[], log: string[]): FocusedElement {
  return { hasAttribute: (n) => attrs.includes(n), blur: () => { log.push("blur"); } };
}

test("with the cursor in a date box the box is left FIRST and the close runs later, never in the same tick", () => {
  const log: string[] = [];
  const queued: Array<() => void> = [];
  closeAfterTheFocusedDateCommits(() => log.push("close"), stand([TYPED_DATE_MARKER], log), (run) => queued.push(run));
  assert.deepEqual(log, ["blur"], "the commit comes first and the close has not run");
  assert.equal(queued.length, 1);
  queued[0]();
  assert.deepEqual(log, ["blur", "close"]);
});

test("anywhere else the close runs at once and nothing is blurred", () => {
  const log: string[] = [];
  const queued: Array<() => void> = [];
  closeAfterTheFocusedDateCommits(() => log.push("close"), stand([], log), (run) => queued.push(run));
  assert.deepEqual(log, ["close"]);
  assert.equal(queued.length, 0, "a plain input reports every keystroke already: waiting would only let the key be pressed twice");
});

test("no focused element closes at once", () => {
  const log: string[] = [];
  closeAfterTheFocusedDateCommits(() => log.push("close"), null, () => { log.push("deferred"); });
  assert.deepEqual(log, ["close"]);
});

test("the close that runs is the one handed in, so a caller passes a function that reads its latest callback", () => {
  let latest = "old";
  const seen: string[] = [];
  const queued: Array<() => void> = [];
  closeAfterTheFocusedDateCommits(() => seen.push(latest), stand([TYPED_DATE_MARKER], []), (run) => queued.push(run));
  latest = "new";          // the commit re-rendered the parent
  queued[0]();
  assert.deepEqual(seen, ["new"]);
});

test("the marker is the one name the box carries and the helper reads", () => {
  assert.equal(TYPED_DATE_MARKER, "data-typed-date");
});
