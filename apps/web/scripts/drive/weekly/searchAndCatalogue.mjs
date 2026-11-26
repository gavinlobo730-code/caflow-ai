/**
 * THE SEARCH BOX IS THE SHARED DIALOG AND THE PRODUCTS AND SERVICES PANEL IS THE SHARED SIDE SHEET (POST-A-130, last step), driven in a
 * browser.
 *
 * These were the last two layers built by hand over the page. The search box (the top bar's Search button, or Ctrl+K) had an Escape
 * listener of its own and nothing else: no name a screen reader announces, Tab walked out of it into the page behind, the page behind
 * still scrolled and focus was not given back. The Products and Services panel, opened from a document line's product picker, had a
 * click beside it and nothing else, not even Escape. The source guard's list of hand-built layers is empty now; this drives:
 *
 *   1. Search is a named modal dialog with focus in its box, the page locked, and Tab and Shift+Tab kept inside; its top edge does not
 *      move when results arrive (it is held at the top, not centred); Escape closes it and gives focus back to the Search button; Ctrl+K
 *      opens it again, and Enter on a result opens that result and closes the dialog;
 *   2. the Products and Services panel is a named modal side sheet with the page locked and Tab kept inside; New Product/Service opens
 *      over it and one Escape closes that dialog alone; the next closes the sheet and frees the page;
 *   3. while a product is being archived, Escape, a click beside the sheet and its close button do not close it; the server's refusal
 *      is then read in the sheet and the request went once.
 *
 * No scenario has a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";
import { ok, refuse } from "../stub.mjs";
import { ITEM } from "../fixtures.mjs";

export const group = "search-and-catalogue";

const focusInside = (dialog) => dialog.evaluate((d) => d.contains(document.activeElement));
const focusIsOn = (locator) => locator.evaluate((el) => el === document.activeElement);
const pageLocked = (page) => page.evaluate(() => document.body.style.overflow);
const topOf = async (dialog) => Math.round((await dialog.boundingBox()).y);

async function tabStaysInside(page, dialog, n, what) {
  await until(() => focusInside(dialog), `focus to be inside ${what}`);
  for (let i = 0; i < n; i += 1) {
    await page.keyboard.press("Tab");
    assert.equal(await focusInside(dialog), true, `Tab number ${i + 1} left ${what}`);
  }
  for (let i = 0; i < n; i += 1) {
    await page.keyboard.press("Shift+Tab");
    assert.equal(await focusInside(dialog), true, `Shift+Tab number ${i + 1} left ${what}`);
  }
}

const SEARCH = /\/api\/search\?/;
const FOUND = { id: "t-1", category: "tasks", title: "File the Asha Traders return", subtitle: "Task", href: "/deadlines/" };

/** A sales invoice being drafted, with its first line's product picker opened to the row that opens the Products and Services panel. */
async function atThePanel(env) {
  const { page } = env;
  await page.goto(env.at("/sales/invoices/new/edit/"), { waitUntil: "networkidle" });
  await page.click('button[aria-label="Line 1 product or service"]');
  await page.locator("[role=listbox] [role=option]", { hasText: "Add Product/Service" }).first().click();
  const sheet = page.getByRole("dialog", { name: "Products and Services", exact: true });
  await sheet.waitFor();
  return sheet;
}

