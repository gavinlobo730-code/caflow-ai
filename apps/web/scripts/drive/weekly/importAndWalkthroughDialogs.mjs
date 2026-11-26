/**
 * THE SHARED IMPORT DIALOG AND THE FILING WALK-THROUGH ARE THE SHARED DIALOG (POST-A-130, twenty-second step), driven in a browser.
 *
 * The import dialog that ten screens open, its "Opening the importer…" placeholder, the filing walk-through and the platform screen's two
 * dialogs were each a layer built by hand over the page. None had a name a screen reader announces, none kept Tab inside, none closed on
 * Escape and none gave focus back. They are the shared Modal now. The source guard holds the five; this drives two of them:
 *
 *   1. the import dialog (on Vendors, which stands for the ten) is a named modal dialog that keeps Tab inside, and Escape closes it and
 *      gives focus back to Import;
 *   2. FOUND WHILE CONVERTING IT: its × and its Cancel were live while the rows were being imported, so it could be closed with the
 *      import still out and nobody was told how many rows landed. While the import is out now, Cancel is held and the ×, Escape and a
 *      click beside it do not close it; the outcome is then read inside it, and the file went once;
 *   3. the filing walk-through is a named modal dialog; its banner, which says what the walk-through is, stays on the dialog's top edge
 *      when the body is scrolled to its end, and its footer on the bottom edge; Escape closes it and gives focus back.
 *
 * The platform screen needs a platform administrator's session, which the stand-in server does not model, and is not driven here.
 *
 * No scenario asserts a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";
import { ok, refuse } from "../stub.mjs";
import { CLIENT_ROW, FAKE_USERS_ROW } from "../fixtures.mjs";

export const group = "import-and-walkthrough-dialogs";

const focusInside = (dialog) => dialog.evaluate((d) => d.contains(document.activeElement));
const pageLocked = (page) => page.evaluate(() => document.body.style.overflow);
const focusIsOn = (locator) => locator.evaluate((el) => el === document.activeElement);

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

const BULK = /api\/vendors\/bulk$/;
const importDialog = (page) => page.getByRole("dialog", { name: "Import Vendors", exact: true });

async function atVendors(env, bulk) {
  const { page, stub } = env;
  stub.route({ method: "POST", re: BULK, ...bulk });
  await page.goto(env.at("/purchases/?tab=vendors"), { waitUntil: "networkidle" });
  const opener = page.getByRole("button", { name: "Import", exact: true });
  await opener.waitFor();
  return opener;
}

const filing = (id, form, status) => ({
  id, firm_id: FAKE_USERS_ROW.firm_id, client_id: CLIENT_ROW.id, client_name: "Acme Traders", company_cin: "U12345MH2020PTC123456",
  form_type: form, period: "FY 2024-25", due_date: "2025-10-30", filed_date: null, srn: null, status, notes: null,
});

export const scenarios = [
  {
    id: "the-import-dialog-is-named-keeps-the-keyboard-and-gives-focus-back",
    title: "Purchases > Vendors > Import: a named modal dialog that keeps Tab inside, locks the page, closes on Escape and gives focus back to Import",
    async run(env) {
      const { page } = env;
      const opener = await atVendors(env, { reply: () => ok({ created: [], duplicates: [], errors: [] }) });
      await opener.focus();
      await opener.click();
      const dialog = importDialog(page);
      await dialog.waitFor();
      assert.equal(await page.getByRole("dialog").count(), 1, "more than one dialog is open");
      assert.equal(await dialog.getAttribute("aria-modal"), "true", "the import dialog does not say it is modal");
      assert.equal(await pageLocked(page), "hidden", "the page behind the import dialog can still scroll");
      assert.equal(await dialog.getByRole("button", { name: "Cancel", exact: true }).count(), 1, "Cancel is not inside the import dialog");
      await tabStaysInside(page, dialog, 8, "the import dialog");
      await page.keyboard.press("Escape");
      await dialog.waitFor({ state: "detached" });
      assert.equal(await pageLocked(page), "", "the page is still locked after the import dialog closed");
      assert.equal(await focusIsOn(opener), true, "focus did not return to Import");
    },
  },
  {
    id: "the-import-dialog-is-held-while-the-rows-are-imported-and-then-says-what-landed",
    title: "Purchases > Vendors > Import > Import 1 row: while the rows are being imported Cancel is held and the ×, Escape and a click beside the dialog do not close it; the outcome is then read inside it and the file went once",
    async run(env) {
      const { page, stub } = env;
      const opener = await atVendors(env, { delay: 2500, reply: () => ok({ created: [{ id: "v-9", name: "Acme Traders" }], duplicates: [], errors: [] }) });
      await opener.click();
      const dialog = importDialog(page);
      await dialog.waitFor();
      await page.locator('input[aria-label="CSV or Excel file to import"]').setInputFiles({
        name: "vendors.csv", mimeType: "text/csv", buffer: Buffer.from("name\nAcme Traders\n") });
      const go = dialog.getByRole("button", { name: /^Import \d+ rows?$/ });
      await go.waitFor({ timeout: 10000 });
      await go.click();
      const cancel = dialog.getByRole("button", { name: "Cancel", exact: true });
      await until(async () => (await cancel.count()) === 1 && await cancel.isDisabled(), "Cancel to be held while the rows are being imported", 3000);
      await dialog.getByRole("button", { name: "Close dialog", exact: true }).click();
      await page.keyboard.press("Escape");
      await page.mouse.click(5, 5);
      assert.equal(await dialog.count(), 1, "the ×, Escape or a click beside it closed the import dialog while the rows were being imported");
      await dialog.getByText("1 new record imported").waitFor({ timeout: 10000 }).catch(() => { throw new Error("what the import did was not shown inside the dialog"); });
      assert.equal(stub.writesTo(BULK, "POST").length, 1, "the file was not imported exactly once");
      await dialog.getByRole("button", { name: "Close", exact: true }).click();
      await dialog.waitFor({ state: "detached" });
    },
  },
  {
    id: "the-filing-walk-through-is-a-named-dialog-whose-banner-and-footer-stay-on-its-edges",
    title: "MCA > Filings > File (demo): a named modal dialog; scrolled to its end, the banner that says what it is stays on the dialog's top edge and the footer on its bottom edge; Escape closes it and gives focus back",
    async run(env) {
      const { page, stub } = env;
      stub.setTable("mca_filings", [filing("m-aoc", "AOC-4", "not_started")]);
      stub.route({ method: "GET", re: /filing-demo\/capabilities$/, reply: () => ok({ enabled: true, flows: ["mca"] }) });
      stub.route({ method: "POST", re: /filing-demo\/mca\/preview$/, ...refuse("This specimen is not part of the drive.", 422) });
      // A short window, so the dialog's body scrolls even with nothing but the refusal in it.
      await page.setViewportSize({ width: 1100, height: 240 });
      await page.goto(`${env.base}/mca/`, { waitUntil: "networkidle" });
      await page.getByRole("button", { name: "Filings", exact: true }).click();
      const opener = page.getByRole("button", { name: "File (demo)" }).first();
      await opener.waitFor();
      await opener.focus();
      await opener.click();
      const dialog = page.getByRole("dialog", { name: "Filing walk-through", exact: true });
      await dialog.waitFor();
      assert.equal(await dialog.getAttribute("aria-modal"), "true", "the walk-through does not say it is modal");
      // The script is refused on purpose: the dialog then holds its banner, one sentence of refusal and its footer, and nothing loads later.
      await dialog.locator("p.text-red-600").waitFor({ timeout: 8000 });
      const edges = await dialog.evaluate((panel) => {
        panel.scrollTop = panel.scrollHeight;
        const banner = panel.querySelector(".bg-amber-100");
        const footer = panel.lastElementChild;
        const p = panel.getBoundingClientRect(), b = banner.getBoundingClientRect(), f = footer.getBoundingClientRect();
        return { scrolls: panel.scrollHeight > panel.clientHeight + 1, scrolled: panel.scrollTop, bannerTop: b.top - p.top, footerBottom: p.bottom - f.bottom, bannerText: banner.textContent ?? "" };
      });
      assert.equal(edges.scrolls, true, "the dialog's body did not scroll, so the banner was not tested against scrolling");
      assert.ok(edges.scrolled > 0, "the dialog's body was not scrolled");
      assert.ok(Math.abs(edges.bannerTop) <= 1.5, `scrolled to its end, the banner is ${edges.bannerTop}px from the dialog's top edge`);
      assert.ok(Math.abs(edges.footerBottom) <= 1.5, `scrolled to its end, the footer is ${edges.footerBottom}px from the dialog's bottom edge`);
      assert.ok(edges.bannerText.trim().length > 20, "the banner says nothing");
      await page.keyboard.press("Escape");
      await dialog.waitFor({ state: "detached" });
      assert.equal(await focusIsOn(opener), true, "focus did not return to File (demo)");
    },
  },
];
