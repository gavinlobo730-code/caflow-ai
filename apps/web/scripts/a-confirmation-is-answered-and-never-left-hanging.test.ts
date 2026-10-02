// A CONFIRMATION IS ANSWERED, AND A SUPERSEDED ONE IS NEVER LEFT HANGING (frontend_ux-21).
//   node --experimental-strip-types --test scripts/a-confirmation-is-answered-and-never-left-hanging.test.ts
//
// `confirmDialog` replaces `window.confirm` at 30-odd sites, every one of which
// reads `if (!(await confirmDialog(…))) return;` — so the three things that matter
// are what each answer is, that cancelling still REFUSES, and that a question never
// stays unanswered. The last is new with this change: asking while a question was
// already open replaced it and left the first caller's promise unresolved for ever,
// which was a stalled handler, and behind a button holding a repeat-click guard
// (components/ui/button.tsx) is a button disabled until the page reloads.
//
// This loads the REAL components/ui/confirm-dialog.tsx through scripts/tsxHarness.ts,
// renders the host with react-dom/server and calls the buttons' `onClick` as a
// browser would. A server render paints nothing and runs no effects, so Escape (an
// effect) and focus are held by a source check below, and a click-through of one
// delete is still owed to a machine with a browser.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { hostElements, loadModule, requireFromWeb, startRecording } from "./tsxHarness.ts";

const React = requireFromWeb("react") as typeof import("react");
const { renderToStaticMarkup } = requireFromWeb("react-dom/server") as typeof import("react-dom/server");
const dialog = loadModule<{
  ConfirmDialogHost: React.ComponentType;
  confirmDialog: (o: unknown) => Promise<boolean>;
  promptDialog: (o: unknown) => Promise<string | null>;
}>("components/ui/confirm-dialog");

const PENDING = Symbol("pending");
/** What a promise is right now: its value, or PENDING. */
async function state<T>(p: Promise<T>): Promise<T | typeof PENDING> {
  return Promise.race([p, new Promise<typeof PENDING>((r) => setImmediate(() => r(PENDING)))]);
}

/** Mount the host; return its markup and its <button>s by label. */
function host() {
  startRecording();
  const html = renderToStaticMarkup(React.createElement(dialog.ConfirmDialogHost));
  const buttons = hostElements("button").map((b) => b.props as { onClick: () => void; disabled?: boolean; children: unknown; className: string });
  const byLabel = (label: string) => {
    const b = buttons.find((x) => String(x.children) === label);
    assert.ok(b, `no button labelled ${label} in ${html}`);
    return b;
  };
  return { html, byLabel };
}

/** Leave nothing open for the next test. */
async function settleAnything() {
  const p = dialog.confirmDialog("clear");
  host().byLabel("Cancel").onClick();
  await p;
}

test("OK answers true and Cancel answers false", async () => {
  const yes = dialog.confirmDialog("Delete this record?");
  host().byLabel("OK").onClick();
  assert.equal(await yes, true);

  const no = dialog.confirmDialog("Delete this record?");
  host().byLabel("Cancel").onClick();
  assert.equal(await no, false, "cancelling must still REFUSE — `if (!(await confirmDialog(…))) return;`");
});

test("a string and an options object are the same call", async () => {
  const p = dialog.confirmDialog({ message: "Remove it?", danger: true, confirmLabel: "Remove", cancelLabel: "Keep" });
  const h = host();
  assert.match(h.html, /Remove it\?/);
  assert.match(h.html, /Are you sure\?/, "a danger dialog is headed for what it is");
  h.byLabel("Keep").onClick();
  assert.equal(await p, false);

  const q = dialog.confirmDialog({ message: "Remove it?", danger: true, confirmLabel: "Remove" });
  assert.match(host().byLabel("Remove").className, /bg-red-600/, "and its confirm button is the destructive one");
  host().byLabel("Remove").onClick();
  assert.equal(await q, true);
});

