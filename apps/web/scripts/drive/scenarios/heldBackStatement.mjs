/**
 * A TDS STATEMENT THE PRODUCT HOLDS BACK IS RECORDED ONLY ON THE CA'S SECOND PRESS (POST-A-402), AND A COMPUTE THAT FAILS OUTRIGHT SAYS SO (POST-A-403).
 *
 * The server refuses to record a statement as CA approved or filed when it holds no deductees or its quarter has not ended, and says the CA may record it anyway: its answer is a refusal with a
 * marker (`can_record_anyway`) and the sentence for a person. The screens used to say that sentence as an error ("Resubmit with acknowledge_incomplete=true"), an instruction no screen could
 * follow. They ask now. Here, on the client's TDS tab and on the firm-level returns page (the approval, and the filing inside its dialog): the sentence is drawn as a question and not as a
 * failure, nothing goes out until the CA presses "Record it anyway", Leave sends nothing, and the request that follows carries the CA's confirmation and nothing before it does; a refusal without
 * the marker is still said as an error with no question; a refusal of the confirmed request is said and the question is gone.
 *
 * And the three compute dialogs (a TDS statement, GSTR-1, GSTR-3B) when the request fails outright: an answer that is not JSON used to leave the dialog on "Computing…" with Compute held until the
 * page was loaded again. Now the dialog says what went wrong, Compute is live again, and a second press works.
 *
 * The sentence is the server's, word for word (tests/test_the_drives_filing_sentences_are_the_servers.py). No scenario has a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { until, pick } from "../kit.mjs";
import { ok, notJson } from "../stub.mjs";
import { CLIENT_ID } from "../fixtures.mjs";

export const group = "held-back-statement";

/** What the status door says for a prepared statement that holds no deductees (routers/tds_workspace.py `_the_refusal`): an HTTP 200 with success false and the marker. */
const HELD_BACK_APPROVAL = "This return cannot be recorded as CA approved because it has no deductees recorded.";
const HELD_BACK_FILING = "This return cannot be recorded as filed because it has no deductees recorded.";
const MARKER = { can_record_anyway: true, incomplete: ["it has no deductees recorded"] };
/** A refusal that offers no way on (the door's sentence for a statement that is already filed). */
const ALREADY_FILED = "This return has already been filed.";
const GSTIN_OF_THE_CLIENT = "27AAACA1234A1ZK";
const JSON_WORDS = /JSON/i;

const STATUS_ROUTE = /api\/tds-workspace\/returns\/tr-1\/status$/;

/** The sentence as the whole text of an element (a substring would let a longer sentence satisfy it). */
const exactly = (text) => new RegExp(`^\\s*${text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*$`);

function counter() {
  let n = 0;
  return { hit: () => { n += 1; }, count: () => n };
}

const bodies = (stub) => stub.writesTo(STATUS_ROUTE).map((w) => JSON.parse(w.body));

// ── the client's TDS tab ─────────────────────────────────────────────────────

