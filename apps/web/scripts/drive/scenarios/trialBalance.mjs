/**
 * Group H2: the trial balance can be narrowed to the accounts a person is looking for, and every total stays the whole ledger's
 * (POST-A-136).
 *
 * A trial balance is the ledger's accounts in one column and a practice looks for one account in it far more often than it reads it
 * through. The search box and the type filter choose which ROWS are drawn; the totals are the server's, for all of the accounts, and the
 * screen says so while a filter is on. A source guard reads that the totals are not taken from the visible rows; this drives what a CA
 * sees: the rows narrowing as they type, the sentence naming what the totals are totals of, the footer figures unchanged, "Clear"
 * bringing the rest back, and an empty result saying so instead of drawing an empty statement.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";
import { ok } from "../stub.mjs";

export const group = "trial-balance";

const LINES = [
  { account_id: "a1", account_code: "1001", account_name: "Cash in Hand", account_type: "Asset", total_debit_paise: 500_000, total_credit_paise: 0 },
  { account_id: "a2", account_code: "1002", account_name: "HDFC Bank", account_type: "Asset", total_debit_paise: 2_500_000, total_credit_paise: 0 },
  { account_id: "l1", account_code: "2003", account_name: "TDS Payable", account_type: "Liability", total_debit_paise: 0, total_credit_paise: 300_000 },
  { account_id: "l2", account_code: "2004", account_name: "TDS Payable - Salary", account_type: "Liability", total_debit_paise: 0, total_credit_paise: 200_000 },
  { account_id: "i1", account_code: "4001", account_name: "Sales", account_type: "Income", total_debit_paise: 0, total_credit_paise: 2_500_000 },
];
const TOTAL = 3_000_000;

async function atTheTrialBalance(env) {
  env.stub.route({
    method: "GET", re: /accounting\/trial-balance/,
    reply: () => ok({ lines: LINES, total_debit_paise: TOTAL, total_credit_paise: TOTAL, is_balanced: true, start_date: null, period_gap: null }),
  });
  await env.page.goto(env.at("/accounting/?tab=trial"), { waitUntil: "networkidle" });
  await env.page.getByText("HDFC Bank").waitFor();
}

const accountRows = (page) => page.locator("tbody tr").filter({ has: page.locator("td.font-mono") });
const footer = (page) => page.locator("tfoot").first().innerText();

export const scenarios = [
  {
    id: "typing-narrows-the-rows-and-the-totals-stay-the-whole-ledgers",
    title: "typing tds leaves the two TDS accounts, the sentence names what the totals are totals of, the footer figures do not move, and Clear brings every account back",
    async run(env) {
      const { page } = env;
      await atTheTrialBalance(env);
      assert.equal(await accountRows(page).count(), 5, "every account should be listed before anything is typed");
      const before = await footer(page);
      assert.equal(await page.getByRole("status").filter({ hasText: /Showing/ }).count(), 0, "a sentence about a filter showed with no filter on");

      await page.locator("#tb-search").fill("tds");
      await until(async () => (await accountRows(page).count()) === 2, "the list to narrow to the two TDS accounts");
      const notice = page.getByRole("status").filter({ hasText: /Showing 2 of 5 accounts/ });
      await notice.waitFor();
      assert.match(await notice.innerText(), /The totals below are for all 5, not only the ones shown\./);
      assert.equal(await footer(page), before, "the footer totals changed with the search: they must be the whole ledger's");

      await page.getByRole("button", { name: "Clear", exact: true }).click();
      await until(async () => (await accountRows(page).count()) === 5, "every account to come back");
      assert.equal(await page.getByRole("status").filter({ hasText: /Showing/ }).count(), 0, "the sentence stayed after Clear");
      assert.equal(await page.locator("#tb-search").inputValue(), "", "the search box kept its text after Clear");
    },
  },
  {
    id: "the-type-filter-narrows-and-combines-with-the-search",
    title: "choosing Asset leaves the two asset accounts; typing bank beside it leaves one; a name in another type leaves none and says so",
    async run(env) {
      const { page } = env;
      await atTheTrialBalance(env);
      await page.locator("#tb-type").selectOption("Asset");
      await until(async () => (await accountRows(page).count()) === 2, "the list to narrow to the asset accounts");
      await page.locator("#tb-search").fill("bank");
      await until(async () => (await accountRows(page).count()) === 1, "the list to narrow to the bank");
      assert.ok((await page.locator("tbody").innerText()).includes("HDFC Bank"));

      await page.locator("#tb-type").selectOption("Liability");
      await page.getByText("No account matches.").waitFor();
      assert.equal(await accountRows(page).count(), 0, "an account was drawn although none matched");
      await page.getByRole("button", { name: "Clear the search" }).click();
      await until(async () => (await accountRows(page).count()) === 5, "every account to come back");
      assert.equal(await page.locator("#tb-type").inputValue(), "", "the type filter kept its choice after the search was cleared");
    },
  },
  {
    id: "the-search-and-the-type-have-names",
    title: "the search box and the type filter are announced by name",
    async run(env) {
      const { page } = env;
      await atTheTrialBalance(env);
      await page.getByLabel("Search accounts by code or name").waitFor();
      await page.getByLabel("Account type").waitFor();
    },
  },
];
