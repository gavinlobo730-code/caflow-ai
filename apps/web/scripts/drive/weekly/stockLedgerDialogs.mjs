/**
 * THE STOCK LEDGER AND THE TWO DIALOGS OVER IT ARE THE SHARED DIALOG (POST-A-130, tenth step), driven in a browser.
 *
 * An item's movement ledger on the Inventory screen was a panel built by hand over the page, and Adjust Stock and Write Down to NRV were two
 * more layers built by hand INSIDE it, under its click-to-close backdrop. None of the three had a name a screen reader announces or kept Tab
 * inside, and which of them an Escape or a click closed was held together by three key listeners and two stopped clicks. All three are the
 * shared Modal now, the two dialogs drawn over the ledger's. The source guard holds the three; this drives what a dialog over a dialog has
 * to get right:
 *
 *   1. the ledger is a dialog named for its item, with "Stock movement ledger" under the name, modal, the page locked, Tab kept inside;
 *      Adjust Stock opens a SECOND dialog named for what it does, Tab stays inside THAT one, and Escape closes it ALONE: the ledger stays
 *      and focus is back on the ledger's Adjust Stock button. Write Down to NRV the same. Escape again closes the ledger and unlocks the page;
 *   2. a click INSIDE the dialog over the ledger closes nothing, and a click beside it (on its backdrop) closes it alone, never the ledger
 *      behind (a dialog drawn in the body still sends its clicks up the component tree, which is why these two could not be converted
 *      before their panel was).
 *
 * That neither closes while its posting is out is the nightly set's (dialog-leftovers), which runs on the same build.
 *
 * No scenario has a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";
import { ok } from "../stub.mjs";

export const group = "stock-ledger-dialogs";

const ITEM = { id: "sc1", name: "Copier paper", description: null, hsn_sac: "4802", unit: "NOS", is_active: true,
  stock_qty_units: 40, avg_cost_paise: 25000, stock_value_paise: 1000000 };

/** Whether focus is inside the dialog with this accessible name (there may be two dialogs open). */
const focusInside = (dialog) => dialog.evaluate((d) => d.contains(document.activeElement));

async function tabStaysInside(page, dialog, n, what) {
  await until(() => focusInside(dialog), `focus to move into ${what}`);
  for (let i = 0; i < n; i += 1) {
    await page.keyboard.press("Tab");
    assert.equal(await focusInside(dialog), true, `Tab number ${i + 1} left ${what}`);
  }
  for (let i = 0; i < n; i += 1) {
    await page.keyboard.press("Shift+Tab");
    assert.equal(await focusInside(dialog), true, `Shift+Tab number ${i + 1} left ${what}`);
  }
}

async function atTheLedger(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /api\/inventory\/items\?/, reply: () => ok([ITEM]) });
  stub.route({ method: "GET", re: /api\/inventory\/items\/sc1\/ledger\?/, reply: () => ok({ item: null, lines: [], opening: null, closing: null }) });
  await page.goto(env.at("/inventory/"), { waitUntil: "networkidle" });
  await page.getByText("Copier paper").first().click();
  const ledger = page.getByRole("dialog", { name: "Copier paper", exact: true });
  await ledger.waitFor();
  return ledger;
}

export const scenarios = [
  {
    id: "the-stock-ledger-is-a-named-dialog-and-a-dialog-over-it-closes-alone-on-escape",
    title: "Inventory > an item's ledger: a named modal dialog that keeps Tab inside; Adjust Stock and Write Down to NRV each open a second named dialog over it that keeps Tab inside itself, and Escape closes that one alone and gives focus back to the ledger's button; Escape again closes the ledger",
    async run(env) {
      const { page } = env;
      const ledger = await atTheLedger(env);
      assert.equal(await ledger.getAttribute("aria-modal"), "true", "the ledger does not say it is modal");
      assert.match(await ledger.innerText(), /Stock movement ledger/, "the ledger lost the line under its name");
      assert.equal(await page.evaluate(() => document.body.style.overflow), "hidden", "the page behind the ledger can still scroll");
      assert.equal(await page.getByRole("dialog").count(), 1, "more than one dialog is open before any is asked for");
      await tabStaysInside(page, ledger, 10, "the stock ledger");

      const cases = [
        { opener: /Adjust Stock/, name: "Adjust Stock — Copier paper" },
        { opener: /Write Down to NRV/, name: "Write Down to NRV — Copier paper" },
      ];
      for (const c of cases) {
        const opener = ledger.getByRole("button", { name: c.opener });
        await opener.focus();
        await opener.click();
        const over = page.getByRole("dialog", { name: c.name, exact: true });
        await over.waitFor();
        assert.equal(await page.getByRole("dialog").count(), 2, `${c.name} is not a second dialog over the ledger`);
        assert.equal(await over.getAttribute("aria-modal"), "true", `${c.name} does not say it is modal`);
        await tabStaysInside(page, over, 9, c.name);
        await page.keyboard.press("Escape");
        await over.waitFor({ state: "detached" });
        assert.equal(await ledger.count(), 1, `Escape on ${c.name} closed the ledger behind it too`);
        assert.equal(await opener.evaluate((el) => el === document.activeElement), true, `focus did not return to the ledger's button after ${c.name} closed`);
        assert.equal(await page.evaluate(() => document.body.style.overflow), "hidden", `the page was unlocked when ${c.name} closed, with the ledger still open`);
      }

      await page.keyboard.press("Escape");
      await ledger.waitFor({ state: "detached" });
      assert.equal(await page.evaluate(() => document.body.style.overflow), "", "the page is still locked after the ledger closed");
    },
  },
  {
    id: "a-click-inside-the-dialog-over-the-stock-ledger-closes-nothing-and-a-click-beside-it-closes-it-alone",
    title: "Inventory > an item's ledger > Adjust Stock: a click inside the dialog closes nothing; a click beside it closes the dialog and leaves the ledger; the dialog's own close button the same",
    async run(env) {
      const { page } = env;
      const ledger = await atTheLedger(env);
      const opener = ledger.getByRole("button", { name: /Adjust Stock/ });
      const over = page.getByRole("dialog", { name: "Adjust Stock — Copier paper", exact: true });

      await opener.click();
      await over.waitFor();
      // Inside: a field, then the dialog's own title. Neither dialog goes.
      await page.getByLabel("Quantity", { exact: true }).click();
      await over.getByRole("heading", { name: "Adjust Stock — Copier paper" }).click();
      assert.equal(await over.count(), 1, "a click inside the dialog closed it");
      assert.equal(await ledger.count(), 1, "a click inside the dialog over the ledger closed the ledger behind it");

      // Beside it: the top dialog's backdrop. It goes alone.
      await page.mouse.click(5, 5);
      await over.waitFor({ state: "detached" });
      assert.equal(await ledger.count(), 1, "a click beside the dialog closed the ledger behind it too");

      // Its own close button: the same.
      await opener.click();
      await over.waitFor();
      await over.getByRole("button", { name: "Close dialog", exact: true }).click();
      await over.waitFor({ state: "detached" });
      assert.equal(await ledger.count(), 1, "the dialog's close button closed the ledger behind it too");

      // And a click beside the ledger, with nothing over it, closes the ledger.
      await page.mouse.click(5, 5);
      await ledger.waitFor({ state: "detached" });
    },
  },
];
