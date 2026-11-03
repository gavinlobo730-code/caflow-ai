// POST-A-136 — narrowing the trial balance on screen to the accounts a person is looking for.
//   node --experimental-strip-types --test lib/accounting/trialBalanceFilter.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { NO_FILTER, SYNTHETIC_ACCOUNT_IDS, accountCounts, filterNotice, filterRows, filterStatementRows, isFiltering, typeChoices } from "./trialBalanceFilter.ts";

const row = (id: string, code: string, name: string, type: string) => ({ account_id: id, account_code: code, account_name: name, account_type: type });
const ROWS = [
  row("a1", "1001", "Cash in Hand", "Asset"),
  row("a2", "1002", "HDFC Bank", "Asset"),
  row("l1", "2003", "TDS Payable", "Liability"),
  row("l2", "2004", "TDS Payable - Salary", "Liability"),
  row("i1", "4001", "Sales", "Income"),
  row("__retained__", "", "Surplus brought forward", "Equity"),
];

test("no filter returns every row, the derived one included, in the server's order", () => {
  assert.deepEqual(filterRows(ROWS, NO_FILTER).map((r) => r.account_id), ["a1", "a2", "l1", "l2", "i1", "__retained__"]);
  assert.equal(isFiltering(NO_FILTER), false);
  assert.equal(isFiltering({ query: "   ", type: "" }), false, "spaces alone are not a filter");
});

test("the search matches the code or the name, ignoring case and surrounding spaces", () => {
  assert.deepEqual(filterRows(ROWS, { query: "  tds ", type: "" }).map((r) => r.account_id), ["l1", "l2"]);
  assert.deepEqual(filterRows(ROWS, { query: "2004", type: "" }).map((r) => r.account_id), ["l2"]);
  assert.deepEqual(filterRows(ROWS, { query: "HDFC", type: "" }).map((r) => r.account_id), ["a2"]);
  assert.deepEqual(filterRows(ROWS, { query: "nothing like this", type: "" }), []);
});

test("the type filter keeps only that type, and combines with the search", () => {
  assert.deepEqual(filterRows(ROWS, { query: "", type: "Asset" }).map((r) => r.account_id), ["a1", "a2"]);
  assert.deepEqual(filterRows(ROWS, { query: "bank", type: "Asset" }).map((r) => r.account_id), ["a2"]);
  assert.deepEqual(filterRows(ROWS, { query: "bank", type: "Liability" }), [], "a name in another type is not a match");
});

test("a derived row is not an account: it is drawn only when nothing is filtered", () => {
  assert.equal(filterRows(ROWS, { query: "surplus", type: "" }).length, 0, "the search cannot find a row that is not an account");
  assert.equal(filterRows(ROWS, { query: "", type: "Equity" }).length, 0);
  assert.equal(filterRows(ROWS, NO_FILTER).some((r) => r.account_id === "__retained__"), true);
});

test("the type choices are the types present, once each, in first-seen order, without the derived row's", () => {
  assert.deepEqual(typeChoices(ROWS), ["Asset", "Liability", "Income"]);
  assert.deepEqual(typeChoices([]), []);
});

test("the counts are of accounts: the derived row is neither shown nor counted", () => {
  assert.deepEqual(accountCounts(ROWS, NO_FILTER), { shown: 5, total: 5 });
  assert.deepEqual(accountCounts(ROWS, { query: "tds", type: "" }), { shown: 2, total: 5 });
  assert.deepEqual(accountCounts(ROWS, { query: "zzz", type: "" }), { shown: 0, total: 5 });
});

test("the notice says what the totals are totals of, only while a filter is on", () => {
  assert.equal(filterNotice(5, 5, NO_FILTER), null);
  assert.equal(filterNotice(2, 5, { query: "tds", type: "" }), "Showing 2 of 5 accounts. The totals below are for all 5, not only the ones shown.");
  assert.equal(filterNotice(1, 1, { query: "cash", type: "" }), "Showing 1 of 1 account. The totals below are for all 1, not only the ones shown.");
  assert.equal(filterNotice(0, 5, { query: "zzz", type: "" }), "Showing 0 of 5 accounts. The totals below are for all 5, not only the ones shown.");
});

// ── the statements keep a derived line under every filter (the review of 2-11-2026) ───────────────────────────────

