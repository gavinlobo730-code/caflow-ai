// apex-sales-purchases-06: the three-way-match panel on the Purchase Cycle
// tab was a bare `<input placeholder="Purchase bill id">` — a CA had to copy
// a raw UUID by hand — and PurchaseBillViewDrawer offered no "match against
// order" action at all.
//
// THE FIX
//     The raw input is replaced by an EntityLookup, the same pattern the
//     note editors already use, searching this client's purchase_bills by
//     bill number, our_reference, vendor name and date (searchPurchaseBills).
//     PurchaseBillViewDrawer gained a "Match against order" action that hands
//     the bill id off to the Purchase Cycle tab via ?tab=purchase-cycle
//     &matchBill=<id> — the same window.history.replaceState convention the
//     page's own ?tab=/?doc= deep-link effect already reacts to (ACC-22) —
//     rather than a prop threaded through PurchaseBills/PurchasesPage.
//
// Run with:
//   node --experimental-strip-types --test scripts/three-way-match-has-a-bill-picker.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");

function read(rel: string): string {
  return fs.readFileSync(path.join(WEB, rel), "utf8");
}

const TAB_SRC = stripComments(read("components/purchases/PurchaseCycleTab.tsx"));
const DRAWER_SRC = stripComments(read("components/purchases/PurchaseBillViewDrawer.tsx"));

test("the raw 'Purchase bill id' text input is gone", () => {
  assert.doesNotMatch(TAB_SRC, /placeholder="Purchase bill id"/);
  assert.doesNotMatch(TAB_SRC, /<input\s+value=\{matchBillId\}/);
});

test("EntityLookup is imported and wired to search purchase bills", () => {
  assert.match(TAB_SRC, /import \{ EntityLookup \} from "@\/components\/lookups\/EntityLookup";/);
  assert.match(TAB_SRC, /<EntityLookup<BillMatchOption>/);
  assert.match(TAB_SRC, /fetchOptions=\{\(q\) => searchPurchaseBills\(clientId, q\)\}/);
});

test("searchPurchaseBills searches by bill number, our_reference, vendor name and date", () => {
  const m = /async function searchPurchaseBills\([\s\S]*?\n\}/.exec(TAB_SRC);
  assert.ok(m, "searchPurchaseBills not found");
  const body = m[0];
  assert.match(body, /bill_no\.ilike\.%\$\{query\}%,our_reference\.ilike\.%\$\{query\}%/);
  assert.match(body, /\.from\("vendors"\)\.select\("id"\)/);
  assert.match(body, /\.ilike\("name", `%\$\{query\}%`\)/);
  assert.match(body, /dateMatch/);
  assert.match(body, /\.gte\("bill_date", dateRange\.gte\)\.lte\("bill_date", dateRange\.lte\)/);
  // Bounded, per CLAUDE.md's reporting-performance rule — no unpaged read of
  // the whole register just to power a picker.
  assert.match(body, /\.limit\(20\)/);
});

test("PurchaseBillViewDrawer offers a 'Match against order' action", () => {
  assert.match(DRAWER_SRC, /<Action onClick=\{\(\) => matchAgainstOrder\(bill\.id\)\} icon=\{<GitCompare size=\{12\} \/>\}>\s*\n\s*Match against order/);
});

test("matchAgainstOrder hands the bill id off via ?tab=purchase-cycle&matchBill=", () => {
  const m = /function matchAgainstOrder\(billId: string\) \{([\s\S]*?)\n  \}/.exec(DRAWER_SRC);
  assert.ok(m, "matchAgainstOrder not found");
  const body = m[1];
  assert.match(body, /p\.set\("tab", "purchase-cycle"\);/);
  assert.match(body, /p\.set\("matchBill", billId\);/);
  assert.match(body, /window\.history\.replaceState/);
  assert.match(body, /onClose\(\);/);
});

test("PurchaseCycleTab reads ?matchBill= once, runs the match, and strips the param", () => {
  assert.match(TAB_SRC, /const matchBillParam = useSearchParams\(\)\.get\("matchBill"\);/);
  const m = /useEffect\(\(\) => \{\s*\n\s*if \(!matchBillParam\) return;([\s\S]*?)\n\s*\}, \[matchBillParam\]\);/.exec(TAB_SRC);
  assert.ok(m, "the ?matchBill= hand-off effect was not found");
  const body = m[1];
  assert.match(body, /setMatchBillId\(matchBillParam\);/);
  assert.match(body, /void runMatch\(matchBillParam\);/);
  assert.match(body, /p\.delete\("matchBill"\);/);
});

test("runMatch accepts an explicit id, for the hand-off, without breaking the manual Match button", () => {
  assert.match(TAB_SRC, /async function runMatch\(id\?: string\) \{/);
  assert.match(TAB_SRC, /const target = \(id \?\? matchBillId\)\.trim\(\);/);
  // The manual button still calls it with no argument, reading the picker's
  // own state.
  assert.match(TAB_SRC, /onClick=\{\(\) => void runMatch\(\)\}/);
});
