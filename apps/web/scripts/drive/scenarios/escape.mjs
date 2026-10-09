/**
 * Group F: Escape and Cancel behave like a stack (frontend_ux-21, -23).
 *
 * A modal opened over a drawer is the topmost thing, and one Escape must close that and only that: closing both
 * would throw away a drawer the CA was reading, closing neither would trap the keyboard. A dirty editor's Cancel
 * asks ONCE, through the in-app dialog, and saying no leaves the editor as it was.
 */
import assert from "node:assert/strict";
import { openInvoiceDrawer } from "../flows.mjs";
import { ok } from "../stub.mjs";

export const group = "escape";

export const scenarios = [
  {
    id: "escape-closes-the-modal-then-the-drawer",
    title: "with Record Payment open over the invoice drawer, one Escape closes the modal only and the second closes the drawer",
    async run(env) {
      const { page } = env;
      const drawer = await openInvoiceDrawer(env, "issued");
      env.stub.route({ method: "POST", re: /receipts\/$/, reply: () => ok({ id: "r1" }) });
      await drawer.getByRole("button", { name: "Record Payment" }).first().click();
      await page.getByRole("dialog").last().getByRole("button", { name: "Record Payment", exact: true }).waitFor();
      assert.equal(await page.getByRole("dialog").count(), 2, "the modal and the drawer should both be open");
      await page.keyboard.press("Escape");
      await page.waitForFunction(() => document.querySelectorAll('[role="dialog"]').length === 1, null, { timeout: 4000 });
      await page.keyboard.press("Escape");
      await page.waitForFunction(() => document.querySelectorAll('[role="dialog"]').length === 0, null, { timeout: 4000 });
    },
  },
  {
    id: "dirty-editor-cancel-asks-once-in-app",
    title: "Cancel on an editor with typing in it asks once, in the app; no leaves it as it was, yes leaves",
    async run(env) {
      const { page } = env;
      env.stub.route({ method: "GET", re: /next-number/, reply: () => ok({ suggested_number: "INV-0001", series_head: "INV-" }) });
      await page.goto(env.at("/sales/invoices/new/edit/"), { waitUntil: "networkidle" });
      await page.click('button:has-text("Select customer")');
      await page.locator("[role=listbox] [role=option]", { hasText: "Beta Stores" }).first().click();
      const here = page.url();
      await page.getByRole("button", { name: "Cancel", exact: true }).first().click();
      const asked = page.getByRole("alertdialog");
      await asked.waitFor();
      assert.equal(await asked.count(), 1, "the person was asked more than once");
      assert.match(await asked.innerText(), /unsaved changes/i);
      await asked.getByRole("button", { name: "Cancel", exact: true }).click();
      await asked.waitFor({ state: "detached" });
      assert.equal(page.url(), here, "saying no still left the editor");
      await page.getByRole("button", { name: "Cancel", exact: true }).first().click();
      await page.getByRole("alertdialog").getByRole("button", { name: "OK", exact: true }).click();
      await page.waitForURL((u) => !u.pathname.includes("/invoices/new/edit"), { timeout: 6000 });
    },
  },
];