const BS = [
  { account_id: "a1", account_code: "1001", account_name: "Cash in hand", account_type: "Asset" },
  { account_id: "e1", account_code: "3001", account_name: "Share capital", account_type: "Equity" },
  { account_id: "__retained__", account_code: "", account_name: "Retained Earnings / Net Profit", account_type: "Equity" },
];

test("a statement draws its derived line under every filter, because it is part of its caption's figure", () => {
  for (const filter of [{ query: "cash", type: "" }, { query: "", type: "Asset" }, { query: "nothing matches", type: "" }, { query: "retained", type: "" }]) {
    assert.ok(filterStatementRows(BS, filter).some((r) => r.account_id === "__retained__"), `hidden under ${JSON.stringify(filter)}`);
  }
});

test("a statement still narrows the real accounts exactly as the trial balance does, and with no filter draws everything", () => {
  const shown = filterStatementRows(BS, { query: "cash", type: "" }).map((r) => r.account_id);
  assert.deepEqual(shown, ["a1", "__retained__"]);
  assert.deepEqual(filterRows(BS, { query: "cash", type: "" }).map((r) => r.account_id), ["a1"], "the trial balance's own helper still hides a derived row");
  assert.deepEqual(filterStatementRows(BS, NO_FILTER).map((r) => r.account_id), ["a1", "e1", "__retained__"]);
});

test("the derived line is not an account and is not counted among them", () => {
  assert.deepEqual(accountCounts(BS, { query: "cash", type: "" }), { shown: 1, total: 2 });
});

// ── the cash-basis advance accounts are accounts: a search finds them (the review of 2-11-2026) ─────────────────────

const CASH_BASIS = [
  row("a1", "1001", "Cash in Hand", "Asset"),
  row("l1", "2003", "Trade Payables", "Liability"),
  row("__advance_customers__", "", "Advance from Customers", "Liability"),
  row("__advance_to_vendors__", "", "Advance to Vendors", "Asset"),
  row("__surplus_bf__", "", "Surplus brought forward", "Equity"),
];

test("the two advance accounts are found by their name and by their type, and are counted", () => {
  assert.deepEqual(filterRows(CASH_BASIS, { query: "advance", type: "" }).map((r) => r.account_id), ["__advance_customers__", "__advance_to_vendors__"]);
  assert.deepEqual(filterRows(CASH_BASIS, { query: "", type: "Liability" }).map((r) => r.account_id), ["l1", "__advance_customers__"]);
  assert.deepEqual(accountCounts(CASH_BASIS, { query: "advance", type: "" }), { shown: 2, total: 4 });
  assert.deepEqual(accountCounts(CASH_BASIS, NO_FILTER), { shown: 4, total: 4 });
  assert.equal(filterNotice(2, 4, { query: "advance", type: "" }), "Showing 2 of 4 accounts. The totals below are for all 4, not only the ones shown.");
});

test("the computed surplus line is still not an account beside them, and the type choices include the advance accounts' types", () => {
  assert.equal(filterRows(CASH_BASIS, { query: "surplus", type: "" }).length, 0);
  assert.equal(filterRows(CASH_BASIS, { query: "", type: "Equity" }).length, 0);
  assert.deepEqual(typeChoices(CASH_BASIS), ["Asset", "Liability"]);
  assert.deepEqual(typeChoices([row("__advance_customers__", "", "Advance from Customers", "Liability")]), ["Liability"], "a type only an advance account has is still offered");
});

test("on a statement an advance account follows the filter like any account, and a computed line is still drawn under every filter", () => {
  const rows = [CASH_BASIS[0], CASH_BASIS[2], CASH_BASIS[3], row("__retained__", "", "Retained Earnings / Net Profit", "Equity")];
  assert.deepEqual(filterStatementRows(rows, { query: "from customers", type: "" }).map((r) => r.account_id), ["__advance_customers__", "__retained__"]);
  assert.deepEqual(filterStatementRows(rows, { query: "", type: "Asset" }).map((r) => r.account_id), ["a1", "__advance_to_vendors__", "__retained__"]);
});

test("the list of synthetic accounts is the two the engine registers, and no computed line is on it", () => {
  assert.deepEqual([...SYNTHETIC_ACCOUNT_IDS].sort(), ["__advance_customers__", "__advance_to_vendors__"]);
  assert.ok(!SYNTHETIC_ACCOUNT_IDS.includes("__surplus_bf__") && !SYNTHETIC_ACCOUNT_IDS.includes("__retained__"));
});
