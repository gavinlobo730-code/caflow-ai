// POST-A-092 — the invoices the ledger and the invoice list disagree about reach the CA.
//
// Run with:
//   node --experimental-strip-types --test scripts/the-invoices-the-ledger-and-the-list-disagree-about-are-listed-where-the-ca-looks.test.ts
//
// WHAT WAS WRONG
//     Issuing an invoice posted its journal entry and then, in a second statement, marked it issued. A failure between the two left a
//     draft with revenue and output tax already in the ledger; `GET /api/sales-invoices/maintenance/unposted` (the other direction)
//     had no screen caller either. Migration 577 makes the issue one transaction, so it cannot leave that behind; invoices an earlier
//     issue left behind, and issued invoices with no entry, are what this panel lists.
//
// THE RULES, NOT SPELLINGS
//     * the Sales Invoices tab renders the panel;
//     * the panel reads the two maintenance endpoints and nothing else (no second data path);
//     * a failed read is SAID, never rendered as an empty panel: an empty panel means "the books and the list agree";
//     * the lists are read through objectWithLists, not trusted;
//     * "nothing in the way" (an empty list) and "not asked" (null) are different statements and are rendered differently;
//     * the panel decides nothing: no arithmetic on a figure, no date arithmetic, no rule of its own;
//     * the one write (posting an entry) goes through the shared single-flight Button, so a second click is ignored.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const PANEL = path.join("components", "invoices", "UnfinishedInvoicesPanel.tsx");

function code(rel: string): string {
  return fs.readFileSync(path.join(WEB, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/^\s*\/\/.*$/gm, " ");
}

test("the Sales Invoices tab renders the panel", () => {
  const src = code(path.join("app", "clients", "[id]", "sales", "page.tsx"));
  assert.match(src, /<UnfinishedInvoicesPanel\b[^>]*clientId=\{clientId\}/);
  assert.match(src, /tab === "invoices"[\s\S]{0,400}<UnfinishedInvoicesPanel\b/);
});

test("the panel reads the two maintenance endpoints and nothing else", () => {
  const src = code(PANEL);
  assert.match(src, /api\.salesInvoices\.postedDrafts\(/);
  assert.match(src, /api\.salesInvoices\.unposted\(/);
  assert.doesNotMatch(src, /supabase|\.from\(/, "no second data path");
});

test("a failed read is said in words, never rendered as an empty panel", () => {
  const src = code(PANEL);
  assert.match(src, /Couldn(&apos;|')t check whether the ledger and the invoice list agree/);
  assert.match(src, /role="alert"/);
  assert.match(src, /catch \{[\s\S]{0,120}setFailed\(true\)/);
  assert.match(src, /setFailed\(gotDrafts === null \|\| gotUnposted === null\)/);
});

test("both lists are read through objectWithLists, not trusted", () => {
  const src = code(PANEL);
  assert.match(src, /objectWithLists<PostedDrafts>\([^)]*"drafts"/);
  assert.match(src, /objectWithLists<Unposted>\([^)]*"unposted"/);
});

test("nothing in the way and not asked are two statements", () => {
  const src = code(PANEL);
  assert.match(src, /d\.blockers === null/);
  assert.match(src, /d\.blockers\.length === 0/);
  assert.match(src, /Not checked/);
});

test("the panel decides nothing: no arithmetic on a figure and no date arithmetic", () => {
  const src = code(PANEL);
  assert.doesNotMatch(src, /new Date\(|Date\.now\(|getTime\(|86_?400/);
  assert.doesNotMatch(src, /_paise\s*[-+*/]\s*|[-+*/]\s*\w+\.\w*_paise/, "a figure is shown as the server sent it");
});

test("the one write goes through the shared single-flight button", () => {
  const src = code(PANEL);
  assert.match(src, /useSingleFlight\(\)/);
  assert.match(src, /<Button[\s\S]{0,200}flight=\{flight\}/);
  assert.match(src, /api\.salesInvoices\.repostJournal\(/);
  assert.doesNotMatch(src, /<button[^>]*onClick=\{\(\) => repost/, "a raw button would take a second click");
});

test("the server's refusal of a repost is shown as the server said it", () => {
  const src = code(PANEL);
  assert.match(src, /setSaid\(r\.error \|\|/);
});
