// The client Reports hub is a DIRECTORY (its own module comment says so) —
// every card is a promise about what the screen behind it shows. Two of those
// promises had drifted from the screen: the "Chart of Accounts" card promised
// a balance column the Accounts tab has never rendered, and the "Journal"
// card's description never named the separate Day Book tab where auto-posted
// entries actually live.
//
// Run with:
//   node --experimental-strip-types --test scripts/reports-hub-copy-matches-the-tabs-it-links-to.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const HUB = fs.readFileSync(path.join(WEB, "app/clients/[id]/reports/page.tsx"), "utf8");
const ACCOUNTING = fs.readFileSync(path.join(WEB, "app/clients/[id]/accounting/page.tsx"), "utf8");

test("the Accounts tab really does render no balance column, which is the premise of the next test", () => {
  // ChartOfAccounts's own column list — Code, Account, Type, Subtype, Scope.
  // If a balance column is ever added there, the hub's card is allowed to
  // promise one again, and this is the test that would need updating first.
  const start = ACCOUNTING.indexOf("function ChartOfAccounts(");
  const end = ACCOUNTING.indexOf("function JournalList(");
  const body = ACCOUNTING.slice(start, end);
  assert.ok(!/header:\s*"Balance"/i.test(body),
    "the Accounts tab grew a Balance column — the hub's card can name it now");
});

test("the Chart of Accounts card no longer promises a balance the tab does not show", () => {
  const coa = HUB.match(/\{ id: "coa",[\s\S]*?\},/)?.[0] ?? "";
  assert.ok(coa.length > 0, "the coa card entry moved or was renamed");
  assert.ok(!/its balance/i.test(coa),
    "the card still promises a balance column the Accounts tab does not have");
});

test("the Journal card names the Day Book tab, where auto-posted entries actually are", () => {
  const journal = HUB.match(/\{ id: "journal",[\s\S]*?\},/)?.[0] ?? "";
  assert.ok(journal.length > 0, "the journal card entry moved or was renamed");
  assert.match(journal, /Day Book/,
    "the Journal card's description does not say where auto-posted entries appear");
});

test("Day Book is a real tab on the Accounting page the Journal card can point a CA to", () => {
  assert.match(ACCOUNTING, /\{ id: "day-book",\s*label: "Day Book" \}/,
    "the Day Book tab this card references does not exist under that id");
});
