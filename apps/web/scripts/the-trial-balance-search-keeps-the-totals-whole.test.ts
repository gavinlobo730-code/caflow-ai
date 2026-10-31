// The trial balance can be narrowed to the accounts a person is looking for, and every total stays the whole ledger's (POST-A-136).
//
// WHAT WAS MISSING
//   The Trial Balance tab listed every account with no way to find one in it. The July 2026 audit asked for an account search and a type
//   filter. The risk in adding one is that the figures under it quietly become the figures of the rows left on screen: a trial balance
//   whose footer says it is balanced over a handful of accounts is a false statement. So the search chooses which rows are DRAWN, every
//   total is the server's (or a sum of ALL the rows), and the screen says so in a sentence whenever a filter is on.
//
// WHAT THIS HOLDS FROM THE BROWSER'S SIDE
//   * the rows drawn come from the filter, and nothing that adds up money is taken from the drawn rows;
//   * the filter module holds no money at all (it narrows rows by code, name and type);
//   * the sentence naming what the totals are totals of is shown whenever a filter is on;
//   * the two controls are announced by name, an empty result says so and offers to clear, and a search does not follow the CA to the
//     next client.
//
// Run with: node --experimental-strip-types --test scripts/the-trial-balance-search-keeps-the-totals-whole.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");
const read = (rel: string) => stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));

const PAGE = read("app/clients/[id]/accounting/page.tsx");
const FILTER = read("lib/accounting/trialBalanceFilter.ts");

/** The source of the TrialBalance component: from its declaration to the next top-level function. */
function trialBalance(): string {
  const at = PAGE.indexOf("function TrialBalance(");
  assert.ok(at >= 0, "function TrialBalance was not found");
  const rest = PAGE.slice(at);
  const next = rest.slice(10).search(/\nfunction [A-Za-z]/);
  return next === -1 ? rest : rest.slice(0, next + 10);
}

test("the files are where this guard thinks they are", () => {
  assert.ok(PAGE.length > 100000 && FILTER.length > 1500 && trialBalance().length > 4000, "a file read as nearly empty");
});

test("the rows drawn come from the filter and the table body maps nothing else", () => {
  const tb = trialBalance();
  assert.ok(/const visibleRows = useMemo\(\(\) => filterRows\(rows, filter\), \[rows, filter\]\)/.test(tb), "the visible rows are not the filter's");
  assert.ok(/\{visibleRows\.map\(\(r\) =>/.test(tb), "the table body does not draw the visible rows");
  assert.ok(!/\{rows\.map\(\(r\) =>/.test(tb), "the table body still draws every row, so the filter changes nothing");
});

test("nothing that adds up money is taken from the rows drawn", () => {
  const tb = trialBalance();
  assert.ok(!/visibleRows\.reduce/.test(tb) && !/visibleRows\.filter\(/.test(tb), "a total is taken from the visible rows");
  assert.ok(/const openingTotals = useMemo\(\(\) => rows\.reduce\(/.test(tb), "the opening totals are no longer a sum of ALL the rows");
  assert.ok(/const periodTotals = useMemo\(\(\) => rows\.reduce\(/.test(tb), "the period totals are no longer a sum of ALL the rows");
  assert.ok(/const grandDebit = totals\.debit;/.test(tb) && /const grandCredit = totals\.credit;/.test(tb), "the closing totals are no longer the server's");
  assert.ok(/formatPaise\(grandDebit\)/.test(tb) && /formatPaise\(grandCredit\)/.test(tb), "the footer does not print the server's totals");
});

test("the filter module holds no money: it narrows rows by code, name and type", () => {
  assert.ok(!/paise/i.test(FILTER), "the filter module reads an amount");
  assert.ok(!/Math\./.test(FILTER) && !/\.reduce\(/.test(FILTER), "the filter module adds something up");
});

test("while a filter is on, the screen says what the totals are totals of", () => {
  const tb = trialBalance();
  assert.ok(/const filterSentence = filterNotice\(accountsShown\.shown, accountsShown\.total, filter\)/.test(tb), "the sentence is not the module's");
  assert.ok(/\{filterSentence && <p role="status"/.test(tb), "the sentence is not shown (and announced) when a filter is on");
  assert.ok(/The totals below are for all \$\{total\}, not only the ones shown\./.test(FILTER), "the sentence does not say the totals are for all of the accounts");
});

test("the two controls are named, an empty result says so, and a search does not follow the CA to the next client", () => {
  const tb = trialBalance();
  assert.ok(/<label htmlFor="tb-search"[^>]*>Search accounts by code or name<\/label>/.test(tb) && /<input id="tb-search" type="search"/.test(tb), "the search box has no name");
  assert.ok(/<label htmlFor="tb-type"[^>]*>Account type<\/label>/.test(tb) && /<select id="tb-type"/.test(tb), "the type filter has no name");
  assert.ok(/No account matches\./.test(tb) && /Clear the search/.test(tb), "an empty result is not said, or cannot be cleared");
  assert.ok(/useEffect\(\(\) => \{ setFilter\(NO_FILTER\); \}, \[clientId\]\)/.test(tb), "a search is carried to the next client");
});
