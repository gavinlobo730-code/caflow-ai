/**
 * Group E: one delete and one prompt (frontend_ux-21).
 *
 * Every question the product asks is an in-app dialog: a native `confirm`, `alert` or `prompt` cannot say what a
 * statutory action will do, blocks the page, and looks like the browser asking. The runner fails ANY native
 * dialog in any scenario (the leave-site prompt aside), so this group needs no assertion for that; what it drives
 * is what the dialogs DO: Cancel sends nothing, the destructive button sends exactly one request, and the reason
 * a CA writes into a prompt is the reason that is sent.
 */
import assert from "node:assert/strict";
import { expectWrites } from "../kit.mjs";
import { openBillDrawer, openInvoiceDrawer } from "../flows.mjs";
import { ok } from "../stub.mjs";
import { PAYROLL_RUN } from "../fixtures.mjs";

export const group = "delete-and-prompt";

export const scenarios = [
  {
    id: "delete-draft-cancel-sends-nothing",
    title: "Cancel in the delete-draft dialog closes it and sends no request",
    async run(env) {
      const { page, stub } = env;
      const drawer = await openInvoiceDrawer(env, "draft");
      stub.route({ method: "DELETE", re: /sales-invoices\/inv-9$/, reply: () => ok(null) });
      await drawer.getByRole("button", { name: "Delete", exact: true }).first().click();
      await page.getByText("Delete draft invoice?").waitFor();
      await page.getByRole("button", { name: "Cancel", exact: true }).last().click();
      await page.getByText("Delete draft invoice?").waitFor({ state: "detached" });
      await expectWrites(stub, /sales-invoices\/inv-9$/, 0, "Cancel in the delete dialog", "DELETE");
    },
  },
  {
    id: "delete-draft-sends-one-delete",
    title: "Delete Draft sends exactly one DELETE and the dialog goes",
    async run(env) {
      const { page, stub } = env;
      const drawer = await openInvoiceDrawer(env, "draft");
      stub.route({ method: "DELETE", re: /sales-invoices\/inv-9$/, reply: () => ok(null) });
      await drawer.getByRole("button", { name: "Delete", exact: true }).first().click();
      await page.getByRole("button", { name: /Delete Draft/ }).click();
      await expectWrites(stub, /sales-invoices\/inv-9$/, 1, "Delete Draft", "DELETE");
      assert.equal(await page.getByText("Delete draft invoice?").count(), 0, "the delete dialog is still open after a successful delete");
    },
  },
  {
    id: "cancel-bill-asks-in-app-and-cancel-sends-nothing",
    title: "Cancel Bill asks through the in-app dialog; saying no sends nothing, yes sends one cancellation",
    async run(env) {
      const { page, stub } = env;
      const drawer = await openBillDrawer(env, "received");
      stub.route({ method: "POST", re: /purchase-bills\/b9\/cancel$/, reply: () => ok({ id: "b9" }) });
      await drawer.getByRole("button", { name: "Cancel Bill", exact: true }).click();
      const question = page.getByRole("alertdialog");
      await question.waitFor();
      await question.getByRole("button", { name: "Cancel", exact: true }).click();
      await question.waitFor({ state: "detached" });
      await expectWrites(stub, /purchase-bills\/b9\/cancel$/, 0, "saying no to Cancel Bill", "POST");
      await drawer.getByRole("button", { name: "Cancel Bill", exact: true }).click();
      await page.getByRole("alertdialog").waitFor();
      // The confirming button is the other one in the dialog.
      await page.getByRole("alertdialog").getByRole("button").last().click();
      await expectWrites(stub, /purchase-bills\/b9\/cancel$/, 1, "saying yes to Cancel Bill", "POST");
    },
  },
  {
    id: "payroll-reverse-prompt",
    title: "Reversing a payroll run asks for a reason; Cancel sends nothing, a short reason is refused, a real one is sent",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "GET", re: /payroll\/runs\?/, reply: () => ok([PAYROLL_RUN]) });
      stub.route({ method: "POST", re: /payroll\/runs\/run1\/reverse$/, reply: () => ok({ id: "run1", status: "review", loan_notes: [] }) });
      await page.goto(env.at("/payroll/?tab=release"), { waitUntil: "networkidle" });
      const reverse = page.getByRole("button", { name: "Reverse", exact: true });
      await reverse.first().click();
      const box = page.locator("#confirm-dialog-input");
      await box.waitFor();
      // 1. Cancel.
      await page.getByRole("alertdialog").getByRole("button", { name: "Cancel", exact: true }).click();
      await page.getByRole("alertdialog").waitFor({ state: "detached" });
      await expectWrites(stub, /payroll\/runs\/run1\/reverse$/, 0, "Cancel in the reversal prompt", "POST");
      // 2. A reason that is too short is refused by the screen, in words, and nothing is sent.
      await reverse.first().click();
      await page.locator("#confirm-dialog-input").fill("short");
      await page.getByRole("alertdialog").getByRole("button", { name: "Reverse", exact: true }).click();
      await page.getByText("A reversal needs a reason of at least ten characters.").waitFor({ timeout: 4000 });
      await expectWrites(stub, /payroll\/runs\/run1\/reverse$/, 0, "a reversal with a four-letter reason", "POST");
      // 3. A real reason is sent, once, WITH the reason.
      const reason = "Wrong attendance imported for September";
      await reverse.first().click();
      await page.locator("#confirm-dialog-input").fill(reason);
      await page.getByRole("alertdialog").getByRole("button", { name: "Reverse", exact: true }).click();
      await expectWrites(stub, /payroll\/runs\/run1\/reverse$/, 1, "a reversal with a real reason", "POST");
      const sent = stub.writesTo(/payroll\/runs\/run1\/reverse$/)[0].body;
      assert.ok(sent.includes(reason),
        `the reason the CA wrote was thrown away: the request body is ${JSON.stringify(sent)}, and the screen says the server records it`);
    },
  },
];
