// A company credit card can be created, and the form does not decide what one
// is (BANK-21).
//
// Run with:
//   node --experimental-strip-types --test scripts/a-credit-card-is-an-account-you-can-create.test.ts
//
// WHAT WAS WRONG
//     The account-type picker hardcoded Current / Savings / Cash Credit /
//     Overdraft, the same four the database CHECK allowed. So a company card
//     could not be created at all: its statement could not be imported, its
//     spend could not be coded through the bank workflow, and the monthly card
//     payment out of the current account posted to whatever ledger somebody
//     picked.
//
// THE RULE, WHICH IS THE DURABLE HALF
//     The type decides whether the account's ledger is an ASSET or a
//     LIABILITY, and for a card which way up its balance reads. Both are the
//     engine's answers — domain/banking/account_kind.py — so the form offers
//     what the engine knows and labels the field with what the engine said.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const PANEL = "components/banking/AccountsPanel.tsx";

function code(rel: string): string {
  return fs.readFileSync(path.join(WEB, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/^\s*\/\/.*$/gm, " ");
}

test("the picker offers what the engine knows", () => {
  const src = code(PANEL);
  assert.match(src, /api\.banking\.bankAccountTypes\(\)/,
    "the vocabulary is served — the type decides the LEDGER, so a picker "
    + "offering a value the engine has never heard of creates the wrong one");
  assert.match(src, /accountTypes\.length \? accountTypes\.map/,
    "the hardcoded list must be a FALLBACK, reached only for the redeploy window");
});

test("the fallback list carries the card, so the window is not a regression", () => {
  const src = code(PANEL);
  const m = src.match(/const FALLBACK_ACCOUNT_TYPES = \[([\s\S]*?)\]/);
  assert.ok(m, "the fallback list is missing");
  const values = [...m[1].matchAll(/"([^"]+)"/g)].map(x => x[1]);
  assert.deepEqual(values,
    ["Current", "Savings", "Cash Credit", "Overdraft", "Credit Card"],
    "the fallback must match apps/api/domain/banking/account_kind.ACCOUNT_TYPES");
});

test("the balance field is labelled by the server, not by the browser", () => {
  const src = code(PANEL);
  assert.match(src, /balance_label/,
    "a card's opening balance is an amount OWED and a bank's is a balance — "
    + "which one is the engine's answer");
  assert.doesNotMatch(src, /accountType === "Credit Card"/,
    "the screen must not decide what a credit card is");
});

test("nothing here flips a sign", () => {
  // The store holds LEDGER sign and the API translates at its own boundary.
  // A second conversion in the browser would double back on itself.
  const src = code(PANEL);
  assert.doesNotMatch(src, /-\s*(openingBal|opening_balance_paise)/,
    "the API hands back the sign the CA reads; negating again inverts it");
});
