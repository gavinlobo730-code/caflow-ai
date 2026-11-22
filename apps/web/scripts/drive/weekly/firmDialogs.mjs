/**
 * TEN MORE HAND-BUILT DIALOGS ON THE FIRM'S OWN SCREENS ARE THE SHARED ONE (POST-A-130, eighth step), driven in a browser.
 *
 * Add Client (and Edit Client), the practice's Add Fee Engagement and Record Receipt, Start Timer and Manual Time Entry, the task
 * template form and Create Task from Template, Add TDS Deduction, Add Challan 281 and Add MCA Filing were each a layer built by hand over
 * the page: no name a screen reader announces, no Tab kept inside, no focus given back, and (the client form aside) no Escape. Each is the
 * shared Modal now. The source guard holds all ten; this drives four of them, opened from a firm-level screen with nothing chosen first:
 *
 *   1. Add Client: named, with its line of explanation, Tab and Shift+Tab kept inside, the page locked, Escape closes and focus returns to
 *      the Add Client button;
 *   2. Manual Time Entry and Start Timer: each named, Escape closes, focus returns to the button that opened it;
 *   3. the task template form: named New Template, Tab kept inside, Escape closes, focus returns.
 *
 * The six not driven here (the two fee dialogs, the template's task dialog, the two TDS dialogs and the MCA filing) are opened by the
 * nightly date checks, which type into them and save: those ran on the same build.
 *
 * No scenario has a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";

export const group = "firm-dialogs";

const insideDialog = (page) => page.evaluate(() => {
  const d = document.querySelector('[role="dialog"]');
  return !!d && d.contains(document.activeElement);
});

async function tabStaysInside(page, n, what) {
  await until(() => insideDialog(page), `focus to move into ${what}`);
  for (let i = 0; i < n; i += 1) {
    await page.keyboard.press("Tab");
    assert.equal(await insideDialog(page), true, `Tab number ${i + 1} left ${what}`);
  }
  for (let i = 0; i < n; i += 1) {
    await page.keyboard.press("Shift+Tab");
    assert.equal(await insideDialog(page), true, `Shift+Tab number ${i + 1} left ${what}`);
  }
}

/** Open `name` from the button `opener`, hold it to the shared dialog's promises, close it with Escape and expect focus back. */
async function namedDialogThatGivesFocusBack(page, opener, name, { tabs = 8, says } = {}) {
  await opener.waitFor();
  await opener.focus();
  await opener.click();
  const dialog = page.getByRole("dialog", { name, exact: true });
  await dialog.waitFor();
  assert.equal(await page.getByRole("dialog").count(), 1, `${name}: more than one dialog is open`);
  assert.equal(await dialog.getAttribute("aria-modal"), "true", `${name} does not say it is modal`);
  assert.equal(await page.evaluate(() => document.body.style.overflow), "hidden", `the page behind ${name} can still scroll`);
  if (says) assert.match(await dialog.innerText(), says, `${name} lost its line of explanation`);
  await tabStaysInside(page, tabs, name);
  await page.keyboard.press("Escape");
  await dialog.waitFor({ state: "detached" });
  assert.equal(await page.evaluate(() => document.body.style.overflow), "", `the page is still locked after ${name} closed`);
  assert.equal(await opener.evaluate((el) => el === document.activeElement), true, `focus did not return to the button that opened ${name}`);
}

export const scenarios = [
  {
    id: "add-client-is-a-named-dialog-that-keeps-tab-inside-and-gives-focus-back",
    title: "Clients > Add Client: a dialog named Add New Client with its line of explanation, Tab and Shift+Tab stay inside, the page is locked, Escape closes it and focus returns to Add Client",
    async run(env) {
      const { page } = env;
      await page.goto(`${env.base}/clients/`, { waitUntil: "networkidle" });
      await namedDialogThatGivesFocusBack(page, page.getByRole("button", { name: "Add Client", exact: true }).first(), "Add New Client",
        { tabs: 14, says: /Register a new client with your firm/ });
    },
  },
  {
    id: "manual-time-entry-and-start-timer-are-named-dialogs-that-give-focus-back",
    title: "Time: Manual Entry opens a dialog named Manual Time Entry and Start Timer one named Start Timer; Escape closes each and focus returns to its button",
    async run(env) {
      const { page } = env;
      await page.goto(`${env.base}/time/`, { waitUntil: "networkidle" });
      await namedDialogThatGivesFocusBack(page, page.getByRole("button", { name: "Manual Entry", exact: true }).first(), "Manual Time Entry", { tabs: 8 });
      await namedDialogThatGivesFocusBack(page, page.getByRole("button", { name: "Start Timer", exact: true }).first(), "Start Timer", { tabs: 6 });
    },
  },
  {
    id: "new-task-template-is-a-named-dialog-that-gives-focus-back",
    title: "Tasks > Templates > New Template: a dialog named New Template, Tab stays inside, Escape closes it and focus returns to the button",
    async run(env) {
      const { page } = env;
      await page.goto(`${env.base}/tasks/templates/`, { waitUntil: "networkidle" });
      await namedDialogThatGivesFocusBack(page, page.getByRole("button", { name: "New Template", exact: true }).first(), "New Template", { tabs: 8 });
    },
  },
];
