/**
 * THE DIALOGS THAT RECORD A RETURN AS FILED, AND THE GST REGISTRATION SHEET, ARE THE SHARED ONES (POST-A-130, fifteenth step), driven in
 * a browser.
 *
 * Mark GSTR-1 as Filed, Mark GSTR-3B as Filed and the TDS statement's Mark as Filed were each a layer built by hand over the page, and Add
 * a GST registration a side sheet built by hand: no name a screen reader announces, no Tab kept inside, no Escape, no focus given back.
 * The two GST dialogs also had no flag for their own request, so they could be closed (Cancel, the ×) while the filing was being recorded:
 * a refusal then arrived on a closed dialog and was never read. Recording a GSTR-1 or GSTR-3B as filed locks the period, so not knowing
 * whether it was recorded is not a small thing. Each is the shared Modal or Drawer now. The source guard holds them; this drives:
 *
 *   1. each of the three Mark as Filed dialogs: named, modal, its Cancel and Confirm Filed inside, the page locked, Tab and Shift+Tab kept
 *      inside, Escape closes it and the page is unlocked;
 *   2. GSTR-1 and GSTR-3B while the filing is being recorded: Cancel is held, the button says Saving…, and the ×, Escape and a click
 *      beside the dialog do not close it; the server's refusal is then read INSIDE the dialog, and the request was sent once;
 *   3. Add a GST registration: a named modal side sheet with its buttons inside, Tab kept inside, Escape closes it and focus is back on the
 *      button that opened it.
 *
 * What each dialog sends, and what a date after today or before the period gets, are the nightly date checks', which run on the same build.
 *
 * The date typed in (2) is before the pinned today in every zone of the matrix, so no scenario has a zone of its own.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";
import { refuse } from "../stub.mjs";
import { openGstr1MarkFiled, openGstr3bMarkFiled, openTdsReturnMarkFiled, openGstRegistrations, typeAndLeave } from "../scenarios/dates.mjs";

export const group = "return-dialogs";

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

const FILED = [
  { id: "gstr1", open: openGstr1MarkFiled, name: "Mark GSTR-1 as Filed", box: "#gstr1-filed-date", write: /gst-workspace\/gstr1\/g1-1\/status$/ },
  { id: "gstr3b", open: openGstr3bMarkFiled, name: "Mark GSTR-3B as Filed", box: "#gstr3b-filed-date", write: /gst-workspace\/gstr3b\/g3-1\/status$/ },
  { id: "tds-statement", open: openTdsReturnMarkFiled, name: /^Mark .+ as Filed$/, box: "#tds-filing-date" },
];

export const scenarios = [
  ...FILED.map((f) => ({
    id: `the-${f.id}-mark-as-filed-dialog-is-named-and-keeps-the-keyboard`,
    title: `${typeof f.name === "string" ? f.name : "TDS > Returns > Mark as Filed"}: a named modal dialog with its buttons inside, the page locked, Tab kept inside, Escape closes it`,
    async run(env) {
      const { page } = env;
      await f.open(env);
      const dialog = page.getByRole("dialog", { name: f.name });
      await dialog.waitFor();
      assert.equal(await page.getByRole("dialog").count(), 1, "more than one dialog is open");
      assert.equal(await dialog.getAttribute("aria-modal"), "true", "the dialog does not say it is modal");
      assert.equal(await pageLocked(page), "hidden", "the page behind the dialog can still scroll");
      for (const name of ["Cancel", "Confirm Filed"]) {
        assert.equal(await dialog.getByRole("button", { name, exact: true }).count(), 1, `${name} is not inside the dialog`);
      }
      assert.equal(await dialog.locator(f.box).count(), 1, "the date filed is not inside the dialog");
      await tabStaysInside(page, dialog, 8, "the Mark as Filed dialog");
      await page.keyboard.press("Escape");
      await dialog.waitFor({ state: "detached" });
      assert.equal(await pageLocked(page), "", "the page is still locked after the dialog closed");
    },
  })),
  ...FILED.filter((f) => f.write).map((f) => ({
    id: `the-${f.id}-mark-as-filed-dialog-is-held-while-the-filing-is-recorded-and-the-refusal-is-read-in-it`,
    title: `${f.name} > Confirm Filed: while the filing is being recorded Cancel is held and the ×, Escape and a click beside the dialog do not close it; the server's refusal is then read inside the dialog`,
    async run(env) {
      const { page, stub } = env;
      await f.open(env);
      const dialog = page.getByRole("dialog", { name: f.name });
      await dialog.waitFor();
      stub.route({ method: "PATCH", re: f.write, delay: 2500, ...refuse("A stub refusal of the filing.", 422) });
      await typeAndLeave(page.locator(f.box), "07/10/2026");
      await dialog.getByRole("button", { name: "Confirm Filed", exact: true }).click();
      await dialog.getByRole("button", { name: "Saving…" }).waitFor({ timeout: 3000 });
      assert.equal(await dialog.getByRole("button", { name: "Cancel", exact: true }).isDisabled(), true, "Cancel is live while the filing is being recorded");
      await dialog.getByRole("button", { name: "Close dialog", exact: true }).click();
      await page.keyboard.press("Escape");
      await page.mouse.click(5, 5);
      assert.equal(await dialog.count(), 1, "the ×, Escape or a click beside it closed the dialog while the filing was being recorded");
      // The refusal arrives on a dialog that is still there, and is read in it.
      await dialog.getByText("A stub refusal of the filing.").waitFor({ timeout: 8000 }).catch(() => { throw new Error("the server's refusal was not shown inside the dialog"); });
      assert.equal(await dialog.getByRole("button", { name: "Cancel", exact: true }).isDisabled(), false, "Cancel stayed held after the answer");
      assert.equal(stub.writesTo(f.write).length, 1, "the filing was not sent exactly once");
    },
  })),
  {
    id: "add-a-gst-registration-is-a-named-side-sheet-that-gives-focus-back",
    title: "A client's GST > Registrations > Add a registration: a named modal side sheet with its buttons inside, Tab kept inside, Escape closes it and focus returns to the button that opened it",
    async run(env) {
      const { page } = env;
      await openGstRegistrations("add")(env);
      const sheet = page.getByRole("dialog", { name: "Add a GST registration", exact: true });
      await sheet.waitFor();
      assert.equal(await sheet.getAttribute("aria-modal"), "true", "the side sheet does not say it is modal");
      for (const name of ["Cancel", "Add"]) {
        assert.equal(await sheet.getByRole("button", { name, exact: true }).count(), 1, `${name} is not inside the side sheet`);
      }
      assert.equal(await pageLocked(page), "hidden", "the page behind the side sheet can still scroll");
      await tabStaysInside(page, sheet, 10, "Add a GST registration");
      await page.keyboard.press("Escape");
      await sheet.waitFor({ state: "detached" });
      assert.equal(await pageLocked(page), "", "the page is still locked after the side sheet closed");
      const back = await page.evaluate(() => (document.activeElement?.textContent ?? "").trim());
      assert.match(back, /Add a registration/, `focus did not return to the button that opened the side sheet (it is on "${back}")`);
    },
  },
];
