/**
 * Group O: the journal editor is finished from the keyboard (POST-A-128, the journal half of the Tally habit).
 *
 * Enter already finished a line (`lib/journal/lineFlow.afterEnter`). The same hand that Tabs now gets the same answer: Tab from the last
 * line's narration adds the next line, carrying the balancing leg, WHILE the entry is out of balance, and a balanced entry never grows a
 * line nobody asked for. An amount cell selects its text on focus, so a balancing figure the screen offered is overtyped and not edited
 * in the middle. The pure rule is unit-tested; this drives what a person's keys do in a real page.
 */
import assert from "node:assert/strict";
import { ok } from "../stub.mjs";
import { pick, until } from "../kit.mjs";

export const group = "journal-keys";

async function openJournal(env) {
  const { page, stub } = env;
  stub.route({ method: "POST", re: /accounting\/journal$/, reply: () => ok({ id: "j-1" }) });
  await page.goto(env.at("/accounting/journal/new/edit/"), { waitUntil: "networkidle" });
  await page.waitForSelector("#je-narration");
  await page.fill("#je-narration", "Being cash sale");
}

const lineCount = (page) => page.locator('input[aria-label="Debit"]').count();

export const scenarios = [
  {
    id: "tab-from-the-last-narration-adds-a-line-while-the-entry-is-out-of-balance",
    title: "Tab from the last line's narration adds the next line, with the balancing leg, and focuses its Account",
    async run(env) {
      const { page } = env;
      await openJournal(env);
      await pick(page, page.locator("#je-account-l0"), "Cash in Hand");
      await page.locator('input[aria-label="Debit"]').first().fill("125000");
      const before = await lineCount(page);
      await page.locator('input[aria-label="Line narration"]').last().focus();
      await page.keyboard.press("Tab");
      await until(async () => (await lineCount(page)) === before + 1, "the next line to be added by Tab");
      // The new line carries what balances the entry (₹1,25,000 on the credit side) and focus is in its Account cell.
      assert.equal(await page.locator('input[aria-label="Credit"]').last().inputValue(), "125000.00", "the balancing leg did not arrive");
      const inAccount = await page.evaluate(() => (document.activeElement?.id ?? "").startsWith("je-account-"));
      assert.ok(inAccount, "focus did not go to the new line's Account cell");
    },
  },
  {
    id: "tab-from-the-last-narration-of-a-balanced-entry-adds-nothing",
    title: "a balanced entry does not grow a line when the last narration is Tabbed out of, and Shift+Tab never adds one",
    async run(env) {
      const { page } = env;
      await openJournal(env);
      await pick(page, page.locator("#je-account-l0"), "Cash in Hand");
      await page.locator('input[aria-label="Debit"]').first().fill("125000");
      await pick(page, page.locator("#je-account-l1"), "Sales");
      // l1 arrived carrying the balancing credit, so the entry balances
      assert.equal(await page.locator('input[aria-label="Credit"]').last().inputValue(), "125000.00");
      const before = await lineCount(page);
      await page.locator('input[aria-label="Line narration"]').last().focus();
      await page.keyboard.press("Tab");
      await page.waitForTimeout(250);
      assert.equal(await lineCount(page), before, "a balanced entry grew a line on Tab");
      // Unbalance it, then Shift+Tab from the same cell: going back is never a request for a line.
      await page.locator('input[aria-label="Debit"]').first().fill("100");
      await page.locator('input[aria-label="Line narration"]').last().focus();
      await page.keyboard.press("Shift+Tab");
      await page.waitForTimeout(250);
      assert.equal(await lineCount(page), before, "Shift+Tab added a line");
    },
  },
  {
    id: "an-amount-cell-selects-its-text-when-focused",
    title: "focusing an amount cell selects what is in it, so the pre-filled balancing figure is overtyped",
    async run(env) {
      const { page } = env;
      await openJournal(env);
      await pick(page, page.locator("#je-account-l0"), "Cash in Hand");
      await page.locator('input[aria-label="Debit"]').first().fill("125000");
      await pick(page, page.locator("#je-account-l1"), "Sales");           // the credit arrives as 125000.00
      const credit = page.locator('input[aria-label="Credit"]').last();
      await credit.focus();
      const selection = await credit.evaluate((el) => ({ start: el.selectionStart, end: el.selectionEnd, length: el.value.length }));
      assert.deepEqual(selection, { start: 0, end: selection.length, length: selection.length }, "the amount was not selected on focus");
      assert.ok(selection.length > 0, "the cell was empty: there was nothing to select");
      await page.keyboard.type("90000");
      assert.equal(await credit.inputValue(), "90000", "typing did not replace the selected figure");
    },
  },
];
