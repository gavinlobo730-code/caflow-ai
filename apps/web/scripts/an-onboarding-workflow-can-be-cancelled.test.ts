// apex-overview-practice-08 (frontend half): the lifecycle page could list
// onboarding workflows and create new ones, but had no way to remove an
// unwanted one — a duplicate-click now gets a server-side 409
// (routers/lifecycle.py's create_onboarding), but nothing let a CA cancel a
// workflow they genuinely no longer want tracked. This pins the Cancel
// button: it soft-cancels through the PATCH .../status route (never a
// DELETE), is confirmed first (the same confirmDialog pattern "New
// Onboarding" already uses), only offers itself on an IN-PROGRESS workflow,
// and disables itself while its own request is in flight.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const FILE = path.resolve(
  import.meta.dirname,
  "..",
  "app",
  "clients",
  "[id]",
  "lifecycle",
  "page.tsx"
);

function read(): string {
  return fs.readFileSync(FILE, "utf8");
}

function stripComments(src: string): string {
  return src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/[^\n]*/g, "$1");
}

function handleCancelWorkflowBody(rawSrc: string): string {
  const start = rawSrc.indexOf("async function handleCancelWorkflow(");
  assert.ok(start > -1, "could not find handleCancelWorkflow");
  const end = rawSrc.indexOf("async function handleUpdateTask(", start);
  assert.ok(end > -1, "could not find the end of handleCancelWorkflow (the next handler after it)");
  return rawSrc.slice(start, end);
}

test("a handleCancelWorkflow function exists", () => {
  const code = stripComments(read());
  assert.match(code, /async function handleCancelWorkflow\(\s*workflowId:\s*string\s*\)/);
});

test("cancelling asks for confirmation before doing anything, via the shared confirmDialog", () => {
  const body = stripComments(handleCancelWorkflowBody(read()));
  const confirmAt = body.search(/await confirmDialog\(/);
  assert.ok(confirmAt > -1, "handleCancelWorkflow does not call confirmDialog");
  const bailAt = body.indexOf("if (!ok) return;");
  assert.ok(bailAt > confirmAt, "no early return when the confirm dialog is declined");
  // And nothing that mutates state (starting the in-flight flag, calling the
  // API) happens before that bail-out.
  const firstMutation = body.search(/setCancellingWorkflowId\(workflowId\)|apiFetch\(/);
  assert.ok(firstMutation > bailAt,
    "work starts before the confirm dialog's answer is checked");
});

test("cancelling PATCHes the status sub-route with status: cancelled — it is never a DELETE", () => {
  const body = stripComments(handleCancelWorkflowBody(read()));
  assert.match(body, /apiFetch\(\s*`\/api\/lifecycle\/onboarding\/\$\{workflowId\}\/status`/,
    "does not call the PATCH .../status route this feature's backend half added");
  assert.match(body, /method:\s*"PATCH"/);
  assert.match(body, /status:\s*"cancelled"/);
  assert.doesNotMatch(body, /method:\s*"DELETE"/,
    "a workflow must be soft-cancelled (status change), never hard-deleted");
});

test("a failed request is surfaced and the in-flight flag is always cleared", () => {
  const body = stripComments(handleCancelWorkflowBody(read()));
  assert.match(body, /catch\s*\(e\)\s*\{[\s\S]*setError\(/,
    "a failed cancel is silently swallowed rather than shown to the CA");
  assert.match(body, /finally\s*\{[\s\S]*setCancellingWorkflowId\(null\)[\s\S]*\}/,
    "the in-flight flag is not cleared in a finally — a failed request would " +
    "leave the button disabled forever");
});

test("a per-workflow in-flight state exists, not one flag shared by every card", () => {
  const code = stripComments(read());
  assert.match(code, /const \[cancellingWorkflowId,\s*setCancellingWorkflowId\]\s*=\s*useState<string \| null>\(null\)/,
    "cancelling is tracked by workflow id — a single boolean would disable " +
    "every card's Cancel button when only one workflow is being cancelled");
});

test("the Cancel control only appears for an in-progress workflow", () => {
  const code = stripComments(read());
  const guardAt = code.search(/wf\.status === "in_progress" &&\s*\(/);
  assert.ok(guardAt > -1, "no in_progress guard found around the Cancel control");
  const nearby = code.slice(guardAt, guardAt + 400);
  assert.match(nearby, /handleCancelWorkflow\(wf\.id\)/,
    "the in_progress-gated block does not render the cancel button");
});

test("a completed or already-cancelled workflow renders no Cancel button", () => {
  // Negative-of-the-negative: assert the JSX is actually conditional, i.e.
  // handleCancelWorkflow is not also reachable from an unconditional button.
  const code = stripComments(read());
  const allCancelButtonSites = [...code.matchAll(/handleCancelWorkflow\(wf\.id\)/g)];
  assert.equal(allCancelButtonSites.length, 1,
    "expected exactly one place that wires up the Cancel button");
});

test("the workflow card names a cancelled workflow distinctly, not as still in progress", () => {
  const code = stripComments(read());
  assert.match(code, /wf\.status === "cancelled"\s*\?\s*"Onboarding Cancelled"/,
    "a cancelled workflow's card does not say so — it would otherwise still " +
    "read \"Onboarding In Progress\"");
});