export const scenarios = [
  {
    id: "search-is-a-named-dialog-that-keeps-the-keyboard-and-gives-focus-back",
    title: "Top bar > Search: a named modal dialog with focus in its box, the page locked, Tab kept inside and its top edge still when results arrive; Escape gives focus back; Ctrl+K opens it and Enter opens a result",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "GET", re: SEARCH, reply: () => ok({ results: [FOUND] }) });
      await page.goto(`${env.base}/tasks/`, { waitUntil: "networkidle" });
      const opener = page.getByRole("button", { name: "Search", exact: true }).first();
      await opener.waitFor();
      await opener.focus();
      await opener.click();
      const dialog = page.getByRole("dialog", { name: "Search", exact: true });
      await dialog.waitFor();
      assert.equal(await page.getByRole("dialog").count(), 1, "more than one dialog is open");
      assert.equal(await dialog.getAttribute("aria-modal"), "true", "Search does not say it is modal");
      assert.equal(await pageLocked(page), "hidden", "the page behind Search can still scroll");
      const box = dialog.getByRole("textbox", { name: "Search", exact: true });
      await until(() => focusIsOn(box), "focus to be in the search box");
      const top = await topOf(dialog);
      await page.keyboard.type("asha");
      await dialog.getByText(FOUND.title).waitFor({ timeout: 8000 });
      assert.equal(await topOf(dialog), top, "the dialog moved when its results arrived");
      await tabStaysInside(page, dialog, 5, "Search");
      await page.keyboard.press("Escape");
      await dialog.waitFor({ state: "detached" });
      assert.equal(await pageLocked(page), "", "the page is still locked after Search closed");
      assert.equal(await focusIsOn(opener), true, "focus did not return to the Search button");

      await page.keyboard.press("Control+k");
      await dialog.waitFor();
      assert.equal(await box.inputValue(), "", "the box kept what was typed the last time");
      await until(() => focusIsOn(box), "focus to be in the search box after Ctrl+K");
      await page.keyboard.type("asha");
      await dialog.getByText(FOUND.title).waitFor({ timeout: 8000 });
      // The screens that match come first; move to the result the server found and open it.
      const rows = await dialog.getByRole("button").filter({ hasText: /\S/ }).allTextContents();
      const at = rows.findIndex((t) => t.includes(FOUND.title));
      assert.ok(at >= 0, "the server's result is not a row");
      for (let i = 0; i < at; i += 1) await page.keyboard.press("ArrowDown");
      await page.keyboard.press("Enter");
      await page.waitForURL(/\/deadlines\/?/, { timeout: 8000 });
      // Focus goes back to the Search button when the dialog closes, and the same Enter must not then press it: the box stays closed.
      await page.waitForTimeout(400);
      assert.equal(await dialog.count(), 0, "Enter on a result opened the result and then opened Search again over it");
    },
  },
  {
    id: "the-products-and-services-panel-is-a-named-side-sheet-and-a-dialog-over-it-closes-alone",
    title: "Sales > invoice > Add Product/Service: a named modal side sheet, the page locked, Tab kept inside; New Product/Service opens over it and one Escape closes that alone, the next closes the sheet",
    async run(env) {
      const { page } = env;
      const sheet = await atThePanel(env);
      assert.equal(await sheet.getAttribute("aria-modal"), "true", "the panel does not say it is modal");
      assert.equal(await pageLocked(page), "hidden", "the page behind the panel can still scroll");
      assert.equal(await sheet.getByRole("button", { name: "Close", exact: true }).count(), 1, "the panel's close button is not inside it");
      await tabStaysInside(page, sheet, 8, "the Products and Services panel");
      await sheet.getByRole("button", { name: "New Product/Service" }).click();
      const form = page.getByRole("dialog", { name: "New Product/Service", exact: true });
      await form.waitFor();
      await tabStaysInside(page, form, 6, "New Product/Service");
      await page.keyboard.press("Escape");
      await form.waitFor({ state: "detached" });
      assert.equal(await sheet.count(), 1, "one Escape closed the panel as well as the dialog over it");
      assert.equal(await pageLocked(page), "hidden", "the page was freed while the panel is still open");
      await page.keyboard.press("Escape");
      await sheet.waitFor({ state: "detached" });
      assert.equal(await pageLocked(page), "", "the page is still locked after the panel closed");
    },
  },
  {
    id: "the-products-and-services-panel-is-held-while-a-product-is-archived-and-the-refusal-is-read-in-it",
    title: "Sales > invoice > Add Product/Service > Archive: while the product is being archived Escape, a click beside the panel and its close button do not close it; the server's refusal is then read in the panel",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "GET", re: /api\/service-catalogue\/?\?/, reply: () => ok([{ ...ITEM, is_active: true }]) });
      stub.route({ method: "PATCH", re: /api\/service-catalogue\/[^/]+$/, delay: 2500, ...refuse("A stub refusal of the archive.", 422) });
      const sheet = await atThePanel(env);
      const archive = sheet.getByRole("button", { name: "Archive", exact: true }).first();
      await archive.waitFor();
      await archive.click();
      const close = sheet.getByRole("button", { name: "Close", exact: true });
      await until(async () => await close.isDisabled(), "the panel's close button to be held while the product is archived", 3000);
      await page.keyboard.press("Escape");
      await page.mouse.click(5, 5);
      assert.equal(await sheet.count(), 1, "Escape or a click beside it closed the panel while the product was being archived");
      await sheet.getByText("A stub refusal of the archive.").waitFor({ timeout: 8000 }).catch(() => { throw new Error("the server's refusal was not shown in the panel"); });
      assert.equal(await close.isDisabled(), false, "the close button stayed held after the answer");
      assert.equal(stub.writesTo(/api\/service-catalogue\/[^/]+$/, "PATCH").length, 1, "the archive was not sent exactly once");
    },
  },
];
