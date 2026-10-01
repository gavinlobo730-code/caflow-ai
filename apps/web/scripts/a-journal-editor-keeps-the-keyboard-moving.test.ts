// ACC-08 — the journal editor's three quick wins, and the purchase bill grid's
// Enter. lib/journal/lineFlow.test.ts holds the ARITHMETIC (Dr 1,000 / Cr 600
// offers Cr 400); this holds the WIRING, because a pure function nothing calls
// fixes nothing.
//
// There is no DOM in this harness, so these are source guards in the repo's
// usual style and the screen itself is not driven by them.
//
// What must hold:
//   * a line added by the button AND by Enter arrives carrying the balancing
//     leg, and an account picked on an amountless line is offered it;
//   * the account box offers to create a ledger, the dialog writes through the
//     one account endpoint FOR THIS CLIENT, and the new ledger comes back on the
//     same line;
//   * NONE of that loosens the balance rule — the editor still refuses to save
//     an unbalanced entry, and the server still checks again;
//   * the bill grid's Enter is delegated, opt-in per cell, and leaves every
//     picker, select and checkbox its own Enter.
//
// Run with: node --experimental-strip-types --test scripts/a-journal-editor-keeps-the-keyboard-moving.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const read = (...p: string[]) =>
  stripComments(fs.readFileSync(path.join(__dirname, "..", ...p), "utf8"));

const editor = read("components", "journal", "JournalEditor.tsx");
const quick = read("components", "journal", "QuickAddLedger.tsx");
const lookup = read("components", "lookups", "AccountLookup.tsx");
const bill = read("components", "purchases", "PurchaseBillEditor.tsx");
const page = read("app", "clients", "[id]", "accounting", "journal", "[entryId]", "edit", "_page.tsx");

test("a new line is offered the balancing leg, by the button and by Enter", () => {
  const add = editor.slice(editor.indexOf("function addLine()"), editor.indexOf("function onLineEnter"));
  assert.match(add, /balancingLeg\(lines\)/);
  assert.match(add, /line\[leg\.side\] = leg\.amount/);
  // The button calls the same function Enter does — one way to add a line.
  assert.match(editor, /<button type="button" onClick=\{addLine\}/);
  assert.doesNotMatch(editor, /setLines\(\(p\) => \[\.\.\.p, newLine\(\)\]\)/,
    "a second way of appending a line would skip the balancing leg");
  const enter = editor.slice(editor.indexOf("function onLineEnter"), editor.indexOf("function setAmount"));
  assert.match(enter, /afterEnter\(idx, lines\.length, isBalanced\)/);
  assert.match(enter, /next\.kind === "add"\) addLine\(\)/);
});

test("an account picked on a line with no amount is offered the leg; one with an amount is left alone", () => {
  const pick = editor.slice(editor.indexOf("function pickAccount"), editor.indexOf("function addLine()"));
  assert.match(pick, /isAmountless\(l\)/);
  assert.match(pick, /balancingLeg\(prev, idx\)/);
  assert.match(editor, /onChange=\{\(id\) => pickAccount\(idx, id\)\}/);
});

test("Enter finishes a line from the amount and narration cells", () => {
  for (const label of ['aria-label="Debit"', 'aria-label="Credit"', 'aria-label="Line narration"']) {
    const at = editor.indexOf(label);
    assert.ok(at > 0, `${label} not found`);
    const tag = editor.slice(at, editor.indexOf("/>", at));
    assert.match(tag, /onKeyDown=\{\(e\) => onLineEnter\(e, idx\)\}/, `${label} has no Enter handler`);
  }
});

