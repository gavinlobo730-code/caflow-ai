/**
 * A DELIVERY CHALLAN IS ISSUED BY A BUTTON, AND GOODS COME BACK ONLY ON AN ISSUED ONE (POST-A-398), driven in a browser.
 *
 * `create_challan` wrote a draft and nothing in the product ever issued one, so a job-work challan made here was not listed on FORM GST ITC-04 until its goods were marked back, the lots of goods
 * could not be recorded against it, and the whole-challan "Record goods back" was offered for a draft. The challan's detail has an "Issue challan" button now, for a draft only; the server asks what
 * a challan must hold when the goods leave and answers a refusal in a sentence; the box for the day the goods came back lists challans the goods have left on only. Against a stubbed server, in Chromium:
 *
 *   1. a draft shows its status, a line saying what a draft is (not recorded as issued; no period runs on it here; not on FORM GST ITC-04) with how many there are, and no "back at once" block;
 *      its detail has the button, says it is a draft, says which day issuing would record (the challan's own date) and shows the server's sentence about the period;
 *   2. one press sends ONE POST to the issue route, the message (a live region) says the challan is issued, and the detail shows it as issued with no button;
 *   3. two presses in one tick send ONE request;
 *   4. a refusal is said beside the button as the server wrote it, the challan stays a draft, and the next press sends again;
 *   5. a challan with a particular still to be recorded says so beside the button and the server's refusal is shown if it is pressed anyway;
 *   6. an issued challan has no button and is offered "Record goods back";
 *   7. the keyboard opens a challan (its first cell is a button), and reaches Issue challan;
 *   8. a refusal to a press is not shown again when the challan is closed and opened again;
 *   9. a challan recorded as received back with no day is not called overdue: it is said to be unable to be timed, and the box offers to record the day;
 *  10. the form for a challan asks for the place of supply once "Inter-state movement" is ticked, sends the one that was picked, and sends none when the tick is taken off again;
 *      it says what Rule 55(1) asks and where a draft is corrected (its panel: POST-A-417).
 *
 * No scenario has a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { expectWrites, pick, sameTickDouble } from "../kit.mjs";
import { ok, refuse } from "../stub.mjs";

export const group = "challan-issue";

const ISSUE = /api\/sales-cycle\/challans\/ch-2\/issue\?/;
const DRAFT = {
  id: "ch-2", document_no: "DC/26-27/0002", document_date: "2026-07-01", reason: "job_work", reason_label: "Job work", status: "draft",
  received_back_on: null, total_paise: 5_000_000,
  // the clock as the server sends it (`Clock.as_dict()`): every field is always there, and the detail reads `statute`
  clock: { applies: false, statute: "", months: null, sent_on: null, due_back_by: null, overdue: null, days_remaining: null, gaps: [],
    consequence: "This challan is a draft: it is not recorded as issued, so no period is running on it here. If the goods left on the challan's date, 2026-07-01, the period under CGST Act s.143 with Rule 45 would end on 2027-06-30." },
};
const ISSUED = {
  ...DRAFT, status: "issued",
  clock: { applies: true, statute: "CGST Act s.143 with Rule 45", months: 12, sent_on: "2026-07-01", due_back_by: "2027-06-30", overdue: false, days_remaining: 236, gaps: [],
    consequence: "CGST Act s.143(3)/(4): goods not received back within the period are DEEMED to have been supplied." },
};
const PARTICULARS = (challan, missing = []) => ({
  challan, lines: [], rule: "CGST Rule 55", reason_label: "Job work",
  particulars: [{ clause: "55(1)(i)", label: "Date and number of the delivery challan", value: `${challan.document_no} dated ${challan.document_date}`, required: true }],
  missing, copies: [{ copy: "original", legend: "ORIGINAL FOR CONSIGNEE" }], clock: challan.clock,
  rule_55_5: { steps: [], gaps: [] }, itc_04: { decided: false, readings: [], refusal: "" }, ca_review_required: true,
});

/** The tab with one challan in `list`, opened on its Delivery Challans, and the detail route answering with `details` (newest first when a scenario adds another). */
async function atTheChallans(env, list, details) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /sales-cycle\/vocabulary/, reply: () => ok({ challan_reasons: [], goods_kinds: [], quote_kinds: [] }) });
  stub.route({ method: "GET", re: /sales-cycle\/quotations\?/, reply: () => ok([]) });
  stub.route({ method: "GET", re: /sales-cycle\/orders\?/, reply: () => ok([]) });
  stub.route({ method: "GET", re: /sales-cycle\/challans\?/, reply: list });
  stub.route({ method: "GET", re: /sales-cycle\/challans\/ch-2\?/, reply: details });
  stub.route({ method: "GET", re: /\/customers/, reply: () => ok([]) });
  await page.goto(env.at("/sales/?tab=sales-cycle"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Delivery Challans" }).click();
  await page.getByText(DRAFT.document_no).first().waitFor();
}

const CREATE = /api\/sales-cycle\/challans$/;

/** The tab on its Delivery Challans with "New" open on a job-work challan: a customer picked, a number, one line with its HSN. Nothing is left but the box under test and Save. */
async function atTheNewChallanForm(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /sales-cycle\/vocabulary/, reply: () => ok({
    quote_kinds: [], quote_statuses: [], order_statuses: [], challan_statuses: [],
    challan_reasons: [{ value: "job_work", label: "Job work", is_a_supply: false }],
    goods_kinds: [{ value: "inputs", label: "Inputs" }],
    not_a_tax_invoice: "This is not a tax invoice.", no_tax_on_a_non_supply: "No tax is charged on a non-supply.",
    job_work_exclusion: "", rule_55_5_steps: [], copies: [], itc_04: { decided: false, readings: [], refusal: "" },
  }) });
  stub.route({ method: "GET", re: /sales-cycle\/quotations\?/, reply: () => ok([]) });
  stub.route({ method: "GET", re: /sales-cycle\/orders\?/, reply: () => ok([]) });
  stub.route({ method: "GET", re: /sales-cycle\/challans\?/, reply: () => ok([]) });
  stub.route({ method: "GET", re: /\/customers/, reply: () => ok([{ id: "cu1", name: "Beta Stores" }]) });
  stub.route({ method: "POST", re: CREATE, reply: () => ok({ id: "sc-1" }) });
  await page.goto(env.at("/sales/?tab=sales-cycle"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Delivery Challans" }).click();
  await page.getByRole("button", { name: "New", exact: true }).click();
  await page.getByText("Number", { exact: true }).waitFor();
  await page.locator("select:has(option[value='cu1'])").first().selectOption("cu1");
  await page.locator("label:has-text('Number') input").first().fill("DC/26-27/0003");
  await page.getByLabel("Line 1 description").fill("Steel bar");
  await page.getByLabel("Line 1 HSN or SAC code").fill("7214");
}

const open = async (page) => { await page.getByText(DRAFT.document_no).first().click(); };
const issueButton = (page) => page.getByRole("button", { name: "Issue challan", exact: true });

export const scenarios = [
  {
    id: "a-draft-says-what-a-draft-is-and-its-detail-says-which-day-issuing-records-and-offers-the-button",
    title: "Delivery Challans: a draft shows its status and what a draft is (not recorded as issued, no period here, not on ITC-04) with how many there are, has no 'back at once' block, and its detail says which day issuing records and offers Issue challan",
    async run(env) {
      const { page } = env;
      await atTheChallans(env, () => ok([DRAFT]), () => ok(PARTICULARS(DRAFT)));
      await page.getByText("1 in draft. A draft is not recorded as issued: no period runs on it here and it is not on FORM GST ITC-04.", { exact: false }).waitFor();
      assert.equal(await page.getByText("have not left", { exact: false }).count() + await page.getByText("has not left", { exact: false }).count(), 0, "a draft is said to be a challan whose goods have not left, which the product cannot know");
      assert.equal(await page.getByText("Mark a whole challan back at once").count(), 0, "a draft is offered the box for the day its goods came back");
      assert.equal(await issueButton(page).count(), 0, "the button is on the list before the challan is opened");
      await open(page);
      await page.getByText(`Challan ${DRAFT.document_no} is a draft`).waitFor();
      await page.getByText("Issuing records that the goods left on 01 Jul 2026, the challan's date", { exact: false }).waitFor();   // the day, written by the one date module
      await page.getByText("would end on 2027-06-30", { exact: false }).waitFor();                         // the server's own sentence about the period
      await issueButton(page).waitFor();
    },
  },
  {
    id: "one-press-of-issue-sends-one-post-and-the-challan-is-then-shown-as-issued",
    title: "Issue challan pressed once sends ONE POST to the issue route, the message says the challan is issued, and the detail no longer offers the button",
    async run(env) {
      const { page, stub } = env;
      let issued = false;
      stub.route({ method: "POST", re: ISSUE, reply: () => { issued = true; return ok(ISSUED); } });
      await atTheChallans(env, () => ok([issued ? ISSUED : DRAFT]), () => ok(PARTICULARS(issued ? ISSUED : DRAFT)));
      await open(page);
      await issueButton(page).click();
      await page.getByRole("status").filter({ hasText: `Challan ${DRAFT.document_no} issued.` }).waitFor();                      // a live region: the success is announced, the button it came from is gone
      await expectWrites(stub, ISSUE, 1, "pressing Issue challan", "POST");
      await page.getByText(`Challan ${DRAFT.document_no} is a draft`).waitFor({ state: "detached" });
      assert.equal(await issueButton(page).count(), 0, "an issued challan is offered the button");
      await page.getByText("Mark a whole challan back at once").waitFor();
    },
  },
  {
    id: "two-presses-of-issue-in-one-tick-send-one-request",
    title: "Issue challan pressed twice in the same tick sends ONE request (it records that the goods left and lists a job-work challan on FORM GST ITC-04)",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "POST", re: ISSUE, reply: () => ok(ISSUED) });
      await atTheChallans(env, () => ok([DRAFT]), () => ok(PARTICULARS(DRAFT)));
      await open(page);
      await sameTickDouble(issueButton(page));
      await expectWrites(stub, ISSUE, 1, "two same-tick presses on Issue challan", "POST");
    },
  },
  {
    id: "a-refusal-is-said-beside-the-button-the-challan-stays-a-draft-and-the-next-press-sends-again",
    title: "a refusal is shown as the server wrote it beside the button, the challan stays a draft, and the next press sends a second request",
    async run(env) {
      const { page, stub } = env;
      const REFUSED = "Challan DC/26-27/0002 is dated 2026-07-01, which has not come, so the goods cannot have left on it. A challan is issued on or after its date.";
      stub.route({ method: "POST", re: ISSUE, ...refuse(REFUSED, 422) });
      await atTheChallans(env, () => ok([DRAFT]), () => ok(PARTICULARS(DRAFT)));
      await open(page);
      await issueButton(page).click();
      await page.getByRole("alert").filter({ hasText: REFUSED }).waitFor();
      await page.getByText(`Challan ${DRAFT.document_no} is a draft`).waitFor();
      await expectWrites(stub, ISSUE, 1, "the refused press", "POST");
      await issueButton(page).click();
      await expectWrites(stub, ISSUE, 2, "the press after a refusal", "POST");
    },
  },
  {
    id: "a-draft-with-a-particular-to-record-says-so-beside-the-button",
    title: "a draft whose Rule 55 view still lists a particular says that the server will not issue it without that, and the server's refusal is shown if the button is pressed",
    async run(env) {
      const { page, stub } = env;
      const MISSING = "55(1)(iii) Name, address and GSTIN or UIN of the consignee, if registered";
      const SAID = `Challan ${DRAFT.document_no} cannot be issued yet: Rule 55(1) asks for ${MISSING}.`;
      stub.route({ method: "POST", re: ISSUE, ...refuse(SAID, 422) });
      await atTheChallans(env, () => ok([DRAFT]), () => ok(PARTICULARS(DRAFT, [MISSING])));
      await open(page);
      await page.getByText("Still to be recorded", { exact: true }).waitFor();
      await page.getByText("the server will not issue the challan without it", { exact: false }).waitFor();
      await page.getByText("Correct draft records the consignee", { exact: false }).waitFor();                      // the place to record it is the draft's own panel (POST-A-417)
      assert.equal(await page.getByText("not edited on this screen", { exact: false }).count(), 0, "the panel still says a draft cannot be edited");
      await issueButton(page).click();
      await page.getByRole("alert").filter({ hasText: SAID }).waitFor();
    },
  },
  {
    id: "an-issued-challan-has-no-button-and-is-offered-goods-back",
    title: "an issued challan's detail has no Issue challan button and the list offers 'Record goods back' for it",
    async run(env) {
      const { page } = env;
      await atTheChallans(env, () => ok([ISSUED]), () => ok(PARTICULARS(ISSUED)));
      await page.getByText("Mark a whole challan back at once").waitFor();
      await page.getByRole("button", { name: "Record goods back", exact: true }).waitFor();
      assert.equal(await page.getByText("in draft.", { exact: false }).count(), 0, "an issued challan is counted as a draft");
      await open(page);
      await page.getByText("Rule 55", { exact: false }).first().waitFor();
      assert.equal(await issueButton(page).count(), 0, "an issued challan is offered the button");
    },
  },
  {
    id: "the-keyboard-opens-a-challan-and-reaches-issue-challan",
    title: "a challan is opened from the keyboard (its number is a button) and Issue challan is then reachable without a mouse",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "POST", re: ISSUE, reply: () => ok(ISSUED) });
      await atTheChallans(env, () => ok([DRAFT]), () => ok(PARTICULARS(DRAFT)));
      const number = page.getByRole("button", { name: DRAFT.document_no, exact: true });
      await number.focus();
      await page.keyboard.press("Enter");
      await page.getByText(`Challan ${DRAFT.document_no} is a draft`).waitFor();
      await issueButton(page).focus();
      await page.keyboard.press("Enter");
      await expectWrites(stub, ISSUE, 1, "Issue challan pressed from the keyboard", "POST");
    },
  },
  {
    id: "a-refusal-to-a-press-is-not-shown-again-when-the-challan-is-closed-and-opened-again",
    title: "the server's refusal to Issue challan is cleared when the challan is closed, so reopening it does not show yesterday's refusal as today's",
    async run(env) {
      const { page, stub } = env;
      const REFUSED = "Challan DC/26-27/0002 has no lines, so there are no goods to send on it.";
      stub.route({ method: "POST", re: ISSUE, ...refuse(REFUSED, 422) });
      await atTheChallans(env, () => ok([DRAFT]), () => ok(PARTICULARS(DRAFT)));
      await open(page);
      await issueButton(page).click();
      await page.getByRole("alert").filter({ hasText: REFUSED }).waitFor();
      await page.getByRole("button", { name: "Close the challan" }).click();
      await page.getByText(`Challan ${DRAFT.document_no} is a draft`).waitFor({ state: "detached" });
      await open(page);
      await issueButton(page).waitFor();
      assert.equal(await page.getByText(REFUSED, { exact: false }).count(), 0, "the refusal to an earlier press came back with the reopened challan");
    },
  },
  {
    id: "a-challan-recorded-as-received-back-with-no-day-is-not-called-overdue-and-the-box-offers-the-day",
    title: "a challan whose status says received back and which has no day is listed as one that cannot be timed (not as overdue), and 'Mark a whole challan back at once' offers to record the day",
    async run(env) {
      const { page } = env;
      const GAP = "This challan is recorded as received back with no day, so whether the goods came back within the period cannot be said. Record the day they came back.";
      const STATUS_ONLY = {
        ...ISSUED, status: "received_back",
        clock: { ...ISSUED.clock, overdue: null, days_remaining: null, gaps: [GAP] },
      };
      await atTheChallans(env, () => ok([STATUS_ONLY]), () => ok(PARTICULARS(STATUS_ONLY)));
      await page.getByText("1 challan cannot be timed yet", { exact: false }).waitFor();
      await page.getByText(GAP, { exact: false }).waitFor();
      assert.equal(await page.getByText("past the statutory period", { exact: false }).count(), 0, "a row with no day is called overdue");
      await page.getByText("Mark a whole challan back at once").waitFor();
      await page.getByRole("button", { name: "Record goods back", exact: true }).waitFor();
    },
  },
  {
    id: "the-challan-form-asks-for-the-place-of-supply-of-an-inter-state-movement-and-sends-it",
    title: "the new-challan form shows 'Place of supply' only once 'Inter-state movement' is ticked, sends the state picked, and sends none when the tick is taken off again",
    async run(env) {
      const { page, stub } = env;
      await atTheNewChallanForm(env);
      const box = page.locator('button[aria-label="Place of supply"]');
      assert.equal(await box.count(), 0, "the place of supply is asked for a movement that is not inter-State");
      await page.getByText("CGST Rule 55(1) asks for the HSN code of every line", { exact: false }).waitFor();
      await page.getByText("a draft saved without one of these is corrected from its panel", { exact: false }).first().waitFor();
      await page.getByLabel("Inter-state movement").check();
      await pick(page, box, "Karnataka");
      await page.getByRole("button", { name: "Save", exact: true }).click();
      await expectWrites(stub, CREATE, 1, "saving an inter-State challan", "POST");
      const sent = JSON.parse(stub.writesTo(CREATE, "POST")[0].body);
      assert.equal(sent.is_inter_state, true);
      assert.equal(sent.place_of_supply, "29", `the state picked (Karnataka, 29) was not sent: ${JSON.stringify(sent.place_of_supply)}`);
    },
  },
  {
    id: "a-place-of-supply-picked-and-then-the-tick-taken-off-is-not-sent",
    title: "a state picked for an inter-State movement is not sent once the tick has been taken off: the challan is not inter-State and names no place",
    async run(env) {
      const { page, stub } = env;
      await atTheNewChallanForm(env);
      await page.getByLabel("Inter-state movement").check();
      await pick(page, page.locator('button[aria-label="Place of supply"]'), "Karnataka");
      await page.getByLabel("Inter-state movement").uncheck();
      assert.equal(await page.locator('button[aria-label="Place of supply"]').count(), 0, "the place of supply stays after the tick is off");
      await page.getByRole("button", { name: "Save", exact: true }).click();
      await expectWrites(stub, CREATE, 1, "saving a challan", "POST");
      const sent = JSON.parse(stub.writesTo(CREATE, "POST")[0].body);
      assert.equal(sent.is_inter_state, false);
      assert.equal(sent.place_of_supply, null, `a place of supply was sent for a movement that is not inter-State: ${JSON.stringify(sent.place_of_supply)}`);
    },
  },
];
