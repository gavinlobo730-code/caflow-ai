/**
 * AN EMPTIED BOX ON THE PRODUCT OR SERVICE EDIT IS SENT AS "TAKE THIS AWAY" (POST-A-399), driven in a browser.
 *
 * The form built its request with `value || undefined`, which JSON drops, so a description, an item group, a note, a unit, a
 * purchase price, a reorder level or an alternate unit the person had EMPTIED reached the server as nothing: the stored value
 * stayed and the form said it was saved. And the alternate unit could not be removed from the form at all: choosing None left
 * its factor in a disabled box, and Save refused over a box the person could not type in.
 *
 * Against a stubbed server, in Chromium, from the sales invoice's product picker and its Products & Services panel:
 *
 *   1. a product with every optional particular on file, each emptied in the form (the alternate unit by choosing None, with
 *      the factor never touched): Save sends ONE PATCH whose body carries null for each of them, and the HSN/SAC code and the
 *      selling price, which were not touched, as they were;
 *   2. a product with none of them on file, renamed and saved: the same keys are ABSENT from the body, never null, so an edit
 *      never erases what the form was not shown.
 *
 * No scenario has a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { ok } from "../stub.mjs";
import { CLIENT_ID } from "../fixtures.mjs";

export const group = "product-edit";

const FULL = {
  id: "sc-good", client_id: CLIENT_ID, name: "TMT bar 12mm", kind: "good", description: "TMT bar, 12mm", hsn_sac: "7214", unit: "KGS",
  gst_rate_bps: 1800, default_rate_paise: 5500000, purchase_price_paise: 4200000, category: "Raw Material", notes: "Buy in lots of 50",
  reorder_level_units: 25, alternate_unit: "BOX", units_per_alternate: 12, is_active: true,
};
const BARE = {
  id: "sc-bare", client_id: CLIENT_ID, name: "Binding wire", kind: "good", description: null, hsn_sac: null, unit: null,
  gst_rate_bps: 1800, default_rate_paise: 900000, purchase_price_paise: null, category: null, notes: null,
  reorder_level_units: null, alternate_unit: null, units_per_alternate: null, is_active: true,
};
const SOFT = ["description", "category", "notes", "unit", "purchase_price_paise", "reorder_level_units", "alternate_unit"];

/** The invoice editor's product picker, its Products & Services panel, and the Edit dialog of the one item the server holds. */
async function openEdit(env, item) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { accounting: ["read", "write", "approve"] } }) });
  stub.route({ method: "GET", re: /service-catalogue/, reply: () => ok([item]) });
  stub.route({ method: "PATCH", re: /api\/service-catalogue\/[^/?]+$/, reply: () => ok({ ...item }) });
  await page.goto(env.at("/sales/invoices/new/edit/"), { waitUntil: "networkidle" });
  await page.click('button[aria-label="Line 1 product or service"]');
  await page.locator("[role=listbox] [role=option]", { hasText: "Add Product/Service" }).first().click();
  await page.getByRole("button", { name: "Edit", exact: true }).first().click();
  const dialog = page.getByRole("dialog", { name: "Edit Product/Service" });
  await dialog.waitFor({ timeout: 10000 });
  return dialog;
}

/** A select by the START of its label: "Unit (optional)" is also the end of "Alternate unit (optional)", and a label that wraps a select carries its options' text. */
const selectOf = (dialog, labelStart) => dialog.locator("label", { hasText: labelStart }).locator("select");

async function saveAndRead(env, dialog) {
  const { stub } = env;
  await dialog.getByRole("button", { name: "Save changes" }).click();
  await stub.quiet();
  const sent = stub.writesTo(/api\/service-catalogue\/[^/?]+$/, "PATCH");
  assert.equal(sent.length, 1, `expected one PATCH, saw ${sent.length}`);
  return JSON.parse(sent[0].body);
}

export const scenarios = [
  {
    id: "an-emptied-box-on-the-product-edit-is-sent-as-null",
    title: "each optional particular on file, emptied in the form (the alternate unit by choosing None): one PATCH carries null for each, and what was not touched as it was",
    async run(env) {
      const dialog = await openEdit(env, FULL);
      await dialog.getByLabel("Description (optional)").fill("");
      await dialog.getByLabel("Item group (optional)").fill("");
      await dialog.getByLabel("Notes (optional)").fill("");
      await dialog.getByLabel("Purchase price (₹, optional)").fill("");
      await dialog.getByLabel("Reorder level (optional)").fill("");
      // None first, the factor never touched: the form empties the factor with it, where it used to keep it in a disabled box.
      await selectOf(dialog, /^Alternate unit \(optional\)/).selectOption("");
      assert.equal(await dialog.getByLabel("Units per alternate").inputValue(), "", "choosing None left the factor in its disabled box");
      await selectOf(dialog, /^Unit \(optional\)/).selectOption("");
      const body = await saveAndRead(env, dialog);
      for (const key of SOFT) {
        assert.ok(key in body, `${key} was emptied and is not in the request at all: ${JSON.stringify(body)}`);
        assert.equal(body[key], null, `${key} was emptied and reached the server as ${JSON.stringify(body[key])}`);
      }
      assert.equal("units_per_alternate" in body, false, "the factor is not sent with a cleared alternate unit: the server clears the pair");
      assert.equal(body.hsn_sac, "7214", "the code was not touched");
      assert.equal(body.default_rate_paise, 5500000, "the selling price was not touched");
      assert.equal(body.name, "TMT bar 12mm");
    },
  },
  {
    id: "an-empty-box-with-nothing-on-file-is-not-sent",
    title: "a product with none of the optional particulars on file, renamed: the request names none of them, and never as null",
    async run(env) {
      const dialog = await openEdit(env, BARE);
      await dialog.getByLabel("Name", { exact: true }).fill("Binding wire 18 gauge");
      const body = await saveAndRead(env, dialog);
      assert.equal(body.name, "Binding wire 18 gauge");
      for (const key of [...SOFT, "hsn_sac", "units_per_alternate"]) {
        assert.equal(key in body, false, `${key} had nothing on file and an empty box, and was sent as ${JSON.stringify(body[key])}`);
      }
      assert.equal(Object.values(body).some((v) => v === null), false, `an edit of an item with nothing on file sent a null: ${JSON.stringify(body)}`);
    },
  },
];
