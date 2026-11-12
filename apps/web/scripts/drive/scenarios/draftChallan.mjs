/**
 * A DRAFT DELIVERY CHALLAN IS CORRECTED AND CANCELLED FROM ITS PANEL (POST-A-417), driven in a browser.
 *
 * A challan is made as a draft whose Rule 55(1) particulars are optional, and the server will not issue it without them. The amendment door dropped a line (so an HSN code could never be added) and no
 * screen called it for a draft, so a challan that lacked a particular was made again under a new number. The draft's panel has "Correct draft" and "Cancel draft" now. Against a stubbed server, in Chromium:
 *
 *   1. "Correct draft" opens a dialog holding what the draft holds; one press of Save sends ONE PATCH carrying only what was changed (a line's HSN code, the consignee's name) and nothing else;
 *   2. the server's refusal is shown in the dialog as an alert, as the server wrote it, the dialog stays open and the next press sends again;
 *   3. a box that held a value and is empty now (the consignee's GSTIN) is said before anything is sent: the door reads a blank as "unchanged", so it is not saved as if it had worked;
 *      an HSN code added to a line AND NOTHING ELSE is a change and is saved (one PATCH carrying that line only); an inter-State job-work draft shows what is being sent and the place of supply, and
 *      changing them sends them;
 *   4. a Save with nothing changed says so and sends nothing;
 *   5. "Cancel draft" asks in the shared dialog first: "Keep it" sends nothing, "Cancel the draft" sends ONE PATCH carrying the status "cancelled" and nothing else, the message says the challan is cancelled and the panel closes;
 *   6. a refusal to a cancel is said beside the button as the server wrote it;
 *   7. an issued challan has neither button.
 *
 * No scenario has a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { pick } from "../kit.mjs";
import { ok, refuse } from "../stub.mjs";

export const group = "draft-challan";

const CHALLAN_URL = /api\/sales-cycle\/challans\/ch-2\?client_id=/;
const DRAFT = {
  id: "ch-2", document_no: "DC/26-27/0002", document_date: "2026-07-01", reason: "job_work", reason_label: "Job work", status: "draft",
  received_back_on: null, total_paise: 5_000_000, goods_kind: "inputs",
  consignee_name: "Precision Castings", consignee_gstin: "27AAPFU0939F1ZV", consignee_address: "Plot 4, Pune", place_of_supply: null, is_inter_state: false,
  clock: { applies: false, statute: "", months: null, sent_on: null, due_back_by: null, overdue: null, days_remaining: null, gaps: [],
    consequence: "This challan is a draft: it is not recorded as issued, so no period is running on it here." },
};
const ISSUED = { ...DRAFT, status: "issued" };
const LINES = [
  { id: "ln-1", description: "Steel bar", hsn_sac: null, quantity: "100", unit: "KGS" },
  { id: "ln-2", description: "Steel plate", hsn_sac: "7208", quantity: "10", unit: "NOS" },
];
const MISSING = "55(1)(iv) HSN code of the goods";
const PARTICULARS = (challan, missing = []) => ({
  challan, lines: LINES, rule: "CGST Rule 55", reason_label: "Job work",
  particulars: [{ clause: "55(1)(i)", label: "Date and number of the delivery challan", value: `${challan.document_no} dated ${challan.document_date}`, required: true }],
  missing, copies: [{ copy: "original", legend: "ORIGINAL FOR CONSIGNEE" }], clock: challan.clock,
  rule_55_5: { steps: [], gaps: [] }, itc_04: { decided: false, readings: [], refusal: "" }, ca_review_required: true,
});

async function atTheDraft(env, challan = DRAFT, missing = [MISSING]) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /sales-cycle\/vocabulary/, reply: () => ok({
    challan_reasons: [{ value: "job_work", label: "Job work", is_a_supply: false }], goods_kinds: [{ value: "inputs", label: "Inputs" }, { value: "capital_goods", label: "Capital goods" }], quote_kinds: [] }) });
  stub.route({ method: "GET", re: /sales-cycle\/quotations\?/, reply: () => ok([]) });
  stub.route({ method: "GET", re: /sales-cycle\/orders\?/, reply: () => ok([]) });
  stub.route({ method: "GET", re: /sales-cycle\/challans\?/, reply: () => ok([challan]) });
  stub.route({ method: "GET", re: CHALLAN_URL, reply: () => ok(PARTICULARS(challan, missing)) });
  stub.route({ method: "GET", re: /\/customers/, reply: () => ok([]) });
  await page.goto(env.at("/sales/?tab=sales-cycle"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Delivery Challans" }).click();
  await page.getByText(challan.document_no).first().click();
  await page.getByRole("button", { name: "Close the challan" }).waitFor();
}

const patchesOf = (stub) => stub.writesTo(CHALLAN_URL, "PATCH").map((w) => JSON.parse(w.body));
const correct = (page) => page.getByRole("button", { name: "Correct draft", exact: true });
const cancel = (page) => page.getByRole("button", { name: "Cancel draft", exact: true });
const dialog = (page) => page.getByRole("dialog", { name: "Correct draft challan DC/26-27/0002" });

export const scenarios = [
  {
    id: "a-draft-is-corrected-from-its-panel-and-one-request-carries-only-what-changed",
    title: "A draft challan: Correct draft opens what the draft holds, and Save sends ONE PATCH with the HSN code of a line and the new consignee name, and nothing that was not changed",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "PATCH", re: CHALLAN_URL, reply: () => ok(DRAFT) });
      await atTheDraft(env);
      await correct(page).click();
      await dialog(page).waitFor();
      assert.equal(await page.getByLabel("Consignee GSTIN").inputValue(), DRAFT.consignee_gstin, "the dialog does not hold what the draft holds");
      assert.equal(await page.getByLabel("Line 2 HSN code").inputValue(), "7208", "a line's HSN code is not shown");
      await page.getByLabel("Line 1 HSN code").fill("7214");
      await page.getByLabel("Consignee name").fill("Precision Castings Pvt Ltd");
      stub.forgetWrites();
      await page.getByRole("button", { name: "Save the correction", exact: true }).click();
      await dialog(page).waitFor({ state: "detached" });
      await stub.quiet();
      const sent = patchesOf(stub);
      assert.equal(sent.length, 1, "expected exactly one request");
      assert.deepEqual(sent[0], { consignee_name: "Precision Castings Pvt Ltd", lines: [{ id: "ln-1", hsn_sac: "7214" }] }, "the request carries more than was changed");
      await page.getByText("The draft was corrected.", { exact: true }).waitFor();
    },
  },
  {
    id: "a-refusal-of-the-correction-is-the-servers-sentence-in-the-dialog-which-stays-open",
    title: "A draft challan: the server refuses an HSN that is not a code — its sentence is shown in the dialog as an alert, the dialog stays open and the next press sends again",
    async run(env) {
      const { page, stub } = env;
      const SAID = "HSN 'SAC-9983' on line ln-1 is not a code: an HSN or SAC is digits only.";
      stub.route({ method: "PATCH", re: CHALLAN_URL, ...refuse(SAID, 422) });
      await atTheDraft(env);
      await correct(page).click();
      await dialog(page).waitFor();
      await page.getByLabel("Line 1 HSN code").fill("SAC-9983");
      stub.forgetWrites();
      const save = page.getByRole("button", { name: "Save the correction", exact: true });
      await save.click();
      await dialog(page).getByRole("alert").filter({ hasText: SAID }).waitFor({ timeout: 4000 });
      assert.equal(await dialog(page).count(), 1, "the dialog closed on a refusal");
      await save.click();
      await dialog(page).getByRole("alert").filter({ hasText: SAID }).waitFor({ timeout: 4000 });
      await stub.quiet();
      assert.equal(patchesOf(stub).length, 2, "the next press did not send again");
    },
  },
  {
    id: "a-box-that-held-a-value-and-is-emptied-is-said-before-anything-is-sent",
    title: "A draft challan: the consignee's GSTIN is emptied — the dialog says a value is replaced there and not removed, and sends nothing, so nothing is saved as if it had worked",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "PATCH", re: CHALLAN_URL, reply: () => ok(DRAFT) });
      await atTheDraft(env);
      await correct(page).click();
      await dialog(page).waitFor();
      await page.getByLabel("Consignee GSTIN").fill("");
      await page.getByLabel("Line 1 HSN code").fill("7214");
      stub.forgetWrites();
      await page.getByRole("button", { name: "Save the correction", exact: true }).click();
      await dialog(page).getByRole("alert").filter({ hasText: "the consignee's GSTIN held a value and is empty now. That box cannot be emptied here" }).waitFor({ timeout: 4000 });
      await stub.quiet();
      assert.equal(patchesOf(stub).length, 0, "a request was sent for a box the door cannot clear");
    },
  },
  {
    id: "an-hsn-code-added-to-a-line-and-nothing-else-is-saved",
    title: "A draft challan: only a line's HSN code is changed — Save sends ONE PATCH carrying that line and nothing else (an edit of a line alone is a change)",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "PATCH", re: CHALLAN_URL, reply: () => ok(DRAFT) });
      await atTheDraft(env);
      await correct(page).click();
      await dialog(page).waitFor();
      await page.getByLabel("Line 1 HSN code").fill("7214");
      stub.forgetWrites();
      await page.getByRole("button", { name: "Save the correction", exact: true }).click();
      await dialog(page).waitFor({ state: "detached" });
      await stub.quiet();
      const sent = patchesOf(stub);
      assert.equal(sent.length, 1, "expected exactly one request");
      assert.deepEqual(sent[0], { lines: [{ id: "ln-1", hsn_sac: "7214" }] });
    },
  },
  {
    id: "an-inter-state-job-work-draft-shows-the-kind-of-goods-and-the-place-of-supply-and-sends-what-changed",
    title: "An inter-State job-work draft: the dialog shows what is being sent and the place of supply, and changing them sends them (and an intra-State draft has no place of supply box)",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "PATCH", re: CHALLAN_URL, reply: () => ok(DRAFT) });
      await atTheDraft(env, { ...DRAFT, is_inter_state: true, place_of_supply: "27" });
      await correct(page).click();
      await dialog(page).waitFor();
      assert.equal(await page.getByLabel("What is being sent").inputValue(), "inputs", "the kind of goods is not shown");
      await page.getByLabel("What is being sent").selectOption("capital_goods");
      await pick(page, page.locator('button[aria-label="Place of supply"]'), "Karnataka");
      stub.forgetWrites();
      await page.getByRole("button", { name: "Save the correction", exact: true }).click();
      await dialog(page).waitFor({ state: "detached" });
      await stub.quiet();
      const sent = patchesOf(stub);
      assert.equal(sent.length, 1, "expected exactly one request");
      assert.deepEqual(sent[0], { goods_kind: "capital_goods", place_of_supply: "29" });
    },
  },
  {
    id: "an-intra-state-draft-has-no-place-of-supply-box",
    title: "An intra-State job-work draft: the dialog has no place of supply box (Rule 55(1)(viii) asks for it for an inter-State movement only)",
    async run(env) {
      const { page } = env;
      await atTheDraft(env);
      await correct(page).click();
      await dialog(page).waitFor();
      assert.equal(await page.locator('button[aria-label="Place of supply"]').count(), 0, "a place of supply is asked for a movement that is not inter-State");
    },
  },
  {
    id: "a-save-with-nothing-changed-says-so-and-sends-nothing",
    title: "A draft challan: Save with nothing changed says nothing was changed and sends nothing",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "PATCH", re: CHALLAN_URL, reply: () => ok(DRAFT) });
      await atTheDraft(env);
      await correct(page).click();
      await dialog(page).waitFor();
      stub.forgetWrites();
      await page.getByRole("button", { name: "Save the correction", exact: true }).click();
      await dialog(page).getByRole("alert").filter({ hasText: "Nothing was changed." }).waitFor({ timeout: 4000 });
      await stub.quiet();
      assert.equal(patchesOf(stub).length, 0);
    },
  },
  {
    id: "cancelling-a-draft-asks-first-and-sends-one-request-carrying-the-cancelled-status",
    title: "A draft challan: Cancel draft asks in the shared dialog — Keep it sends nothing; Cancel the draft sends ONE PATCH with the status cancelled and nothing else, says it is cancelled and closes the panel",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "PATCH", re: CHALLAN_URL, reply: () => ok({ ...DRAFT, status: "cancelled" }) });
      await atTheDraft(env);
      stub.forgetWrites();
      await cancel(page).click();
      await page.getByRole("button", { name: "Keep it", exact: true }).click();
      await stub.quiet();
      assert.equal(patchesOf(stub).length, 0, "Keep it sent a request");
      await cancel(page).click();
      await page.getByRole("button", { name: "Cancel the draft", exact: true }).click();
      await page.getByText("Challan DC/26-27/0002 cancelled.", { exact: true }).waitFor();
      await stub.quiet();
      const sent = patchesOf(stub);
      assert.equal(sent.length, 1, "expected exactly one request");
      assert.deepEqual(sent[0], { status: "cancelled" });
      assert.equal(await page.getByRole("button", { name: "Close the challan" }).count(), 0, "the panel of a cancelled draft stayed open");
    },
  },
  {
    id: "a-refusal-to-a-cancel-is-said-beside-the-button",
    title: "A draft challan: the server refuses a cancel — its sentence is shown beside the button, the panel stays and the next press can send again",
    async run(env) {
      const { page, stub } = env;
      const SAID = "Challan DC/26-27/0002 was changed while it was being amended. Reload it and look at its status.";
      stub.route({ method: "PATCH", re: CHALLAN_URL, ...refuse(SAID, 409) });
      await atTheDraft(env);
      await cancel(page).click();
      await page.getByRole("button", { name: "Cancel the draft", exact: true }).click();
      await page.getByRole("alert").filter({ hasText: SAID }).waitFor({ timeout: 4000 });
      assert.equal(await page.getByRole("button", { name: "Close the challan" }).count(), 1, "the panel closed on a refusal");
      assert.equal(await cancel(page).isEnabled(), true, "Cancel draft stayed held after a refusal");
    },
  },
  {
    id: "an-issued-challan-has-neither-button",
    title: "An issued challan: the panel offers neither Correct draft nor Cancel draft",
    async run(env) {
      const { page } = env;
      await atTheDraft(env, ISSUED, []);
      assert.equal(await correct(page).count(), 0, "an issued challan is offered a correction");
      assert.equal(await cancel(page).count(), 0, "an issued challan is offered Cancel draft");
    },
  },
];
