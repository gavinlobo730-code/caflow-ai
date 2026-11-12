/**
 * A DRAFT DELIVERY CHALLAN IS CORRECTED AND CANCELLED FROM ITS PANEL (POST-A-417).
 *
 * A challan is made as a draft whose Rule 55(1) particulars are optional, and the server will not issue it without them. The amendment door took the consignee, the kind of goods and the place of
 * supply but DROPPED a line, and no screen called it for a draft, so a challan that lacked a particular was made again under a new number while the draft kept its own. This is the browser's half
 * (`apps/api/tests/test_a_draft_delivery_challans_lines_are_corrected_in_words_and_hsn_code_only.py` is the server's):
 *
 *   * the correction form and the two buttons exist for a DRAFT only, and the tab never says a draft cannot be edited;
 *   * the form sends one inline body, with no status and no spread, carrying only what changed, and a line by its id with a changed description and/or HSN code and nothing else of a line;
 *   * a box that held a value and is empty now (the ones the door reads a blank as "unchanged" for) is said before a request is sent, and an HSN box can be emptied;
 *   * the form holds no sentence of the server's: it judges no GSTIN, no state code, no HSN;
 *   * a cancel asks in the shared dialog (never a browser pop-up), goes through its own wrapper, which sends the cancelled status and nothing else, and says a refusal beside the button.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const read = (p: string) => readFileSync(path.join(WEB, p), "utf8");
const strip = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, " ").replace(/^\s*\/\/.*$/gm, " ");

const tab = strip(read("components/sales/SalesCycleTab.tsx"));
const editorRaw = read("components/sales/DraftChallanEditor.tsx");
const editor = strip(editorRaw);
const api = read("lib/api/index.ts");

test("the strip does not make the scan vacuous", () => {
  assert.ok(editor.includes("DraftChallanEditor") && tab.includes("DraftChallanEditor"));
  assert.ok(editorRaw.length - editor.length > 800, "there were comments to strip");
});

test("the form and the two buttons are for a draft only", () => {
  // the form is drawn only while it is open AND the open detail is a draft
  assert.match(tab, /\{correcting && vocab && detail\?\.challan && detail\.challan\.status === "draft" && \(\s*<DraftChallanEditor/, "the form is drawn for a challan that is not a draft");
  // both buttons sit inside the block that is drawn for a draft's detail
  const block = /\{detail\.challan && detail\.challan\.status === "draft" && \([\s\S]*?\n              \)\}/.exec(tab)?.[0] ?? "";
  assert.ok(block.length > 300, "the draft's block was not found");
  assert.match(block, /onClick=\{\(\) => setCorrecting\(true\)\}[\s\S]*?Correct draft/, "Correct draft is not in the draft's block");
  assert.match(block, /onClick=\{\(\) => cancelDraft\(detail\.challan as DeliveryChallan\)\}[\s\S]*?Cancel draft/, "Cancel draft is not in the draft's block");
  assert.equal((tab.match(/>\s*Correct draft\s*</g) ?? []).length, 1);
  assert.equal((tab.match(/>\s*Cancel draft\s*</g) ?? []).length, 1);
  // closing the detail, opening another and changing tab all close the form and clear the answer: an open form is never carried to another challan
  assert.equal((tab.match(/setCorrecting\(false\)/g) ?? []).length >= 4, true, "the form is not closed on every way out of the detail");
  assert.equal((tab.match(/setCancelAnswer\(null\)/g) ?? []).length >= 4, true, "a refusal to a cancel is not cleared on every way out of the detail");
});

test("every detail the tab opens is given its list of lines, so the correction form never maps a missing one", () => {
  const all = tab.match(/objectWithLists<ChallanParticulars>\(/g) ?? [];
  const withLines = tab.match(/objectWithLists<ChallanParticulars>\(r\.data, "copies", "missing", "particulars", "lines"\)/g) ?? [];
  assert.ok(all.length >= 2, "the tab opens a detail from fewer places than it did");
  assert.equal(withLines.length, all.length, "a detail is opened without its lines made a list");
});

test("no sentence in the product says a draft cannot be edited on this screen", () => {
  assert.ok(!/not edited on this screen/.test(tab), "the tab still says a draft is not edited here");
  assert.ok(!/not edited on this screen/.test(editor));
});

test("the form sends one inline body: no status, no spread, a line by its id with only its description and HSN code", () => {
  const calls = editor.match(/api\.salesCycle\.updateChallan\(/g) ?? [];
  assert.equal(calls.length, 1, "the form must reach the amendment door from one place");
  const call = /api\.salesCycle\.updateChallan\(challan\.id, clientId, \{([\s\S]*?)\n      \}\);/.exec(editor)?.[1] ?? "";
  assert.ok(call.length > 200, "the request body was not found");
  assert.ok(!/\bstatus\b/.test(call), "the correction asks for a status");
  assert.ok(!/\.\.\./.test(call), "the body spreads another object, which can carry a key this rule cannot see");
  for (const key of ["consignee_name", "consignee_gstin", "consignee_address", "goods_kind", "place_of_supply", "lines"]) {
    assert.match(call, new RegExp(`${key}:`), `${key} is not sent`);
  }
  // each box is sent only when it CHANGED, and the kind of goods and the place of supply only where the draft has them
  assert.match(call, /goods_kind: jobWork && kind !== wasKind \? kind : undefined/);
  assert.match(call, /place_of_supply: challan\.is_inter_state && place !== wasPlace \? place : undefined/);
  assert.match(call, /consignee_gstin: gstin !== wasGstin \? gstin\.trim\(\) : undefined/);
  // (an unchanged box is `undefined` and leaves the request)
  assert.equal((call.match(/: undefined/g) ?? []).length >= 7, true, "a box is sent whether or not it changed");
  // a line carries its id and the two fields, and nothing else of a line
  const line = /changedLines\.map\(\(l\) => \(\{([\s\S]*?)\}\)\)/.exec(call)?.[1] ?? "";
  assert.match(line, /id: l\.id/);
  assert.match(line, /description:/);
  assert.match(line, /hsn_sac:/);
  assert.ok(!/quantity|unit|rate|tax|gst_rate/.test(line), "a line is sent with more than its description and HSN code");
});

test("a box that held a value and is empty now is said before anything is sent, and the HSN box can be emptied", () => {
  const fn = /function removedBoxes\(\)[\s\S]*?\n  \}/.exec(editor)?.[0] ?? "";
  assert.match(fn, /wasGstin && !gstin\.trim\(\)/, "an emptied GSTIN is not caught");
  assert.match(fn, /wasPlace && !place\.trim\(\)/, "an emptied place of supply is not caught");
  assert.match(fn, /wasKind && !kind\.trim\(\)/, "an emptied kind of goods is not caught");
  assert.ok(!/hsn/i.test(fn), "an emptied HSN box is refused, and the server clears it");
  const save = /async function save\(\)[\s\S]*?\n  \}/.exec(editor)?.[0] ?? "";
  const judged = save.indexOf("removedBoxes()");
  assert.ok(judged >= 0, "the emptied boxes are never asked about before a save");
  assert.ok(judged < save.indexOf("updateChallan("), "the emptied box is judged after the request is sent");
  assert.match(editor, /be emptied here: type the new value/, "the sentence is not said");
  assert.match(save, /Nothing was changed\./, "a Save with nothing changed is not said");
  // an edit of a line alone is a change (the central use: an HSN code added to a draft that had none)
  assert.match(editor, /const anyChange = [^;]*lines\.some\(lineChanged\);/, "a correction of a line alone is not counted as a change");
  assert.match(save, /Nothing was changed\./, "a Save with nothing changed is not said");
});

test("the form judges nothing: no GSTIN rule, no state list, no HSN rule and none of the server's sentences", () => {
  for (const banned of [/is not a code/, /keeps a description/, /check digit/i, /VALID_STATE_CODES/, /\^\[0-9\]/, /\\d\{/, /gstin\.ts/, /hsn_digits/, /is not a line of challan/, /corrected twice/]) {
    assert.ok(!banned.test(editor), `the form holds ${banned}`);
  }
  assert.match(editor, /res\.error \|\| "That was refused\."/, "a refusal is not the server's sentence");
  assert.match(editor, /role="alert"/, "a refusal is not said as an alert");
});

test("closing is held while a save is out, so a refusal is not lost to a dialog that went away", () => {
  assert.match(editor, /const \[saving, setSaving\] = useState\(false\)/);
  assert.match(editor, /const close = \(\) => \{ if \(!saving\) onClose\(\); \};/);
  assert.match(editor, /onClose=\{close\}/, "Escape and the backdrop reach onClose, not close");
  assert.match(editor, /onClick=\{close\}/, "the Close button reaches onClose, not close");
  const save = /async function save\(\)[\s\S]*?\n  \}/.exec(editor)?.[0] ?? "";
  assert.ok(save.indexOf("setSaving(true)") > -1 && save.indexOf("setSaving(true)") < save.indexOf("updateChallan("), "saving is not set before the request");
  assert.match(save, /finally \{\s*setSaving\(false\);/, "saving is not cleared when the answer is a refusal");
});

test("the form is the shared modal and its boxes are labelled", () => {
  assert.match(editor, /<Modal\b/);
  assert.ok(!/window\.(confirm|alert|prompt)|\bconfirm\(|\balert\(/.test(editor), "a browser pop-up");
  for (const label of ["Consignee name", "Consignee GSTIN", "Consignee address"]) assert.match(editor, new RegExp(`aria-label="${label}"`));
  assert.match(editor, /aria-label=\{`Line \$\{i \+ 1\} description`\}/);
  assert.match(editor, /aria-label=\{`Line \$\{i \+ 1\} HSN code`\}/);
  assert.match(editor, /<StateLookup placeOfSupply[\s\S]*?ariaLabel="Place of supply"/);
});

test("a cancel asks in the shared dialog first, goes through its own wrapper and says a refusal beside the button", () => {
  const fn = /async function cancelDraft\(challan: DeliveryChallan\)[\s\S]*?\n  \}/.exec(tab)?.[0] ?? "";
  assert.ok(fn.length > 300, "cancelDraft was not found");
  assert.ok(fn.indexOf("confirmDialog(") > -1 && fn.indexOf("confirmDialog(") < fn.indexOf("api.salesCycle.cancelChallan("), "the cancel is sent before it is asked");
  assert.match(fn, /danger: true/);
  assert.match(fn, /if \(!ok\) return;/, "Keep it does not stop the cancel");
  assert.match(fn, /res\.error \|\| "That was refused\."/);
  assert.equal((tab.match(/api\.salesCycle\.cancelChallan\(/g) ?? []).length, 1, "a challan is cancelled from more than one place");
  assert.ok(!/window\.(confirm|alert|prompt)|\bconfirm\(/.test(tab), "a browser pop-up");
  // the wrapper sends the cancelled status and nothing else
  assert.match(api, /cancelChallan: \(id: string, clientId: string\) =>[\s\S]*?body: JSON\.stringify\(\{ status: "cancelled" \}\)/, "the wrapper sends more than the cancelled status");
  assert.match(tab, /cancelAnswer\.text\}<\/p>/, "a refusal to a cancel is not said beside the button");
});

test("the amendment wrapper is still never given a status: the one status the screen asks for has its own wrapper", () => {
  for (const file of ["components/sales/SalesCycleTab.tsx", "components/sales/DraftChallanEditor.tsx"]) {
    const text = strip(read(file));
    for (const m of text.matchAll(/api\.salesCycle\.updateChallan\(([^;]*?)\);/g)) {
      assert.ok(!/\bstatus\b/.test(m[1]), `${file}: the amendment door is asked for a status`);
    }
  }
});
