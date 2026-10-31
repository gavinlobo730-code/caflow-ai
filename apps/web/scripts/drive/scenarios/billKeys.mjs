/**
 * Group P: the purchase bill's line grid is finished from the keyboard (POST-A-128, the bill half of the Tally habit).
 *
 * Enter already moved down a column and added a line. Tab from a line's LAST data cell (the rate, or the last cess cell where the grid shows
 * cess) now goes to the next line's description, adding the line when it is the last and has something on it, instead of walking to the
 * Remove button past a read-only Amount. A blank last line leaves Tab alone, and Shift+Tab is never intercepted. The pure rule is
 * unit-tested (lib/purchases/billGridFlow); this drives what a person's keys do in a real page.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";

export const group = "bill-keys";

async function openBill(env) {
  await env.page.goto(env.at("/purchases/bills/new/edit/"), { waitUntil: "networkidle" });
  await env.page.waitForSelector('input[aria-label="Line 1 description"]');
}

const lineCount = (page) => page.locator('input[data-cell="description"]').count();
const focusedLabel = (page) => page.evaluate(() => document.activeElement?.getAttribute("aria-label") ?? "");

export const scenarios = [
  {
    id: "tab-from-the-last-cell-of-the-last-line-adds-a-line-and-focuses-its-description",
    title: "Tab from the rate of a bill's only line, once it has a description, adds the next line and focuses its description",
    async run(env) {
      const { page } = env;
      await openBill(env);
      await page.fill('input[aria-label="Line 1 description"]', "Printer paper");
      await page.fill('input[aria-label="Line 1 rate"]', "500");
      assert.equal(await lineCount(page), 1);
      await page.locator('input[aria-label="Line 1 rate"]').focus();
      await page.keyboard.press("Tab");
      await until(async () => (await lineCount(page)) === 2, "the next line to be added by Tab");
      await until(async () => (await focusedLabel(page)) === "Line 2 description", "focus to land in the new line's description");
    },
  },
  {
    id: "tab-from-the-last-cell-of-an-earlier-line-goes-to-the-next-lines-description",
    title: "Tab from the rate of a line that is not the last goes to the next line's description and adds nothing",
    async run(env) {
      const { page } = env;
      await openBill(env);
      await page.fill('input[aria-label="Line 1 description"]', "Printer paper");
      await page.locator('input[aria-label="Line 1 rate"]').focus();
      await page.keyboard.press("Tab");                                   // adds line 2
      await until(async () => (await lineCount(page)) === 2, "line 2 to exist");
      await page.locator('input[aria-label="Line 1 rate"]').focus();
      await page.keyboard.press("Tab");
      await until(async () => (await focusedLabel(page)) === "Line 2 description", "focus to go to line 2's description");
      assert.equal(await lineCount(page), 2, "a Tab from an earlier line added a line");
    },
  },
  {
    id: "tab-on-an-untouched-blank-last-line-is-left-alone",
    title: "Tab from the rate of a blank last line adds no line (the keyboard is not a way to grow the bill) and moves as the browser does",
    async run(env) {
      const { page } = env;
      await openBill(env);
      await page.locator('input[aria-label="Line 1 rate"]').focus();
      await page.keyboard.press("Tab");
      await page.waitForTimeout(250);
      assert.equal(await lineCount(page), 1, "Tab on a blank last line grew the bill");
      assert.notEqual(await focusedLabel(page), "Line 2 description");
    },
  },
  {
    id: "shift-tab-never-adds-a-line",
    title: "Shift+Tab from the rate of the last line, which has something on it, adds no line",
    async run(env) {
      const { page } = env;
      await openBill(env);
      await page.fill('input[aria-label="Line 1 description"]', "Printer paper");
      await page.locator('input[aria-label="Line 1 rate"]').focus();
      await page.keyboard.press("Shift+Tab");
      await page.waitForTimeout(250);
      assert.equal(await lineCount(page), 1, "Shift+Tab added a line");
    },
  },
  {
    id: "tab-from-a-middle-cell-is-the-browsers",
    title: "Tab from the quantity (not the line's last cell) adds no line and does not skip to the next line",
    async run(env) {
      const { page } = env;
      await openBill(env);
      await page.fill('input[aria-label="Line 1 description"]', "Printer paper");
      await page.locator('input[aria-label="Line 1 quantity"]').focus();
      await page.keyboard.press("Tab");
      await page.waitForTimeout(250);
      assert.equal(await lineCount(page), 1, "Tab from a middle cell added a line");
      assert.match(await focusedLabel(page), /^Line 1 /, "Tab from the quantity left the line it is on");
    },
  },
];