async function atTdsWithAPreparedReturn(env) {
  const { page, stub } = env;
  const reads = counter();
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { tds: ["read", "write", "compute", "approve"] } }) });
  stub.route({ method: "GET", re: /api\/tds-workspace\/returns\?/, reply: () => { reads.hit(); return ok({
    returns: [{ id: "tr-1", client_id: CLIENT_ID, return_type: "26Q", statement_form: "Form 26Q", quarter: "Q1", financial_year: "2025-26", due_date: "2025-07-31", status: "prepared" }],
    has_more: false, limit: 200, max_limit: 200 }); } });
  await page.goto(env.at("/compliance/tds/"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Returns", exact: true }).click();
  await page.getByRole("button", { name: "CA Approve", exact: true }).waitFor();
  return reads;
}

/** The status door as the server answers a statement with no deductees: the question the first time, the recording when the CA's confirmation is in the request. */
const heldBackUnlessConfirmed = (sentence, finalStatus) => ({
  method: "PATCH", re: STATUS_ROUTE,
  reply: (_req, raw) => {
    const b = JSON.parse(raw);
    return b.acknowledge_incomplete === true ? ok({ id: "tr-1", status: finalStatus }) : { success: false, data: MARKER, error: sentence };
  },
});

const clientTabAsks = {
  id: "a-held-back-tds-statement-is-asked-about-and-recorded-on-the-second-press",
  title: "A client's TDS > Returns > CA Approve on a statement with no deductees: the server's sentence is a question (not an error), nothing is sent until Record it anyway, Leave sends nothing, and the confirmed request carries the flag",
  async run(env) {
    const { page, stub } = env;
    const reads = await atTdsWithAPreparedReturn(env);
    stub.route(heldBackUnlessConfirmed(HELD_BACK_APPROVAL, "ca_approved"));
    stub.forgetWrites();
    const approve = page.getByRole("button", { name: "CA Approve", exact: true });
    const sentence = page.getByText(HELD_BACK_APPROVAL, { exact: true });
    const record = page.getByRole("button", { name: "Record it anyway", exact: true });
    const leave = page.getByRole("button", { name: "Leave it as it is", exact: true });
    const before = reads.count();

    // the first press: the sentence is asked about, and the request that went out carried no confirmation
    await approve.click();
    await sentence.waitFor({ timeout: 4000 });
    await record.waitFor();
    await leave.waitFor();
    await stub.quiet();
    assert.deepEqual(bodies(stub).map((b) => b.acknowledge_incomplete), [undefined], "the first press sent the CA's confirmation, or sent more than one request");
    assert.equal(bodies(stub)[0].status, "ca_approved");
    assert.equal(await page.getByRole("alert").filter({ hasText: exactly(HELD_BACK_APPROVAL) }).count(), 0, "the held-back sentence was drawn as an error paragraph");
    // …and it is ANNOUNCED: it replaces a refusal a screen reader used to be told about, and asks for an answer (the alert is the question, with its two buttons)
    assert.equal(await page.getByRole("alert").filter({ has: record }).count(), 1, "the question is not announced to a screen reader");
    assert.equal(reads.count(), before, "the list was read again over a question");
    assert.equal(await approve.count(), 1, "the row's button went away over a question, as though it had worked");

    // Leave: the question goes and nothing is sent
    await leave.click();
    await until(async () => (await sentence.count()) === 0, "the question to go when the CA left it as it is");
    await stub.quiet();
    assert.equal(bodies(stub).length, 1, "Leave sent a request");

    // the CA presses again, is asked again, and records it anyway: the request that follows carries the confirmation, and the list is read again
    await approve.click();
    await sentence.waitFor({ timeout: 4000 });
    await stub.quiet();
    assert.deepEqual(bodies(stub).map((b) => b.acknowledge_incomplete), [undefined, undefined], "a second first-press sent the confirmation");
    await record.click();
    await until(async () => (await sentence.count()) === 0, "the question to go once the CA had recorded it anyway");
    await stub.quiet();
    const sent = bodies(stub);
    assert.equal(sent.length, 3);
    assert.equal(sent[2].acknowledge_incomplete, true, "the confirmed request did not carry the CA's confirmation");
    assert.equal(sent[2].status, "ca_approved", "the confirmed request asked for another status than the one the question was about");
    await until(() => reads.count() > before, "the list to be read again after the statement was recorded");
  },
};

const clientTabOtherRefusals = {
  id: "a-tds-status-refusal-without-the-marker-is-an-error-and-a-refused-confirmation-says-so",
  title: "A client's TDS > Returns > CA Approve: a refusal that offers no way on is said as an error with no question; a confirmation the server refuses is said and the question is gone",
  async run(env) {
    const { page, stub } = env;
    await atTdsWithAPreparedReturn(env);
    const approve = page.getByRole("button", { name: "CA Approve", exact: true });
    const record = page.getByRole("button", { name: "Record it anyway", exact: true });
    // 1. a refusal nothing may be recorded over: an error, and no question
    stub.route({ method: "PATCH", re: STATUS_ROUTE, reply: () => ({ success: false, data: null, error: ALREADY_FILED }) });
    await approve.click();
    await page.getByRole("alert").filter({ hasText: exactly(ALREADY_FILED) }).first().waitFor({ timeout: 4000 });
    assert.equal(await record.count(), 0, "a refusal with no way on was drawn with a Record it anyway");
    // 2. a question whose confirmation is then refused: the sentence of the refusal is said and the question is not left standing
    stub.route({ method: "PATCH", re: STATUS_ROUTE, reply: (_req, raw) => (JSON.parse(raw).acknowledge_incomplete === true
      ? { success: false, data: null, error: ALREADY_FILED } : { success: false, data: MARKER, error: HELD_BACK_APPROVAL }) });
    await approve.click();
    await record.waitFor({ timeout: 4000 });
    assert.equal(await page.getByRole("alert").filter({ hasText: exactly(ALREADY_FILED) }).count(), 0, "the last error was still on the screen over the new question");
    await record.click();
    await page.getByRole("alert").filter({ hasText: exactly(ALREADY_FILED) }).first().waitFor({ timeout: 4000 });
    await until(async () => (await record.count()) === 0, "the question to go once its confirmation had been refused");
  },
};

// ── the firm-level returns page ──────────────────────────────────────────────

async function atFirmReturnsPageWithAComputedStatement(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { tds: ["read", "write", "approve", "compute"] } }) });
  stub.route({ method: "POST", re: /api\/tds\/26q\/from-books$/, reply: (_req, raw) => ok({
    form: "26Q", tan: "MUMA12345B", deductor_name: "Acme Traders Pvt Ltd", financial_year: JSON.parse(raw).financial_year, quarter: JSON.parse(raw).quarter,
    quarter_end_date: "2026-09-30", total_tds_deducted_paise: 0, total_tds_deposited_paise: 0, deductee_count: 0,
    deductees: [], challans: [], validation_errors: [], warnings: [] }) });
  stub.route({ method: "POST", re: /api\/tds-workspace\/returns$/, reply: () => ok({ id: "tr-1" }) });
  await page.goto(`${env.base}/tds/returns/`, { waitUntil: "networkidle" });
  await pick(page, page.locator('button[aria-label="Client"]'), "Acme Traders Pvt Ltd");
  await page.getByLabel("Quarter", { exact: true }).selectOption("Q2");           // Q2 of FY 2026-27 has ended at the pinned 8 October 2026
  await page.getByRole("button", { name: "Compute 26Q", exact: true }).click();
  await page.getByRole("button", { name: "CA Approve", exact: true }).waitFor();
}

