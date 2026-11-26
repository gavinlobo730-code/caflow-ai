/**
 * SEVEN DIALOGS OF THE SETTINGS AND ACCOUNTING SET-UP SCREENS ARE THE SHARED ONE (POST-A-130, sixteenth step), driven in a browser.
 *
 * Record a notification (statutory values), New Schedule, New Invoice Template, the HSN library's Edit, Add a ledger, Add Supplier and the
 * year-lock PIN dialog were each a layer built by hand over the page: no name a screen reader announces, no Tab kept inside, no Escape, no
 * focus given back. Each is the shared Modal now. The source guard holds the seven; this drives six of them:
 *
 *   1. Record a notification, New Schedule, New Invoice Template, Add a ledger and Add Supplier: each named, modal, the page locked, Tab
 *      and Shift+Tab kept inside, Escape closes it and the page is unlocked;
 *   2. the year-lock PIN dialog: named Lock Year, focus is in the PIN box, Tab stays inside; and a PIN typed and then abandoned is NOT in
 *      the box when the dialog is opened again (the hand-built one stayed mounted and kept it, behind its "show" eye, for whoever opened
 *      it next on that screen).
 *
 * The HSN library's Edit needs a library row and is not driven here.
 *
 * No scenario asserts a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";
import { ok } from "../stub.mjs";
import { openStatutoryValues } from "../scenarios/dates.mjs";

export const group = "settings-dialogs";

const focusInside = (dialog) => dialog.evaluate((d) => d.contains(document.activeElement));
const pageLocked = (page) => page.evaluate(() => document.body.style.overflow);
const everything = { role: "Partner", permissions: {
  accounting: ["read", "write", "approve"], client: ["read", "write"], settings: ["read", "write"], branding: ["read", "write"],
  payroll: ["read", "write"], report: ["read", "write"] } };

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

/** A firm-level screen, signed in as a Partner, with the button that opens its dialog pressed. */
function byButton(path, button, extra) {
  return async (env) => {
    const { page, stub } = env;
    stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok(everything) });
    if (extra) extra(stub);
    await page.goto(`${env.base}${path}`, { waitUntil: "networkidle" });
    await page.getByRole("button", { name: button }).first().click();
  };
}

const FORMS = [
  { id: "record-a-notification", open: openStatutoryValues, name: "Record a notification", buttons: ["Cancel", "Record"] },
  { id: "new-schedule", open: byButton("/settings/scheduled-reports/", "New Schedule"), name: "New Schedule", buttons: ["Cancel", "Create Schedule"] },
  { id: "new-invoice-template", name: "New Invoice Template", buttons: ["Cancel", "Create Template"],
    open: byButton("/settings/invoice-templates/", "New Template", (stub) => stub.route({ method: "GET", re: /api\/invoice-templates(\?|$)/, reply: () => ok({ templates: [] }) })) },
  { id: "add-a-ledger", open: byButton("/accounting/account-groups/", "Add ledger"), name: "Add a ledger", buttons: ["Cancel", "Add ledger"] },
  { id: "add-supplier", open: byButton("/accounting/suppliers/", "Add Supplier"), name: "Add Supplier", buttons: ["Cancel", "Save Supplier"] },
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
      await tabStaysInside(page, dialog, 9, f.name);
      await page.keyboard.press("Escape");
      await dialog.waitFor({ state: "detached" });
      assert.equal(await pageLocked(page), "", `the page is still locked after ${f.name} closed`);
    },
  })),
  {
    id: "the-year-lock-pin-dialog-is-named-and-a-pin-typed-and-abandoned-is-not-there-when-it-opens-again",
    title: "Accounting > Lock year > Lock: a dialog named Lock Year with focus in the PIN box and Tab kept inside; a PIN typed and abandoned with Escape is not in the box when the dialog is opened again",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok(everything) });
      stub.route({ method: "GET", re: /api\/accounting\/year-lock$/, reply: () => ok({ locked_financial_years: [], pin_set: true }) });
      await page.goto(`${env.base}/accounting/lock-year/`, { waitUntil: "networkidle" });
      const opener = page.getByRole("button", { name: "Lock Year", exact: true }).first();
      await opener.waitFor();
      await opener.click();
      const dialog = page.getByRole("dialog", { name: "Lock Year", exact: true });
      await dialog.waitFor();
      assert.equal(await dialog.getAttribute("aria-modal"), "true", "the PIN dialog does not say it is modal");
      const pin = dialog.getByLabel("PIN", { exact: true });
      await until(() => pin.evaluate((el) => el === document.activeElement), "focus to be in the PIN box");
      await pin.fill("4321");
      await tabStaysInside(page, dialog, 6, "the PIN dialog");
      await page.keyboard.press("Escape");
      await dialog.waitFor({ state: "detached" });
      // Opened again, by anybody: the box is empty.
      await opener.click();
      await dialog.waitFor();
      assert.equal(await dialog.getByLabel("PIN", { exact: true }).inputValue(), "", "the PIN typed before is still in the box when the dialog is opened again");
      await page.keyboard.press("Escape");
      await dialog.waitFor({ state: "detached" });
      assert.equal(stub.writesTo(/api\/accounting\/year-lock$/, "POST").length, 0, "a PIN that was typed and abandoned was sent");
    },
  },
];