test("a question asked while another is open answers the older one NO, and is itself still open", async () => {
  const first = dialog.confirmDialog("First?");
  const second = dialog.confirmDialog("Second?");
  assert.equal(await state(first), false, "the superseded question resolves — it must not hang");
  assert.equal(await state(second), PENDING, "the new one is waiting for its answer");
  const h = host();
  assert.match(h.html, /Second\?/);
  assert.doesNotMatch(h.html, /First\?/);
  h.byLabel("OK").onClick();
  assert.equal(await second, true);
});

test("a prompt answers with the text, or null when cancelled", async () => {
  const typed = dialog.promptDialog({ message: "Why?", defaultValue: "because the rate was wrong" });
  host().byLabel("OK").onClick();
  assert.equal(await typed, "because the rate was wrong");

  const cancelled = dialog.promptDialog({ message: "Why?", defaultValue: "half a thought" });
  host().byLabel("Cancel").onClick();
  assert.equal(await cancelled, null, "null is how window.prompt said cancel, and the callers test for it");
});

test("a required prompt cannot be confirmed blank", async () => {
  const p = dialog.promptDialog({ message: "Reason (required):", required: true, confirmLabel: "Suspend" });
  const h = host();
  assert.equal(h.byLabel("Suspend").disabled, true, "nothing typed, nothing to confirm");
  h.byLabel("Cancel").onClick();
  assert.equal(await p, null);

  const filled = dialog.promptDialog({ message: "Reason (required):", required: true, defaultValue: "  ", confirmLabel: "Suspend" });
  assert.equal(host().byLabel("Suspend").disabled, true, "blanks are not an answer");
  host().byLabel("Cancel").onClick();
  await filled;

  const ok = dialog.promptDialog({ message: "Reason (required):", required: true, defaultValue: "duplicate firm", confirmLabel: "Suspend" });
  assert.equal(host().byLabel("Suspend").disabled, false);
  host().byLabel("Suspend").onClick();
  assert.equal(await ok, "duplicate firm");
});

test("a prompt that is not required may be confirmed empty, and answers an empty string", async () => {
  const p = dialog.promptDialog({ message: "Note?" });
  const h = host();
  assert.equal(h.byLabel("OK").disabled, false);
  h.byLabel("OK").onClick();
  assert.equal(await p, "");
});

test("a prompt superseded by a confirm answers null, and a confirm superseded by a prompt answers false", async () => {
  const prompt = dialog.promptDialog("Why?");
  const confirm = dialog.confirmDialog("Sure?");
  assert.equal(await state(prompt), null);
  assert.equal(await state(confirm), PENDING);
  const prompt2 = dialog.promptDialog("Again?");
  assert.equal(await state(confirm), false);
  assert.equal(await state(prompt2), PENDING);
  await settleAnything();
  assert.equal(await state(prompt2), null);
});

test("a multi-line prompt renders a textarea and a one-line one an input", async () => {
  const a = dialog.promptDialog({ message: "Why?", multiline: true });
  assert.match(host().html, /<textarea/);
  host().byLabel("Cancel").onClick();
  await a;
  const b = dialog.promptDialog({ message: "Why?" });
  assert.match(host().html, /<input[^>]*type="text"/);
  host().byLabel("Cancel").onClick();
  await b;
});

test("Escape dismisses whatever is open, by the same route as Cancel", () => {
  // The listener is an effect, which a server render never runs, so this is the
  // source saying it: Escape cancels (false for a confirm, null for a prompt).
  const src = readFileSync(join(import.meta.dirname, "../components/ui/confirm-dialog.tsx"), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
  assert.match(src, /e\.key === "Escape"\)\s*dismiss\(\)/);
  assert.match(src, /function cancelCurrent\(\)[\s\S]*?open\.resolve\(false\)[\s\S]*?open\.resolve\(null\)/);
});
