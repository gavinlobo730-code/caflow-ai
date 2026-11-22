/**
 * THE SALES SCREEN'S ELEVEN HAND-BUILT DIALOGS ARE THE SHARED ONE (POST-A-130, sixth step), driven in a browser.
 *
 * The sales screen is the most used screen a client's books have, and it held eleven dialogs built by hand as a layer over the page: the
 * recurring template editor and its history, the statement's Email and Apply credit boxes, Online Payment, Send Invoice, Send Payment
 * Reminder, Delivery History, Delete draft invoice?, Deactivate Customer? and the customer's permanent-delete flow. None had a name a
 * screen reader announces, none kept Tab inside, none closed on Escape and none gave focus back. Each is the shared Modal now. The source
 * guard holds all eleven; this drives five of them, chosen for the ways they differ:
 *
 *   1. Delete draft invoice? is named and says what a delete does, Escape closes it with nothing sent, and while the delete is in flight
 *      Escape and a click outside do nothing and one DELETE is sent;
 *   1b. Online Payment is opened from INSIDE the invoice drawer (a dialog over a side panel): Tab stays in the dialog, one Escape closes
 *      the dialog and leaves the drawer open, and the next closes the drawer;
 *   2. Send Invoice is opened from a row's menu: named for its invoice, Tab and Shift+Tab stay inside, the page is locked, Escape closes;
 *   3. Deactivate Customer? is named, keeps Tab inside and closes on Escape with nothing sent;
 *   4. the customer's permanent-delete flow names each of its states: "Can't delete this customer" with what is linked, from which
 *      "Deactivate instead" opens Deactivate Customer?; and "Delete Customer?" for a customer with nothing linked.
 *
 * No scenario has a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { until, expectWrites } from "../kit.mjs";
import { openInvoiceDrawer } from "../flows.mjs";
import { ok } from "../stub.mjs";
import { CUSTOMER, invoiceRow } from "../fixtures.mjs";

export const group = "sales-dialogs";

const insideDialog = (page, name) => page.evaluate((n) => {
  const all = [...document.querySelectorAll('[role="dialog"]')];
  const d = all.find((x) => (x.getAttribute("aria-labelledby") && document.getElementById(x.getAttribute("aria-labelledby"))?.textContent?.trim() === n));
  return !!d && d.contains(document.activeElement);
}, name);

async function tabStaysInside(page, name, n) {
  await until(() => insideDialog(page, name), `focus to move into ${name}`);
  for (let i = 0; i < n; i += 1) {
    await page.keyboard.press("Tab");
    assert.equal(await insideDialog(page, name), true, `Tab number ${i + 1} left ${name}`);
  }
  for (let i = 0; i < n; i += 1) {
    await page.keyboard.press("Shift+Tab");
    assert.equal(await insideDialog(page, name), true, `Shift+Tab number ${i + 1} left ${name}`);
  }
}

async function atTheCustomers(env) {
  const { page, stub } = env;
  stub.setTable("customers", [CUSTOMER]);
  await page.goto(env.at("/sales/"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Customers", exact: true }).first().click();
  await page.getByLabel(`Actions for ${CUSTOMER.name}`).waitFor();
}

const DEPENDENCIES = new RegExp(`api/customers/${CUSTOMER.id}/dependencies$`);

export const scenarios = [
  {
    id: "delete-draft-invoice-is-a-named-dialog-that-holds-while-it-deletes",
    title: "Sales > a draft's menu > Delete: a named dialog that says what a delete does; Escape closes it and sends nothing; while the delete is in flight Escape and a click outside do nothing and ONE delete is sent",
    async run(env) {
      const { page, stub } = env;
      const DELETE = /sales-invoices\/inv-9$/;
      const row = invoiceRow("draft", "inv-9");
      stub.setTable("client_sales_invoices", [row]);
      await page.goto(env.at("/sales/"), { waitUntil: "networkidle" });
      const open = async () => {
        await page.getByLabel(`Actions for invoice ${row.invoice_no}`).click();
        await page.getByRole("button", { name: "Delete draft", exact: true }).click();
      };
      await open();
      const dialog = page.getByRole("dialog", { name: "Delete draft invoice?", exact: true });
      await dialog.waitFor();
      assert.equal(await dialog.getAttribute("aria-modal"), "true", "the delete dialog does not say it is modal");
      assert.match(await dialog.innerText(), /Only drafts can be deleted/, "the dialog lost the sentence that says what a delete does");
      assert.equal(await page.getByText("Delete draft invoice?").count(), 1, "the question is written twice");
      await until(() => insideDialog(page, "Delete draft invoice?"), "focus to move into the delete dialog");
      stub.forgetWrites();
      await page.keyboard.press("Escape");
      await dialog.waitFor({ state: "detached" });
      assert.equal(stub.writesTo(DELETE, "DELETE").length, 0, "Escape deleted the draft");

      stub.route({ method: "DELETE", re: DELETE, delay: 1200, reply: () => ok(null) });
      await open();
      await dialog.waitFor();
      await dialog.getByRole("button", { name: /Delete Draft/ }).click();
      await dialog.getByRole("button", { name: "Deleting…" }).waitFor();
      await page.keyboard.press("Escape");
      await page.mouse.click(12, 500);
      assert.equal(await dialog.count(), 1, "the dialog closed while its delete was still in flight");
      await dialog.waitFor({ state: "detached", timeout: 8000 });
      await expectWrites(stub, DELETE, 1, "Delete Draft with Escape pressed while it was in flight", "DELETE");
    },
  },
  {
    id: "online-payment-over-the-invoice-drawer-closes-alone-on-escape",
    title: "Sales > an issued invoice's drawer > Payment Link: a dialog named for its invoice opens OVER the drawer; one Escape closes the dialog and leaves the drawer, and the next closes the drawer",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "GET", re: /api\/payments\?invoice_id=inv-9$/, reply: () => ok({ links: [], payments: [], online_payment: { available: false, reason: "Online payment is not set up for this practice." }, can_pay_online: false }) });
      const drawer = await openInvoiceDrawer(env, "issued");
      const opener = drawer.getByRole("button", { name: "Payment Link", exact: true });
      await opener.click();
      const row = invoiceRow("issued", "inv-9");
      const name = `Online Payment · ${row.invoice_no}`;
      const dialog = page.getByRole("dialog", { name, exact: true });
      await dialog.waitFor();
      assert.equal(await page.getByRole("dialog").count(), 2, "the dialog is not open over the drawer");
      await until(() => insideDialog(page, name), "focus to move into the payment dialog");
      for (const key of ["Tab", "Tab", "Tab", "Shift+Tab", "Shift+Tab", "Shift+Tab", "Shift+Tab"]) {
        await page.keyboard.press(key);
        assert.equal(await insideDialog(page, name), true, `${key} left the payment dialog for the drawer behind it`);
      }
      await page.keyboard.press("Escape");
      await dialog.waitFor({ state: "detached" });
      assert.equal(await opener.isVisible(), true, "Escape on the dialog closed the drawer beneath it too");
      assert.equal(await page.getByRole("dialog").count(), 1, "the drawer went with the dialog");
      await page.keyboard.press("Escape");
      await until(async () => (await page.getByRole("dialog").count()) === 0, "the drawer to close on the next Escape");
    },
  },
  {
    id: "send-invoice-is-a-named-dialog-that-keeps-tab-inside-and-closes-on-escape",
    title: "Sales > an issued invoice's menu > Send: a dialog named for its invoice, Tab and Shift+Tab stay inside, the page is locked, Escape closes it and nothing is sent",
    async run(env) {
      const { page, stub } = env;
      const row = invoiceRow("issued", "inv-9");
      stub.setTable("client_sales_invoices", [row]);
      await page.goto(env.at("/sales/"), { waitUntil: "networkidle" });
      await page.getByLabel(`Actions for invoice ${row.invoice_no}`).click();
      await page.getByRole("button", { name: "Send", exact: true }).click();
      const name = `Send Invoice ${row.invoice_no}`;
      const dialog = page.getByRole("dialog", { name, exact: true });
      await dialog.waitFor();
      assert.equal(await page.getByRole("dialog").count(), 1, "Send opened more than one dialog");
      assert.equal(await dialog.getAttribute("aria-modal"), "true", "Send Invoice does not say it is modal");
      assert.equal(await page.evaluate(() => document.body.style.overflow), "hidden", "the page behind Send Invoice can still scroll");
      assert.equal(await dialog.getByRole("button", { name: /Send Invoice/ }).count(), 1, "the send button is not inside the dialog");
      await tabStaysInside(page, name, 8);
      stub.forgetWrites();
      await page.keyboard.press("Escape");
      await dialog.waitFor({ state: "detached" });
      assert.equal(await page.evaluate(() => document.body.style.overflow), "", "the page is still locked after Send Invoice closed");
      assert.equal(stub.writesTo(/sales-invoices\/inv-9\/send/, "POST").length, 0, "closing the dialog sent the invoice");
    },
  },
  {
    id: "deactivate-customer-is-a-named-dialog-and-escape-sends-nothing",
    title: "Sales > Customers > a customer's menu > Deactivate: a named dialog, Tab stays inside, Escape closes it and no change is sent",
    async run(env) {
      const { page, stub } = env;
      await atTheCustomers(env);
      await page.getByLabel(`Actions for ${CUSTOMER.name}`).click();
      await page.getByRole("button", { name: "Deactivate", exact: true }).first().click();
      const dialog = page.getByRole("dialog", { name: "Deactivate Customer?", exact: true });
      await dialog.waitFor();
      assert.equal(await dialog.getAttribute("aria-modal"), "true", "Deactivate Customer? does not say it is modal");
      assert.match(await dialog.innerText(), new RegExp(`${CUSTOMER.name}\\s+will no\\s+longer be available for new invoices`), "the dialog does not say whose record it is");
      await tabStaysInside(page, "Deactivate Customer?", 6);
      stub.forgetWrites();
      await page.keyboard.press("Escape");
      await dialog.waitFor({ state: "detached" });
      assert.equal(stub.writesTo(/customers/, "PATCH").length, 0, "Escape deactivated the customer");
    },
  },
  {
    id: "the-permanent-delete-flow-names-each-of-its-states",
    title: "Sales > Customers > Delete: a customer with linked records gets a dialog named \"Can't delete this customer\" that lists them, Deactivate instead opens Deactivate Customer?; one with nothing linked gets \"Delete Customer?\"",
    async run(env) {
      const { page, stub } = env;
      await atTheCustomers(env);
      stub.route({ method: "GET", re: DEPENDENCIES, reply: () => ok({ can_delete: false, dependencies: { invoices: 2, receipts: 1 } }) });
      await page.getByLabel(`Actions for ${CUSTOMER.name}`).click();
      await page.getByRole("button", { name: "Delete", exact: true }).first().click();
      const blocked = page.getByRole("dialog", { name: "Can't delete this customer", exact: true });
      await blocked.waitFor();
      const said = await blocked.innerText();
      assert.match(said, /Invoices: 2/, "the linked invoices are not listed");
      assert.match(said, /Receipts: 1/, "the linked receipts are not listed");
      await blocked.getByRole("button", { name: "Deactivate instead", exact: true }).click();
      const deactivate = page.getByRole("dialog", { name: "Deactivate Customer?", exact: true });
      await deactivate.waitFor();
      assert.equal(await page.getByRole("dialog").count(), 1, "the blocked dialog stayed open behind Deactivate Customer?");
      await until(() => insideDialog(page, "Deactivate Customer?"), "focus to move into Deactivate Customer?");
      await page.keyboard.press("Escape");
      await deactivate.waitFor({ state: "detached" });

      stub.route({ method: "GET", re: DEPENDENCIES, reply: () => ok({ can_delete: true, dependencies: {} }) });
      await page.getByLabel(`Actions for ${CUSTOMER.name}`).click();
      await page.getByRole("button", { name: "Delete", exact: true }).first().click();
      const clean = page.getByRole("dialog", { name: "Delete Customer?", exact: true });
      await clean.waitFor();
      assert.match(await clean.innerText(), /This permanently removes the customer and cannot be undone/);
      assert.equal(await clean.getByRole("button", { name: "Delete permanently", exact: true }).count(), 1, "the delete button is not inside the dialog");
      await until(() => insideDialog(page, "Delete Customer?"), "focus to move into Delete Customer?");
      stub.forgetWrites();
      await page.keyboard.press("Escape");
      await clean.waitFor({ state: "detached" });
      assert.equal(stub.writesTo(/customers/, "DELETE").length, 0, "Escape deleted the customer");
    },
  },
];