const firmPageAsks = {
  id: "a-held-back-tds-statement-is-asked-about-on-the-firm-page-for-the-approval-and-for-the-filing",
  title: "TDS > Returns (firm): a statement with no deductees is asked about for its approval (beside the buttons, announced, gone with its statement) and for its filing (inside the dialog, which holds while the request is out and scrolls on a short screen); each is recorded only by Record it anyway, which sends the flag",
  async run(env) {
    const { page, stub } = env;
    await atFirmReturnsPageWithAComputedStatement(env);
    stub.route({ method: "PATCH", re: STATUS_ROUTE, reply: (_req, raw) => {
      const b = JSON.parse(raw);
      if (b.acknowledge_incomplete === true) return ok({ id: "tr-1", status: b.status });
      return { success: false, data: MARKER, error: b.status === "filed" ? HELD_BACK_FILING : HELD_BACK_APPROVAL };
    } });
    stub.forgetWrites();
    const approve = page.getByRole("button", { name: "CA Approve", exact: true });
    const record = page.getByRole("button", { name: "Record it anyway", exact: true });
    const leave = page.getByRole("button", { name: "Leave it as it is", exact: true });
    const question = page.getByText(HELD_BACK_APPROVAL, { exact: true });

    // the approval, on the page: asked, announced, and gone with the statement it was asked about
    await approve.click();
    await question.waitFor({ timeout: 4000 });
    await stub.quiet();
    assert.deepEqual(bodies(stub).map((b) => b.acknowledge_incomplete), [undefined], "the first press of CA Approve sent the CA's confirmation");
    assert.equal(await page.getByRole("alert").filter({ has: record }).count(), 1, "the approval question is not announced to a screen reader");
    await page.getByLabel("Quarter", { exact: true }).selectOption("Q3");
    await until(async () => (await question.count()) === 0, "the approval question to go with its statement when the quarter changed");
    assert.equal(await record.count(), 0, "a Record it anyway was left standing for a statement that is not on the screen");
    await page.getByLabel("Quarter", { exact: true }).selectOption("Q2");
    await page.getByRole("button", { name: "Compute 26Q", exact: true }).click();
    await approve.waitFor();
    stub.forgetWrites();

    // Leave sends nothing; the second press asks again; Record it anyway sends the flag
    await approve.click();
    await question.waitFor({ timeout: 4000 });
    await leave.click();
    await until(async () => (await question.count()) === 0, "the approval's question to go when the CA left it");
    assert.equal(bodies(stub).length, 1, "Leave sent a request");
    await approve.click();
    await record.waitFor({ timeout: 4000 });
    await record.click();
    await page.getByRole("button", { name: "Mark as Filed", exact: true }).waitFor({ timeout: 4000 });     // approved: the page now offers the filing
    const approvals = bodies(stub);
    assert.equal(approvals.length, 3);
    assert.equal(approvals[2].acknowledge_incomplete, true, "the confirmed approval did not carry the CA's confirmation");
    assert.equal(approvals[2].status, "ca_approved");

    // the filing, inside the dialog, on a SHORT screen: the dialog is 424 px tall and the question makes it 602 (measured), so on a screen under about 650 px
    // its bottom buttons left the page; it scrolls now. 440 px is the control: the first version's Cancel cannot be reached there with the question showing.
    await page.setViewportSize({ width: 1280, height: 440 });
    await page.getByRole("button", { name: "Mark as Filed", exact: true }).click();
    const dialog = page.locator("div.fixed.inset-0.z-50");                      // the Mark as Filed dialog (the only full-screen overlay the page opens)
    const confirmFiled = dialog.getByRole("button", { name: "Confirm Filed", exact: true });
    const cancel = dialog.getByRole("button", { name: "Cancel", exact: true });
    await page.getByLabel("PRN (Provisional Receipt Number)", { exact: true }).fill("PRN0000000001");
    await page.locator("#tds-filing-date").fill("07/10/2026");
    await page.locator("#tds-filing-date").press("Tab");                          // the box judges the day when it is left
    stub.forgetWrites();
    await confirmFiled.click();
    await dialog.getByText(HELD_BACK_FILING, { exact: true }).waitFor({ timeout: 4000 });
    await stub.quiet();
    const filed = bodies(stub);
    assert.deepEqual(filed.map((b) => b.acknowledge_incomplete), [undefined], "the first press of Confirm Filed sent the CA's confirmation");
    assert.equal(filed[0].status, "filed");
    assert.equal(await page.getByText(HELD_BACK_APPROVAL, { exact: true }).count(), 0, "the approval's question was still there");
    assert.equal(await page.getByRole("alert").filter({ has: record }).count(), 1, "the filing question is not announced to a screen reader");

    // Cancel, the BOTTOM button, with the question showing: reachable only if the dialog scrolls. The dialog opened again starts blank and asks nothing.
    await cancel.click({ timeout: 3000 });
    await until(async () => (await page.getByLabel("PRN (Provisional Receipt Number)", { exact: true }).count()) === 0, "the dialog to close on Cancel");
    await page.getByRole("button", { name: "Mark as Filed", exact: true }).click();
    assert.equal(await dialog.getByText(HELD_BACK_FILING, { exact: true }).count(), 0, "the dialog opened again still asked the last question");
    assert.equal(await page.getByLabel("PRN (Provisional Receipt Number)", { exact: true }).inputValue(), "", "the dialog opened again held the last PRN");
    await page.getByLabel("PRN (Provisional Receipt Number)", { exact: true }).fill("PRN0000000001");
    await page.locator("#tds-filing-date").fill("07/10/2026");
    await page.locator("#tds-filing-date").press("Tab");
    stub.forgetWrites();
    await confirmFiled.click();
    await dialog.getByText(HELD_BACK_FILING, { exact: true }).waitFor({ timeout: 4000 });

    // what the question would record is what was typed: a changed acknowledgement number drops it, and Confirm Filed asks again
    await page.getByLabel("Acknowledgement Number", { exact: true }).fill("ACK0001");
    await until(async () => (await dialog.getByText(HELD_BACK_FILING, { exact: true }).count()) === 0, "the filing question to go when the acknowledgement number changed");
    await confirmFiled.click();
    await dialog.getByText(HELD_BACK_FILING, { exact: true }).waitFor({ timeout: 4000 });

    // the confirmed request is slow: while it is out the dialog is held (the pressed button has gone, so nothing else would hold it)
    stub.route({ method: "PATCH", re: STATUS_ROUTE, delay: 1500, reply: (_req, raw) => ok({ id: "tr-1", status: JSON.parse(raw).status }) });
    stub.forgetWrites();
    await dialog.getByRole("button", { name: "Record it anyway", exact: true }).click();                // reaching it on a 560-px-high screen needs the dialog to scroll
    await until(async () => await confirmFiled.isDisabled(), "Confirm Filed to be held while the filing is being recorded");
    assert.equal(await cancel.isDisabled(), true, "Cancel was live while the filing was being recorded");
    await until(async () => (await page.getByLabel("PRN (Provisional Receipt Number)", { exact: true }).count()) === 0, "the dialog to close once the filing was recorded");
    await stub.quiet();
    const confirmed = bodies(stub);
    assert.equal(confirmed.length, 1);
    assert.equal(confirmed[0].acknowledge_incomplete, true, "the confirmed filing did not carry the CA's confirmation");
    assert.equal(confirmed[0].status, "filed");
    assert.equal(confirmed[0].prn, "PRN0000000001", "the confirmed filing lost the PRN the CA typed");
    assert.equal(confirmed[0].ack_number, "ACK0001", "the confirmed filing lost the acknowledgement number the CA typed");
    assert.equal(confirmed[0].filing_date, "2026-10-07", "the confirmed filing lost the date the CA stated");
  },
};

