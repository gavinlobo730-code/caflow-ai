// The journal editor is finished from the keyboard: Tab from the last narration adds the next line while the entry is out of balance, and an
// amount cell selects its text on focus (POST-A-128, the journal half).
//
// WHAT WAS MISSING
//   Enter already finished a line, and InvoiceEditor creates a row on an end-of-row Tab; the journal editor made a Tab-driven hand walk
//   off the last narration to the Remove button and the buttons below, and a balancing figure the screen had offered had to be edited
//   in the middle rather than overtyped. The rule is `lib/journal/lineFlow.afterTab` (unit-tested beside it) and
//   `scripts/drive/scenarios/journalKeys.mjs` drives it in Chromium; this holds that the editor really hands its key to the rule.
//
// Run with: node --experimental-strip-types --test scripts/the-journal-editor-is-finished-from-the-keyboard.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const WEB = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const EDITOR = stripComments(fs.readFileSync(path.join(WEB, "components/journal/JournalEditor.tsx"), "utf8"));

test("the editor asks the pure rule where Tab from the last narration goes, and never intercepts Shift+Tab or a modified Tab", () => {
  const handler = EDITOR.slice(EDITOR.indexOf("function onNarrationKeyDown"));
  const body = handler.slice(0, handler.indexOf("\n  }\n") + 5);
  assert.ok(body.length > 200, "the handler could not be found");
  assert.ok(/afterTab\(idx, lines\.length, isBalanced\)\.kind === "add"/.test(body), "the key is not decided by lineFlow.afterTab on the editor's own verdict");
  assert.ok(/e\.key === "Tab" && !e\.shiftKey && !e\.ctrlKey && !e\.metaKey && !e\.altKey/.test(body), "Shift+Tab or a modified Tab can be intercepted");
  assert.ok(/e\.preventDefault\(\);\s*addLine\(\);/.test(body), "the new line is not added through the editor's own addLine (which carries the balancing leg)");
  assert.ok(/onLineEnter\(e, idx\)/.test(body), "every other key lost the narration cell's Enter rule");
  assert.ok(/!readOnly/.test(body), "a read-only entry can grow a line");
});

test("only the narration cell hands its Tab to the rule, and both amount cells select their text on focus", () => {
  assert.equal((EDITOR.match(/onKeyDown=\{\(e\) => onNarrationKeyDown\(e, idx\)\}/g) ?? []).length, 1, "the narration cell does not use the Tab rule");
  assert.equal((EDITOR.match(/onFocus=\{\(e\) => e\.currentTarget\.select\(\)\}/g) ?? []).length, 2, "an amount cell does not select its text on focus");
});
