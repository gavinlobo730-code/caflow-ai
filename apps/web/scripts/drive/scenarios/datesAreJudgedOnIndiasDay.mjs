/**
 * A DATE THAT FEEDS A READ, A DRAFT OR A RECORD IS JUDGED ON INDIA'S DAY AND HELD BEFORE IT IS USED (POST-A-393).
 *
 * Five of the six items of that ledger line are about what a screen does with a date box (or with what a box feeds); the source guard
 * (`a-date-that-feeds-a-read-a-draft-or-a-record-is-judged-on-indias-day-and-held-before-it-is-used.test.ts`) holds the wiring, and this drives what a person sees:
 *
 *   * the day a stock transfer starts from, and the day the Schedule III ageing starts from, is INDIA's: at 20:00 UTC on 8 October it is already 9 October in India, and 8 October in Los Angeles;
 *   * the ageing schedule reads nothing for a box that is cleared or holds text that is not a date (the server answers a missing date as at today, which put today's figures under a box that said
 *     nothing), and says why no schedule is shown;
 *   * the overdue-interest panel holds "Prepare draft invoice" while the table on screen is for another date than the box holds (the read for the new date is out, or failed);
 *   * a tax audit recorded as filed is refused a filing date that has not come, while one in progress may carry a planned day (the line is drawn by the status); a box whose bound moves is judged
 *     again WITHOUT being remounted, so text it could not read stays a problem;
 *   * the ITC-04 job worker's challan date is held when it is after the day the goods came back, in whichever order the two are typed;
 *   * the Form 15CA / 15CB fields of a purchase bill are sent when their block is drawn and not when the server has said the bill does not withhold under section 195, and a reading that FAILED
 *     keeps the block (and what was typed in it) drawn;
 *   * an older answer for a date a box no longer holds never paints over the newer one (the ageing schedule and the interest table).
 *
 * The database's side of the tax audit (migration 584) and the ITC-04 job worker's challan date (the server's rule) are tested in Python.
 */
import assert from "node:assert/strict";
import { TZ_MATRIX, pick, until } from "../kit.mjs";
import { ok } from "../stub.mjs";
import { VENDOR } from "../fixtures.mjs";

export const group = "dates";

/** 20:00 UTC on 8 October 2026: 01:30 on 9 October in India, 13:00 on 8 October in Los Angeles, 10:00 on 9 October at UTC+14. Only in the first is the browser's day not India's. */
const INDIA_IS_ALREADY_TOMORROW = "2026-10-08T20:00:00Z";
const INDIAS_DAY = "09/10/2026";

/** Type into a date box the way a person does, and leave it: the value is committed on blur. Does NOT wait for the network to go quiet (a scenario that holds a request open needs the moment). */
async function typeAndLeaveNow(box, text) {
  await box.fill("");
  if (text) await box.pressSequentially(text);
  await box.press("Tab");
}

const permissions = (stub, permissionsByResource) => stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: permissionsByResource }) });

// ── the stock transfer ─────────────────────────────────────────────────────────────────────────────

async function openStockTransfer(env) {
  const { page, stub } = env;
  permissions(stub, { inventory: ["read", "write"], accounting: ["read", "write"] });
  stub.route({ method: "GET", re: /api\/inventory\/items\?/, reply: () => ok([{
    id: "sc1", name: "Copier paper", description: null, hsn_sac: "4802", unit: "NOS", is_active: true, stock_qty_units: 40, avg_cost_paise: 25000, stock_value_paise: 1000000 }]) });
  stub.route({ method: "GET", re: /api\/inventory\/godowns\?/, reply: () => ok({ unallocated_means: "Stock not yet placed in a godown.", godowns: [
    { id: "g1", name: "Main godown", code: "MAIN", state_code: "27", gstin: null, is_default: true, is_active: true },
    { id: "g2", name: "Pune godown", code: "PUN", state_code: "27", gstin: null, is_default: false, is_active: true }] }) });
  stub.route({ method: "GET", re: /api\/inventory\/position-detail\?/, reply: () => ok({ rows: [{
    service_catalogue_id: "sc1", item_name: "Copier paper", unit: "NOS", godown_id: "g1", godown_name: "Main godown", batch_id: null, batch_no: null, expiry_date: null, qty_units: "40", value_paise: 1000000 }] }) });
  stub.route({ method: "GET", re: /api\/inventory\/expiry\?/, reply: () => ok({ bucket_order: [], bucket_labels: {}, buckets: {}, rows: [], notes: [] }) });
  stub.route({ method: "GET", re: /api\/inventory\/batches\?/, reply: () => ok([]) });
  stub.route({ method: "GET", re: /api\/inventory\/transfer-preview\?/, reply: () => ok({ is_supply: false, reason: "Both godowns are in the same state, so this is not a supply." }) });
  await page.goto(env.at("/inventory/"), { waitUntil: "networkidle" });
  const panel = page.locator("div.rounded-xl.overflow-hidden").filter({ has: page.getByRole("heading", { name: /Move stock between godowns/ }) }).last();
  await panel.waitFor();
  return panel.locator("label").filter({ has: page.locator("span").filter({ hasText: /^Date$/ }) }).locator("input").first();
}

