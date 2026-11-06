/**
 * THE NINE WRITES THAT DROPPED THEIR ANSWER (POST-A-391). On a client's MCA, TDS and GST compliance pages nine writes were `await apiFetch(…)` with nothing reading what came back: the KYC
 * change of a director and the status change of a filing (MCA); the creation of a TDS return, a TDS return's status change and the save of a statement computed from the books (TDS); the
 * creation of a GSTR-1 and of a GSTR-3B and the save of each computed from the books (GST). A server that refused (these routers answer a refusal as an HTTP 200 with success false, or as a 4xx)
 * changed nothing on a row, which looked like a button that does nothing; or closed the form or the dialog as though it had saved, which looked like a return that existed and did not.
 *
 * Every scenario here has the stub go wrong THREE ways (success false; a 404 whose body is a detail; an answer that is not JSON, so the page's own catch is reached) and asserts what the person sees:
 * the sentence, drawn as an alert the person can reach; a row left as it was and a list not read again; a form or dialog still open with what was typed (or computed) still in it, and still usable
 * after a failure. Then the stub accepts: the LAST sentence shown goes (a row action: while the next press is still out, and not only when the list is read again) and the list is read again, or
 * the form closes (the create and the save); and after a refusal Cancel closes the form, and the form opened again holds none of the last attempt's sentences. Where the sentence is drawn in the
 * page (inside the form that raised it, above the table for a row action) is held by the source guard; here it is proved to be on screen and reachable. The refusals' sentences are the routers' own,
 * word for word (tests/test_the_drives_filing_sentences_are_the_servers.py).
 * No scenario has a date, so none has a zone: they are their own group and run every night.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";
import { ok, refuse, notJson } from "../stub.mjs";
import { CLIENT_ID } from "../fixtures.mjs";

export const group = "compliance-answers";

/** What the MCA doors say when their body fails (routers/mca_workspace.py): an HTTP 200 with success false. */
const MCA_COULD_NOT_SENTENCE = "Unable to complete MCA operation. Please try again.";
/** What the GST doors say when their body fails (routers/gst_workspace.py): an HTTP 200 with success false. */
const GST_COULD_NOT_SENTENCE = "Unable to complete GST operation. Please try again.";
/** What the TDS doors say for a failure nobody anticipated (routers/tds_workspace.py `_could_not`): an HTTP 200 with success false. */
const TDS_COULD_NOT_STATUS_SENTENCE = "Could not update the TDS return status. The cause has been logged; please try again, and report it if it keeps failing.";
/** What the TDS door says when the save of a quarter's statement fails (routers/tds_workspace.py `create_return`): an HTTP 200 with success false. */
const TDS_COULD_NOT_SAVE_SENTENCE = "Could not save Form 26Q for Q1 FY 2025-26. The cause has been logged; please try again, and report it if it keeps failing.";
/** What `assert_client_access` raises (HTTP 404, core/authz.py) for a client the caller is not assigned to. */
const CLIENT_NOT_FOUND_SENTENCE = "Not found";
const GSTIN_OF_THE_CLIENT = "27AAACA1234A1ZK";

/** The wording of the browser's own error for a body it cannot read as JSON (Chromium: `Unexpected token '<', "<html><bod"... is not valid JSON`). */
const JSON_WORDS = /JSON/i;

/** The three ways a request goes wrong, and the sentence each puts on the screen: a string is the whole sentence, a pattern is part of the browser's own wording. */
const WAYS = [
  { name: "answers success false", route: (sentence) => ({ reply: () => ({ success: false, data: null, error: sentence }) }), says: (spec) => spec.refusal },
  { name: "refuses with a status", route: () => refuse(CLIENT_NOT_FOUND_SENTENCE, 404), says: () => CLIENT_NOT_FOUND_SENTENCE },
  // A proxy's error page that arrives with a 200: `res.json()` throws and the handler's own catch says so. The payroll page reads such a body as nothing, and says its own sentence.
  { name: "answers something that is not JSON", route: () => notJson(), says: (spec) => spec.unreadable ?? JSON_WORDS },
];

