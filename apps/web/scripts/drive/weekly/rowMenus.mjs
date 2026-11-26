/**
 * A ROW'S "MORE" MENU IS THE SHARED ONE (POST-A-130, ninth step), driven in a browser.
 *
 * Eight row menus on the Sales and Purchases screens were a menu plus an invisible layer over the whole window that caught the click
 * closing it. From the keyboard the menu opened with focus left on the row's button behind the layer, Escape did nothing, and the first
 * click anywhere was swallowed, another row's own button included. Each is `components/ui/row-menu` now. The source guard holds all eight;
 * this drives the invoice list's, the customer list's and the bill list's:
 *
 *   1. opened from the keyboard, focus is on the menu's first action; ArrowDown, ArrowUp, End and Home move between its actions; Escape
 *      closes it and focus is back on the row's button, which says it is collapsed again;
 *   2. with one row's menu open, ONE click on another row's button opens that row's menu (the layer used to eat the click), and a click
 *      on the button that opened a menu only closes it;
 *   3. an action that opens a dialog gives focus back to the ROW'S button when the dialog closes (it used to go nowhere: the action it
 *      came from had gone with the menu);
 *   4. a click on the page outside closes the menu, and nothing covers the window while a menu is open;
 *   5. the bill list's menu, on the Purchases screen, the same from the keyboard.
 *
 * No scenario has a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";
import { CUSTOMER, invoiceRow, billRow } from "../fixtures.mjs";

export const group = "row-menus";

const menu = (page) => page.locator("[data-row-menu]");
const focusedText = (page) => page.evaluate(() => (document.activeElement?.textContent ?? "").trim());
const focusIsOn = (locator) => locator.evaluate((el) => el === document.activeElement);

async function atTwoDraftInvoices(env) {
  const { page, stub } = env;
  const a = invoiceRow("draft", "inv-9");
  const b = { ...invoiceRow("draft", "inv-8"), invoice_no: "INV-0008" };
  stub.setTable("client_sales_invoices", [a, b]);
  await page.goto(env.at("/sales/"), { waitUntil: "networkidle" });
  const first = page.getByLabel(`Actions for invoice ${a.invoice_no}`);
  const second = page.getByLabel(`Actions for invoice ${b.invoice_no}`);
  await first.waitFor();
  await second.waitFor();
  return { a, b, first, second };
}

export const scenarios = [
  {
    id: "a-row-menu-opened-from-the-keyboard-takes-focus-moves-by-the-arrows-and-gives-focus-back-on-escape",
    title: "Sales > an invoice's menu from the keyboard: focus lands on its first action, the arrow keys, End and Home move between actions, Escape closes it and focus returns to the row's button",
    async run(env) {
      const { page } = env;
      const { first } = await atTwoDraftInvoices(env);
      assert.equal(await first.getAttribute("aria-haspopup"), "true", "the row's button does not say it opens something");
      assert.equal(await first.getAttribute("aria-expanded"), "false", "the row's button says its menu is open before it is");
      await first.focus();
      await page.keyboard.press("Enter");
      await menu(page).waitFor();
      assert.equal(await menu(page).getAttribute("role"), "group");
      assert.ok((await menu(page).getAttribute("aria-label"))?.trim(), "the menu has no name");
      assert.equal(await first.getAttribute("aria-expanded"), "true", "the row's button does not say its menu is open");
      await until(async () => (await focusedText(page)) === "View details", "focus to land on the menu's first action");
      await page.keyboard.press("ArrowDown");
      assert.equal(await focusedText(page), "Edit draft", "ArrowDown did not move to the next action");
      await page.keyboard.press("End");
      assert.equal(await focusedText(page), "Delete draft", "End did not move to the last action");
      await page.keyboard.press("ArrowDown");
      assert.equal(await focusedText(page), "View details", "ArrowDown on the last action did not come round to the first");
      await page.keyboard.press("ArrowUp");
      assert.equal(await focusedText(page), "Delete draft", "ArrowUp on the first action did not go round to the last");
      await page.keyboard.press("Home");
      assert.equal(await focusedText(page), "View details", "Home did not move to the first action");
      await page.keyboard.press("Escape");
      await menu(page).waitFor({ state: "detached" });
      assert.equal(await focusIsOn(first), true, "focus did not return to the row's button on Escape");
      assert.equal(await first.getAttribute("aria-expanded"), "false", "the row's button still says its menu is open");
    },
  },
  {
    id: "one-click-on-another-rows-button-opens-that-rows-menu-and-the-opening-button-closes-its-own",
    title: "Sales: with one invoice's menu open, ONE click on another row's button opens that row's menu; a click on the button that opened a menu closes it and does not open it again",
    async run(env) {
      const { page } = env;
      const { first, second } = await atTwoDraftInvoices(env);
      // The LOWER row's menu first: it drops below its own row, so the upper row's button is clear of the menu itself.
      await second.click();
      await menu(page).waitFor();
      assert.equal(await second.getAttribute("aria-expanded"), "true");
      // Nothing covers the window while a menu is open: the other row's button is what a click at its place reaches.
      const reached = await first.evaluate((el) => {
        const r = el.getBoundingClientRect();
        const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
        return !!hit && (hit === el || el.contains(hit));
      });
      assert.equal(reached, true, "something covers the other row's button while a menu is open");
      await first.click();
      await until(async () => (await first.getAttribute("aria-expanded")) === "true", "the other row's menu to open on ONE click");
      assert.equal(await menu(page).count(), 1, "two menus are open");
      assert.equal(await second.getAttribute("aria-expanded"), "false", "the lower row's button still says its menu is open");
      // The button that opened it: one click closes, and the same click does not open it again.
      await first.click();
      await menu(page).waitFor({ state: "detached" });
      await new Promise((r) => setTimeout(r, 250));
      assert.equal(await menu(page).count(), 0, "the click that closed the menu opened it again");
      assert.equal(await first.getAttribute("aria-expanded"), "false");
    },
  },
  {
    id: "an-action-that-opens-a-dialog-gives-focus-back-to-the-rows-button-when-the-dialog-closes",
    title: "Sales > a draft's menu > Delete draft, then Escape on the dialog: focus is on the row's button, not lost; and a click on the page outside an open menu closes it",
    async run(env) {
      const { page } = env;
      const { first } = await atTwoDraftInvoices(env);
      await first.focus();
      await page.keyboard.press("Enter");
      await menu(page).waitFor();
      await page.keyboard.press("End");
      assert.equal(await focusedText(page), "Delete draft");
      await page.keyboard.press("Enter");
      const dialog = page.getByRole("dialog", { name: "Delete draft invoice?", exact: true });
      await dialog.waitFor();
      assert.equal(await menu(page).count(), 0, "the menu stayed open behind the dialog");
      await until(() => dialog.evaluate((d) => d.contains(document.activeElement)), "focus to move into the dialog");
      await page.keyboard.press("Escape");
      await dialog.waitFor({ state: "detached" });
      assert.equal(await focusIsOn(first), true, "focus did not return to the row's button after the dialog closed");

      await first.click();
      await menu(page).waitFor();
      // A click on the page outside (the screen's own tab, already chosen) closes it, and the click is the tab's as usual.
      await page.getByRole("button", { name: "Sales Invoices", exact: true }).first().click();
      await menu(page).waitFor({ state: "detached" });
    },
  },
  {
    id: "the-customer-lists-menu-and-the-bill-lists-menu-work-from-the-keyboard",
    title: "Sales > Customers and Purchases > Bills: each row's menu opens from the keyboard with focus on its first action, and Escape gives focus back to the row's button",
    async run(env) {
      const { page, stub } = env;
      stub.setTable("customers", [CUSTOMER]);
      await page.goto(env.at("/sales/"), { waitUntil: "networkidle" });
      await page.getByRole("button", { name: "Customers", exact: true }).first().click();
      const customer = page.getByLabel(`Actions for ${CUSTOMER.name}`);
      await customer.waitFor();
      await customer.focus();
      await page.keyboard.press("Enter");
      await menu(page).waitFor();
      await until(() => menu(page).evaluate((m) => m.contains(document.activeElement) && document.activeElement !== m), "focus to land on an action of the customer's menu");
      await page.keyboard.press("Escape");
      await menu(page).waitFor({ state: "detached" });
      assert.equal(await focusIsOn(customer), true, "focus did not return to the customer row's button");

      stub.setTable("purchase_bills", [billRow("draft", "b9")]);
      await page.goto(env.at("/purchases/?tab=bills"), { waitUntil: "networkidle" });
      const bill = page.getByLabel(/Actions for bill/).first();
      await bill.waitFor();
      await bill.focus();
      await page.keyboard.press("Enter");
      await menu(page).waitFor();
      await until(async () => (await focusedText(page)) === "View details", "focus to land on the bill menu's first action");
      await page.keyboard.press("ArrowDown");
      assert.notEqual(await focusedText(page), "View details", "ArrowDown did not move in the bill's menu");
      await page.keyboard.press("Escape");
      await menu(page).waitFor({ state: "detached" });
      assert.equal(await focusIsOn(bill), true, "focus did not return to the bill row's button");
    },
  },
];
