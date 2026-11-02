/**
 * Group S: the Balance Sheet's search, driven in a browser (POST-A-136).
 *
 * The source guard holds that no figure is taken from the rows drawn; this proves what a person SEES in Chromium against a stubbed server:
 * a search chooses which account rows are drawn under their captions and nothing else. Every caption keeps its heading and its whole
 * figure, the totals do not move, a sentence says so, and Clear brings the rows back.
 *
 *   1. with no filter, every account is drawn and there is no sentence;
 *   2. a search for "bank" draws the bank and not the cash account, and says "Showing 1 of 5 accounts. Each caption's figure and every
 *      total are for all 5, not only the ones shown.";
 *   3. while it is on, the caption's figure (the sum of its accounts, cash AND bank) and the total assets are the same figures as before;
 *   4. a search that matches nothing draws no account row, keeps every caption and total, and Clear brings everything back.
 */
import assert from "node:assert/strict";
import { ok } from "../stub.mjs";

export const group = "statement-filter";

const BALANCE_SHEET = /api\/accounting\/balance-sheet(\?|$)/;
const line = (id, code, name, caption, paise) => ({ account_id: id, account_code: code, account_name: name, schedule_iii_caption: caption, balance_paise: paise });

const DATA = {
  assets: [{ label: "Assets", total_paise: 1_000_000, lines: [
    line("a-cash", "1001", "Cash in hand", "Cash and Cash Equivalents", 100_000),
    line("a-bank", "1002", "HDFC Bank", "Cash and Cash Equivalents", 400_000),
    line("a-debt", "1100", "Sundry debtors", "Trade Receivables", 500_000)] }],
  liabilities: [{ label: "Liabilities", total_paise: 300_000, lines: [line("l-cred", "2001", "Sundry creditors", "Trade Payables", 300_000)] }],
  equity: [{ label: "Equity", total_paise: 700_000, lines: [line("e-cap", "3001", "Share capital", "Share Capital", 700_000)] }],
  total_assets_paise: 1_000_000,
  total_liabilities_equity_paise: 1_000_000,
  is_balanced: true,
};

async function atTheBalanceSheet(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: BALANCE_SHEET, reply: () => ok(DATA) });
  await page.goto(env.at("/accounting/?tab=balance-sheet"), { waitUntil: "networkidle" });
  await page.getByText("Cash in hand", { exact: true }).waitFor();
}

const search = (page) => page.getByRole("searchbox", { name: "Search accounts by code or name" });
/** The text of the table row whose first cell is exactly `label`. */
const rowText = async (page, label) => (await page.locator("tr", { has: page.getByText(label, { exact: true }) }).first().innerText()).replace(/\s+/g, " ");
const SENTENCE = (shown) => `Showing ${shown} of 5 accounts. Each caption's figure and every total are for all 5, not only the ones shown.`;

export const scenarios = [
  {
    id: "with-no-filter-every-account-is-drawn-and-nothing-is-said",
    title: "no filter: every account row, no sentence, no Clear",
    async run(env) {
      const { page } = env;
      await atTheBalanceSheet(env);
      for (const name of ["Cash in hand", "HDFC Bank", "Sundry debtors", "Sundry creditors", "Share capital"]) {
        assert.ok(await page.getByText(name, { exact: true }).isVisible(), `${name} is not drawn with no filter`);
      }
      assert.equal(await page.getByText(/^Showing \d+ of \d+ accounts?\./).count(), 0, "a sentence appears with no filter on");
      assert.equal(await page.getByRole("button", { name: "Clear", exact: true }).count(), 0, "Clear shows with no filter on");
    },
  },
  {
    id: "a-search-draws-the-matching-rows-and-leaves-every-figure-whole",
    title: "searching 'bank' draws HDFC Bank and not Cash in hand; the caption's figure and the total do not move; the sentence says so",
    async run(env) {
      const { page } = env;
      await atTheBalanceSheet(env);
      const captionBefore = await rowText(page, "Cash and Cash Equivalents");
      const totalBefore = await rowText(page, "Total Assets");
      assert.match(captionBefore, /5,000\.00/, `the caption's figure is cash plus bank (Rs 5,000.00): ${captionBefore}`);
      await search(page).fill("bank");
      await page.getByText("Cash in hand", { exact: true }).waitFor({ state: "detached" });
      assert.ok(await page.getByText("HDFC Bank", { exact: true }).isVisible(), "the matching account is not drawn");
      assert.ok(!(await page.getByText("Sundry debtors", { exact: true }).isVisible().catch(() => false)), "a non-matching account is drawn");
      assert.equal(await rowText(page, "Cash and Cash Equivalents"), captionBefore, "the caption's figure moved with the filter");
      assert.equal(await rowText(page, "Total Assets"), totalBefore, "the total moved with the filter");
      assert.ok(await page.getByText(SENTENCE(1)).isVisible(), "the sentence is missing or wrong");
    },
  },
  {
    id: "a-search-that-matches-nothing-keeps-every-caption-and-total-and-clear-restores-the-rows",
    title: "no match: no account rows, every caption and total kept; Clear brings the rows back",
    async run(env) {
      const { page } = env;
      await atTheBalanceSheet(env);
      const totalBefore = await rowText(page, "Total Assets");
      await search(page).fill("zzz-no-such-account");
      await page.getByText("Cash in hand", { exact: true }).waitFor({ state: "detached" });
      assert.equal(await rowText(page, "Total Assets"), totalBefore);
      for (const caption of ["Cash and Cash Equivalents", "Trade Receivables", "Trade Payables", "Share Capital"]) {
        assert.ok(await page.getByText(caption, { exact: true }).isVisible(), `the caption ${caption} was hidden by the search`);
      }
      assert.ok(await page.getByText(SENTENCE(0)).isVisible(), "an empty result does not say 0 of 5");
      await page.getByRole("button", { name: "Clear", exact: true }).click();
      await page.getByText("Cash in hand", { exact: true }).waitFor();
      assert.equal(await search(page).inputValue(), "");
      assert.equal(await page.getByText(/^Showing \d+ of \d+ accounts?\./).count(), 0, "the sentence stays after Clear");
    },
  },
];
