/**
 * THE THREE FILING TRACKERS' DIALOGS ARE THE SHARED ONE (POST-A-130, twelfth step), driven in a browser.
 *
 * On the GST, Income Tax and MCA trackers, recording that a return was filed (one row, or several at once) and adding a deadline or a
 * filing were eight layers built by hand: no name a screen reader announces, no Tab kept inside, no Escape, no focus given back. Each is the
 * shared Modal now, with its buttons in the shared footer. The source guard holds the eight; this drives:
 *
 *   1. each tracker's Mark Filed prompt for one row: a dialog named "Mark … as Filed", modal, the page locked, its Cancel and Confirm
 *      inside, Tab and Shift+Tab kept inside, Escape closes it and focus is back on the row's button;
 *   2. Add GST Filing and Add ITR Deadline: named, Tab kept inside, Escape closes;
 *   3. the Income Tax tracker's prompt for SEVERAL rows, while the filings are out: its Cancel is held, and its close button, Escape and a
 *      click beside it do not close it (the hand-built one closed on its Cancel and its ×, over requests that then landed on nothing); the
 *      filing is recorded once.
 *
 * That the GST and MCA prompts for several rows are held while they are out is the nightly set's (dialog-leftovers), and what each prompt
 * sends is the nightly date checks': both run on the same build.
 *
 * No scenario asserts a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";
import { openGstTracker, openItrTracker, openMcaTracker } from "../scenarios/dates.mjs";

export const group = "tracker-dialogs";

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

const SINGLE = [
  { tracker: "GST", open: openGstTracker("single"), name: /^Mark .+ as Filed$/, opener: /^Mark as Filed$/ },
  { tracker: "Income Tax", open: openItrTracker("single"), name: "Mark ITR as Filed", opener: /^Mark Filed$/ },
  { tracker: "MCA", open: openMcaTracker("single"), name: "Mark ROC Filing as Filed", opener: /^Mark Filed$/ },
];

export const scenarios = [
  ...SINGLE.map((t) => ({
    id: `the-${t.tracker.toLowerCase().replace(/\s+/g, "-")}-trackers-mark-filed-prompt-is-a-named-dialog-that-gives-focus-back`,
    title: `${t.tracker} tracker > Mark Filed (one row): a named modal dialog with its buttons inside, Tab kept inside, the page locked, Escape closes it and focus returns to the row's button`,
    async run(env) {
      const { page } = env;
      await t.open(env);
      const dialog = page.getByRole("dialog", { name: t.name });
      await dialog.waitFor();
      assert.equal(await page.getByRole("dialog").count(), 1, `${t.tracker}: more than one dialog is open`);
      assert.equal(await dialog.getAttribute("aria-modal"), "true", `${t.tracker}: the prompt does not say it is modal`);
      assert.equal(await pageLocked(page), "hidden", `${t.tracker}: the page behind the prompt can still scroll`);
      for (const name of ["Cancel", "Confirm Filing"]) {
        assert.equal(await dialog.getByRole("button", { name, exact: true }).count(), 1, `${t.tracker}: ${name} is not inside the dialog`);
      }
      assert.match(await dialog.innerText(), /CA Confirmation Required/i, `${t.tracker}: the prompt lost its warning that nothing is submitted to the portal`);
      await tabStaysInside(page, dialog, 8, `the ${t.tracker} prompt`);
      await page.keyboard.press("Escape");
      await dialog.waitFor({ state: "detached" });
      assert.equal(await pageLocked(page), "", `${t.tracker}: the page is still locked after the prompt closed`);
      const back = await page.evaluate(() => (document.activeElement?.textContent ?? "").trim());
      assert.match(back, t.opener, `${t.tracker}: focus did not return to the row's button (it is on "${back}")`);
    },
  })),
  {
    id: "add-gst-filing-and-add-itr-deadline-are-named-dialogs-that-keep-the-keyboard",
    title: "GST tracker > Add GST Filing and Income Tax tracker > Add ITR Deadline: each a named modal dialog with its buttons inside, Tab kept inside, Escape closes it",
    async run(env) {
      const { page } = env;
      const cases = [
        { open: openGstTracker("add"), name: "Add GST Filing", buttons: ["Cancel", "Save Filing"] },
        { open: openItrTracker("add"), name: "Add ITR Deadline", buttons: ["Cancel", "Add Deadline"] },
      ];
      for (const c of cases) {
        await c.open(env);
        const dialog = page.getByRole("dialog", { name: c.name, exact: true });
        await dialog.waitFor();
        assert.equal(await dialog.getAttribute("aria-modal"), "true", `${c.name} does not say it is modal`);
        for (const name of c.buttons) {
          assert.equal(await dialog.getByRole("button", { name, exact: true }).count(), 1, `${c.name}: ${name} is not inside the dialog`);
        }
        await tabStaysInside(page, dialog, 10, c.name);
        await page.keyboard.press("Escape");
        await dialog.waitFor({ state: "detached" });
        assert.equal(await pageLocked(page), "", `the page is still locked after ${c.name} closed`);
      }
    },
  },
  {
    id: "the-income-tax-trackers-prompt-for-several-rows-is-held-while-the-filings-are-out",
    title: "Income Tax tracker > Mark Filed (several) > Confirm: while the filings are out, Cancel is held and the close button, Escape and a click beside the dialog do not close it; the filing is recorded once",
    async run(env) {
      const { page, stub } = env;
      await openItrTracker("batch")(env);
      const dialog = page.getByRole("dialog", { name: /^Mark \d+ ITR Filings? as Filed$/ });
      await dialog.waitFor();
      const date = dialog.locator("#itr-batch-filed-date");
      await date.fill("28/07/2026");
      await date.blur();
      stub.setWriteDelay(3000);
      await dialog.getByRole("button", { name: /^Confirm Filing/ }).click();
      await dialog.getByRole("button", { name: "Saving…" }).waitFor({ timeout: 3000 });
      assert.equal(await dialog.getByRole("button", { name: "Cancel", exact: true }).isDisabled(), true, "Cancel is live while the filings are out");
      await dialog.getByRole("button", { name: "Close dialog", exact: true }).click();
      await page.keyboard.press("Escape");
      await page.mouse.click(5, 5);
      assert.equal(await dialog.count(), 1, "the ×, Escape or a click beside it closed the prompt while the filings were out");
      stub.setWriteDelay(0);
      await stub.quiet({ timeoutMs: 15_000 });
      assert.equal(stub.writesTo(/compliance\/calendar\/itr-1\/filed$/).length, 1, "the filing was not recorded exactly once");
    },
  },
];
