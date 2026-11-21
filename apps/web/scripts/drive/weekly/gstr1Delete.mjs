/**
 * AN UNFILED GSTR-1 CAN BE DELETED FROM ITS ROW, AND A FILED ONE CANNOT (POST-A-547), driven in a browser.
 *
 * The server could always delete an unfiled GSTR-1's saved working (`DELETE /api/gst-workspace/gstr1/{id}`: refused once
 * filed, and for an approved return without the right to approve). No row offered it, so a working computed for the wrong
 * month stayed on the list for good, while the GSTR-3B row beside it had Delete all along.
 *
 * Against a stubbed server, in Chromium, on a client's GST screen:
 *
 *   1. a draft row offers Delete and a filed row does not; saying no to the question sends nothing; saying yes sends ONE
 *      DELETE to that return's own address, and the list is read again and no longer holds it;
 *   2. the server's refusal is shown in the server's words, as an alert, and the row is still there with its button live.
 *
 * No scenario has a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";
import { ok } from "../stub.mjs";

export const group = "gstr1-delete";

const GSTIN = "27AAACA1111A1Z1";
const BASE = { gstin: GSTIN, total_taxable_paise: 1000000 };
const DRAFT = { ...BASE, id: "g1-draft", period: "082026", status: "draft" };
const FILED = { ...BASE, id: "g1-filed", period: "072026", status: "submitted", arn: "AA270726000001A" };

const REFUSAL = "This GSTR-1 was approved by a Manager or a Partner. Deleting it needs permission to approve GST returns.";

/** The GST screen with two GSTR-1 rows, read from `rows()` each time so a scenario can change what the server holds. */
async function atGstr1Rows(env, rows) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { gst: ["read", "write", "approve", "compute"] } }) });
  stub.route({ method: "GET", re: /api\/gst-workspace\/returns\?/, reply: () => ok({ gstr1: rows(), gstr3b: [] }) });
  stub.route({ method: "GET", re: /client-gst-registrations\/kinds$/, reply: () => ok({
    registration_types: [{ value: "regular", files_gstr1_and_3b: true, files_cmp08: false, files_gstr8: false, files_gstr4_annual: false, other_return_form: null }],
    composition_categories: [], filing_frequencies: ["monthly", "quarterly"], composition_rates_verified: false }) });
  stub.route({ method: "GET", re: /client-gst-registrations\?/, reply: () => ok([
    { id: null, gstin: GSTIN, state_code: "27", registration_type: "regular", filing_frequency: "monthly", is_primary: true, trade_name: null,
      effective_from: null, effective_to: null, label: "Maharashtra (primary)", files_gstr1_and_3b: true, files_cmp08: false, files_gstr8: false, files_gstr4_annual: false }]) });
  await page.goto(env.at("/compliance/gst/"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "GSTR-1", exact: true }).click();
  await page.getByRole("button", { name: "Validate", exact: true }).waitFor();
}

const deleteButtons = (page) => page.locator("[data-delete-gstr1]");
const question = (page) => page.getByRole("alertdialog");

export const scenarios = [
  {
    id: "an-unfiled-gstr1-is-deleted-from-its-row-and-a-filed-one-offers-no-delete",
    title: "a draft row offers Delete and a filed one does not; No sends nothing; Yes sends one DELETE to that return and the list no longer holds it",
    async run(env) {
      const { page, stub } = env;
      let held = [DRAFT, FILED];
      const sent = [];
      stub.route({ method: "DELETE", re: /gst-workspace\/gstr1\/[^/]+$/, reply: (_req, _body, url) => {
        sent.push(String(url)); held = held.filter((r) => r.id !== "g1-draft"); return ok({ deleted: true }); } });
      await atGstr1Rows(env, () => held);

      assert.equal(await deleteButtons(page).count(), 1, "exactly one row (the unfiled one) offers Delete");
      const filedRow = page.locator("tr", { hasText: "ARN AA270726000001A" });
      assert.equal(await filedRow.locator("[data-delete-gstr1]").count(), 0, "a filed return's row offers Delete");

      await deleteButtons(page).click();
      await question(page).waitFor();
      assert.match(await question(page).innerText(), /Delete the GSTR-1 for 082026\?/, "the question does not name the return");
      assert.match(await question(page).innerText(), /Nothing has been filed/, "the question does not say what is and is not removed");
      await question(page).getByRole("button", { name: "Cancel", exact: true }).click();
      await question(page).waitFor({ state: "detached" });
      assert.equal(sent.length, 0, "saying no still sent a delete");

      await deleteButtons(page).click();
      await question(page).getByRole("button", { name: "Delete", exact: true }).click();
      await until(() => sent.length === 1, "the delete was not sent");
      assert.match(sent[0], /\/api\/gst-workspace\/gstr1\/g1-draft$/, "the delete went to another address");
      await until(async () => (await deleteButtons(page).count()) === 0, "the deleted return is still on the list");
      assert.equal(sent.length, 1, "the delete was sent more than once");
      assert.equal(await filedRow.count(), 1, "the filed return left the list with it");
    },
  },
  {
    id: "a-refused-gstr1-delete-is-said-in-the-servers-words-and-the-row-stays",
    title: "the server's refusal is shown as worded, as an alert, and the row and its button are still there",
    async run(env) {
      const { page, stub } = env;
      let asked = 0;
      stub.route({ method: "DELETE", re: /gst-workspace\/gstr1\/g1-draft$/, // this router answers a refusal as HTTP 200 with success false, which is why the screen must read the answer
        reply: () => { asked += 1; return { success: false, data: null, error: REFUSAL }; } });
      await atGstr1Rows(env, () => [DRAFT, FILED]);

      await deleteButtons(page).click();
      await question(page).getByRole("button", { name: "Delete", exact: true }).click();
      await until(() => asked === 1, "the delete was not sent");
      await page.getByText(REFUSAL).first().waitFor({ timeout: 4000 });
      assert.equal(await deleteButtons(page).count(), 1, "the row lost its Delete after a refusal");
      assert.equal(await deleteButtons(page).isDisabled(), false, "the button stayed held after the refusal");
      assert.equal(asked, 1, "the delete was sent more than once");
    },
  },
];
