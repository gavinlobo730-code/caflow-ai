/**
 * TWO GAPS FORM GST ITC-04 NAMES ABOUT A JOB-WORK CHALLAN ARE CLOSED FROM THE DELIVERY CHALLANS TAB (POST-A-431, POST-A-423), driven in a browser.
 *
 *   POST-A-431. A challan of tools, moulds, dies, jigs or fixtures recorded as received back with no day was named by the statement, and the tab's "Mark a whole challan back at once" listed a challan only
 *   while a section 143 period ran on it (tools run none), so no screen could give it a day. The box lists every challan recorded as back with no day now.
 *   POST-A-423. A job-work challan whose job worker has no GSTIN and whose State was never recorded (a movement within the client's own State has no place of supply box) had no screen that recorded it.
 *   The challan's panel has the box now; it writes the place of supply, the State the goods go to.
 *
 * Against a stubbed server, in Chromium:
 *
 *   1. a received-back tools challan with no day is listed in the box (no clock applies to it), a typed day and "Record goods back" send ONE PATCH carrying that day and nothing else;
 *      an issued tools challan, which runs no period either, is NOT listed (nothing is recorded as back on it);
 *   2. a job-work challan with neither a GSTIN nor a State shows the State box in its panel; picking a State and pressing "Record the State" sends ONE PATCH carrying the place of supply and nothing else,
 *      says it was recorded, and the box STAYS, now holding that State, so a wrong pick can be changed: pressing it again with the same State says so and sends nothing; changing it sends the new one;
 *   3. the box is not offered to a challan that holds a GSTIN (it reads its State from the GSTIN), one that is cancelled or one that is not job work;
 *   4. pressing it with no State picked says so and sends nothing; a refusal is the server's sentence in the box, which stays;
 *   5. a place of supply already recorded that the States list cannot offer (96, Other Country: the inter-State form offers the longer list) is SHOWN in words and not as an empty picker, and a State picked
 *      over it is sent;
 *   6. the words follow the challan's status: an issued challan "is named until one is recorded", a draft "will be" on the statement once it is issued.
 *
 * No scenario has a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { pick } from "../kit.mjs";
import { ok, refuse } from "../stub.mjs";

export const group = "job-work-gaps";

const URL_OF = (id) => new RegExp(`api/sales-cycle/challans/${id}\\?client_id=`);
const BASE = {
  id: "ch-1", document_no: "DC/26-27/0001", document_date: "2026-07-01", reason: "job_work", reason_label: "Job work", status: "issued", goods_kind: "inputs",
  received_back_on: null, total_paise: 5_000_000, consignee_name: "Precision Castings", consignee_gstin: null, consignee_address: "Plot 4", place_of_supply: null, is_inter_state: false,
  clock: { applies: true, statute: "CGST Act s.143 with Rule 45", months: 12, sent_on: "2026-07-01", due_back_by: "2027-06-30", overdue: false, days_remaining: 200, gaps: [], consequence: "" },
};
const NO_CLOCK = { applies: false, statute: "", months: null, sent_on: null, due_back_by: null, overdue: null, days_remaining: null, gaps: [], consequence: "" };
const PARTICULARS = (challan) => ({
  challan, lines: [], rule: "CGST Rule 55", reason_label: "Job work",
  particulars: [{ clause: "55(1)(i)", label: "Date and number of the delivery challan", value: `${challan.document_no} dated ${challan.document_date}`, required: true }],
  missing: [], copies: [{ copy: "original", legend: "ORIGINAL FOR CONSIGNEE" }], clock: challan.clock, rule_55_5: { steps: [], gaps: [] },
  itc_04: { decided: false, readings: [], refusal: "" }, ca_review_required: true,
});

/** `challans` are LIVE: the stub's replies are read when the request arrives, so a scenario's PATCH that changes one is seen by the re-read the screen makes after it. */
async function atTheTab(env, challans) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /sales-cycle\/vocabulary/, reply: () => ok({ challan_reasons: [], goods_kinds: [], quote_kinds: [] }) });
  stub.route({ method: "GET", re: /sales-cycle\/quotations\?/, reply: () => ok([]) });
  stub.route({ method: "GET", re: /sales-cycle\/orders\?/, reply: () => ok([]) });
  stub.route({ method: "GET", re: /sales-cycle\/challans\?/, reply: () => ok(challans) });
  for (const c of challans) stub.route({ method: "GET", re: URL_OF(c.id), reply: () => ok(PARTICULARS(c)) });
  stub.route({ method: "GET", re: /\/customers/, reply: () => ok([]) });
  await page.goto(env.at("/sales/?tab=sales-cycle"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Delivery Challans" }).click();
  await page.getByText(challans[0].document_no).first().waitFor();
}

const patchesOf = (stub, id) => stub.writesTo(URL_OF(id), "PATCH").map((w) => JSON.parse(w.body));
const stateBox = (page) => page.locator('[data-testid="job-worker-state-box"]');
const open = (page, no) => page.getByText(no).first().click();

export const scenarios = [
  {
    id: "a-received-back-tools-challan-with-no-day-is-listed-and-given-its-day",
    title: "A tools challan recorded as received back with no day is listed in the whole-challan box although no period runs on it; a typed day and Record goods back send ONE PATCH carrying that day",
    async run(env) {
      const { page, stub } = env;
      const TOOLS = { ...BASE, id: "ch-1", status: "received_back", goods_kind: "moulds_dies_jigs_fixtures_tools", clock: NO_CLOCK };
      const ISSUED_TOOLS = { ...BASE, id: "ch-2", document_no: "DC/26-27/0002", goods_kind: "moulds_dies_jigs_fixtures_tools", clock: NO_CLOCK };
      stub.route({ method: "PATCH", re: URL_OF("ch-1"), reply: () => ok({ ...TOOLS, received_back_on: "2026-07-15" }) });
      await atTheTab(env, [TOOLS, ISSUED_TOOLS]);
      await page.getByText("Mark a whole challan back at once").waitFor();
      await page.getByLabel(`Date the goods came back, challan ${TOOLS.document_no}`).fill("15/07/2026");
      await page.getByLabel(`Date the goods came back, challan ${TOOLS.document_no}`).blur();
      assert.equal(await page.getByLabel(`Date the goods came back, challan ${ISSUED_TOOLS.document_no}`).count(), 0, "an issued challan that runs no period is offered a back day");
      stub.forgetWrites();
      await page.getByRole("button", { name: "Record goods back", exact: true }).click();
      await stub.quiet();
      assert.deepEqual(patchesOf(stub, "ch-1"), [{ received_back_on: "2026-07-15" }]);
    },
  },
  {
    id: "the-job-workers-state-is-recorded-from-the-challans-panel-and-stays-to-be-changed",
    title: "A job-work challan with neither a GSTIN nor a State shows the State box; Record the State sends ONE PATCH carrying the place of supply, the box then holds that State and can change it; the same State again sends nothing",
    async run(env) {
      const { page, stub } = env;
      const live = { ...BASE };
      stub.route({ method: "PATCH", re: URL_OF("ch-1"), reply: (_req, raw) => { Object.assign(live, JSON.parse(raw)); return ok(live); } });
      await atTheTab(env, [live]);
      await open(page, live.document_no);
      await stateBox(page).waitFor();
      await stateBox(page).getByText("No GSTIN or State is recorded for the job worker").waitFor();
      await stateBox(page).getByText("so the statement names this challan until one is", { exact: false }).waitFor();
      await pick(page, page.locator('button[aria-label="State of the job worker"]'), "Karnataka");
      await page.getByRole("button", { name: "Record the State", exact: true }).focus();
      stub.forgetWrites();
      await page.getByRole("button", { name: "Record the State", exact: true }).click();
      await page.getByText("The job worker's State was recorded.", { exact: true }).waitFor();
      await stub.quiet();
      assert.deepEqual(patchesOf(stub, "ch-1"), [{ place_of_supply: "29" }]);
      // the box is still there, now saying the State is recorded, and pressing it with the same State sends nothing
      await stateBox(page).getByText("The job worker has no GSTIN recorded, so their State is the one below").waitFor();
      assert.equal(await page.evaluate(() => document.activeElement?.textContent?.trim()), "Record the State", "the keyboard focus was dropped from the button by the save");
      stub.forgetWrites();
      await page.getByRole("button", { name: "Record the State", exact: true }).click();
      await stateBox(page).getByRole("alert").filter({ hasText: "That is the State already recorded." }).waitFor({ timeout: 4000 });
      await stub.quiet();
      assert.equal(patchesOf(stub, "ch-1").length, 0, "the same State was sent again");
      // and a different one is a change
      await pick(page, page.locator('button[aria-label="State of the job worker"]'), "Maharashtra");
      await page.getByRole("button", { name: "Record the State", exact: true }).click();
      await stub.quiet();
      assert.deepEqual(patchesOf(stub, "ch-1"), [{ place_of_supply: "27" }]);
    },
  },
  {
    id: "the-state-box-is-not-offered-where-a-gstin-is-held-or-the-challan-is-cancelled-or-is-not-job-work",
    title: "The State box is not offered to a challan that holds a GSTIN, a cancelled one or one that is not job work",
    async run(env) {
      const { page } = env;
      const cases = [
        { ...BASE, id: "ch-1", consignee_gstin: "29BBBBB1111B1ZR" },
        { ...BASE, id: "ch-3", document_no: "DC/26-27/0003", status: "cancelled" },
        { ...BASE, id: "ch-4", document_no: "DC/26-27/0004", reason: "other_than_supply" },
      ];
      await atTheTab(env, cases);
      for (const c of cases) {
        await open(page, c.document_no);
        await page.getByRole("button", { name: "Close the challan" }).waitFor();
        assert.equal(await stateBox(page).count(), 0, `${c.document_no} is offered the State box`);
        await page.getByRole("button", { name: "Close the challan" }).click();
      }
    },
  },
  {
    id: "pressing-the-state-box-with-nothing-picked-says-so-and-a-refusal-is-the-servers-sentence",
    title: "Record the State with nothing picked says so and sends nothing; a refusal is the server's sentence in the box, which stays",
    async run(env) {
      const { page, stub } = env;
      const SAID = "'99' is not a state code. The place of supply is a two-digit state code (CGST s.25 and the IGST Act's own list).";
      stub.route({ method: "PATCH", re: URL_OF("ch-1"), ...refuse(SAID, 422) });
      await atTheTab(env, [BASE]);
      await open(page, BASE.document_no);
      await stateBox(page).waitFor();
      stub.forgetWrites();
      await page.getByRole("button", { name: "Record the State", exact: true }).click();
      await stateBox(page).getByRole("alert").filter({ hasText: "Pick the State first." }).waitFor();
      await stub.quiet();
      assert.equal(patchesOf(stub, "ch-1").length, 0, "a request was sent with no State picked");
      await pick(page, page.locator('button[aria-label="State of the job worker"]'), "Karnataka");
      await page.getByRole("button", { name: "Record the State", exact: true }).click();
      await stateBox(page).getByRole("alert").filter({ hasText: SAID }).waitFor({ timeout: 4000 });
      assert.equal(await stateBox(page).count(), 1, "the box went away on a refusal");
    },
  },
  {
    id: "a-recorded-place-of-supply-the-states-list-cannot-offer-is-shown-in-words",
    title: "A place of supply of 96 (Other Country) already recorded on a job-work challan with no GSTIN is shown in words and not as an empty picker; Record the State with nothing picked sends nothing, and a State picked over it is sent",
    async run(env) {
      const { page, stub } = env;
      const live = { ...BASE, place_of_supply: "96", is_inter_state: true };
      stub.route({ method: "PATCH", re: URL_OF("ch-1"), reply: (_req, raw) => { Object.assign(live, JSON.parse(raw)); return ok(live); } });
      await atTheTab(env, [live]);
      await open(page, live.document_no);
      await stateBox(page).waitFor();
      await stateBox(page).getByText("The recorded place of supply (96) is not on the list of States").waitFor();
      await stateBox(page).getByText("reads this value for the job worker because no GSTIN is held", { exact: false }).waitFor();
      stub.forgetWrites();
      await page.getByRole("button", { name: "Record the State", exact: true }).click();
      await stateBox(page).getByRole("alert").filter({ hasText: "Pick the State first." }).waitFor();
      await stub.quiet();
      assert.equal(patchesOf(stub, "ch-1").length, 0, "a request was sent with the picker empty");
      await pick(page, page.locator('button[aria-label="State of the job worker"]'), "Karnataka");
      await page.getByRole("button", { name: "Record the State", exact: true }).click();
      await stub.quiet();
      assert.deepEqual(patchesOf(stub, "ch-1"), [{ place_of_supply: "29" }]);
      await stateBox(page).getByText("The job worker has no GSTIN recorded, so their State is the one below").waitFor();
    },
  },
  {
    id: "the-state-boxs-words-follow-the-challans-status",
    title: "An issued challan is told it is named until a State is recorded; a draft is told the statement will name it once it is issued",
    async run(env) {
      const { page } = env;
      const draft = { ...BASE, id: "ch-1", status: "draft" };
      const issued = { ...BASE, id: "ch-2", document_no: "DC/26-27/0002" };
      await atTheTab(env, [draft, issued]);
      await open(page, draft.document_no);
      await stateBox(page).getByText("Once this challan is issued, the FORM GST ITC-04 statement", { exact: false }).waitFor();
      assert.equal(await stateBox(page).getByText("names this challan until one is", { exact: false }).count(), 0, "a draft is told it is already named");
      await page.getByRole("button", { name: "Close the challan" }).click();
      await open(page, issued.document_no);
      await stateBox(page).getByText("so the statement names this challan until one is", { exact: false }).waitFor();
      assert.equal(await stateBox(page).getByText("Once this challan is issued", { exact: false }).count(), 0, "an issued challan is told it is not issued yet");
    },
  },
];