const lateRefusal = {
  id: "a-refusal-that-arrives-after-the-statement-has-gone-asks-nothing",
  title: "TDS > Returns (firm): CA Approve is pressed, the quarter is changed while the request is out, and the refusal that arrives afterwards (about a statement that is no longer on the screen) is not drawn as a question",
  async run(env) {
    const { page, stub } = env;
    await atFirmReturnsPageWithAComputedStatement(env);
    stub.route({ method: "PATCH", re: STATUS_ROUTE, delay: 1500, reply: () => ({ success: false, data: MARKER, error: HELD_BACK_APPROVAL }) });
    stub.forgetWrites();
    await page.getByRole("button", { name: "CA Approve", exact: true }).click();
    await page.getByLabel("Quarter", { exact: true }).selectOption("Q3");              // the statement is gone while its refusal is still out
    await stub.quiet();                                                                  // …and the refusal has now arrived
    await new Promise((resolve) => setTimeout(resolve, 400));
    assert.equal(bodies(stub).length, 1, "expected the one request that was out");
    assert.equal(await page.getByText(HELD_BACK_APPROVAL, { exact: true }).count(), 0, "a refusal about a statement that was gone was drawn as a question");
    assert.equal(await page.getByRole("button", { name: "Record it anyway", exact: true }).count(), 0, "a Record it anyway was left standing for a statement that is not on the screen");
  },
};