// ── the Schedule III ageing ─────────────────────────────────────────────────────────────────────────

const AGEING_TABLE = (title) => ({ title, buckets: [], rows: [], column_totals: {}, total_paise: 0, unbilled_dues_paise: null, unbilled_accounts: [] });
const AGEING_SCHEDULE = {
  as_of: "2026-10-09", division: "I", statute: "Schedule III to the Companies Act 2013", ageing_from: "the due date",
  receivables: AGEING_TABLE("Trade receivables ageing"), payables: { ...AGEING_TABLE("Trade payables ageing"), unclassified_paise: 0, unclassified_vendors: [] },
  unbilled_reviewed_on: null, gaps: [],
};

// ── the overdue interest ────────────────────────────────────────────────────────────────────────────

const INTEREST_PREVIEW = (asOf) => ok({
  as_of: asOf, convention: { statement: "stub", day_count: "stub", as_of: asOf },
  statutory_reading: { section: "stub", grade: "S", text: "stub" }, caveats: [], gaps: [],
  totals: { interest_paise: 1_200_00, parties_with_interest: 1, parties_without_terms: 0, overdue_outstanding_paise: 50_000_00 },
  parties: [{ customer_id: "c-beta", customer_name: "Beta Stores", terms_set: true, terms: { rate_bps: 1800, grace_days: 0, basis: "simple" },
    overdue_outstanding_paise: 50_000_00, interest_paise: 1_200_00, documents: [] }],
});

