/**
 * THE BANK'S DIALOGS AND THE OPENING-DOCUMENT SHEET ARE THE SHARED DIALOG OR SIDE SHEET (POST-A-130, eighteenth step), driven in a browser.
 *
 * Bank accounts and statements, Add (and Edit) Bank Account, Import Bank Statement and Reopen this reconciliation were layers built by
 * hand over the page, the first of them with two more opened inside it; Add an opening invoice (or bill) was a side sheet built by hand.
 * Only the first said it was a dialog, none kept Tab inside, none closed on Escape and none gave focus back. They are the shared Modal
 * and Drawer now. The source guard holds the five; this drives what each has to get right:
 *
 *   1. the Accounts panel is a named modal dialog that keeps Tab inside; Add Bank Account opens a SECOND named dialog over it that keeps
 *      Tab inside itself, and Escape closes that one alone and gives focus back to the panel's button; Escape again closes the panel;
 *   2. while a new bank account is being saved, its Cancel is held and its ×, Escape and a click beside it close neither it nor the
 *      panel behind it; the server's refusal is then read inside the dialog and the request went once;
 *   3. Import Bank Statement is a named modal dialog; while the statement is being imported its Cancel is held and its ×, Escape and a
 *      click beside it do not close it (the import is a write, and closing would leave nobody knowing whether it landed); the outcome
 *      is then read inside it and Done closes it;
 *   4. Reopen this reconciliation is a named modal dialog with its period under its name; Escape closes it and what was typed is gone
 *      when it is opened again; while the reopening is out it is held, and the refusal is read inside it;
 *   5. Add an opening invoice is a named modal side sheet that keeps Tab inside and gives focus back on Escape; while the document is
 *      being recorded it is held, and the refusal is read inside it.
 *
 * No scenario asserts a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";
import { ok, refuse } from "../stub.mjs";
import { CLIENT_ID } from "../fixtures.mjs";

export const group = "bank-panel-dialogs";

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

/** The three ways out of a shared dialog other than its Cancel, tried while it should be held. */
async function tryEveryOtherWayOut(page, dialog) {
  await dialog.getByRole("button", { name: "Close dialog", exact: true }).click();
  await page.keyboard.press("Escape");
  await page.mouse.click(5, 5);
}

const BANKING = { role: "Partner", permissions: { banking: ["read", "write", "approve"], accounting: ["read", "write", "approve"] } };
const ACCOUNT = { id: "ba-1", client_id: CLIENT_ID, bank_name: "Axis Bank", account_no: "918020033445566", ifsc: "UTIB0000915", account_type: "Current",
  is_active: true, opening_balance_paise: 0, opening_balance_date: null, coa_account_id: null, currency: "INR", ledger_account_id: "acc-bank" };
const COUNTS = { needs_you: 0, proposed: 0, ready: 0, covered: 0, passed: 0, set_aside: 0, to_do: 0, undrafted: 0, trusted_pending: 0, tds_decision_pending: 0 };
const UPLOAD = /api\/banking\/statements\/upload$/;