// ── a compute that fails outright ────────────────────────────────────────────

const TDS_RESULT = {
  form: "26Q", tan: "MUMA12345B", deductor_name: "Acme Traders Pvt Ltd", financial_year: "2025-26", quarter: "Q1", quarter_end_date: "2025-06-30",
  total_tds_deducted_paise: 1000000, total_tds_deposited_paise: 1000000, deductee_count: 1, deductees: [], challans: [], validation_errors: [], warnings: [], challan_gaps: [],
  reconciliation: { matched: true, account_found: true },
};
const GSTR1_RESULT = {
  payload: {}, summary: {}, invoice_count: 3, taxable_total_paise: 1000000, tax_total_paise: 180000, total_igst_paise: 0, total_cgst_paise: 90000, total_sgst_paise: 90000, total_cess_paise: 0,
  validation_errors: [], validation_warnings: [], payload_gaps: [], reconciliation: { reconciled: true, net_output_gst: { books_paise: 180000, ledger_paise: 180000, difference_paise: 0 } },
};
const GSTR3B_RESULT = {
  payload: {}, working: {}, tax_liability_paise: 180000, itc_claimed_paise: 100000, net_tax_paise: 80000, cash_payable_paise: 80000, rcm_cash_paise: 0, itc_carried_forward_paise: 0,
  reconciliation: { reconciled: true, output_gst: { ledger_paise: 180000, computed_paise: 180000 }, itc: { ledger_paise: 100000, computed_paise: 100000 } },
};