/** A sentence as the whole text of an alert (a substring would let "Not found" be satisfied by any longer alert that contains it); a pattern is used as it is. */
const exactly = (sentence) => (sentence instanceof RegExp ? sentence : new RegExp(`^\\s*${sentence.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*$`));
const alertsSaying = (page, sentence) => page.getByRole("alert").filter({ hasText: exactly(sentence) });

/** The sentence, drawn as an alert the person can reach (a trial click fails if something is drawn over it). */
async function alertSays(page, sentence, what) {
  const loc = alertsSaying(page, sentence).first();
  await loc.waitFor({ timeout: 4000 }).catch(() => { throw new Error(`${what}: "${sentence}"`); });
  await loc.click({ trial: true, timeout: 1500 }).catch((e) => {
    throw new Error(`${what} where the person can reach it: "${sentence}" is drawn behind something (${String(e.message).split("\n")[0].slice(0, 120)})`);
  });
}

/** Every sentence any of the three ways can have put on the screen for this spec: none of them may be there after the next press has begun or the form is opened again. */
async function assertNoSentenceOfAnyWay(page, spec, when) {
  for (const way of WAYS) {
    const sentence = way.says(spec);
    assert.equal(await alertsSaying(page, sentence).count(), 0, `${spec.what}: "${sentence}" (it ${way.name}) was still on the screen ${when}`);
  }
}

/** A counter for the reads of one list, so "the list was read again" can be asked. */
function counter() {
  let n = 0;
  return { hit: () => { n += 1; }, count: () => n };
}

// ── the screens ──────────────────────────────────────────────────────────────────────────────────────────────

async function atMca(env, { directors = [], filings = [] } = {}) {
  const { page, stub } = env;
  const reads = counter();
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { mca: ["read", "write", "approve"] } }) });
  stub.route({ method: "GET", re: /mca-workspace\/directors\?client_id=/, reply: () => { reads.hit(); return ok(directors); } });
  stub.route({ method: "GET", re: /mca-workspace\/filings\?client_id=/, reply: () => { reads.hit(); return ok(filings); } });
  stub.setTable("mca_companies", []);
  await page.goto(`${env.base}/clients/${CLIENT_ID}/compliance/mca/`, { waitUntil: "networkidle" });
  return reads;
}

async function openMcaDirectors(env) {
  const reads = await atMca(env, { directors: [{ id: "md-1", client_id: CLIENT_ID, din: "01234567", director_name: "Asha Rao", designation: "Director", date_of_appointment: "2025-04-01", kyc_status: "pending" }] });
  await env.page.getByRole("button", { name: "Directors", exact: true }).click();
  await env.page.getByText("Asha Rao", { exact: true }).waitFor();
  return reads;
}

async function openMcaFilings(env) {
  const reads = await atMca(env, { filings: [{ id: "mf-1", client_id: CLIENT_ID, category: "annual", form_type: "AOC-4", financial_year: "2025-26", due_date: "2026-10-30", status: "not_started" }] });
  await env.page.getByRole("button", { name: "Annual Filings", exact: true }).click();
  await env.page.getByText("AOC-4", { exact: true }).first().waitFor();
  return reads;
}

