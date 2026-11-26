/**
 * EIGHT DIALOGS OF THE PRACTICE'S OWN SCREENS ARE THE SHARED ONE (POST-A-130, fourteenth step), driven in a browser.
 *
 * New Engagement Letter, the engagement template form and a letter's detail; Renew this DSC, Correct this record and Add DSC Record; Add
 * Lead (and Edit Lead) and Convert to Client were each a layer built by hand over the page. The engagement dialogs closed on Escape through
 * a key listener of their own; none of the eight had a name a screen reader announces, kept Tab inside or gave focus back. Each is the
 * shared Modal now. The source guard holds the eight; this drives:
 *
 *   1. New Engagement Letter, Add Lead, and the three DSC dialogs: each named, modal, the page locked, Tab and Shift+Tab kept inside,
 *      Escape closes it and the page is unlocked; the DSC renewal and correction keep their line of explanation under the name;
 *   2. Add Lead also gives focus back to the Add Lead button.
 *
 * That the engagement template form and a letter's detail are held while their own request is out is the nightly set's
 * (dialog-leftovers), and what each form sends is the nightly date checks': both run on the same build.
 *
 * No scenario asserts a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";
import { openNewEngagementLetter, openDscRenew, openDscCorrect, openDscAdd, openAddLead } from "../scenarios/dates.mjs";

export const group = "practice-dialogs";

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

const FORMS = [
  { id: "new-engagement-letter", open: openNewEngagementLetter, name: "New Engagement Letter", buttons: ["Cancel", "Create Engagement"] },
  { id: "renew-this-dsc", open: openDscRenew, name: "Renew this DSC", buttons: ["Cancel", "Record the renewal"], says: /Asha Rao .* expires/ },
  { id: "correct-this-dsc-record", open: openDscCorrect, name: "Correct this record", buttons: ["Cancel", "Save the correction"], says: /For something keyed wrongly/ },
  { id: "add-dsc-record", open: openDscAdd, name: "Add DSC Record", buttons: ["Cancel", "Add DSC"] },
];

export const scenarios = [
  ...FORMS.map((f) => ({
    id: `${f.id}-is-a-named-dialog-that-keeps-the-keyboard`,
    title: `${f.name}: a named modal dialog with its buttons inside, the page locked, Tab kept inside, Escape closes it`,
    async run(env) {
      const { page } = env;
      await f.open(env);
      const dialog = page.getByRole("dialog", { name: f.name, exact: true });
      await dialog.waitFor();
      assert.equal(await page.getByRole("dialog").count(), 1, `${f.name}: more than one dialog is open`);
      assert.equal(await dialog.getAttribute("aria-modal"), "true", `${f.name} does not say it is modal`);
      assert.equal(await pageLocked(page), "hidden", `the page behind ${f.name} can still scroll`);
      for (const name of f.buttons) {
        assert.equal(await dialog.getByRole("button", { name, exact: true }).count(), 1, `${f.name}: ${name} is not inside the dialog`);
      }
      if (f.says) assert.match(await dialog.innerText(), f.says, `${f.name} lost the line under its name`);
      await tabStaysInside(page, dialog, 9, f.name);
      await page.keyboard.press("Escape");
      await dialog.waitFor({ state: "detached" });
      assert.equal(await pageLocked(page), "", `the page is still locked after ${f.name} closed`);
    },
  })),
  {
    id: "add-lead-is-a-named-dialog-that-gives-focus-back",
    title: "Pipeline > Add Lead: a named modal dialog around the form, Tab kept inside, Escape closes it and focus returns to the Add Lead button",
    async run(env) {
      const { page } = env;
      await openAddLead(env);
      const dialog = page.getByRole("dialog", { name: "Add Lead", exact: true });
      await dialog.waitFor();
      assert.equal(await dialog.getAttribute("aria-modal"), "true", "Add Lead does not say it is modal");
      assert.equal(await dialog.getByRole("button", { name: "Add Lead", exact: true }).count(), 1, "the saving button is not inside the dialog");
      await tabStaysInside(page, dialog, 10, "Add Lead");
      await page.keyboard.press("Escape");
      await dialog.waitFor({ state: "detached" });
      const back = await page.evaluate(() => (document.activeElement?.textContent ?? "").trim());
      assert.equal(back, "Add Lead", `focus did not return to the Add Lead button (it is on "${back}")`);
    },
  },
];