async function openTdsComputeDialog(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { tds: ["read", "write", "compute", "approve"] } }) });
  stub.route({ method: "GET", re: /api\/tds-workspace\/returns\?/, reply: () => ok({ returns: [], has_more: false, limit: 200, max_limit: 200 }) });
  await page.goto(env.at("/compliance/tds/"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Returns", exact: true }).click();
  await page.getByRole("heading", { name: "TDS Returns", exact: true }).waitFor();
  await page.getByRole("button", { name: "Compute from Books", exact: true }).first().click();
  await page.getByLabel("Financial year (for example 2025-26)", { exact: true }).fill("2025-26");
  await page.getByLabel("TAN (10 characters)", { exact: true }).fill("MUMA12345B");
  await page.getByLabel("Deductor name", { exact: true }).fill("Acme Traders Pvt Ltd");
  await page.getByLabel("Deductor PAN", { exact: true }).fill("AAACA1234A");
}

async function openGstComputeDialog(env, tab, periodLabel) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { gst: ["read", "write", "approve", "compute"] } }) });
  stub.route({ method: "GET", re: /api\/gst-workspace\/returns\?/, reply: () => ok({ gstr1: [], gstr3b: [] }) });
  stub.route({ method: "GET", re: /client-gst-registrations\/kinds$/, reply: () => ok({
    registration_types: [{ value: "regular", files_gstr1_and_3b: true, files_cmp08: false, files_gstr8: false, files_gstr4_annual: false, other_return_form: null }],
    composition_categories: [], filing_frequencies: ["monthly", "quarterly"], composition_rates_verified: false }) });
  stub.route({ method: "GET", re: /client-gst-registrations\?/, reply: () => ok([
    { id: null, gstin: GSTIN_OF_THE_CLIENT, state_code: "27", registration_type: "regular", filing_frequency: "monthly", is_primary: true, trade_name: null,
      effective_from: null, effective_to: null, label: "Maharashtra (primary)", files_gstr1_and_3b: true, files_cmp08: false, files_gstr8: false, files_gstr4_annual: false }]) });
  await page.goto(env.at("/compliance/gst/"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: tab, exact: true }).click();
  await page.getByRole("button", { name: "Compute from Books", exact: true }).first().click();
  await page.getByLabel(periodLabel, { exact: true }).fill("092026");
}

const COMPUTES = [
  { id: "a-tds-compute", what: "A client's TDS > Returns > Compute from Books", open: openTdsComputeDialog, route: /api\/tds\/26q\/from-books$/, result: TDS_RESULT },
  { id: "a-gstr1-compute", what: "A client's GST > GSTR-1 > Compute from Books", open: (env) => openGstComputeDialog(env, "GSTR-1", "GSTR-1 return period to compute (MMYYYY)"), route: /api\/gst\/gstr1\/from-books$/, result: GSTR1_RESULT },
  { id: "a-gstr3b-compute", what: "A client's GST > GSTR-3B > Compute from Books", open: (env) => openGstComputeDialog(env, "GSTR-3B", "GSTR-3B return period to compute (MMYYYY)"), route: /api\/gst\/gstr3b\/from-books$/, result: GSTR3B_RESULT },
];

const computeScenarios = COMPUTES.map((spec) => ({
  id: `${spec.id}-that-fails-outright-says-so-and-can-be-pressed-again`,
  title: `${spec.what}: an answer that is not JSON (a proxy's page that arrives as a 200) is said in the dialog as an alert, Compute is live again and not stuck on "Computing…", and a second press computes`,
  async run(env) {
    const { page, stub } = env;
    await spec.open(env);
    stub.route({ method: "POST", re: spec.route, ...notJson() });
    stub.forgetWrites();
    const compute = page.getByRole("button", { name: "Compute", exact: true });
    await compute.click();
    await page.getByRole("alert").filter({ hasText: JSON_WORDS }).first().waitFor({ timeout: 4000 });
    await stub.quiet();
    assert.equal(stub.writesTo(spec.route).length, 1, `${spec.what}: expected the one failed request`);
    assert.equal(await page.getByRole("button", { name: "Computing…", exact: true }).count(), 0, `${spec.what}: the dialog stayed on "Computing…" after the request failed`);
    assert.equal(await compute.isDisabled(), false, `${spec.what}: Compute stayed held after the request failed`);
    assert.equal(await page.getByRole("button", { name: "Save as Draft", exact: true }).count(), 0, `${spec.what}: a statement was offered for saving after the request failed`);
    // a second press computes (the stub answers properly now), and the sentence of the failure goes with the press
    stub.route({ method: "POST", re: spec.route, reply: (_req, raw) => ok({ ...spec.result, ...(JSON.parse(raw).period ? { period: JSON.parse(raw).period, gstin: GSTIN_OF_THE_CLIENT } : {}) }) });
    await compute.click();
    await page.getByRole("button", { name: "Save as Draft", exact: true }).waitFor({ timeout: 4000 });
    assert.equal(await page.getByRole("alert").filter({ hasText: JSON_WORDS }).count(), 0, `${spec.what}: the sentence of the failure stayed on the screen over a computed statement`);
  },
}));

export const scenarios = [clientTabAsks, clientTabOtherRefusals, firmPageAsks, lateRefusal, ...computeScenarios];