async function atTds(env, returns = []) {
  const { page, stub } = env;
  const reads = counter();
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { tds: ["read", "write", "compute", "approve"] } }) });
  stub.route({ method: "GET", re: /api\/tds-workspace\/returns\?/, reply: () => { reads.hit(); return ok({ returns, has_more: false, limit: 200, max_limit: 200 }); } });
  await page.goto(env.at("/compliance/tds/"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Returns", exact: true }).click();
  await page.getByRole("heading", { name: "TDS Returns", exact: true }).waitFor();
  return reads;
}

async function openTdsReturnsWithOne(env) {
  return atTds(env, [{ id: "tr-1", client_id: CLIENT_ID, return_type: "26Q", statement_form: "Form 26Q", quarter: "Q1", financial_year: "2025-26", due_date: "2025-07-31", status: "pending" }]);
}

async function openTdsNewReturn(env) {
  const reads = await atTds(env);
  await env.page.getByRole("button", { name: "+ New Return", exact: true }).click();
  await env.page.getByLabel("Financial year (for example 2025-26)", { exact: true }).fill("2025-26");
  return reads;
}

async function openTdsCompute(env) {
  const reads = await atTds(env);
  const { page, stub } = env;
  stub.route({ method: "POST", re: /api\/tds\/26q\/from-books$/, reply: (_req, raw) => ok({
    form: "26Q", tan: "MUMA12345B", deductor_name: "Acme Traders Pvt Ltd", financial_year: JSON.parse(raw).financial_year, quarter: JSON.parse(raw).quarter,
    quarter_end_date: "2025-06-30", total_tds_deducted_paise: 1000000, total_tds_deposited_paise: 1000000, deductee_count: 1,
    deductees: [], challans: [], validation_errors: [], warnings: [], challan_gaps: [],
    reconciliation: { matched: true, account_found: true } }) });
  await page.getByRole("button", { name: "Compute from Books", exact: true }).first().click();   // the header's; an empty list offers one too
  await page.getByLabel("Financial year (for example 2025-26)", { exact: true }).fill("2025-26");
  await page.getByLabel("TAN (10 characters)", { exact: true }).fill("MUMA12345B");
  await page.getByLabel("Deductor name", { exact: true }).fill("Acme Traders Pvt Ltd");
  await page.getByLabel("Deductor PAN", { exact: true }).fill("AAACA1234A");
  await page.getByRole("button", { name: "Compute", exact: true }).click();
  await page.getByRole("button", { name: "Save as Draft", exact: true }).waitFor();
  return reads;
}

async function atGst(env, tab) {
  const { page, stub } = env;
  const reads = counter();
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { gst: ["read", "write", "approve", "compute"] } }) });
  stub.route({ method: "GET", re: /api\/gst-workspace\/returns\?/, reply: () => { reads.hit(); return ok({ gstr1: [], gstr3b: [] }); } });
  stub.route({ method: "GET", re: /client-gst-registrations\/kinds$/, reply: () => ok({
    registration_types: [{ value: "regular", files_gstr1_and_3b: true, files_cmp08: false, files_gstr8: false, files_gstr4_annual: false, other_return_form: null }],
    composition_categories: [], filing_frequencies: ["monthly", "quarterly"], composition_rates_verified: false }) });
  stub.route({ method: "GET", re: /client-gst-registrations\?/, reply: () => ok([
    { id: null, gstin: GSTIN_OF_THE_CLIENT, state_code: "27", registration_type: "regular", filing_frequency: "monthly", is_primary: true, trade_name: null,
      effective_from: null, effective_to: null, label: "Maharashtra (primary)", files_gstr1_and_3b: true, files_cmp08: false, files_gstr8: false, files_gstr4_annual: false }]) });
  await page.goto(env.at("/compliance/gst/"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: tab, exact: true }).click();
  await page.getByRole("button", { name: "Compute from Books", exact: true }).first().waitFor();
  return reads;
}

async function openGstNew(env, tab, heading, periodLabel) {
  const reads = await atGst(env, tab);
  await env.page.getByRole("button", { name: `+ New ${tab}`, exact: true }).click();
  await env.page.getByLabel(periodLabel, { exact: true }).fill("092026");
  await env.page.getByRole("button", { name: "Save Draft", exact: true }).waitFor();
  return reads;
}

async function openGstCompute(env, tab, periodLabel, fromBooks, resultBody) {
  const reads = await atGst(env, tab);
  const { page, stub } = env;
  stub.route({ method: "POST", re: fromBooks, reply: (_req, raw) => ok({ period: JSON.parse(raw).period, gstin: GSTIN_OF_THE_CLIENT, ...resultBody }) });
  await page.getByRole("button", { name: "Compute from Books", exact: true }).first().click();
  await page.getByLabel(periodLabel, { exact: true }).fill("092026");
  await page.getByRole("button", { name: "Compute", exact: true }).click();
  await page.getByRole("button", { name: "Save as Draft", exact: true }).waitFor();
  return reads;
}

// Opening the same form AGAIN after a Cancel (the sentence of the last attempt must not be there). A compute dialog is computed again, because the sentence of a refused save lives in the
// result that is saved.
async function reopenTdsNewReturn(env) {
  await env.page.getByRole("button", { name: "+ New Return", exact: true }).click();
  await env.page.getByLabel("Financial year (for example 2025-26)", { exact: true }).waitFor();
}

