/**
 * sweep-client-inventory-docs-reports-06 — the godowns table's Trash-can icon
 * closed a godown with nothing asking first: no native `confirm()`, no
 * modal, and the response's `res.success` was never read. A misclick was
 * permanent from the screen's own point of view, because a closed row was
 * never labelled as closed, kept its alarming orange "Not recorded"
 * registration warning as though the decision still mattered, and had no
 * action anywhere in the UI to undo it — although `is_active` is an ordinary
 * column and reopening is just setting it back.
 *
 * This is the reverse of `whether-a-stock-transfer-is-a-supply-is-the-servers-
 * answer.test.ts`'s discipline, aimed at one control on the same screen: not
 * "does the browser avoid deciding a statutory question", but "does closing a
 * godown behave like the destructive-ish action it is".
 */
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const PANEL = path.join(WEB, "components/inventory/LocationsAndBatches.tsx");

function withoutComments(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, "")
    .split("\n")
    .map((l) => l.replace(/(^|\s)\/\/.*$/, "$1"))
    .join("\n");
}

const raw = fs.readFileSync(PANEL, "utf8");
const code = withoutComments(raw);

/** The body of `closeGodown`, isolated so a confirm() or a success check
 *  written for a DIFFERENT handler in the same file cannot satisfy this. */
function functionBody(name: string): string {
  const start = code.indexOf(`function ${name}(`);
  assert.ok(start !== -1, `function ${name} not found in ${PANEL}`);
  const open = code.indexOf("{", start);
  let depth = 0, end = -1;
  for (let i = open; i < code.length; i++) {
    if (code[i] === "{") depth++;
    else if (code[i] === "}") { depth--; if (depth === 0) { end = i; break; } }
  }
  assert.ok(end !== -1, `unbalanced braces reading ${name}`);
  return code.slice(open, end);
}

test("closing a godown asks first and can be undone", async (t) => {
  const closeBody = functionBody("closeGodown");

  await t.test("a close asks for confirmation before firing the request", () => {
    assert.match(closeBody, /confirm\(/,
      "closeGodown fires the DELETE with nothing asking first — a single " +
        "misclick permanently closes a godown");
    // The confirm has to gate the request, not merely appear somewhere in the
    // function — it must be textually BEFORE the fetch it is meant to guard.
    const confirmAt = closeBody.search(/confirm\(/);
    const requestAt = closeBody.search(/request</);
    assert.ok(confirmAt >= 0 && requestAt > confirmAt,
      "confirm() does not precede the request it is meant to gate");
  });

  await t.test("a refusal from the server is shown, not swallowed", () => {
    assert.match(closeBody, /res\.success/,
      "closeGodown ignores res.success — a refusal from the server never " +
        "reaches the CA");
    assert.match(closeBody, /setError\(/);
  });

  await t.test("a reopen path exists and is a real request, not a placeholder", () => {
    const reopenBody = functionBody("reopenGodown");
    assert.match(reopenBody, /\/reopen/,
      "there is no way via the UI to reopen a closed godown");
    assert.match(reopenBody, /res\.success/,
      "reopenGodown ignores res.success too");
  });

  await t.test("a closed godown is labelled, not merely dimmed", () => {
    assert.match(code, /!g\.is_active/);
    assert.match(code, />\s*Closed\s*</,
      "no 'Closed' badge is rendered for an inactive godown");
  });

  await t.test("the alarming registration warning is withheld once closed", () => {
    // The active branch still gets the loud colour; the inactive branch must
    // use a quieter one, so the warning does not keep telling a CA to act on
    // a decision a closed godown can no longer make.
    assert.match(code, /g\.is_active[\s\S]{0,200}text-state-attention/,
      "the active branch lost its warning colour");
    assert.match(code, /text-ps-hint/,
      "the closed branch does not use a quieter tone for the same field");
  });

  await t.test("the close and reopen actions are told apart by is_active", () => {
    assert.match(code, /g\.is_active\s*\?[\s\S]{0,120}closeGodown/);
    assert.match(code, /reopenGodown/);
  });

  await t.test("the comment strip does not make the scan vacuous", () => {
    assert.ok(code.length > raw.length / 2, "too much of the file was stripped");
    assert.match(code, /export function LocationsAndBatches/);
  });
});
