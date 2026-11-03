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
  {
    id: "ctrl-d-copies-the-line-and-focuses-the-copys-account",
    title: "Ctrl+D in a line's cell puts a copy of the line (account, amount) right after it and focuses the copy's Account; Ctrl+Shift+D and Ctrl+D outside the lines do nothing",
    async run(env) {
      const { page } = env;
      await openJournal(env);
      await pick(page, page.locator("#je-account-l0"), "Cash in Hand");
      await page.locator('input[aria-label="Debit"]').first().fill("125000");
      await page.locator('input[aria-label="Line narration"]').first().fill("Counter sale");
      const before = await lineCount(page);
      // outside a line's cell, and with Shift held, nothing is copied
      await page.locator("#je-narration").focus();
      await page.keyboard.press("Control+d");
      await page.locator('input[aria-label="Debit"]').first().focus();
      await page.keyboard.press("Control+Shift+D");
      await page.waitForTimeout(250);
      assert.equal(await lineCount(page), before, "a copy was made by a key that is not the chord, or outside a line");
      await page.locator('input[aria-label="Debit"]').first().focus();
      await page.keyboard.press("Control+d");
      await until(async () => (await lineCount(page)) === before + 1, "the copy to appear");
      // the copy sits right after the line it came from, carries its amount and narration, and focus is in its Account cell
      const debits = await page.locator('input[aria-label="Debit"]').evaluateAll((els) => els.map((e) => e.value));
      assert.equal(debits[0], "125000", "the original changed");
      assert.equal(debits[1], "125000", "the copy did not carry the amount, or is not the next line");
      const narrations = await page.locator('input[aria-label="Line narration"]').evaluateAll((els) => els.map((e) => e.value));
      assert.equal(narrations[1], "Counter sale", "the copy did not carry the narration");
      // the Account cells are the pickers whose id is `je-account-<line key>`; the copy's is the second one
      const accountIds = await page.evaluate(() => [...document.querySelectorAll('[id^="je-account-"]')].map((e) => e.id).filter((id) => /^je-account-l\d+$/.test(id)));
      assert.equal(accountIds.length, before + 1, `expected ${before + 1} Account cells, found ${accountIds.join(", ")}`);
      await until(async () => (await page.evaluate(() => document.activeElement?.id ?? "")) === accountIds[1], "focus to go to the copy's Account cell");
    },
  },
  {
    id: "a-five-line-journal-is-entered-from-the-keyboard-alone-and-posts-once",
    title: "a five-line balanced journal is entered with typed values, Tab and Enter alone (no mouse), and Enter on Post Entry sends exactly one entry whose debits equal its credits",
    async run(env) {
      const { page, stub } = env;
      await openJournal(env);
      // The balancing leg is carried onto each new line, so lines two to four are overtyped as debits and line five keeps the credit.
      const DEBITS = [["Purchases", "100"], ["Purchases", "200"], ["Purchases", "300"], ["Cash in Hand", "400"]];
      const typeAccount = async (line, name) => {
        // A line the keyboard added has a generated id, so the line is found by its place: the Account pickers, in order.
        await page.locator('[id^="je-account-"]').nth(line).focus();
        await page.keyboard.press("Enter");                               // the picker opens with its search box focused
        await page.keyboard.type(name);
        await page.keyboard.press("Enter");                               // the highlighted match is chosen
      };
      for (let i = 0; i < DEBITS.length; i += 1) {
        await typeAccount(i, DEBITS[i][0]);
        await page.keyboard.press("Tab");                                  // Account -> Debit (selected on focus)
        await page.keyboard.type(DEBITS[i][1]);
        await page.keyboard.press("Tab");                                  // Debit -> Credit
        await page.keyboard.press("Tab");                                  // Credit -> narration
        await page.keyboard.press("Tab");                                  // narration of the last line, out of balance: adds the next line
        await until(async () => (await lineCount(page)) === i + 2, `line ${i + 2} to be added by Tab`);
      }
      // Line five arrives with the balancing credit of 1,000.00; its account is the only thing left to say.
      await typeAccount(4, "Sales");
      assert.equal(await page.locator('input[aria-label="Credit"]').nth(4).inputValue(), "1000.00", "the balancing credit was not carried onto line five");
      // Tab to Post Entry and press Enter on it: nothing but the keyboard has touched the page since the narration was typed.
      let onPost = false;
      for (let i = 0; i < 40 && !onPost; i += 1) {
        await page.keyboard.press("Tab");
        onPost = await page.evaluate(() => /^\s*Post Entry\s*$/.test(document.activeElement?.textContent ?? ""));
      }
      assert.ok(onPost, "Tab never reached Post Entry");
      await page.keyboard.press("Enter");
      await until(() => stub.writesTo(/accounting\/journal$/, "POST").length >= 1, "the entry to be posted");
      await page.waitForTimeout(500);
      const posted = stub.writesTo(/accounting\/journal$/, "POST");
      assert.equal(posted.length, 1, `the entry was posted ${posted.length} times, not once`);
      const body = JSON.parse(posted[0].body);
      const lines = body.lines ?? body.entries ?? [];
      assert.equal(lines.length, 5, `the posted entry has ${lines.length} lines, not five: ${posted[0].body.slice(0, 300)}`);
      const sum = (key) => lines.reduce((n, l) => n + Number(l[key] ?? 0), 0);
      assert.equal(sum("debit_paise"), 100000, `debits came to ${sum("debit_paise")} paise`);
      assert.equal(sum("credit_paise"), 100000, `credits came to ${sum("credit_paise")} paise`);
    },
  },
];
