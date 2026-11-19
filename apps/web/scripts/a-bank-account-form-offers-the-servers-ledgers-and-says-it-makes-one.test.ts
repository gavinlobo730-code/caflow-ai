// The add-a-bank-account form. Run with:
//   node --experimental-strip-types --test scripts/a-bank-account-form-offers-the-servers-ledgers-and-says-it-makes-one.test.ts
//
// WHAT WAS WRONG (POST-A-492; the owner, 18-11-2026: "the ledger is not created automatically, we have to do it manually")
//   The route creates a ledger named "<bank> — <last four digits>" when the form names none, but the form's box said
//   "— Not linked —" with help text telling the person to link an account, and offered every asset and liability ledger read
//   straight from the database, "Cash in Hand" among them. So a person chose one by hand, and could choose a cash ledger.
//
// THE RULE, as the source states it: the form's default says it creates a ledger and shows the name the server says it will
// get; the choices come from the server's list (which leaves out cash ledgers and ledgers of other bank accounts), never from a
// chart read in the browser. The rule itself is tests/test_a_bank_account_gets_a_ledger_of_its_own_or_is_not_saved.py.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const WEB = join(import.meta.dirname, "..");
const read = (rel: string) => readFileSync(join(WEB, rel), "utf8");

test("the form's default option says a ledger is created, with the name the server gave", () => {
  const s = read("components/banking/AccountsPanel.tsx");
  assert.match(s, /Create a new ledger for this account\$\{newLedgerName \? ` — “\$\{newLedgerName\}”` : ""\}/);
  assert.doesNotMatch(s, /Links this bank account to a chart-of-accounts asset account/, "the sentence that told a person to link one is gone");
  assert.match(s, /a cash ledger cannot be used/);
});

test("the choices are the server's list, and the form reads no chart of accounts of its own", () => {
  const s = read("components/banking/AccountsPanel.tsx");
  assert.match(s, /api\.banking\.ledgerChoices\(/);
  assert.match(s, /setNewLedgerName\(res\.data\?\.new_ledger_name \?\? null\)/);
  assert.doesNotMatch(s, /\.from\("chart_of_accounts"\)/);
  const api = read("lib/api/index.ts");
  assert.match(api, /\/api\/banking\/accounts\/ledger-choices\?/);
});
