// A year-end adjustment names its two accounts by PICKING them, and sends the account's id. Run with:
//   node --experimental-strip-types --test scripts/the-year-end-adjustment-names-an-account-by-picking-it.test.ts
//
// WHAT WAS WRONG (PRE-A-019, found by the twelfth slice of the browser drive)
//     The form's Debit Account and Credit Account boxes were plain text ("e.g. 5001 / Salary Expense") and the page sent what was typed, while
//     `year_end_adjustments.debit_account_id` and `credit_account_id` are uuid (migration 293) and a row's account must be the client's own or a
//     firm-level one (migration 570). So a code or a name was refused by the database ("That is not a valid id."): as built, the form could only be
//     saved by someone who typed an account's id. The list showed the raw id too.
//
// THE RULE (about what the screen sends, not about a component's name)
//     No text box in the adjustment form is labelled as an account; both accounts are chosen with the shared account picker over the client's chart,
//     the picker is fed what the database accepts (the client's accounts and the firm-level ones, active only), and the list names an account
//     instead of printing its id.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");
const PAGE = "app/clients/[id]/year-end/[engagementId]/adjustments/_page.tsx";
const src = () => stripComments(fs.readFileSync(path.join(WEB, PAGE), "utf8"));

test("neither account is a free-text box, and both are the shared account picker", () => {
  const s = src();
  assert.doesNotMatch(s, /<input\s+aria-label="(Debit|Credit) Account"/, "an account is typed as text again, where the column holds an id");
  for (const which of ["Debit", "Credit"]) {
    assert.match(s, new RegExp(`<AccountLookup[^>]*ariaLabel="${which} Account"`, "s"), `${which} Account is not the account picker`);
  }
});

test("the picker is fed the client's accounts and the firm-level ones, active only, and the list names an account", () => {
  const s = src();
  assert.match(s, /\.from\("chart_of_accounts"\)/);
  assert.match(s, /\.or\(`client_id\.eq\.\$\{clientId\},client_id\.is\.null`\)/, "the picker is not limited to the client's accounts and the firm-level ones");
  assert.match(s, /\.eq\("is_active", true\)/);
  assert.match(s, /adj\.debit_account_name \?\? accountLabel\(adj\.debit_account_id\)/, "the list prints an account's id");
  assert.match(s, /adj\.credit_account_name \?\? accountLabel\(adj\.credit_account_id\)/, "the list prints an account's id");
});

test("the request carries the chosen ids, and the date box hints at the engagement's own year without refusing", () => {
  const s = src();
  assert.match(s, /debit_account_id: debitAccount\.trim\(\)/);
  assert.match(s, /credit_account_id: creditAccount\.trim\(\)/);
  assert.match(s, /min=\{fyBounds\?\.start\}/);
  assert.match(s, /max=\{fyBounds\?\.end\}/);
  assert.doesNotMatch(s, /afterMax/, "a date outside the engagement's year is a hint (a reversal on 1 April is a real entry), not a refusal");
});
