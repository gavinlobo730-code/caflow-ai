// The P&L Statement on /reports says how much of each total is credit and debit notes, from the server's own figures, and says
// nothing when the server did not say (POST-A-502, migration 766).
//
// Run with:
//   node --experimental-strip-types --test scripts/the-pl-statement-says-how-much-of-its-figures-is-credit-and-debit-notes.test.ts
//
// WHAT WAS WRONG. The statement added invoices and bills and nothing else, so a month with a sales credit note showed more
// revenue than the books hold. The server now nets the four CGST section 34 notes as the ledger posts them; the screen's job
// is to SAY so, in words, next to the totals it draws, so a reader is never left to wonder whether a figure is net of a note.
//
// THE RULES (a screen says what it read, what it did not, and never shows an unknown as a value):
//   1. each sentence is drawn from the server's field and only when that field is a number: an answer from before the
//      migration lacks the keys, and "not read" is not nil;
//   2. the browser adds nothing: no note field appears in an arithmetic expression (the server's answer is drawn as it comes);
//   3. the three sentences exist: net of notes to customers, net of notes from suppliers, and "no notes were issued".
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const read = (rel: string) => fs.readFileSync(path.join(WEB, rel), "utf8");
const PAGE = read("app/reports/page.tsx");
const API = read("lib/api/index.ts");

test("the answer's three note keys are optional in the type, because an answer from before the migration lacks them", () => {
  assert.match(API, /revenue_notes_paise\?: number; expense_notes_paise\?: number; note_documents\?: number;/);
});

test("each sentence is drawn only from a figure the server sent, and says what it is net of", () => {
  assert.match(PAGE, /typeof t\.revenue_notes_paise === "number" && t\.revenue_notes_paise !== 0/);
  assert.match(PAGE, /typeof t\.expense_notes_paise === "number" && t\.expense_notes_paise !== 0/);
  assert.match(PAGE, /t\.note_documents === 0/);
  assert.match(PAGE, /Net of the credit and debit notes issued to customers in this period: \{formatPaise\(t\.revenue_notes_paise\)\}/);
  assert.match(PAGE, /Net of the debit and credit notes received from suppliers in this period: \{formatPaise\(t\.expense_notes_paise\)\}/);
  assert.match(PAGE, /No credit or debit notes were issued in this period\./);
});

test("the browser adds nothing to the server's note figures", () => {
  const arithmetic = /\bt\.(revenue_notes_paise|expense_notes_paise|note_documents)\s*[-+*/]|[-+*/]\s*t\.(revenue_notes_paise|expense_notes_paise|note_documents)\b/;
  assert.doesNotMatch(PAGE, arithmetic, "a note figure is used in arithmetic in the browser");
  assert.doesNotMatch(PAGE, /revenue_total_paise\s*[-+]|expense_total_paise\s*[-+]/, "a total is re-derived in the browser");
});
