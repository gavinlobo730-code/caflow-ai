/**
 * THE PURCHASES SCREEN'S THREE DIALOGS AND THE CLIENTS LIST'S THREE ARE THE SHARED ONE (POST-A-130, seventh step), driven in a browser.
 *
 * Delete draft purchase bill?, Deactivate Vendor? and the vendor's permanent-delete flow on a client's Purchases screen, and Archive Client,
 * Restore Client and Permanently Delete on the firm's Clients list, were built by hand as a layer over the page: no name a screen reader
 * announces, no Tab kept inside, no Escape, no focus given back. Each is the shared Modal now. The source guard holds all six; this drives
 * five of them:
 *
 *   1. Delete draft purchase bill? is named and says what a delete does, Escape closes it with nothing sent, and while the delete is in
 *      flight Escape and a click outside do nothing and one DELETE is sent;
 *   2. Deactivate Vendor? is named, keeps Tab inside and closes on Escape with nothing sent;
 *   3. the vendor's permanent-delete flow names each of its states, and "Deactivate instead" opens Deactivate Vendor? in its place;
 *   4. Archive Client is named, keeps Tab inside and closes on Escape with nothing sent; Permanently Delete is named, says it cannot be
 *      undone, holds its button until the client's name is typed, and closes on Escape with nothing sent.
 *
 * No scenario has a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { until, expectWrites } from "../kit.mjs";
import { ok } from "../stub.mjs";
import { VENDOR, CLIENT_ID, CLIENT_ROW, billRow } from "../fixtures.mjs";

export const group = "purchase-and-client-dialogs";

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

async function atTheVendors(env) {
  const { page, stub } = env;
  stub.setTable("vendors", [VENDOR]);
  await page.goto(env.at("/purchases/"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Vendors", exact: true }).first().click();
  await page.getByLabel(`Actions for ${VENDOR.name}`).waitFor();
}

const DEPENDENCIES = new RegExp(`api/vendors/${VENDOR.id}/dependencies$`);

export const scenarios = [
  {
    id: "delete-draft-bill-is-a-named-dialog-that-holds-while-it-deletes",
    title: "Purchases > a draft bill's menu > Delete draft: a named dialog that says what a delete does; Escape sends nothing; while the delete is in flight Escape and a click outside do nothing and ONE delete is sent",
    async run(env) {
      const { page, stub } = env;
      const DELETE = /purchase-bills\/b9$/;
      stub.setTable("purchase_bills", [billRow("draft", "b9")]);
      await page.goto(env.at("/purchases/?tab=bills"), { waitUntil: "networkidle" });
      const open = async () => {
        await page.getByLabel(/Actions for bill/).first().click();
        await page.getByRole("button", { name: "Delete draft", exact: true }).click();
      };
      await open();
      const dialog = page.getByRole("dialog", { name: "Delete draft purchase bill?", exact: true });
      await dialog.waitFor();
      assert.equal(await dialog.getAttribute("aria-modal"), "true", "the delete dialog does not say it is modal");
      assert.match(await dialog.innerText(), /Only drafts can be deleted/, "the dialog lost the sentence that says what a delete does");
      assert.equal(await page.getByText("Delete draft purchase bill?").count(), 1, "the question is written twice");
      await until(() => insideDialog(page, "Delete draft purchase bill?"), "focus to move into the delete dialog");
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
    id: "deactivate-vendor-is-a-named-dialog-and-escape-sends-nothing",
    title: "Purchases > Vendors > a vendor's menu > Deactivate: a named dialog, Tab stays inside, Escape closes it and no change is sent",
    async run(env) {
      const { page, stub } = env;
      await atTheVendors(env);
      await page.getByLabel(`Actions for ${VENDOR.name}`).click();
      await page.getByRole("button", { name: "Deactivate", exact: true }).first().click();
      const dialog = page.getByRole("dialog", { name: "Deactivate Vendor?", exact: true });
      await dialog.waitFor();
      assert.equal(await dialog.getAttribute("aria-modal"), "true", "Deactivate Vendor? does not say it is modal");
      assert.match(await dialog.innerText(), new RegExp(`${VENDOR.name}\\s+will no\\s+longer be available for new bills`), "the dialog does not say whose record it is");
      await tabStaysInside(page, "Deactivate Vendor?", 6);
      stub.forgetWrites();
      await page.keyboard.press("Escape");
      await dialog.waitFor({ state: "detached" });
      assert.equal(stub.writesTo(/vendors/, "PATCH").length, 0, "Escape deactivated the vendor");
    },
  },
  {
    id: "the-vendors-permanent-delete-flow-names-each-of-its-states",
    title: "Purchases > Vendors > Delete: a vendor with linked records gets a dialog named \"Can't delete this vendor\", Deactivate instead opens Deactivate Vendor?; one with nothing linked gets \"Delete Vendor?\"",
    async run(env) {
      const { page, stub } = env;
      await atTheVendors(env);
      stub.route({ method: "GET", re: DEPENDENCIES, reply: () => ok({ can_delete: false, dependencies: { bills: 3 } }) });
      await page.getByLabel(`Actions for ${VENDOR.name}`).click();
      await page.getByRole("button", { name: "Delete", exact: true }).first().click();
      const blocked = page.getByRole("dialog", { name: "Can't delete this vendor", exact: true });
      await blocked.waitFor();
      assert.match(await blocked.innerText(), /Bills: 3/, "what is linked is not listed");
      await blocked.getByRole("button", { name: "Deactivate instead", exact: true }).click();
      const deactivate = page.getByRole("dialog", { name: "Deactivate Vendor?", exact: true });
      await deactivate.waitFor();
      assert.equal(await page.getByRole("dialog").count(), 1, "the blocked dialog stayed open behind Deactivate Vendor?");
      await until(() => insideDialog(page, "Deactivate Vendor?"), "focus to move into Deactivate Vendor?");
      await page.keyboard.press("Escape");
      await deactivate.waitFor({ state: "detached" });

      stub.route({ method: "GET", re: DEPENDENCIES, reply: () => ok({ can_delete: true, dependencies: {} }) });
      await page.getByLabel(`Actions for ${VENDOR.name}`).click();
      await page.getByRole("button", { name: "Delete", exact: true }).first().click();
      const clean = page.getByRole("dialog", { name: "Delete Vendor?", exact: true });
      await clean.waitFor();
      assert.equal(await clean.getByRole("button", { name: "Delete permanently", exact: true }).count(), 1, "the delete button is not inside the dialog");
      await until(() => insideDialog(page, "Delete Vendor?"), "focus to move into Delete Vendor?");
      stub.forgetWrites();
      await page.keyboard.press("Escape");
      await clean.waitFor({ state: "detached" });
      assert.equal(stub.writesTo(/vendors/, "DELETE").length, 0, "Escape deleted the vendor");
    },
  },
  {
    id: "archive-client-and-permanently-delete-are-named-dialogs-and-escape-sends-nothing",
    title: "Clients > a client's menu: Archive Client is a named dialog that keeps Tab inside; Permanently Delete is named, says it cannot be undone and holds its button until the name is typed; Escape closes each and sends nothing",
    async run(env) {
      const { page, stub } = env;
      await page.goto(`${env.base}/clients/`, { waitUntil: "networkidle" });
      const row = page.locator("tr, [role=row], a, div").filter({ hasText: CLIENT_ROW.client_name }).filter({ has: page.getByTitle("More actions") }).last();
      const openMenu = async () => { await row.hover(); await row.getByTitle("More actions").click(); };
      await openMenu();
      await page.getByRole("button", { name: "Archive", exact: true }).first().click();
      const archive = page.getByRole("dialog", { name: "Archive Client", exact: true });
      await archive.waitFor();
      assert.equal(await archive.getAttribute("aria-modal"), "true", "Archive Client does not say it is modal");
      assert.match(await archive.innerText(), new RegExp(`Archive ${CLIENT_ROW.client_name}\\?`), "the dialog does not say which client");
      await tabStaysInside(page, "Archive Client", 6);
      stub.forgetWrites();
      await page.keyboard.press("Escape");
      await archive.waitFor({ state: "detached" });
      assert.equal(stub.writesTo(new RegExp(`/api/clients/${CLIENT_ID}/archive$`), "POST").length, 0, "Escape archived the client");

      await openMenu();
      await page.getByRole("button", { name: /Permanent Delete/ }).click();
      const del = page.getByRole("dialog", { name: "Permanently Delete", exact: true });
      await del.waitFor();
      assert.match(await del.innerText(), /This cannot be undone/, "the dialog no longer says a delete cannot be undone");
      const button = del.getByRole("button", { name: "Delete Permanently", exact: true });
      assert.equal(await button.isDisabled(), true, "Delete Permanently is live before the client's name is typed");
      await del.getByLabel(`Type ${CLIENT_ROW.client_name} to confirm`).fill(CLIENT_ROW.client_name);
      assert.equal(await button.isDisabled(), false, "Delete Permanently stayed held after the name was typed");
      await tabStaysInside(page, "Permanently Delete", 6);
      stub.forgetWrites();
      await page.keyboard.press("Escape");
      await del.waitFor({ state: "detached" });
      assert.equal(stub.writesTo(new RegExp(`/api/clients/${CLIENT_ID}$`), "DELETE").length, 0, "Escape deleted the client");
    },
  },
];