export const scenarios = [
  {
    id: "stock-transfer-date-starts-from-indias-day",
    title: "Inventory > Locations > Move stock between godowns: the day the stock moved starts from India's day, not the browser's",
    contexts: TZ_MATRIX,
    async run(env) {
      const { context } = env;
      await context.clock.setFixedTime(new Date(INDIA_IS_ALREADY_TOMORROW));
      const box = await openStockTransfer(env);
      assert.equal(await box.inputValue(), INDIAS_DAY, "the transfer's date did not start from India's day (it started from the browser's)");
      // The two forms beside it on the same page post to the books too: the adjustment and the write-down start from India's day as well.
      const { page } = env;
      for (const [button, id, what] of [["Adjust", "#stock-adjust-date", "stock adjustment"], ["Write down", "#writedown-date", "NRV write-down"]]) {
        await page.getByRole("button", { name: button, exact: true }).first().click();
        const dateBox = page.locator(id);
        await dateBox.waitFor({ timeout: 4000 });
        assert.equal(await dateBox.inputValue(), INDIAS_DAY, `the ${what}'s date did not start from India's day (it started from the browser's)`);
        await page.getByRole("button", { name: "Cancel", exact: true }).click();
        await dateBox.waitFor({ state: "detached", timeout: 4000 });
      }
    },
  },
  {
    id: "ageing-as-at-starts-from-indias-day-and-is-not-read-blank-or-unreadable",
    title: "Reports > Ageing schedules: As at starts from India's day; a cleared box or text that is not a date asks the server for nothing and says why; a date asks for that date",
    contexts: TZ_MATRIX,
    async run(env) {
      const { page, stub, context } = env;
      await context.clock.setFixedTime(new Date(INDIA_IS_ALREADY_TOMORROW));
      const asked = [];
      permissions(stub, { accounting: ["read", "write", "approve"], report: ["read"], client: ["read", "write"] });
      stub.route({ method: "GET", re: /api\/accounting\/schedule-iii\/ageing\?/, reply: (_req, _raw, url) => { asked.push(url.searchParams.get("as_of")); return ok(AGEING_SCHEDULE); } });
      await page.goto(env.at("/reports/ageing/"), { waitUntil: "networkidle" });
      const box = page.locator("#ageing-as-at");
      await box.waitFor();
      assert.equal(await box.inputValue(), INDIAS_DAY, "the schedule's As at did not start from India's day");
      assert.deepEqual(asked, ["2026-10-09"], "the first reading was not asked for India's day");
      const note = page.getByText("As at: enter the date this schedule is as at.");
      assert.equal(await note.count(), 0, "the note is shown over a box that holds a date");
      assert.ok(await page.getByText("Trade receivables ageing").count() >= 1, "the schedule for India's day is not on the screen, so 'nothing stays after the box is cleared' below would prove nothing");

      await typeAndLeaveNow(box, "");
      await note.waitFor({ timeout: 4000 }).catch(() => { throw new Error("a cleared As at did not say that no schedule is shown until it holds a date"); });
      await page.waitForTimeout(700);
      assert.deepEqual(asked, ["2026-10-09"], "a CLEARED As at asked the server for a schedule (it answers as at today, under a box that says nothing)");
      assert.equal(await page.getByText("Trade receivables ageing").count(), 0, "the last date's schedule stayed on the screen under a cleared box");

      await typeAndLeaveNow(box, "31/02/2026");
      await note.waitFor({ timeout: 4000 });
      await page.waitForTimeout(700);
      assert.deepEqual(asked, ["2026-10-09"], "an As at that is not a date asked the server for a schedule");

      await typeAndLeaveNow(box, "15/09/2026");
      await until(() => asked.length === 2, "the schedule to be asked for the date typed");
      assert.equal(asked[1], "2026-09-15", `the schedule was asked for ${asked[1]}`);
      await note.waitFor({ state: "detached", timeout: 4000 });
    },
  },
  {
    id: "overdue-interest-prepare-is-held-while-the-table-is-another-dates",
    title: "Sales > Overdue Interest: while the table for a newly typed date is being worked out, or could not be, Prepare draft invoice is held (and after a failed reading the panel says why in words); it opens when the table is the box's date",
    async run(env) {
      const { page, stub, context } = env;
      await context.clock.setFixedTime(new Date(INDIA_IS_ALREADY_TOMORROW));
      permissions(stub, { sales: ["read", "write"] });
      // The panel asks `as_of` (lib/api: lateInterest.preview); the stub answers with the date it was asked for, as the server does.
      const asked = [];
      const preview = (delay) => ({ method: "GET", re: /api\/late-interest\/preview\?/, ...(delay ? { delay } : {}),
        reply: (_req, _raw, url) => { asked.push(url.searchParams.get("as_of")); return INTEREST_PREVIEW(url.searchParams.get("as_of")); } });
      stub.route(preview());
      stub.route({ method: "GET", re: /api\/late-interest\/terms\?/, reply: () => ok({ customers: [] }) });
      stub.route({ method: "POST", re: /api\/late-interest\/drafts$/, reply: () => ok({ drafts: [], not_drafted: [], failed: [], caveats: [] }) });
      await page.goto(env.at("/sales/?tab=interest"), { waitUntil: "networkidle" });
      const prepare = page.getByRole("button", { name: "Prepare draft invoice" }).first();
      await prepare.waitFor();
      assert.deepEqual(asked, ["2026-10-09"], "the first table was not asked for India's day");
      assert.equal(await prepare.isDisabled(), false, "Prepare is held over a table that is the box's date");
      const held = page.getByText(/The table below is worked out as at/);
      assert.equal(await held.count(), 0, "the panel says Prepare is held over a table that is the box's date");
      const box = page.locator("#overdue-as-at");

      // A newly typed date whose reading is slow: the table is still the old date's and Prepare is held, with the reason on the button (the reading is out, so the Refresh button is spinning
      // and no note is drawn: it would flash on every date typed).
      stub.route(preview(1500));
      await typeAndLeaveNow(box, "15/09/2026");
      await until(async () => await prepare.isDisabled(), "Prepare to be held while the table for the new date is worked out");
      assert.match(await prepare.getAttribute("title") ?? "", /as at 09 Oct 2026\. Prepare opens again once it is worked out as at 15 Sep 2026\./, "Prepare is held without saying why, or names the wrong dates");
      await until(async () => !(await prepare.isDisabled()), "Prepare to open again once the table is the new date's");
      assert.equal(await held.count(), 0, "the held note stayed after the table was the box's date");
      assert.equal(asked.at(-1), "2026-09-15", `the table was asked for ${asked.at(-1)}`);
      await stub.quiet();

      // A newly typed date whose reading FAILS: the table stays the old date's, and Prepare stays held (a draft would be computed as at the new date).
      stub.route({ method: "GET", re: /api\/late-interest\/preview\?/, reply: () => ({ success: false, data: null, error: "Interest could not be worked out." }) });
      await typeAndLeaveNow(box, "20/09/2026");
      await page.getByText("Interest could not be worked out.").first().waitFor({ timeout: 4000 });
      assert.equal(await prepare.isDisabled(), true, "Prepare opened over a table that is another date's after the reading for the box's date failed");
      // The reading is over and failed: nothing is spinning, the figures below are another date's, and the panel says so in words where it can be read (a title on a disabled button is not).
      await held.first().waitFor({ timeout: 4000 }).catch(() => { throw new Error("after a failed reading Prepare is held and the panel does not say so in words"); });
      assert.match(await held.first().innerText(), /as at 15 Sep 2026\. Prepare opens again once it is worked out as at 20 Sep 2026\./, "after a failed reading the note does not name the table that is on screen");
      stub.forgetWrites();
      await prepare.click({ force: true, timeout: 1000 }).catch(() => { /* a held button may refuse the click; either way nothing may be sent */ });
      await page.waitForTimeout(500);
      assert.equal(stub.writesTo(/api\/late-interest\/drafts$/).length, 0, "a draft was prepared as at a date whose table was not on screen");

      // Back to a date whose reading works: the table is the box's again and the note goes.
      stub.route(preview());
      await typeAndLeaveNow(box, "15/09/2026");
      await until(async () => !(await prepare.isDisabled()), "Prepare to open once the box holds the date the table is for");
      assert.equal(await held.count(), 0, "the held note stayed over a table that is the box's date");
    },
  },
  {
    id: "tax-audit-dates-are-bounded-only-when-the-status-says-the-act-is-done",
    title: "Income Tax > Tax Audit > Add Audit: a filing date after today is refused for an audit recorded as filed, in whichever order the status and the day are given, an audit date after today for one recorded as completed, and a planned day is accepted for one in progress",
    async run(env) {
      const { page, stub } = env;
      permissions(stub, { income_tax: ["read", "write", "approve"] });
      stub.setTable("tax_audits", []);
      await page.goto(`${env.base}/income-tax/tax-audit/`, { waitUntil: "networkidle" });
      await page.getByRole("button", { name: "Add Audit", exact: true }).first().click();
      await pick(page, page.locator('button[aria-label="Client"]'), "Acme Traders Pvt Ltd");
      const filing = page.locator("#tax-audit-filing-date");
      const audit = page.locator("#tax-audit-date");
      const status = page.locator("#tax-audit-status");
      const save = page.getByRole("button", { name: "Add Audit", exact: true }).last();
      // The pinned clock is 8 October 2026 in India; a day typed after it reads "<label>: 20 Nov 2026 is after 08 Oct 2026."
      const said = (label, day) => page.getByText(`${label}: ${day} is after 08 Oct 2026.`);
      const refusedBySave = async (label, day, what) => {
        stub.forgetWrites();
        await save.click();
        await said(label, day).first().waitFor({ timeout: 4000 }).catch(() => { throw new Error(`${what}: Save did not say "${label}: ${day} is after 08 Oct 2026."`); });
        await page.waitForTimeout(300);
        assert.equal(stub.writesTo(/rest\/v1\/tax_audits/).length, 0, `${what}: the audit was SENT`);
      };
      await filing.waitFor();

      // In progress: a planned day is no problem (proved at the end: the audit in progress is SENT with its planned days).
      await status.selectOption("in_progress");
      await typeAndLeaveNow(filing, "20/11/2026");

      // The status is changed AFTER the day was typed: the box is judged again (a bound that follows another field is not re-read by a box that already holds a day), and says so under itself.
      await status.selectOption("filed");
      await page.getByText("20 Nov 2026 is after 08 Oct 2026.", { exact: true }).first().waitFor({ timeout: 4000 })
        .catch(() => { throw new Error("the status changed to filed over a filing date in the future, and the box did not say so under itself"); });
      await refusedBySave("Filing date", "20 Nov 2026", "an audit changed to filed AFTER its filing date was typed");
      // ...and the sentence goes with its cause: the status is switched back to one that may carry a planned day, and the banner Save raised is not left saying the day is wrong.
      await status.selectOption("in_progress");
      await said("Filing date", "20 Nov 2026").first().waitFor({ state: "detached", timeout: 4000 })
        .catch(() => { throw new Error("the banner that said the filing date was after today stayed after the status no longer asked it"); });

      // The other order: the status is filed first and the day is typed afterwards (a different day, so the sentence is a new one).
      await status.selectOption("in_progress");
      await status.selectOption("filed");
      await typeAndLeaveNow(filing, "21/11/2026");
      await refusedBySave("Filing date", "21 Nov 2026", "a filing date typed after today for an audit recorded as filed");

      // Text that cannot be read is not a day, and a status change does not make it one or take it away: it stays a problem, in its own sentence, and nothing is sent.
      await status.selectOption("in_progress");
      await typeAndLeaveNow(filing, "31/02/2026");
      await status.selectOption("filed");
      stub.forgetWrites();
      await save.click();
      await page.getByText(/Filing date: .*28 days/).first().waitFor({ timeout: 4000 })
        .catch(() => { throw new Error("a filing date that is not a date was forgotten when the status changed: Save did not refuse it"); });
      await page.waitForTimeout(300);
      assert.equal(stub.writesTo(/rest\/v1\/tax_audits/).length, 0, "an audit with a filing date that is not a date was SENT after the status changed");
      assert.equal(await filing.inputValue(), "31/02/2026", "the text in the box was dropped by the status change");
      await typeAndLeaveNow(filing, "21/11/2026");

      // Completed: the filing date is not asked (it is not filed); the audit date is.
      await status.selectOption("completed");
      await typeAndLeaveNow(audit, "22/11/2026");
      await refusedBySave("Audit date", "22 Nov 2026", "an audit date typed after today for an audit recorded as completed");
      assert.equal(await said("Filing date", "21 Nov 2026").count(), 0, "the filing date was still being refused for an audit that is only completed");

      // Back to in progress: both are planned days and the audit is recorded.
      await status.selectOption("in_progress");
      stub.forgetWrites();
      await save.click();
      await until(() => stub.writesTo(/rest\/v1\/tax_audits/).length === 1, "the audit in progress, with planned days, to be sent");
    },
  },
  {
    id: "itc04-challan-date-after-the-day-the-goods-came-back-holds-the-lot",
    title: "Sales > Challans > FORM GST ITC-04: a job worker's challan dated after the day the goods came back holds the lot, in whichever order the two days are typed, and the lot is recorded once they agree",
    async run(env) {
      const { page, stub, context } = env;
      await context.clock.setFixedTime(new Date(INDIA_IS_ALREADY_TOMORROW));
      stub.route({ method: "GET", re: /api\/customers/, reply: () => ok([{ id: "cu1", name: "Beta Stores" }]) });
      stub.route({ method: "GET", re: /sales-cycle\/vocabulary$/, reply: () => ok({
        quote_kinds: [], quote_statuses: [], order_statuses: [], challan_statuses: [], challan_reasons: [], goods_kinds: [],
        not_a_tax_invoice: "", no_tax_on_a_non_supply: "", job_work_exclusion: "", rule_55_5_steps: [], copies: [], itc_04: { decided: false, readings: [], refusal: "" },
      }) });
      stub.route({ method: "GET", re: /sales-cycle\/itc-04\?/, reply: () => ok({
        client_id: env.clientId, financial_year: "2026-27", as_of: "2026-10-09",
        period: { decided: true, readings: [], refusal: "", preceding_year_aato_paise: null, verified: false },
        readings: [], selected_window: null, table_4: null, table_5a: null,
        table_5b: { derived: false, reason: "" }, table_5c: { derived: false, reason: "" },
        outstanding: [{
          challan_id: "ch-1", challan_no: "JW/001", challan_date: "2026-06-01", job_worker: { name: "Gamma Works" }, goods_kind: "inputs",
          lines: [{ challan_line_id: "cl-1", description: "Steel sheet", uqc: "KGS", sent: "5", returned: "0", lost_or_wasted: "0", outstanding: "5", taxable_value_at_stake_paise: 100000 }],
          taxable_value_at_stake_paise: 100000,
          clock: { applies: true, due_back_by: "2027-06-01", days_remaining: 236, overdue: false, consequence: "", gaps: [] },
        }],
        gaps: [], nothing_is_filed: true, verified: false, ca_review_required: true,
      }) });
      stub.route({ method: "POST", re: /sales-cycle\/challans\/ch-1\/returns$/, reply: () => ok({ id: "ret-1", challan_marked_received_back: false }) });
      await page.goto(env.at("/sales/?tab=sales-cycle"), { waitUntil: "networkidle" });
      await page.getByRole("button", { name: "Delivery Challans", exact: true }).click();
      const openLot = async () => {
        await page.getByRole("button", { name: "Record a lot", exact: true }).click();
        await page.getByText("Quantity returned", { exact: true }).waitFor();
        await page.locator("label:has-text('Quantity returned') input").first().fill("2");
      };
      const cameBack = page.locator("#itc04-came-back-on");
      const challanDate = page.locator("#itc04-challan-date");
      const record = page.getByRole("button", { name: "Record this lot", exact: true });
      const sentence = (challan, back) => page.getByText(`Job worker's challan date: ${challan} is after ${back}.`);
      const press = async (what, challan, back) => {
        stub.forgetWrites();
        await record.click();
        await sentence(challan, back).first().waitFor({ timeout: 4000 }).catch(() => { throw new Error(`${what}: Record this lot did not say "Job worker's challan date: ${challan} is after ${back}."`); });
        await page.waitForTimeout(300);
        assert.equal(stub.writesTo(/challans\/ch-1\/returns$/).length, 0, `${what}: the lot was SENT`);
      };

      // Text that cannot be read in the challan's box is a problem, and moving the came-back day does not drop it (the lot would be recorded without a challan day, silently).
      await openLot();
      await typeAndLeaveNow(challanDate, "31/02/2026");
      await typeAndLeaveNow(cameBack, "10/06/2026");
      stub.forgetWrites();
      await record.click();
      await page.getByText(/Job worker's challan date: .*28 days/).first().waitFor({ timeout: 4000 })
        .catch(() => { throw new Error("a challan date that is not a date was forgotten when the came-back day changed: Record this lot did not refuse it"); });
      await page.waitForTimeout(300);
      assert.equal(stub.writesTo(/challans\/ch-1\/returns$/).length, 0, "a lot with a challan date that is not a date was SENT after the came-back day changed");
      assert.equal(await challanDate.inputValue(), "31/02/2026", "the challan's text was dropped when the came-back day changed");

      // The challan's day is typed FIRST (the came-back box is emptied, so nothing bounds it yet) and the day the goods came back after it: the box is judged against the bound that arrived later.
      await typeAndLeaveNow(cameBack, "");
      await typeAndLeaveNow(challanDate, "12/06/2026");
      await typeAndLeaveNow(cameBack, "10/06/2026");
      await press("the challan's day typed before the came-back day", "12 Jun 2026", "10 Jun 2026");

      // Put right by moving the came-back day to the challan's: the sentence goes and the lot is recorded once, with the two days as typed.
      await typeAndLeaveNow(cameBack, "12/06/2026");
      stub.forgetWrites();
      await record.click();
      await until(() => stub.writesTo(/challans\/ch-1\/returns$/).length === 1, "the lot to be recorded once the challan is not after the day the goods came back");
      const body = JSON.parse(stub.writesTo(/challans\/ch-1\/returns$/)[0].body);
      assert.equal(body.returned_on, "2026-06-12", "the lot was recorded for another came-back day than the one typed");
      assert.equal(body.job_worker_challan_date, "2026-06-12", "the lot was recorded with another challan day than the one typed");
      assert.equal(await sentence("12 Jun 2026", "10 Jun 2026").count(), 0, "the sentence stayed after the days agreed");

      // The other order: the came-back day first, the challan's after it.
      await openLot();
      await typeAndLeaveNow(cameBack, "10/06/2026");
      await typeAndLeaveNow(challanDate, "12/06/2026");
      await press("a challan day typed after the came-back day", "12 Jun 2026", "10 Jun 2026");
      // The day the goods came back is moved later than the challan's, and the lot is recorded again.
      await typeAndLeaveNow(cameBack, "15/06/2026");
      stub.forgetWrites();
      await record.click();
      await until(() => stub.writesTo(/challans\/ch-1\/returns$/).length === 1, "the lot to be recorded when the came-back day was moved past the challan's");
    },
  },
  {
    id: "ageing-an-older-answer-never-paints-over-the-newer",
    title: "Reports > Ageing schedules: the schedule for a date the box no longer holds, answered last, is not drawn over the schedule for the date it holds",
    async run(env) {
      const { page, stub, context } = env;
      await context.clock.setFixedTime(new Date(INDIA_IS_ALREADY_TOMORROW));
      permissions(stub, { accounting: ["read", "write", "approve"], report: ["read"], client: ["read", "write"] });
      // The first reading (whatever day the screen starts from) is slow; the one for the date typed meanwhile is quick, so the OLDER answer arrives last. The quick route is registered last,
      // so it is tried first and takes only the date typed; every other date is slow.
      const tagged = (word) => ({ ...AGEING_SCHEDULE, receivables: AGEING_TABLE(`Trade receivables ageing ${word}`) });
      stub.route({ method: "GET", re: /api\/accounting\/schedule-iii\/ageing\?/, delay: 2000, reply: () => ok(tagged("OLD")) });
      stub.route({ method: "GET", re: /api\/accounting\/schedule-iii\/ageing\?.*as_of=2026-09-15/, reply: () => ok(tagged("NEW")) });
      await page.goto(env.at("/reports/ageing/"), { waitUntil: "domcontentloaded" });
      const box = page.locator("#ageing-as-at");
      await box.waitFor();
      await typeAndLeaveNow(box, "15/09/2026");
      await page.getByText("Trade receivables ageing NEW").first().waitFor({ timeout: 4000 });
      // The slow answer for 9 October lands now; it must not replace the one on screen.
      await page.waitForTimeout(2600);
      assert.equal(await page.getByText("Trade receivables ageing OLD").count(), 0, "the schedule for the date the box no longer holds was drawn over the newer one");
      assert.ok(await page.getByText("Trade receivables ageing NEW").count() >= 1, "the schedule for the date in the box is no longer on the screen");
    },
  },
  {
    id: "overdue-interest-an-older-answer-never-paints-over-the-newer",
    title: "Sales > Overdue Interest: the table for a date the box no longer holds, answered last, is not drawn over the table for the date it holds, and Prepare opens",
    async run(env) {
      const { page, stub, context } = env;
      await context.clock.setFixedTime(new Date(INDIA_IS_ALREADY_TOMORROW));
      permissions(stub, { sales: ["read", "write"] });
      const tagged = (asOf, word) => {
        const r = INTEREST_PREVIEW(asOf);
        r.data.parties[0].customer_name = `Beta Stores ${word}`;
        return r;
      };
      // The first reading (whatever day the panel starts from) is slow; the date typed meanwhile is quick. The quick route is registered last, so it is tried first.
      stub.route({ method: "GET", re: /api\/late-interest\/preview\?/, delay: 2000, reply: (_req, _raw, url) => tagged(url.searchParams.get("as_of"), "OLD") });
      stub.route({ method: "GET", re: /api\/late-interest\/preview\?.*as_of=2026-09-15/, reply: () => tagged("2026-09-15", "NEW") });
      stub.route({ method: "GET", re: /api\/late-interest\/terms\?/, reply: () => ok({ customers: [] }) });
      await page.goto(env.at("/sales/?tab=interest"), { waitUntil: "domcontentloaded" });
      const box = page.locator("#overdue-as-at");
      await box.waitFor();
      await typeAndLeaveNow(box, "15/09/2026");
      await page.getByText("Beta Stores NEW").first().waitFor({ timeout: 4000 });
      await page.waitForTimeout(2600);
      assert.equal(await page.getByText("Beta Stores OLD").count(), 0, "the table for the date the box no longer holds was drawn over the newer one");
      const prepare = page.getByRole("button", { name: "Prepare draft invoice" }).first();
      assert.equal(await prepare.isDisabled(), false, "Prepare stayed held over a table that is the box's date (the older answer set the date the table is for)");
    },
  },
  {
    id: "bill-form-15ca-is-sent-where-it-is-drawn-and-a-failed-reading-keeps-what-was-typed",
    title: "Purchases > bill editor: the Form 15CA acknowledgement typed in the block is sent while the block is drawn, including when the section 195 reading FAILED, and is not sent once the server says the bill does not withhold under section 195",
    async run(env) {
      const { page, stub } = env;
      const preview195 = { taxable_amount_paise: 100000, total_paise: 118000, total_gst_paise: 18000, tds_paise: 20800, tds_rate_bps: 2000, tds_section: "195", tds_surcharge_paise: 0, tds_cess_paise: 800,
        tds_nature_of_income: "Fees for technical services", tds_basis: "Part II of the First Schedule", tds_citation: "s.195", tds_shortfall_paise: 0, net_payable_paise: 97200,
        txn_currency: "INR", txn_total: 1180, txn_net_payable: 972 };
      const open = async () => {
        stub.setTable("vendors", [{ ...VENDOR, tds_applicable: true, tds_section: "195", tds_rate_bps: 2000 }]);
        stub.route({ method: "POST", re: /purchase-bills\/tds-preview/, reply: () => ok(preview195) });
        stub.route({ method: "POST", re: /purchase-bills\/$/, reply: () => ok({ id: "b-new" }) });
        await page.goto(env.at("/purchases/bills/new/edit/"), { waitUntil: "networkidle" });
        await pick(page, page.locator('button[aria-label="Vendor"]'), "Gamma Supplies");
        await page.fill('input[placeholder="INV-001"]', "GS/2026/114");
        await pick(page, page.locator('button[aria-label="Line 1 product or service"]'), "Consulting");
        await page.getByLabel("Line 1 rate", { exact: true }).fill("1000");
        await page.locator("#bill-15ca-date").waitFor({ timeout: 10000 });
        await page.getByLabel("Form 15CA acknowledgement no.").fill("ACK-777");
      };
      const saveDraft = page.getByRole("button", { name: "Save Draft" });
      const sentAck = async () => {
        await until(() => stub.writesTo(/purchase-bills\/$/).length === 1, "the bill to be saved");
        return JSON.parse(stub.writesTo(/purchase-bills\/$/)[0].body).form_15ca_ack_no;
      };

      // The reading FAILS after the acknowledgement was typed (a line changes and the preview cannot be worked out): the block and what is in it stay, and the bill is saved with it.
      await open();
      stub.route({ method: "POST", re: /purchase-bills\/tds-preview/, reply: () => ({ success: false, data: null, error: "The TDS on this bill could not be computed." }) });
      await page.getByLabel("Line 1 rate", { exact: true }).fill("1100");
      await page.getByText("The TDS on this bill could not be computed.").first().waitFor({ timeout: 6000 });
      const ackBox = page.getByLabel("Form 15CA acknowledgement no.");
      assert.equal(await ackBox.inputValue(), "ACK-777", "a failed reading took the block (and the acknowledgement typed in it) away");
      // The next edit starts a NEW reading (the preview clears its error when it starts again, and its answer is already gone): the block must not vanish while that reading is out...
      await page.getByLabel("Line 1 rate", { exact: true }).fill("1150");
      assert.equal(await ackBox.count(), 1, "the block vanished while the reading was out again after it failed");
      // ...nor when the last character of the acknowledgement is deleted (the box would unmount under the cursor and could not be typed in again).
      await ackBox.fill("");
      assert.equal(await ackBox.count(), 1, "the block vanished when the acknowledgement was emptied while the reading was in error");
      await ackBox.fill("ACK-888");
      // Saved at once, with the reading still out: what is drawn is sent.
      stub.forgetWrites();
      await saveDraft.click();
      assert.equal(await sentAck(), "ACK-888", "the acknowledgement typed in the drawn block was not sent after the reading failed");

      // The server SAYS the bill does not withhold under section 195 (another section): the block goes, and what was typed in it is not sent with a bill it no longer belongs to.
      await open();
      stub.route({ method: "POST", re: /purchase-bills\/tds-preview/, reply: () => ok({ ...preview195, tds_section: "194J", tds_rate_bps: 1000 }) });
      await page.getByLabel("Line 1 rate", { exact: true }).fill("1200");
      await page.locator("#bill-15ca-date").waitFor({ state: "detached", timeout: 6000 })
        .catch(() => { throw new Error("the block stayed after the server said the bill does not withhold under section 195"); });
      stub.forgetWrites();
      await saveDraft.click();
      assert.equal(await sentAck(), undefined, "the acknowledgement was sent with a bill whose block is no longer drawn");
    },
  },
];
