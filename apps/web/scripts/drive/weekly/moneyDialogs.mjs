/**
 * TWELVE MORE HAND-BUILT DIALOGS ARE THE SHARED ONE (POST-A-130, fifth step), driven in a browser.
 *
 * The dialogs where money is recorded were hand-built overlays: applying a receipt to invoices, applying a vendor payment to bills, marking a
 * payroll run paid, applying a salary structure, an employee's portal access, a new loan and a new fixed deposit, a recurring journal, a
 * retainer, a recurring bill and its history, and the New Task form. None of them had a name a screen reader could announce, none kept Tab
 * inside, none closed on Escape and none gave focus back; the keyboard walked out to the page behind an open money dialog. Each is the shared
 * Modal (the history panel is the shared Drawer) now. The source guard holds all twelve; this drives three of them, which stand for the rest
 * because they are the same component, and each of the three differs in the one way that matters:
 *
 *   1. applying a receipt (a dialog with a note under its title, opened from a table row): named, modal, the page locked, Tab and Shift+Tab
 *      kept inside, Escape closes it and focus returns to the row's button; and WHILE THE ALLOCATION IS BEING SAVED Escape does nothing,
 *      because closing a dialog with a write in flight leaves the person not knowing whether it applied;
 *   2. Add Loan and Add Fixed Deposit (dialogs whose buttons are the shared footer): named, the buttons inside the dialog and the bar ON the
 *      dialog's bottom edge (it sat 16px above it, a white strip the form showed through), Tab kept inside, Escape closes and focus returns
 *      to the button that opened it;
 *   3. New Task (a dialog around a form): named, focus moves into it, Escape closes it and focus returns.
 *
 * No scenario has a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";
import { ok } from "../stub.mjs";
import { CUSTOMER } from "../fixtures.mjs";

export const group = "money-dialogs";

const ALLOCATE = /api\/receipts\/r1\/allocate$/;
const RECEIPT = {
  id: "r1", receipt_no: "RCT-0001", receipt_date: "2026-10-02", customer_id: CUSTOMER.id, amount_paise: 5_000_000, tds_paise: 200_000,
  payment_mode: "bank", bank_account_id: null, reference_no: null, allocated_paise: 0, unallocated_paise: 5_200_000, is_reversed: false,
  customers: { name: CUSTOMER.name },
};
const INVOICES = [
  { id: "i1", invoice_no: "INV/26-27/0001", invoice_date: "2026-08-01", total_paise: 3_540_000, outstanding_paise: 3_000_000, status: "issued" },
];

const insideDialog = (page) => page.evaluate(() => {
  const d = document.querySelector('[role="dialog"]');
  return !!d && d.contains(document.activeElement);
});
const pageLocked = (page) => page.evaluate(() => document.body.style.overflow);

/** Tab and Shift+Tab, `n` times each, never leave the open dialog. */
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

async function atTheReceipts(env) {
  const { page, stub } = env;
  stub.setTable("receipts", [RECEIPT]);
  stub.setTable("customers", [CUSTOMER]);
  stub.setTable("client_sales_invoices", INVOICES);
  stub.setTable("receipt_allocations", []);
  await page.goto(env.at("/sales/?tab=receipts"), { waitUntil: "networkidle" });
  const opener = page.getByRole("button", { name: "Apply", exact: true }).first();
  await opener.waitFor();
  return opener;
}

