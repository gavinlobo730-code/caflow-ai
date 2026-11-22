/**
 * SIX PURCHASE AND STOCK PANELS ARE THE SHARED DIALOG OR SIDE SHEET (POST-A-130, seventeenth step), driven in a browser.
 *
 * Record a Bill of Entry, Landed costs and the self-invoice / payment voucher panel were side sheets built by hand; New godown, New lot
 * and the physical stock count sheet were layers built by hand over the page. None had a name a screen reader announces, none kept Tab
 * inside, none closed on Escape and none gave focus back. The three sheets are the shared Drawer now and the other three the shared
 * Modal. The source guard holds the six; this drives three of them:
 *
 *   1. Record a Bill of Entry: a named modal side sheet with its Cancel and Save inside, the page locked, Tab and Shift+Tab kept inside,
 *      Escape closes it and focus is back on the button that opened it;
 *   2. New godown and New lot: each a named modal dialog with its Cancel and Create inside, Tab kept inside, Escape closes it.
 *
 * That New lot keeps its buttons on a window 320 pixels tall, and that New godown and New lot are held while a Create is out, are the
 * nightly set's, which runs on the same build. Landed costs, the self-invoice panel and the count sheet each need a bill or a count on
 * record and are not driven here.
 *
 * No scenario asserts a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";
import { openBillOfEntry, openStockLocations } from "../scenarios/dates.mjs";

export const group = "stock-and-purchase-panels";

const focusInside = (dialog) => dialog.evaluate((d) => d.contains(document.activeElement));
const pageLocked = (page) => page.evaluate(() => document.body.style.overflow);

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

async function namedAndKept(page, dialog, name, buttons) {
  await dialog.waitFor();
  assert.equal(await page.getByRole("dialog").count(), 1, `${name}: more than one dialog is open`);
  assert.equal(await dialog.getAttribute("aria-modal"), "true", `${name} does not say it is modal`);
  assert.equal(await pageLocked(page), "hidden", `the page behind ${name} can still scroll`);
  for (const b of buttons) {
    assert.equal(await dialog.getByRole("button", { name: b, exact: true }).count(), 1, `${name}: ${b} is not inside it`);
  }
  await tabStaysInside(page, dialog, 9, name);
  await page.keyboard.press("Escape");
  await dialog.waitFor({ state: "detached" });
  assert.equal(await pageLocked(page), "", `the page is still locked after ${name} closed`);
}

export const scenarios = [
  {
    id: "record-a-bill-of-entry-is-a-named-side-sheet-that-gives-focus-back",
    title: "Purchases > Bills of Entry > Record a Bill of Entry: a named modal side sheet with Cancel and Save inside, Tab kept inside, Escape closes it and focus returns to the button that opened it",
    async run(env) {
      const { page } = env;
      await openBillOfEntry(env);
      const sheet = page.getByRole("dialog", { name: "Record a Bill of Entry", exact: true });
      await namedAndKept(page, sheet, "Record a Bill of Entry", ["Cancel", "Save"]);
      const back = await page.evaluate(() => (document.activeElement?.textContent ?? "").trim());
      assert.match(back, /Record a Bill of Entry/, `focus did not return to the button that opened the side sheet (it is on "${back}")`);
    },
  },
  {
    id: "new-godown-and-new-lot-are-named-dialogs-that-keep-the-keyboard",
    title: "Inventory > Locations > New godown and New lot: each a named modal dialog with Cancel and Create inside, Tab kept inside, Escape closes it",
    async run(env) {
      const { page } = env;
      await openStockLocations("transfer")(env);
      await page.getByRole("button", { name: /Add godown/ }).first().click();
      await namedAndKept(page, page.getByRole("dialog", { name: "New godown", exact: true }), "New godown", ["Cancel", "Create"]);
      await openStockLocations("lot")(env);
      await namedAndKept(page, page.getByRole("dialog", { name: "New lot", exact: true }), "New lot", ["Cancel", "Create"]);
    },
  },
];