/** The bank screen's Entries tab with the Accounts panel open and no account on record. */
async function atTheAccountsPanel(env, { create } = {}) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok(BANKING) });
  stub.route({ method: "GET", re: /api\/banking\/accounts\/deletable\?/, reply: () => ok({}) });
  stub.route({ method: "GET", re: /api\/banking\/accounts\?/, reply: () => ok([]) });
  stub.route({ method: "POST", re: /api\/banking\/accounts$/, ...(create ?? { reply: () => ok({ id: "ba-new" }) }) });
  await page.goto(env.at("/bank/?tab=entries"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Accounts", exact: true }).click();
  const panel = page.getByRole("dialog", { name: "Bank accounts and statements", exact: true });
  await panel.waitFor();
  return panel;
}

const SESSION = { id: "rec-1", bank_account_id: "ba-1", account_no: "918020033445566", statement_start_date: "2026-04-01", statement_end_date: "2026-04-30",
  opening_balance_paise: 0, closing_balance_paise: 0, adjustments_paise: 0, adjustments_reason: null, status: "completed", completed_at: "2026-05-04T10:00:00Z",
  reopen_count: 0, reopened_at: null, reopen_reason: null };
const SUMMARY = { opening_balance_paise: 0, deposits_paise: 0, withdrawals_paise: 0, adjustments_paise: 0, reconciled_book_balance_paise: 0,
  statement_closing_balance_paise: 0, difference_paise: 0, reconciles: true };
const REOPEN = /api\/banking\/reconciliations\/rec-1\/reopen$/;

/** The bank screen's Reconcile tab on a completed reconciliation, with Reopen this reconciliation open. */
async function atReopen(env, reopen) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok(BANKING) });
  stub.route({ method: "GET", re: /api\/banking\/accounts(\?|$)/, reply: () => ok([ACCOUNT]) });
  stub.route({ method: "GET", re: /api\/banking\/reconciliations\/rec-1\/report$/, reply: () => ok({
    reconciliation: SESSION, summary: SUMMARY, ties_out: true, reconciled: [], unreconciled: [], exceptions: [], not_passed: [],
    counts: { reconciled: 0, unreconciled: 0, exceptions: 0, not_passed: 0 } }) });
  stub.route({ method: "GET", re: /api\/banking\/reconciliations(\?|$)/, reply: () => ok([SESSION]) });
  stub.route({ method: "POST", re: REOPEN, ...reopen });
  await page.goto(env.at("/bank/?tab=reconcile"), { waitUntil: "networkidle" });
  await page.getByLabel("Reconciliation session").selectOption("rec-1");
  const opener = page.getByRole("button", { name: "Reopen…", exact: true });
  await opener.waitFor();
  await opener.click();
  const dialog = page.getByRole("dialog", { name: "Reopen this reconciliation", exact: true });
  await dialog.waitFor();
  return { dialog, opener };
}

const OPENING_DOC = /api\/opening-documents$/;

/** The Opening Balances tab with Add an opening invoice open on a customer, a number, a date and an amount. */
async function atTheOpeningInvoice(env, record) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /api\/customers/, reply: () => ok([{ id: "cu1", name: "Beta Stores" }]) });
  stub.route({ method: "POST", re: OPENING_DOC, ...record });
  await page.goto(env.at("/accounting/?tab=opening-balances"), { waitUntil: "networkidle" });
  const opener = page.getByRole("button", { name: "Add a document" }).first();
  await opener.focus();
  await opener.click();
  const sheet = page.getByRole("dialog", { name: "Add an opening invoice", exact: true });
  await sheet.waitFor();
  return { sheet, opener };
}

