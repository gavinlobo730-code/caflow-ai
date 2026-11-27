/**
 * EDIT BANK ACCOUNT AND ADD AN OPENING BILL ARE DRIVEN IN A BROWSER (POST-A-555).
 *
 * The eighteenth step of POST-A-130 moved the bank's Add Bank Account dialog and the opening-document side sheet onto the shared dialog and
 * Drawer and drove the INVOICE half of the sheet and the ADD half of the dialog. The same two components open as Edit Bank Account (over an
 * account on record) and as Add an opening bill (on the Payable switch, with a vendor for a customer). Against a stubbed server, in Chromium:
 *
 *   1. Edit Bank Account, opened from an account's row in the Accounts panel, is a named modal dialog over the panel, with its Cancel and
 *      Save Changes inside, focus in the first field, Tab and Shift+Tab kept inside, and Escape closes it ALONE (the panel stays) and gives
 *      focus back to the row's Edit button;
 *   2. while the change is being saved its Cancel is held, the ×, Escape and a click beside it close neither it nor the panel, the request
 *      goes ONCE, and the server's refusal is read inside the dialog;
 *   3. Add an opening bill (Opening Balances > Payable > Add a document) is a named modal side sheet that asks for a VENDOR and a BILL
 *      number (not a customer and an invoice number), keeps Tab inside, and Escape closes it and gives focus back to Add a document.
 *
 * No scenario asserts a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";
import { ok, refuse } from "../stub.mjs";
import { CLIENT_ID } from "../fixtures.mjs";

export const group = "bank-account-edit-and-opening-bill";

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

const BANKING = { role: "Partner", permissions: { banking: ["read", "write", "approve"], accounting: ["read", "write", "approve"] } };
const ACCOUNT = { id: "ba-1", client_id: CLIENT_ID, bank_name: "Axis Bank", account_no: "918020033445566", ifsc: "UTIB0000915", account_type: "Current",
  is_active: true, opening_balance_paise: 0, opening_balance_date: null, coa_account_id: null, currency: "INR", ledger_account_id: "acc-bank" };
const UPDATE = /api\/banking\/accounts\/ba-1$/;

/** The bank screen with the Accounts panel open on one account, and that account's Edit pressed. */
async function atEditBankAccount(env, update) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok(BANKING) });
  stub.route({ method: "GET", re: /api\/banking\/accounts\/deletable\?/, reply: () => ok({}) });
  stub.route({ method: "GET", re: /api\/banking\/accounts\?/, reply: () => ok([ACCOUNT]) });
  stub.route({ method: "PATCH", re: UPDATE, ...(update ?? { reply: () => ok(ACCOUNT) }) });
  await page.goto(env.at("/bank/?tab=entries"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Accounts", exact: true }).click();
  const panel = page.getByRole("dialog", { name: "Bank accounts and statements", exact: true });
  await panel.waitFor();
  const opener = panel.getByRole("button", { name: "Edit", exact: true }).first();
  await opener.waitFor();
  await opener.focus();
  await opener.click();
  const dialog = page.getByRole("dialog", { name: "Edit Bank Account", exact: true });
  await dialog.waitFor();
  return { panel, dialog, opener };
}

export const scenarios = [
  {
    id: "edit-bank-account-is-a-named-dialog-over-the-panel-that-closes-alone-and-gives-focus-back",
    title: "Bank > Accounts > an account's Edit: a named modal dialog over the panel with its buttons inside, focus in the first field, Tab kept inside; Escape closes it alone and focus returns to the row's Edit button",
    async run(env) {
      const { page } = env;
      const { panel, dialog, opener } = await atEditBankAccount(env);
      assert.equal(await page.getByRole("dialog").count(), 2, "Edit Bank Account is not a second dialog over the panel");
      assert.equal(await dialog.getAttribute("aria-modal"), "true", "Edit Bank Account does not say it is modal");
      for (const name of ["Cancel", "Save Changes"]) {
        assert.equal(await dialog.getByRole("button", { name, exact: true }).count(), 1, `${name} is not inside Edit Bank Account`);
      }
      assert.equal(await dialog.getByLabel("Bank Name", { exact: true }).evaluate((el) => el === document.activeElement), true, "focus is not in the first field of Edit Bank Account");
      await tabStaysInside(page, dialog, 10, "Edit Bank Account");
      await page.keyboard.press("Escape");
      await dialog.waitFor({ state: "detached" });
      assert.equal(await panel.count(), 1, "Escape on Edit Bank Account closed the panel behind it too");
      assert.equal(await opener.evaluate((el) => el === document.activeElement), true, "focus did not return to the row's Edit button");
      assert.equal(await pageLocked(page), "hidden", "the page was unlocked when Edit Bank Account closed, with the panel still open");
    },
  },
  {
    id: "edit-bank-account-is-held-while-it-is-saved-and-the-refusal-is-read-in-it",
    title: "Edit Bank Account > Save Changes: while the change is out Cancel is held and the ×, Escape and a click beside it close neither the dialog nor the panel, the request goes once, and the refusal is read inside the dialog",
    async run(env) {
      const { page, stub } = env;
      const { panel, dialog } = await atEditBankAccount(env, { delay: 2500, ...refuse("A stub refusal of the account change.", 422) });
      await dialog.getByLabel("Bank Name", { exact: true }).fill("Axis Bank Ltd");
      stub.forgetWrites();
      await dialog.getByRole("button", { name: "Save Changes", exact: true }).click();
      await dialog.getByRole("button", { name: "Saving…" }).waitFor({ timeout: 3000 });
      assert.equal(await dialog.getByRole("button", { name: "Cancel", exact: true }).isDisabled(), true, "Cancel is live while the change is being saved");
      await dialog.getByRole("button", { name: "Close dialog", exact: true }).click({ force: true }).catch(() => {});
      await page.keyboard.press("Escape");
      await page.mouse.click(5, 5);
      assert.equal(await dialog.count(), 1, "the ×, Escape or a click beside it closed Edit Bank Account while the change was being saved");
      assert.equal(await panel.count(), 1, "the panel behind Edit Bank Account was closed while the change was being saved");
      await dialog.getByText("A stub refusal of the account change.").waitFor({ timeout: 8000 })
        .catch(() => { throw new Error("the server's refusal was not shown inside Edit Bank Account"); });
      assert.equal(await dialog.getByRole("button", { name: "Cancel", exact: true }).isDisabled(), false, "Cancel stayed held after the answer");
      const sent = stub.writesTo(UPDATE, "PATCH");
      assert.equal(sent.length, 1, "the change was not sent exactly once");
      assert.equal(JSON.parse(sent[0].body).bank_name, "Axis Bank Ltd", "the request did not carry the edited name");
    },
  },
  {
    id: "add-an-opening-bill-is-a-named-side-sheet-that-asks-for-a-vendor-and-gives-focus-back",
    title: "Accounting > Opening Balances > Payable > Add a document: a named modal side sheet that asks for a Vendor and a Bill number, keeps Tab inside, and Escape closes it and gives focus back",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok(BANKING) });
      stub.route({ method: "GET", re: /api\/vendors\//, reply: () => ok([{ id: "v1", name: "Gupta Stationers" }]) });
      await page.goto(env.at("/accounting/?tab=opening-balances"), { waitUntil: "networkidle" });
      await page.getByRole("button", { name: /^Payable$/ }).click();
      const opener = page.getByRole("button", { name: "Add a document" }).first();
      await opener.waitFor();
      await opener.focus();
      await opener.click();
      const sheet = page.getByRole("dialog", { name: "Add an opening bill", exact: true });
      await sheet.waitFor();
      assert.equal(await sheet.getAttribute("aria-modal"), "true", "the side sheet does not say it is modal");
      assert.equal(await pageLocked(page), "hidden", "the page behind the side sheet can still scroll");
      assert.equal(await sheet.locator("label:has-text('Vendor')").count() > 0, true, "the sheet does not ask for a Vendor");
      assert.equal(await sheet.locator("label:has-text('Bill number')").count() > 0, true, "the sheet does not ask for a Bill number");
      assert.equal(await sheet.locator("label:has-text('Customer')").count(), 0, "a bill's sheet asks for a Customer");
      for (const name of ["Cancel", "Record"]) {
        assert.equal(await sheet.getByRole("button", { name, exact: true }).count(), 1, `${name} is not inside the side sheet`);
      }
      await tabStaysInside(page, sheet, 8, "Add an opening bill");
      await page.keyboard.press("Escape");
      await sheet.waitFor({ state: "detached" });
      assert.equal(await opener.evaluate((el) => el === document.activeElement), true, "focus did not return to Add a document");
      assert.equal(await pageLocked(page), "", "the page is still locked after the side sheet closed");
      assert.equal(stub.allWrites().length, 0, "opening and closing the sheet wrote something");
    },
  },
];
