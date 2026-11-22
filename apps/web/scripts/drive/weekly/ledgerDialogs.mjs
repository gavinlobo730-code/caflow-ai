/**
 * THE ACCOUNT LEDGER, THE ACCOUNT EDITOR OVER IT AND ADD ACCOUNT ARE THE SHARED DIALOG AND SIDE SHEET (POST-A-130, eleventh step),
 * driven in a browser.
 *
 * On a client's Accounting screen an account's ledger was a panel built by hand over the page, Edit Account was another layer built by hand
 * inside it (it stopped every click, because it sat under the ledger's click-to-close backdrop), and Add Account was a side sheet built by
 * hand. None had a name a screen reader announces, none kept Tab inside, none gave focus back. The ledger and the editor are the shared
 * Modal now and Add Account is the shared Drawer. The source guard holds the three; this drives:
 *
 *   1. the ledger is a dialog named for its account, with "Account ledger" under the name, modal, the page locked, Tab kept inside; Edit
 *      opens a SECOND dialog named Edit Account, Tab stays inside THAT one, a click inside it closes nothing, a click beside it closes it
 *      alone, and Escape closes it alone and gives focus back to the ledger's Edit; Escape again closes the ledger and unlocks the page;
 *   2. while the editor's save is out, Escape, a click beside it and its close button close neither it nor the ledger, and the save is
 *      sent once;
 *   3. Add Account is a named modal side sheet that keeps Tab inside, and Escape closes it and gives focus back to the Add Account button.
 *
 * That Add Account is held while ITS save is out is the nightly set's (dialog-leftovers), which runs on the same build.
 *
 * No scenario has a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";
import { ok } from "../stub.mjs";
import { CLIENT_ID } from "../fixtures.mjs";

export const group = "ledger-dialogs";

const ACCOUNT = { id: "acc-cash", account_code: "1001", account_name: "Cash in hand", account_type: "Asset", account_subtype: "Cash", is_active: true, client_id: CLIENT_ID };
const UPDATE = /api\/accounting\/accounts\/acc-cash(\?|$)/;

const focusInside = (dialog) => dialog.evaluate((d) => d.contains(document.activeElement));
const pageLocked = (page) => page.evaluate(() => document.body.style.overflow);

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
  stub.setTable("chart_of_accounts", [ACCOUNT]);
  stub.route({ method: "GET", re: /api\/accounting\/ledger\?/, reply: () => ok({ account_id: "acc-cash", account_name: "Cash in hand", opening_balance_paise: 0, opening_is_debit: true,
    closing_balance_paise: 0, closing_is_debit: true, lines: [], total: 0 }) });
  await page.goto(env.at("/accounting/?tab=coa"), { waitUntil: "networkidle" });
  await page.locator("tr[data-row-clickable]").filter({ hasText: "Cash in hand" }).first().click();
  const ledger = page.getByRole("dialog", { name: "Cash in hand", exact: true });
  await ledger.waitFor();
  return ledger;
}

export const scenarios = [
  {
    id: "the-account-ledger-is-a-named-dialog-and-the-editor-over-it-closes-alone",
    title: "Accounting > Chart of accounts > an account's ledger: a named modal dialog that keeps Tab inside; Edit opens a second named dialog over it; a click inside the editor closes nothing, a click beside it and Escape close it alone and Escape gives focus back to Edit; Escape again closes the ledger",
    async run(env) {
      const { page } = env;
      const ledger = await atTheLedger(env);
      assert.equal(await ledger.getAttribute("aria-modal"), "true", "the ledger does not say it is modal");
      assert.match(await ledger.innerText(), /Account ledger/, "the ledger lost the line under its name");
      assert.equal(await pageLocked(page), "hidden", "the page behind the ledger can still scroll");
      assert.equal(await page.getByRole("dialog").count(), 1, "more than one dialog is open before any is asked for");
      await tabStaysInside(page, ledger, 10, "the account ledger");

      const edit = ledger.getByRole("button", { name: "Edit", exact: true });
      const editor = page.getByRole("dialog", { name: "Edit Account", exact: true });
      await edit.focus();
      await edit.click();
      await editor.waitFor();
      assert.equal(await page.getByRole("dialog").count(), 2, "Edit Account is not a second dialog over the ledger");
      assert.equal(await editor.getAttribute("aria-modal"), "true", "Edit Account does not say it is modal");
      assert.equal(await editor.getByRole("button", { name: "Save Changes", exact: true }).count(), 1, "Save Changes is not inside the dialog");
      await tabStaysInside(page, editor, 8, "Edit Account");

      // Inside: a field, then the dialog's own title. Neither dialog goes (every click in the hand-built editor had to be stopped for this).
      await editor.getByRole("textbox").first().click();
      await editor.getByRole("heading", { name: "Edit Account" }).click();
      assert.equal(await editor.count(), 1, "a click inside Edit Account closed it");
      assert.equal(await ledger.count(), 1, "a click inside Edit Account closed the ledger behind it");

      // Beside it: it goes alone.
      await page.mouse.click(5, 5);
      await editor.waitFor({ state: "detached" });
      assert.equal(await ledger.count(), 1, "a click beside Edit Account closed the ledger behind it too");

      // Escape: it goes alone, and focus is back on the ledger's Edit.
      await edit.focus();
      await edit.click();
      await editor.waitFor();
      await until(() => focusInside(editor), "focus to move into Edit Account");
      await page.keyboard.press("Escape");
      await editor.waitFor({ state: "detached" });
      assert.equal(await ledger.count(), 1, "Escape on Edit Account closed the ledger behind it too");
      assert.equal(await edit.evaluate((el) => el === document.activeElement), true, "focus did not return to the ledger's Edit after Edit Account closed");
      assert.equal(await pageLocked(page), "hidden", "the page was unlocked when Edit Account closed, with the ledger still open");

      await page.keyboard.press("Escape");
      await ledger.waitFor({ state: "detached" });
      assert.equal(await pageLocked(page), "", "the page is still locked after the ledger closed");
    },
  },
  {
    id: "the-account-editor-over-the-ledger-is-held-while-its-save-is-out",
    title: "Accounting > an account's ledger > Edit > Save Changes: while the save is out, Escape, a click beside the dialog and its close button close neither it nor the ledger, and the save is sent once",
    async run(env) {
      const { page, stub } = env;
      const ledger = await atTheLedger(env);
      stub.route({ method: "PATCH", re: UPDATE, delay: 2500, reply: () => ok({ id: "acc-cash" }) });
      await ledger.getByRole("button", { name: "Edit", exact: true }).click();
      const editor = page.getByRole("dialog", { name: "Edit Account", exact: true });
      await editor.waitFor();
      await editor.getByRole("textbox").first().fill("Cash in hand — head office");
      await editor.getByRole("button", { name: "Save Changes", exact: true }).click();
      await editor.getByRole("button", { name: "Saving…" }).waitFor();
      await page.keyboard.press("Escape");
      await page.mouse.click(5, 5);
      await editor.getByRole("button", { name: "Close dialog", exact: true }).click();
      assert.equal(await editor.count(), 1, "Edit Account closed while its save was still out");
      assert.equal(await ledger.count(), 1, "the ledger behind Edit Account closed while the save was still out");
      await editor.waitFor({ state: "detached", timeout: 10_000 });
      assert.equal(await ledger.count(), 1, "the ledger closed with the editor after the save");
      assert.equal(stub.writesTo(UPDATE, "PATCH").length, 1, "the account's change was not sent exactly once");
    },
  },
  {
    id: "add-account-is-a-named-side-sheet-that-keeps-the-keyboard-and-gives-focus-back",
    title: "Accounting > Chart of accounts > Add Account: a named modal side sheet with its buttons inside, Tab kept inside, the page locked, Escape closes it and focus returns to the Add Account button",
    async run(env) {
      const { page } = env;
      await page.goto(env.at("/accounting/?tab=coa"), { waitUntil: "networkidle" });
      const opener = page.getByRole("button", { name: "Add Account" }).first();
      await opener.waitFor();
      await opener.focus();
      await opener.click();
      const sheet = page.getByRole("dialog", { name: "Add Account", exact: true });
      await sheet.waitFor();
      assert.equal(await sheet.getAttribute("aria-modal"), "true", "Add Account does not say it is modal");
      assert.equal(await sheet.getByRole("button", { name: "Cancel", exact: true }).count(), 1, "Cancel is not inside the side sheet");
      assert.equal(await sheet.getByRole("button", { name: "Add Account", exact: true }).count(), 1, "the save button is not inside the side sheet");
      assert.equal(await pageLocked(page), "hidden", "the page behind Add Account can still scroll");
      await tabStaysInside(page, sheet, 12, "Add Account");
      await page.keyboard.press("Escape");
      await sheet.waitFor({ state: "detached" });
      assert.equal(await pageLocked(page), "", "the page is still locked after Add Account closed");
      assert.equal(await opener.evaluate((el) => el === document.activeElement), true, "focus did not return to the Add Account button");
    },
  },
];