async function reopenTdsCompute(env) {
  await env.page.getByRole("button", { name: "Compute from Books", exact: true }).first().click();
  await env.page.getByRole("button", { name: "Compute", exact: true }).click();
  await env.page.getByRole("button", { name: "Save as Draft", exact: true }).waitFor();
}

async function reopenGstNew(env, tab, periodLabel) {
  await env.page.getByRole("button", { name: `+ New ${tab}`, exact: true }).click();
  await env.page.getByLabel(periodLabel, { exact: true }).waitFor();
}

async function reopenGstCompute(env) {
  await env.page.getByRole("button", { name: "Compute from Books", exact: true }).first().click();
  await env.page.getByRole("button", { name: "Compute", exact: true }).click();
  await env.page.getByRole("button", { name: "Save as Draft", exact: true }).waitFor();
}

const GSTR1_RESULT = {
  payload: {}, summary: {}, invoice_count: 3, taxable_total_paise: 1000000, tax_total_paise: 180000, total_igst_paise: 0, total_cgst_paise: 90000, total_sgst_paise: 90000, total_cess_paise: 0,
  validation_errors: [], validation_warnings: [], payload_gaps: [], reconciliation: { reconciled: true, net_output_gst: { books_paise: 180000, ledger_paise: 180000, difference_paise: 0 } },
};
const GSTR3B_RESULT = {
  payload: {}, working: {}, tax_liability_paise: 180000, itc_claimed_paise: 100000, net_tax_paise: 80000, cash_payable_paise: 80000, rcm_cash_paise: 0, itc_carried_forward_paise: 0,
  reconciliation: { reconciled: true, output_gst: { ledger_paise: 180000, computed_paise: 180000 }, itc: { ledger_paise: 100000, computed_paise: 100000 } },
};