export const scenarios = [
  {
    id: "the-accounts-panel-is-a-named-dialog-and-add-bank-account-over-it-closes-alone-on-escape",
    title: "Bank > Accounts: a named modal dialog that keeps Tab inside; Add Bank Account opens a second named dialog over it that keeps Tab inside itself, and Escape closes that one alone and gives focus back to the panel's button; Escape again closes the panel",
    async run(env) {
      const { page } = env;
      const panel = await atTheAccountsPanel(env);
      assert.equal(await panel.getAttribute("aria-modal"), "true", "the Accounts panel does not say it is modal");
      assert.match(await panel.innerText(), /Add an account once; import a statement when the bank sends one/, "the panel lost the line under its name");
      assert.equal(await pageLocked(page), "hidden", "the page behind the panel can still scroll");
      assert.equal(await page.getByRole("dialog").count(), 1, "more than one dialog is open before any is asked for");
      await tabStaysInside(page, panel, 6, "the Accounts panel");

      const opener = panel.getByRole("button", { name: "Add Account" }).first();
      await opener.focus();
      await opener.click();
      const form = page.getByRole("dialog", { name: "Add Bank Account", exact: true });
      await form.waitFor();
      assert.equal(await page.getByRole("dialog").count(), 2, "Add Bank Account is not a second dialog over the panel");
      assert.equal(await form.getAttribute("aria-modal"), "true", "Add Bank Account does not say it is modal");
      for (const name of ["Cancel", "Add Account"]) {
        assert.equal(await form.getByRole("button", { name, exact: true }).count(), 1, `${name} is not inside Add Bank Account`);
      }
      assert.equal(await form.getByLabel("Bank Name", { exact: true }).evaluate((el) => el === document.activeElement), true, "focus is not in the first field of Add Bank Account");
      await tabStaysInside(page, form, 10, "Add Bank Account");
      await page.keyboard.press("Escape");
      await form.waitFor({ state: "detached" });
      assert.equal(await panel.count(), 1, "Escape on Add Bank Account closed the panel behind it too");
      assert.equal(await opener.evaluate((el) => el === document.activeElement), true, "focus did not return to the panel's Add Account button");
      assert.equal(await pageLocked(page), "hidden", "the page was unlocked when Add Bank Account closed, with the panel still open");

      await page.keyboard.press("Escape");
      await panel.waitFor({ state: "detached" });
      assert.equal(await pageLocked(page), "", "the page is still locked after the panel closed");
    },
  },
  {
    id: "add-bank-account-is-held-while-it-is-saved-and-the-refusal-is-read-in-it",
    title: "Bank > Accounts > Add Bank Account > Add Account: while the account is being saved Cancel is held and the ×, Escape and a click beside the dialog close neither it nor the panel behind it; the server's refusal is then read inside the dialog",
    async run(env) {
      const { page, stub } = env;
      const panel = await atTheAccountsPanel(env, { create: { delay: 2500, ...refuse("A stub refusal of the bank account.", 422) } });
      await panel.getByRole("button", { name: "Add Account" }).first().click();
      const form = page.getByRole("dialog", { name: "Add Bank Account", exact: true });
      await form.waitFor();
      await form.getByLabel("Bank Name", { exact: true }).fill("Axis Bank");
      await form.getByLabel("Account Number", { exact: true }).fill("918020033445566");
      await form.getByRole("button", { name: "Add Account", exact: true }).click();
      await form.getByRole("button", { name: "Saving…" }).waitFor({ timeout: 3000 });
      assert.equal(await form.getByRole("button", { name: "Cancel", exact: true }).isDisabled(), true, "Cancel is live while the account is being saved");
      await tryEveryOtherWayOut(page, form);
      assert.equal(await form.count(), 1, "the ×, Escape or a click beside it closed Add Bank Account while the account was being saved");
      assert.equal(await panel.count(), 1, "the panel behind Add Bank Account was closed while the account was being saved");
      await form.getByText("A stub refusal of the bank account.").waitFor({ timeout: 8000 }).catch(() => { throw new Error("the server's refusal was not shown inside the dialog"); });
      assert.equal(await form.getByRole("button", { name: "Cancel", exact: true }).isDisabled(), false, "Cancel stayed held after the answer");
      assert.equal(stub.writesTo(/api\/banking\/accounts$/).length, 1, "the bank account was not sent exactly once");
    },
  },
  {
    id: "import-bank-statement-is-a-named-dialog-held-while-the-statement-is-imported",
    title: "Bank > Import statement: a named modal dialog that keeps Tab inside; while the statement is being imported Cancel is held and the ×, Escape and a click beside it do not close it; the outcome is read inside it and Done closes it",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok(BANKING) });
      stub.route({ method: "GET", re: /api\/banking\/accounts/, reply: () => ok([ACCOUNT]) });
      stub.route({ method: "GET", re: /api\/banking\/entries\/counts/, reply: () => ok(COUNTS) });
      stub.route({ method: "GET", re: /api\/banking\/entries\?/, reply: () => ok({ rows: [], total: 0, ledger_order: [] }) });
      stub.route({ method: "POST", re: UPLOAD, delay: 2500,
        reply: () => ok({ imported: 12, duplicates_skipped: 0, verified: true, totals_check: { agrees: true, label: "Closing Balance" } }) });
      await page.goto(env.at("/bank/"), { waitUntil: "networkidle" });
      const openImport = page.getByRole("button", { name: /Import statement/ }).first();
      await until(async () => (await openImport.count()) > 0 && await openImport.isEnabled(), "Import statement to be offered", 20000);
      await openImport.click();
      const dialog = page.getByRole("dialog", { name: "Import Bank Statement", exact: true });
      await dialog.waitFor();
      assert.equal(await dialog.getAttribute("aria-modal"), "true", "the import dialog does not say it is modal");
      assert.equal(await pageLocked(page), "hidden", "the page behind the import dialog can still scroll");
      for (const name of ["Cancel", "Import"]) {
        assert.equal(await dialog.getByRole("button", { name, exact: true }).count(), 1, `${name} is not inside the import dialog`);
      }
      await tabStaysInside(page, dialog, 8, "the import dialog");

      await page.locator('input[aria-label="Statement File * (.csv, .xlsx or .pdf)"]').setInputFiles({
        name: "statement-apr.csv", mimeType: "text/csv", buffer: Buffer.from("Date,Narration,Debit,Credit,Balance\n01/04/2026,Opening,,,0.00\n") });
      await dialog.getByRole("button", { name: "Import", exact: true }).click();
      await dialog.getByRole("button", { name: "Importing…" }).waitFor({ timeout: 3000 });
      assert.equal(await dialog.getByRole("button", { name: "Cancel", exact: true }).isDisabled(), true, "Cancel is live while the statement is being imported");
      await tryEveryOtherWayOut(page, dialog);
      assert.equal(await dialog.count(), 1, "the ×, Escape or a click beside it closed the import dialog while the statement was being imported");
      await dialog.getByText("12 transactions imported").waitFor({ timeout: 8000 }).catch(() => { throw new Error("the outcome of the import was not shown inside the dialog"); });
      assert.equal(stub.writesTo(UPLOAD).length, 1, "the statement was not sent exactly once");
      await dialog.getByRole("button", { name: "Done", exact: true }).click();
      await dialog.waitFor({ state: "detached" });
      assert.equal(await pageLocked(page), "", "the page is still locked after the import dialog closed");
    },
  },
  {
    id: "reopen-this-reconciliation-is-a-named-dialog-that-forgets-what-was-typed-and-is-held-while-reopening",
    title: "Bank > Reconcile > Reopen…: a named modal dialog with its period under its name; Escape closes it, gives focus back and forgets the reason typed; while the reopening is out it is held, and the server's refusal is read inside it",
    async run(env) {
      const { page, stub } = env;
      const { dialog, opener } = await atReopen(env, { delay: 2500, ...refuse("A stub refusal of the reopening.", 403) });
      assert.equal(await dialog.getAttribute("aria-modal"), "true", "the Reopen dialog does not say it is modal");
      assert.match(await dialog.innerText(), /01[/-]04[/-]2026|1 Apr 2026|01 Apr 2026/, "the Reopen dialog lost the period under its name");
      for (const name of ["Cancel", "Reopen"]) {
        assert.equal(await dialog.getByRole("button", { name, exact: true }).count(), 1, `${name} is not inside the Reopen dialog`);
      }
      const reason = dialog.locator("textarea");
      assert.equal(await reason.evaluate((el) => el === document.activeElement), true, "focus is not in the reason box");
      await tabStaysInside(page, dialog, 6, "the Reopen dialog");
      await reason.fill("April rent was reconciled into March by mistake");
      await page.keyboard.press("Escape");
      await dialog.waitFor({ state: "detached" });
      assert.equal(await opener.evaluate((el) => el === document.activeElement), true, "focus did not return to Reopen…");
      assert.equal(stub.writesTo(REOPEN).length, 0, "abandoning the Reopen dialog sent something");

      await opener.click();
      await dialog.waitFor();
      assert.equal(await reason.inputValue(), "", "the reason typed and abandoned was still in the box when the dialog was opened again");
      await reason.fill("April rent was reconciled into March by mistake");
      await dialog.getByRole("button", { name: "Reopen", exact: true }).click();
      await dialog.getByRole("button", { name: "Reopening…" }).waitFor({ timeout: 3000 });
      assert.equal(await dialog.getByRole("button", { name: "Cancel", exact: true }).isDisabled(), true, "Cancel is live while the reopening is out");
      await tryEveryOtherWayOut(page, dialog);
      assert.equal(await dialog.count(), 1, "the ×, Escape or a click beside it closed the Reopen dialog while the reopening was out");
      await dialog.getByText("A stub refusal of the reopening.").waitFor({ timeout: 8000 }).catch(() => { throw new Error("the server's refusal was not shown inside the dialog"); });
      assert.equal(stub.writesTo(REOPEN).length, 1, "the reopening was not sent exactly once");
    },
  },
  {
    id: "add-an-opening-invoice-is-a-named-side-sheet-held-while-the-document-is-recorded",
    title: "Accounting > Opening Balances > Add a document: a named modal side sheet with its buttons inside that keeps Tab inside and gives focus back on Escape; while the document is being recorded it is held, and the server's refusal is read inside it",
    async run(env) {
      const { page, stub } = env;
      const { sheet, opener } = await atTheOpeningInvoice(env, { delay: 2500, ...refuse("A stub refusal of the opening document.", 422) });
      assert.equal(await sheet.getAttribute("aria-modal"), "true", "the side sheet does not say it is modal");
      assert.equal(await pageLocked(page), "hidden", "the page behind the side sheet can still scroll");
      for (const name of ["Cancel", "Record"]) {
        assert.equal(await sheet.getByRole("button", { name, exact: true }).count(), 1, `${name} is not inside the side sheet`);
      }
      await tabStaysInside(page, sheet, 8, "Add an opening invoice");
      await page.keyboard.press("Escape");
      await sheet.waitFor({ state: "detached" });
      assert.equal(await opener.evaluate((el) => el === document.activeElement), true, "focus did not return to Add a document");
      assert.equal(await pageLocked(page), "", "the page is still locked after the side sheet closed");

      await opener.click();
      await sheet.waitFor();
      await sheet.locator("label:has-text('Customer') select").selectOption("cu1");
      await sheet.locator("label:has-text('Invoice number') input").fill("OLD/2025/0042");
      await sheet.locator("#opening-doc-date").fill("15/07/2025");
      await sheet.locator("label:has-text('Still outstanding') input").fill("15000");
      await sheet.getByRole("button", { name: "Record", exact: true }).click();
      await sheet.getByRole("button", { name: "Saving…" }).waitFor({ timeout: 3000 });
      assert.equal(await sheet.getByRole("button", { name: "Cancel", exact: true }).isDisabled(), true, "Cancel is live while the document is being recorded");
      await sheet.getByRole("button", { name: "Close", exact: true }).click({ force: true }).catch(() => {});
      await page.keyboard.press("Escape");
      await page.mouse.click(5, 5);
      assert.equal(await sheet.count(), 1, "the ×, Escape or a click beside it closed the side sheet while the document was being recorded");
      await sheet.getByText("A stub refusal of the opening document.").waitFor({ timeout: 8000 }).catch(() => { throw new Error("the server's refusal was not shown inside the side sheet"); });
      assert.equal(await sheet.getByRole("button", { name: "Cancel", exact: true }).isDisabled(), false, "Cancel stayed held after the answer");
      assert.equal(stub.writesTo(OPENING_DOC).length, 1, "the opening document was not sent exactly once");
    },
  },
];
