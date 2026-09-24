// A customer's credit limit, on the screens — SALES-25 (b), migration 414.
//
// It is a COMMERCIAL term and not a statutory one: no Act sets it and it
// changes no figure on the invoice, its tax or its journal. `domain/sales/
// credit_limit.py` is the rule and says so on every answer; these assert that
// the browser can RECORD one, SEE where a customer stands, and never decides
// any of it itself.
//
// WHAT IS ASSERTED
//   1. The customer form can record it, and BLANK is carried as null rather
//      than parsed to 0 — "no limit" and "cash only" are different answers and
//      the column is nullable precisely so they can be told apart.
//   2. The amount goes through the one money parser. `Math.round(parseFloat(x)
//      * 100)` on a figure typed the Indian way records Rs 1.
//   3. The invoice editor ASKS before the CA saves, not only after. A screen
//      must never invite somebody to type what the server will refuse.
//   4. The firm's block switch is OFF in the form's own defaults.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const WEB = path.resolve(import.meta.dirname, "..");
const read = (p: string) => fs.readFileSync(path.join(WEB, p), "utf8");

test("the customer form records a limit and carries blank as null", () => {
  const src = read("components/customers/CustomerFormModal.tsx");
  assert.match(src, /credit_limit_paise: creditLimitPaise/,
    "the form does not send the limit");
  assert.match(src, /creditLimit\.trim\(\) === ""\s*\n?\s*\?\s*null/,
    "blank must be sent as null. Parsing it to 0 would put the customer on " +
    "the strictest possible terms — 0 is a real limit meaning cash only");
});

test("the typed amount goes through the one money parser", () => {
  const src = read("components/customers/CustomerFormModal.tsx");
  assert.match(src, /paiseFromRupeeInput\(creditLimit\)/);
  const code = src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:])\/\/[^\n]*/g, "$1");
  assert.doesNotMatch(code, /parseFloat\(creditLimit/,
    "parseFloat('1,25,000') is 1 — a CA typing the amount the way Indian " +
    "amounts are grouped would record one rupee");
});

test("the invoice editor asks before the save, not only after", () => {
  const src = read("components/invoices/InvoiceEditor.tsx");
  assert.match(src, /sales-invoices\/credit-position/,
    "the editor never asks where the customer stands, so the first the CA " +
    "hears of a limit is the server's answer to a save");
  assert.match(src, /credit_limit\?\.state === "would_exceed"/,
    "the save result's assessment is not read");
});

test("the panel shows a limit only where one is recorded", () => {
  const src = read("components/invoices/InvoiceEditor.tsx");
  assert.match(src, /creditPosition\.state !== "not_set"/,
    "`not_set` is the answer for every customer nobody has set a limit for, " +
    "and a line saying so on all of them is a line the CA stops reading");
});

test("the firm's block switch is off in the settings form's own defaults", () => {
  const src = read("app/settings/invoice-settings/page.tsx");
  assert.match(src, /credit_limit_blocks: false,/,
    "blocking must be opt-in: a block stops a CA recording a supply that has " +
    "already happened");
  assert.match(src, /credit_limit_blocks: form\.credit_limit_blocks,/,
    "the toggle is rendered but never sent — the ACC-06 shape");
});