async function openPayrollPt(env) {
  const { page, stub } = env;
  const reads = counter();
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { payroll: ["read", "write", "approve"] } }) });
  stub.route({ method: "GET", re: /api\/payroll\/statutory-identity\?/, reply: () => { reads.hit(); return ok({
    identity: {}, fields: [], pt_registrations: [{ state: "MH", ptrc_number: "PTRC-MH-1", ptec_number: "PTEC-MH-1" }] }); } });
  await page.goto(env.at("/payroll/"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Setup", exact: true }).click();
  await page.getByText("PTRC-MH-1", { exact: true }).waitFor();
  return reads;
}

// ── the specs ────────────────────────────────────────────────────────────────────────────────────────────────

/** A control on a ROW or above a table: its answer is said above the table, the row stays as it was and the list is not read again over a refusal. */
const ROW_ACTIONS = [
  { id: "a-directors-kyc-change", what: "A client's MCA > Directors > Mark KYC Active", open: openMcaDirectors, button: "Mark KYC Active", method: "PATCH", write: /mca-workspace\/directors\/md-1$/, refusal: MCA_COULD_NOT_SENTENCE, rowId: "md-1" },
  { id: "a-filings-status-change", what: "A client's MCA > Annual Filings > Start", open: openMcaFilings, button: "Start", method: "PATCH", write: /mca-workspace\/filings\/mf-1\/status$/, refusal: MCA_COULD_NOT_SENTENCE, rowId: "mf-1" },
  { id: "a-tds-returns-status-change", what: "A client's TDS > Returns > Prepare", open: openTdsReturnsWithOne, button: "Prepare", method: "PATCH", write: /api\/tds-workspace\/returns\/tr-1\/status$/, refusal: TDS_COULD_NOT_STATUS_SENTENCE, rowId: "tr-1" },
  { id: "a-pt-registration-removal", what: "A client's Payroll > Setup > Professional tax registrations > Remove (the tenth write of this shape and the last in the app)", open: openPayrollPt, button: "Remove", method: "DELETE",
    write: /api\/payroll\/statutory-identity\/pt/, refusal: CLIENT_NOT_FOUND_SENTENCE, rowId: "MH",
    unreadable: "Couldn't remove the registration." },
];

/** A form or a dialog with a button that writes: its answer is said inside it, beside that button; over a refusal it stays open with what was typed or computed in it. */
const FORM_SAVES = [
  { id: "a-new-tds-return", what: "A client's TDS > Returns > + New Return", open: openTdsNewReturn, reopen: reopenTdsNewReturn, press: "Save", write: /api\/tds-workspace\/returns$/, refusal: TDS_COULD_NOT_SAVE_SENTENCE,
    stillOpen: (p) => p.getByText("New TDS Return", { exact: true }).count(), keeps: async (p) => assert.equal(await p.getByLabel("Financial year (for example 2025-26)", { exact: true }).inputValue(), "2025-26", "the year typed was lost") },
  { id: "a-tds-statement-computed-from-the-books", what: "A client's TDS > Returns > Compute from Books > Save as Draft", open: openTdsCompute, reopen: reopenTdsCompute, press: "Save as Draft", write: /api\/tds-workspace\/returns$/, refusal: TDS_COULD_NOT_SAVE_SENTENCE,
    stillOpen: (p) => p.getByRole("button", { name: "Save as Draft", exact: true }).count(), keeps: async (p) => assert.equal(await p.getByLabel("TAN (10 characters)", { exact: true }).inputValue(), "MUMA12345B", "the computed statement's form lost the TAN") },
  { id: "a-new-gstr1", what: "A client's GST > GSTR-1 > + New GSTR-1", open: (env) => openGstNew(env, "GSTR-1", "New GSTR-1", "New GSTR-1 return period (MMYYYY)"), reopen: (env) => reopenGstNew(env, "GSTR-1", "New GSTR-1 return period (MMYYYY)"), press: "Save Draft", write: /api\/gst-workspace\/gstr1$/, refusal: GST_COULD_NOT_SENTENCE,
    stillOpen: (p) => p.getByLabel("New GSTR-1 return period (MMYYYY)", { exact: true }).count(), keeps: async (p) => assert.equal(await p.getByLabel("New GSTR-1 return period (MMYYYY)", { exact: true }).inputValue(), "092026", "the period typed was lost") },
  { id: "a-gstr1-computed-from-the-books", what: "A client's GST > GSTR-1 > Compute from Books > Save as Draft", open: (env) => openGstCompute(env, "GSTR-1", "GSTR-1 return period to compute (MMYYYY)", /api\/gst\/gstr1\/from-books$/, GSTR1_RESULT), reopen: reopenGstCompute, press: "Save as Draft", write: /api\/gst-workspace\/gstr1$/, refusal: GST_COULD_NOT_SENTENCE,
    stillOpen: (p) => p.getByRole("button", { name: "Save as Draft", exact: true }).count(), keeps: async (p) => assert.equal(await p.getByLabel("GSTR-1 return period to compute (MMYYYY)", { exact: true }).inputValue(), "092026", "the computed return's period was lost") },
  { id: "a-new-gstr3b", what: "A client's GST > GSTR-3B > + New GSTR-3B", open: (env) => openGstNew(env, "GSTR-3B", "New GSTR-3B", "New GSTR-3B return period (MMYYYY)"), reopen: (env) => reopenGstNew(env, "GSTR-3B", "New GSTR-3B return period (MMYYYY)"), press: "Save Draft", write: /api\/gst-workspace\/gstr3b$/, refusal: GST_COULD_NOT_SENTENCE,
    stillOpen: (p) => p.getByLabel("New GSTR-3B return period (MMYYYY)", { exact: true }).count(), keeps: async (p) => assert.equal(await p.getByLabel("New GSTR-3B return period (MMYYYY)", { exact: true }).inputValue(), "092026", "the period typed was lost") },
  { id: "a-gstr3b-computed-from-the-books", what: "A client's GST > GSTR-3B > Compute from Books > Save as Draft", open: (env) => openGstCompute(env, "GSTR-3B", "GSTR-3B return period to compute (MMYYYY)", /api\/gst\/gstr3b\/from-books$/, GSTR3B_RESULT), reopen: reopenGstCompute, press: "Save as Draft", write: /api\/gst-workspace\/gstr3b$/, refusal: GST_COULD_NOT_SENTENCE,
    stillOpen: (p) => p.getByRole("button", { name: "Save as Draft", exact: true }).count(), keeps: async (p) => assert.equal(await p.getByLabel("GSTR-3B return period to compute (MMYYYY)", { exact: true }).inputValue(), "092026", "the computed return's period was lost") },
];


/** A statement computed for one form is not saved as another (found by the independent read of POST-A-391): the boxes that choose the statement (the form, the quarter, the year) are held while a
 *  compute is out, and changing one empties the computed result, so there is nothing of the old choice left to save under the new one. */
const COMPUTE_CHOICE = {
  id: "a-tds-statement-computed-for-one-form-cannot-be-saved-as-another",
  title: "A client's TDS > Returns > Compute from Books: the boxes that choose the statement are held while a compute is out, and changing one empties the computed result",
  async run(env) {
    const { page, stub } = env;
    await atTds(env);
    stub.route({ method: "POST", re: /api\/tds\/26q\/from-books$/, delay: 1200, reply: (_req, raw) => ok({
      form: "26Q", tan: "MUMA12345B", deductor_name: "Acme Traders Pvt Ltd", financial_year: JSON.parse(raw).financial_year, quarter: JSON.parse(raw).quarter,
      quarter_end_date: "2025-06-30", total_tds_deducted_paise: 1000000, total_tds_deposited_paise: 1000000, deductee_count: 1,
      deductees: [], challans: [], validation_errors: [], warnings: [], challan_gaps: [],
      reconciliation: { matched: true, account_found: true } }) });
    await page.getByRole("button", { name: "Compute from Books", exact: true }).first().click();
    await page.getByLabel("Financial year (for example 2025-26)", { exact: true }).fill("2025-26");
    await page.getByLabel("TAN (10 characters)", { exact: true }).fill("MUMA12345B");
    await page.getByLabel("Deductor name", { exact: true }).fill("Acme Traders Pvt Ltd");
    await page.getByLabel("Deductor PAN", { exact: true }).fill("AAACA1234A");
    const type = page.getByLabel("Return type", { exact: true });
    const quarter = page.getByLabel("Quarter", { exact: true });
    const year = page.getByLabel("Financial year (for example 2025-26)", { exact: true });
    await page.getByRole("button", { name: "Compute", exact: true }).click();
    // while the compute is out the three boxes are held: a late answer cannot land on a choice it was not computed for
    await until(async () => await type.isDisabled(), "the Return type box to be held while the compute is out");
    assert.equal(await quarter.isDisabled(), true, "the Quarter box was live while the compute was out");
    assert.equal(await year.isDisabled(), true, "the year box was live while the compute was out");
    const save = page.getByRole("button", { name: "Save as Draft", exact: true });
    await save.waitFor();
    assert.equal(await type.isDisabled(), false, "the Return type box stayed held after the compute came back");
    // choosing another form empties the result: there is no 26Q statement left to save as a 24Q one
    stub.forgetWrites();
    await type.selectOption("24Q");
    await until(async () => (await save.count()) === 0, "the computed 26Q statement to go when the Return type was changed to 24Q");
    await quarter.selectOption("Q3");
    assert.equal(await save.count(), 0, "a statement was offered for saving after the form was changed");
    assert.equal(stub.writesTo(/api\/tds-workspace\/returns$/).length, 0, "a request to save went out for a statement that was computed for another form");
  },
};

export const scenarios = [
  ...ROW_ACTIONS.map((spec) => ({
    id: `${spec.id}-says-a-refusal-above-the-table-and-changes-nothing`,
    title: `${spec.what}: when the server refuses (success false, or a status) its sentence is said above the table, the row is as it was and the list is not read again; accepted, the sentence goes and the list is read again`,
    async run(env) {
      const { page, stub } = env;
      const reads = await spec.open(env);
      const button = page.getByRole("button", { name: spec.button, exact: true });
      await button.waitFor();
      for (const way of WAYS) {
        stub.route({ method: spec.method, re: spec.write, ...way.route(spec.refusal) });
        stub.forgetWrites();
        const before = reads.count();
        await button.click();
        await alertSays(page, way.says(spec), `${spec.what}: the request went wrong (it ${way.name}) and was not said`);
        await stub.quiet();
        assert.equal(stub.writesTo(spec.write).length, 1, `${spec.what}: expected the one refused request (it ${way.name})`);
        assert.equal(await button.count(), 1, `${spec.what}: the row's button went away over a refusal (it ${way.name}), as though it had worked`);
        assert.equal(reads.count(), before, `${spec.what}: the list was read again over a refusal (it ${way.name})`);
      }
      // The next press is accepted, slowly: the sentence of the LAST refusal (it is the one on the screen) must be gone while this request is still out, and not only when the list is
      // read again after it (a screen that kept it until the reload said a thing about a press that was over).
      stub.route({ method: spec.method, re: spec.write, delay: 1500, reply: () => ok({ id: spec.rowId }) });
      stub.forgetWrites();
      const before = reads.count();
      await button.click();
      await until(async () => (await alertsSaying(page, WAYS[WAYS.length - 1].says(spec)).count()) === 0, `${spec.what}: the last sentence was still on the screen while the next press was out`);
      assert.equal(reads.count(), before, `${spec.what}: the last sentence went only when the list was read again, not when the next press began`);
      await until(() => reads.count() > before, `${spec.what}: the list was not read again after the server accepted the change`);
      await assertNoSentenceOfAnyWay(page, spec, "after the change was accepted");
    },
  })),
  ...FORM_SAVES.map((spec) => ({
    id: `${spec.id}-says-a-refusal-inside-and-stays-open`,
    title: `${spec.what}: when the server refuses (success false, or a status) its sentence is said inside the form, which stays open with what was typed or computed; Cancel starts the next one clean; accepted, the form closes`,
    async run(env) {
      const { page, stub } = env;
      const reads = await spec.open(env);
      const press = page.getByRole("button", { name: spec.press, exact: true });
      for (const way of WAYS) {
        stub.route({ method: "POST", re: spec.write, ...way.route(spec.refusal) });
        stub.forgetWrites();
        await press.click();
        await alertSays(page, way.says(spec), `${spec.what}: the server's refusal (it ${way.name}) was not said`);
        await stub.quiet();
        assert.equal(stub.writesTo(spec.write).length, 1, `${spec.what}: expected the one refused request (it ${way.name})`);
        assert.ok(await spec.stillOpen(page) >= 1, `${spec.what}: the form closed over a refusal (it ${way.name}), as though it had saved`);
        await spec.keeps(page);
      }
      // Cancel after a refusal closes the form; the form opened AGAIN holds nothing of the last attempt's sentences (a compute dialog is computed again, because its sentence lives in the
      // result it saves).
      await page.getByRole("button", { name: "Cancel", exact: true }).first().click();
      await until(async () => (await spec.stillOpen(page)) === 0, `${spec.what}: Cancel did not close the form`);
      await spec.reopen(env);
      assert.ok(await spec.stillOpen(page) >= 1, `${spec.what}: the form did not open again`);
      await assertNoSentenceOfAnyWay(page, spec, "when the form was opened again after a Cancel");
      // …and a failure left it usable: this time the server accepts and the form closes.
      stub.route({ method: "POST", re: spec.write, reply: () => ok({ id: "new-1" }) });
      stub.forgetWrites();
      await press.click();
      await until(async () => (await spec.stillOpen(page)) === 0, `${spec.what}: the form stayed open after the server accepted it, following refusals`);
    },
  })),
  ...FORM_SAVES.map((spec) => ({
    id: `${spec.id}-closes-when-the-server-accepts`,
    title: `${spec.what}: when the server accepts, the form closes and the list is read again`,
    async run(env) {
      const { page, stub } = env;
      const reads = await spec.open(env);
      stub.route({ method: "POST", re: spec.write, reply: () => ok({ id: "new-1" }) });
      stub.forgetWrites();
      const before = reads.count();
      await page.getByRole("button", { name: spec.press, exact: true }).click();
      await until(async () => (await spec.stillOpen(page)) === 0, `${spec.what}: the form stayed open after the server accepted it`);
      await until(() => reads.count() > before, `${spec.what}: the list was not read again after the server accepted it`);
      await stub.quiet();
      assert.equal(stub.writesTo(spec.write).length, 1, `${spec.what}: expected one request`);
    },
  })),
  COMPUTE_CHOICE,
];