export const scenarios = [
  {
    id: "applying-a-receipt-is-a-named-dialog-that-keeps-the-keyboard-and-holds-while-it-saves",
    title: "Sales > Receipts > Apply: a named modal dialog with the receipt's figures under its title, Tab kept inside, the page locked, Escape closes and returns focus; Escape does nothing while the allocation is being saved",
    async run(env) {
      const { page, stub } = env;
      const opener = await atTheReceipts(env);
      await opener.focus();
      await opener.click();
      const dialog = page.getByRole("dialog", { name: "Apply RCT-0001" });
      await dialog.waitFor();
      assert.equal(await page.getByRole("dialog").count(), 1, "applying a receipt opened more than one dialog");
      assert.equal(await dialog.getAttribute("aria-modal"), "true", "the dialog does not say it is modal");
      assert.match(await dialog.innerText(), /to settle \(.*received \+ .*TDS\)/, "the dialog no longer says what the receipt settles");
      assert.equal(await pageLocked(page), "hidden", "the page behind the dialog can still scroll");
      await page.getByLabel("Amount to apply to INV/26-27/0001").waitFor();
      await tabStaysInside(page, 10, "the receipt dialog");

      // Escape with nothing in flight closes it and gives focus back to the row's button.
      await page.keyboard.press("Escape");
      await dialog.waitFor({ state: "detached" });
      assert.equal(await pageLocked(page), "", "the page is still locked after the dialog closed");
      assert.equal(await opener.evaluate((el) => el === document.activeElement), true, "focus did not return to the row's Apply button");

      // While the allocation is being saved, Escape and a click beside the panel are ignored.
      stub.route({ method: "PATCH", re: ALLOCATE, delay: 1200, reply: () => ok({ receipt_id: "r1", unallocated_paise: 5_100_000 }) });
      await opener.click();
      await dialog.waitFor();
      await page.getByLabel("Amount to apply to INV/26-27/0001").fill("1000");
      await dialog.getByRole("button", { name: "Apply", exact: true }).click();
      await dialog.getByRole("button", { name: "Applying…" }).waitFor();
      await page.keyboard.press("Escape");
      await page.mouse.click(12, 400);
      assert.equal(await dialog.count(), 1, "the dialog closed while its allocation was still being saved");
      await dialog.waitFor({ state: "detached", timeout: 8000 });
      assert.equal(stub.writesTo(ALLOCATE, "PATCH").length, 1, "the allocation was not sent exactly once");
    },
  },
  {
    id: "add-loan-and-add-fixed-deposit-are-named-dialogs-with-their-buttons-inside",
    title: "Accounting > Loans: Add Loan and Add Fixed Deposit are named modal dialogs whose Cancel and save buttons are inside, Tab stays inside, Escape closes and focus returns to the button that opened it",
    async run(env) {
      const { page } = env;
      await page.goto(`${env.base}/accounting/loans/`, { waitUntil: "networkidle" });
      const cases = [
        { tab: null, opener: "Add Loan", name: "Add Loan", save: "Add Loan" },
        { tab: "Fixed Deposits", opener: "Add FD", name: "Add Fixed Deposit", save: "Add FD" },
      ];
      for (const c of cases) {
        if (c.tab) await page.getByRole("button", { name: c.tab, exact: true }).click();
        const opener = page.getByRole("button", { name: c.opener, exact: true }).first();
        await opener.focus();
        await opener.click();
        const dialog = page.getByRole("dialog", { name: c.name, exact: true });
        await dialog.waitFor();
        assert.equal(await dialog.getAttribute("aria-modal"), "true", `${c.name} does not say it is modal`);
        assert.equal(await dialog.getByRole("button", { name: "Cancel", exact: true }).count(), 1, `${c.name}: Cancel is not inside the dialog`);
        assert.equal(await dialog.getByRole("button", { name: c.save, exact: true }).count(), 1, `${c.name}: the save button is not inside the dialog`);
        assert.equal(await pageLocked(page), "hidden", `the page behind ${c.name} can still scroll`);
        // The button bar sits ON the panel's bottom edge: no strip of the panel beneath it for the form to show through while it scrolls.
        const gap = await dialog.evaluate((d) => d.getBoundingClientRect().bottom - [...d.children].at(-1).getBoundingClientRect().bottom);
        assert.ok(Math.abs(gap) <= 1, `${c.name}: the button bar ends ${gap}px above the dialog's bottom edge`);
        await tabStaysInside(page, 14, c.name);
        await page.keyboard.press("Escape");
        await dialog.waitFor({ state: "detached" });
        assert.equal(await pageLocked(page), "", `the page is still locked after ${c.name} closed`);
        assert.equal(await opener.evaluate((el) => el === document.activeElement), true, `focus did not return to the ${c.opener} button`);
      }
    },
  },
  {
    id: "new-task-is-a-named-dialog-that-escape-closes-and-gives-focus-back",
    title: "Tasks > New Task: a named modal dialog around the form, focus moves in, Tab stays inside, Escape closes it and focus returns to New Task",
    async run(env) {
      const { page } = env;
      await page.goto(`${env.base}/tasks/`, { waitUntil: "networkidle" });
      const opener = page.getByRole("button", { name: "New Task", exact: true }).first();
      await opener.focus();
      await opener.click();
      const dialog = page.getByRole("dialog", { name: "New Task", exact: true });
      await dialog.waitFor();
      assert.equal(await dialog.getAttribute("aria-modal"), "true", "New Task does not say it is modal");
      assert.match(await dialog.innerText(), /Create a task for a client/, "the dialog lost its line of explanation");
      assert.equal(await dialog.getByRole("button", { name: "Create Task", exact: true }).count(), 1, "Create Task is not inside the dialog");
      await tabStaysInside(page, 12, "New Task");
      await page.keyboard.press("Escape");
      await dialog.waitFor({ state: "detached" });
      assert.equal(await opener.evaluate((el) => el === document.activeElement), true, "focus did not return to the New Task button");
    },
  },
];
