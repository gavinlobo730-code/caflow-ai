// POST-A-136 — narrowing the trial balance on screen to the accounts a person is looking for.
//   node --experimental-strip-types --test lib/accounting/trialBalanceFilter.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { NO_FILTER, accountCounts, filterNotice, filterRows, isFiltering, typeChoices } from "./trialBalanceFilter.ts";

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