test("the account box offers to create a ledger and the dialog is wired", () => {
  assert.match(editor, /onCreate=\{clientId && !readOnly/);
  assert.match(editor, /<QuickAddLedger/);
  assert.match(lookup, /onCreate\?: \(label: string\)/);
  // The page hands the editor the client; without it no Create row appears.
  assert.match(page, /clientId=\{clientId\}/);
});

test("the new ledger comes back selected on the SAME line, by key", () => {
  assert.match(editor, /lineKey: line\.key/);
  assert.match(editor, /findIndex\(\(l\) => l\.key === quickAdd\.lineKey\)/);
  assert.match(editor, /pickAccount\(at, account\.id\)/);
  assert.match(editor, /setCreated\(\(prev\) => \[\.\.\.prev, account\]\)/);
});

test("the ledger is created through the account endpoint, for this client, and decides nothing", () => {
  assert.match(quick, /api\.accounting\.createAccount\(/);
  // The second argument is the client: omitting it creates a FIRM-LEVEL account
  // every client of the firm would see, which is not what a voucher means.
  assert.match(quick, /\}, clientId,\s*\) as/);
  assert.doesNotMatch(quick, /account_subtype|schedule_iii|parent_group/,
    "where an account sits on the balance sheet is not decided by finishing a voucher");
  assert.doesNotMatch(quick, /localStorage|sessionStorage/);
});

test("none of it loosens the balance rule", () => {
  // The editor still refuses locally...
  assert.match(editor, /if \(!isBalanced\) \{ setLocalError\("Debits must equal credits before saving\."\); return; \}/);
  // ...and the buttons stay disabled until the entry balances.
  const disabled = editor.match(/disabled=\{saving \|\| !isBalanced\}/g) ?? [];
  assert.equal(disabled.length, 3, "Save Correction, Save Draft and Post Entry must all stay gated");
  // The leg is OFFERED, never posted: it only ever fills a cell the CA can overtype.
  assert.doesNotMatch(editor, /onSave\(.*balancingLeg/);
});

test("the balancing arithmetic is the one amount parser's, and nothing is multiplied by 100", () => {
  const flow = read("lib", "journal", "lineFlow.ts");
  assert.match(flow, /paiseFromRupeeInput/);
  assert.match(flow, /rupeeInputFromPaise/);
  assert.doesNotMatch(flow, /\* ?100|parseFloat|Number\(/);
});

// ── the purchase bill grid ──────────────────────────────────────────────────

test("the bill grid's Enter is delegated and opt-in per cell", () => {
  assert.match(bill, /<tbody ref=\{gridRef\} onKeyDown=\{onLineGridKeyDown\}/);
  const handler = bill.slice(bill.indexOf("function onLineGridKeyDown"), bill.indexOf("// Look up catalogue items"));
  // Only a plain INPUT carrying data-cell takes part.
  assert.match(handler, /target instanceof HTMLInputElement \? target\.dataset\.cell/);
  assert.match(handler, /if \(!cell \|\| !gridRef\.current\) return;/);
  // A modified Enter is somebody's shortcut and is left alone.
  assert.match(handler, /e\.shiftKey \|\| e\.ctrlKey \|\| e\.metaKey \|\| e\.altKey/);
});

test("the cells that take part are the five plain inputs, and no picker, select or checkbox", () => {
  const cells = [...bill.matchAll(/data-cell="([A-Za-z]+)"/g)].map((m) => m[1]).sort();
  assert.deepEqual(cells, ["cessPerUnit", "cessPercent", "description", "qty", "rate"]);
  // A `data-cell` on anything that is not an <input> would be ignored by the
  // handler's own instanceof check, but it would still read as taking part.
  for (const m of bill.matchAll(/<(\w+)[^>]*data-cell=/g)) {
    assert.equal(m[1], "input", `data-cell on <${m[1]}>`);
  }
});

test("Enter on the last line adds one only when that line has something on it", () => {
  const handler = bill.slice(bill.indexOf("function onLineGridKeyDown"), bill.indexOf("// Look up catalogue items"));
  assert.match(handler, /last\.description\.trim\(\) \|\| last\.rate \|\| last\.hsn_sac \|\| last\.service_catalogue_id/);
  assert.match(handler, /addLine\(\);\s*setFocusCell\(\{ row: row \+ 1, cell \}\)/);
});
