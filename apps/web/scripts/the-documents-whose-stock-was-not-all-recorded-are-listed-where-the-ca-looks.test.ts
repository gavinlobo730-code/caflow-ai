// POST-A-092 — the documents whose stock was not all recorded reach the CA, and the CA can complete them.
//
// Run with:
//   node --experimental-strip-types --test scripts/the-documents-whose-stock-was-not-all-recorded-are-listed-where-the-ca-looks.test.ts
//
// WHAT WAS WRONG
//     A sales invoice, purchase bill, credit note or debit note moves stock AFTER it is issued, and a failure there never un-issues it. The
//     response that issued it said so once, on the screen that issued it, and the only advice was to adjust stock by hand or to cancel
//     the document. Nothing found the document again afterwards. Migration 579 counts them in the database; this panel lists them and asks
//     the server to complete one.
//
// THE RULES, NOT SPELLINGS
//     * the Inventory tab renders the panel;
//     * the panel reads the finder and the retry endpoint and nothing else (no second data path, no table of its own);
//     * a failed read is SAID, never rendered as an empty panel: an empty panel means "every goods document has its stock";
//     * the list is read through objectWithLists, not trusted;
//     * the panel decides nothing: no arithmetic of its own on a figure, no date arithmetic, no stock rule; the result of a retry is the
//       server's own sentence;
//     * the one write goes through the shared single-flight Button, so a second click is ignored while one retry is working;
//     * a list cut at the server's limit says how many more there are.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const PANEL = path.join("components", "inventory", "UnrecordedStockPanel.tsx");

function code(rel: string): string {
  return fs.readFileSync(path.join(WEB, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/^\s*\/\/.*$/gm, " ");
}

test("the Inventory tab renders the panel for the client", () => {
  const src = code(path.join("app", "clients", "[id]", "inventory", "page.tsx"));
  assert.match(src, /<UnrecordedStockPanel\b[^>]*clientId=\{clientId\}/);
});

test("the panel reads the finder and the retry and nothing else", () => {
  const src = code(PANEL);
  assert.match(src, /api\.inventory\.unrecordedStock\(/);
  assert.match(src, /api\.inventory\.retryStockEffect\(/);
  assert.doesNotMatch(src, /supabase|\.from\(/, "no second data path");
  const api = code(path.join("lib", "api", "index.ts"));
  assert.match(api, /\/api\/inventory\/stock-effects\/unrecorded\?/);
  assert.match(api, /\/api\/inventory\/stock-effects\/retry`/);
});

test("a failed read is said in words, never rendered as an empty panel", () => {
  const src = code(PANEL);
  assert.match(src, /Couldn(&apos;|')t check which documents have unrecorded stock/);
  assert.match(src, /role="alert"/);
  assert.match(src, /catch \{[\s\S]{0,120}setFailed\(true\)/);
  assert.match(src, /setFailed\(got === null\)/);
});

test("the list is read through objectWithLists, not trusted", () => {
  assert.match(code(PANEL), /objectWithLists<UnrecordedStock>\([^)]*"documents"/);
});

test("the panel decides nothing: no arithmetic on a figure, no date arithmetic, and the retry's sentence is shown as it came", () => {
  const src = code(PANEL);
  assert.doesNotMatch(src, /Math\.|\*\s*100|\/\s*100|new Date\(|Date\.now|parseFloat|parseInt|Number\(/);
  assert.match(src, /text: r\.data\.message/, "the server's sentence, not a sentence of the screen's");
  assert.match(src, /r\.error \|\|/);
});

test("a refusal the client threw is shown in the server's own words, not replaced by a sentence of the screen's", () => {
  const src = code(PANEL);
  assert.match(src, /catch \(e\) \{[\s\S]{0,400}e instanceof Error && e\.message\.trim\(\) \? e\.message/);
});

test("the write asks first, in the shared dialog, and warns about a hand adjustment", () => {
  const src = code(PANEL);
  assert.match(src, /await confirmDialog\(\{/);
  assert.match(src, /already adjusted this[\s"+]*stock by hand/);
  assert.match(src, /if \(!sure\) return;[\s\S]{0,80}setBusy\(d\.document_id\)/, "the question comes before anything is sent");
  assert.doesNotMatch(src, /window\.confirm|\bconfirm\(/, "no browser pop-up");
});

test("a document that carries no goods line is not rendered as a problem", () => {
  assert.match(code(PANEL), /ok: r\.data\.recorded !== false/);
});

test("the one write goes through the shared single-flight button", () => {
  const src = code(PANEL);
  assert.match(src, /useSingleFlight\(\)/);
  assert.match(src, /<Button[\s\S]{0,200}flight=\{flight\}/);
  assert.match(src, /disabled=\{busy !== null\}/);
});

test("a list cut at the server's limit says how many more there are", () => {
  assert.match(code(PANEL), /found\.total > found\.documents\.length/);
});
