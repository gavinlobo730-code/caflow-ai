import { test } from "node:test";
import assert from "node:assert/strict";
import { readIssuePreflight, readinessFrom, holdsTheIssue, HELD_SENTENCE } from "./issueReadiness.ts";

// POST-A-125. The editor shows what the server says stands between a saved draft and its issue. This is the browser's whole decision
// about that payload, so it is tested as a decision: a payload that is not the shape is NO ANSWER and never "ready".

const placeholder = {
  code: "INVOICE_NO_PLACEHOLDER",
  message: "This invoice still carries the placeholder number DRAFT-ABCDEFGHIJ.",
  action: { kind: "fix_in_editor", field: "invoice_no", label: "Enter the invoice number" },
};

test("an empty blocker list is ready", () => {
  assert.deepEqual(readIssuePreflight({ ready: true, blockers: [] }), { ready: true, blockers: [] });
});

test("the sentence and the action are kept exactly as the server sent them", () => {
  const read = readIssuePreflight({ ready: false, blockers: [placeholder] });
  assert.deepEqual(read?.blockers[0], placeholder);
  assert.equal(read?.ready, false);
});

test("ready is read from the blockers and not trusted beside a non-empty list", () => {
  const read = readIssuePreflight({ ready: true, blockers: [placeholder] });
  assert.equal(read?.ready, false);
  assert.equal(read?.blockers.length, 1);
});

test("a payload that is not an object with a blockers list is no answer", () => {
  for (const bad of [null, undefined, [], "ready", 0, true, {}, { ready: true }, { blockers: "none" }, { blockers: {} }]) {
    assert.equal(readIssuePreflight(bad), null, JSON.stringify(bad));
  }
});

test("a blocker with no sentence makes the whole answer unreadable instead of reading as ready", () => {
  assert.equal(readIssuePreflight({ ready: false, blockers: [{ code: "X", message: "  ", action: null }] }), null);
  assert.equal(readIssuePreflight({ ready: false, blockers: [placeholder, { code: "Y" }] }), null);
  assert.equal(readIssuePreflight({ ready: false, blockers: [null] }), null);
});

test("an action this build does not know costs the button and not the sentence", () => {
  const future = { code: "NEW", message: "Something new is in the way.", action: { kind: "open_the_portal", label: "Open" } };
  const read = readIssuePreflight({ ready: false, blockers: [future] });
  assert.equal(read?.blockers[0].message, "Something new is in the way.");
  assert.equal(read?.blockers[0].action, null);
});

test("an editor action for a field the editor does not have is dropped, and one without a label too", () => {
  const field = { code: "A", message: "m", action: { kind: "fix_in_editor", field: "customer", label: "Fix" } };
  const label = { code: "B", message: "m", action: { kind: "seed_chart_of_accounts", label: " " } };
  const read = readIssuePreflight({ ready: false, blockers: [field, label] });
  assert.deepEqual(read?.blockers.map((b) => b.action), [null, null]);
});

test("the chart of accounts action is read with its label", () => {
  const coa = { code: "COA_MISSING", message: "no account", action: { kind: "seed_chart_of_accounts", label: "Set up the chart of accounts" } };
  assert.deepEqual(readIssuePreflight({ ready: false, blockers: [coa] })?.blockers[0].action,
    { kind: "seed_chart_of_accounts", label: "Set up the chart of accounts" });
});

test("a refused or empty answer is unknown, with the server's reason when it gave one", () => {
  assert.deepEqual(readinessFrom({ success: false, data: null, error: "Invoice not found" }), { status: "unknown", reason: "Invoice not found" });
  assert.deepEqual(readinessFrom(null), { status: "unknown", reason: "The server did not answer." });
  assert.deepEqual(readinessFrom({ success: false, error: "  " }), { status: "unknown", reason: "The server did not answer." });
});

test("a successful answer in the wrong shape is unknown and never ready", () => {
  const state = readinessFrom({ success: true, data: [] });
  assert.equal(state.status, "unknown");
});

test("ready and blocked come only from a well-formed successful answer", () => {
  assert.deepEqual(readinessFrom({ success: true, data: { ready: true, blockers: [] } }), { status: "ready" });
  const blocked = readinessFrom({ success: true, data: { ready: false, blockers: [placeholder] } });
  assert.equal(blocked.status, "blocked");
});

test("the issue is held only by a blocked answer about a draft with nothing unsaved", () => {
  const blocked = { status: "blocked" as const, blockers: [] };
  assert.equal(holdsTheIssue(blocked, false), true);
  assert.equal(holdsTheIssue(blocked, true), false, "unsaved changes make the answer old, and the chain asks again");
  for (const state of [{ status: "loading" as const }, { status: "ready" as const }, { status: "unknown" as const, reason: "x" }]) {
    assert.equal(holdsTheIssue(state, false), false, state.status);
  }
  assert.ok(HELD_SENTENCE.length > 20);
});
