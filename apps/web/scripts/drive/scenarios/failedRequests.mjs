/**
 * A REQUEST THAT FAILS OUTRIGHT IS SAID IN THE PRODUCT'S WORDS (POST-A-406, POST-A-405, POST-A-382). A proxy's page that arrives with a 200 used to reach the screen as the browser's own
 * `Unexpected token '<', "<html>…" is not valid JSON`; a dropped connection as `Failed to fetch`; a 422 from the income-tax doors as "Unprocessable Entity" over the sentence the server wrote.
 * The five GSTR-3B row actions (Validate and CA Approve, Mark as filed, Recheck, Recompute from books, Delete) released their hold in a `finally` and said NOTHING when the request threw, so a CA who
 * pressed Approve while the connection dropped saw a button that did nothing.
 *
 * A dropped connection cannot be driven (the runner does not allow the console error it leaves), so what a page that is not JSON says stands for it here, and the words of each engine for a dropped
 * connection are held by the unit test of `lib/api/failureSentence`. The sentences below are that module's, pinned to it by the same test.
 * No scenario has a date, so none has a zone: they are their own group and run every night.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";
import { ok, refuse, notJson } from "../stub.mjs";
import { CLIENT_ID } from "../fixtures.mjs";

export const group = "failed-requests";

/** What a person is told when the server's answer was not the product's own: for a change (a request that may have gone through) and for a read (a result that did not come back). */
const NOT_OURS_WRITE = "The server's answer was not the product's own (a network or gateway error page can do this), so it is not known whether the request went through. If this was a change, reload the page to see whether it was recorded before you try again.";
const NOT_OURS_READ = "The server's answer was not the product's own (a network or gateway error page can do this), so no result came back. Try again in a moment.";
/** What a person is told over a gateway's error page under a failed status (a 502 while the API wakes). */
const ERROR_PAGE_502 = "The server answered with an error page (error 502) instead of the product's own answer. Try again in a moment; if this was a change, reload the page to see whether it was recorded first.";

const GSTIN_OF_THE_CLIENT = "27AAACA1234A1ZK";
const BROWSER_WORDS = /Unexpected token|is not valid JSON|Failed to fetch|JSON\.parse|Unprocessable/i;

/** The sentence as the whole text of an element (a substring would let a longer sentence satisfy it). */
const exactly = (text) => new RegExp(`^\\s*${text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*$`);

async function saysIt(page, sentence, what) {
  const loc = page.getByText(exactly(sentence)).first();
  await loc.waitFor({ timeout: 4000 }).catch(() => { throw new Error(`${what}: "${sentence}" was not said`); });
  return loc;
}

async function noBrowserWords(page, what) {
  const text = await page.locator("body").innerText();
  assert.doesNotMatch(text, BROWSER_WORDS, `${what}: the browser's own words are on the screen`);
}

// ── the GSTR-3B tab's row actions ────────────────────────────────────────────────────────────────────────────

const BASE_ROW = { gstin: GSTIN_OF_THE_CLIENT, total_taxable_paise: 1000000, tax_liability_paise: 180000, itc_claimed_paise: 100000, net_tax_paise: 80000, cash_payable_paise: 80000 };
const ROWS = [
  { ...BASE_ROW, id: "g3-draft", period: "082026", status: "draft" },
  { ...BASE_ROW, id: "g3-valid", period: "072026", status: "validated" },
  { ...BASE_ROW, id: "g3-appr", period: "062026", status: "ca_approved" },
];

async function atGstr3bRows(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { gst: ["read", "write", "approve", "compute"] } }) });
  stub.route({ method: "GET", re: /api\/gst-workspace\/returns\?/, reply: () => ok({ gstr1: [], gstr3b: ROWS }) });
  stub.route({ method: "GET", re: /client-gst-registrations\/kinds$/, reply: () => ok({
    registration_types: [{ value: "regular", files_gstr1_and_3b: true, files_cmp08: false, files_gstr8: false, files_gstr4_annual: false, other_return_form: null }],
    composition_categories: [], filing_frequencies: ["monthly", "quarterly"], composition_rates_verified: false }) });
  stub.route({ method: "GET", re: /client-gst-registrations\?/, reply: () => ok([
    { id: null, gstin: GSTIN_OF_THE_CLIENT, state_code: "27", registration_type: "regular", filing_frequency: "monthly", is_primary: true, trade_name: null,
      effective_from: null, effective_to: null, label: "Maharashtra (primary)", files_gstr1_and_3b: true, files_cmp08: false, files_gstr8: false, files_gstr4_annual: false }]) });
  await page.goto(env.at("/compliance/gst/"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "GSTR-3B", exact: true }).click();
  await page.getByRole("button", { name: "Validate", exact: true }).waitFor();
}

/** One row action: the request goes out once, comes back as a page that is not JSON, and what the person sees is the sentence, with the button live again and the row as it was. */
const ROW_ACTIONS = [
  {
    id: "validate", what: "Validate", method: "PATCH", re: /gst-workspace\/gstr3b\/g3-draft\/status$/,
    button: (p) => p.getByRole("button", { name: "Validate", exact: true }), working: "Working…", status: "draft",
  },
  {
    id: "ca-approve", what: "CA Approve", method: "PATCH", re: /gst-workspace\/gstr3b\/g3-valid\/status$/,
    button: (p) => p.getByRole("button", { name: "CA Approve", exact: true }), working: "Checking books…", status: "validated",
  },
  {
    id: "recheck", what: "Recheck", method: "POST", re: /gst-workspace\/gstr3b\/g3-draft\/recompute\?dry_run=true$/,
    button: (p) => p.getByRole("button", { name: "Recheck", exact: true }).first(), working: "…", status: "draft",
    // a check against the books never writes, so a failure says that no result came back
    sentence: NOT_OURS_READ,
  },
  {
    id: "delete", what: "Delete (after saying yes)", method: "DELETE", re: /gst-workspace\/gstr3b\/g3-draft$/,
    button: (p) => p.getByRole("button", { name: "Delete", exact: true }).first(), working: "Working…", status: "draft",
    async confirm(p) { await p.getByRole("alertdialog").waitFor(); await p.getByRole("alertdialog").getByRole("button", { name: "Delete", exact: true }).click(); },
  },
];

const gstr3bRowActions = ROW_ACTIONS.map((spec) => ({
  id: `a-gstr3b-${spec.id}-that-fails-outright-says-so-and-lets-go-of-the-row`,
  title: `A client's GST > GSTR-3B > ${spec.what}: a page that is not JSON is said above the table in the product's words, the button is live again and the row is as it was`,
  async run(env) {
    const { page, stub } = env;
    await atGstr3bRows(env);
    stub.route({ method: spec.method, re: spec.re, ...notJson() });
    stub.forgetWrites();
    await spec.button(page).click();
    if (spec.confirm) await spec.confirm(page);
    const sentence = spec.sentence ?? NOT_OURS_WRITE;
    await saysIt(page, sentence, `${spec.what}: the request threw and was not said`);
    await stub.quiet();
    assert.equal(stub.writesTo(spec.re).length, 1, `${spec.what}: expected the one failed request`);
    await noBrowserWords(page, spec.what);
    // the hold was let go of: the button reads as it did and can be pressed again, and the row is where it was
    assert.equal(await page.getByRole("button", { name: spec.working, exact: true }).count(), 0, `${spec.what}: the row stayed held ("${spec.working}")`);
    assert.equal(await spec.button(page).isDisabled(), false, `${spec.what}: the button stayed disabled after the request failed`);
    assert.ok(await page.getByText(ROWS.find((r) => r.status === spec.status).period, { exact: true }).count() >= 1, `${spec.what}: the row went away over a failure`);
    // pressing it again sends a second request (the failure left nothing stuck) and the sentence of the first goes with the press
    stub.forgetWrites();
    stub.route({ method: spec.method, re: spec.re, delay: 1200, reply: () => ok({ id: "g3" }) });
    await spec.button(page).click();
    if (spec.confirm) await spec.confirm(page);
    await until(async () => (await page.getByText(exactly(sentence)).count()) === 0, `${spec.what}: the sentence of the failure stayed over the next press`);
    await until(() => stub.writesTo(spec.re).length === 1, `${spec.what}: a second press sent no request`);
  },
}));

const gstr3bMarkFiled = {
  id: "a-gstr3b-mark-as-filed-that-fails-outright-says-so-in-the-dialog-and-keeps-it-open",
  title: "A client's GST > GSTR-3B > Mark as filed > Record as filed: a page that is not JSON is said inside the dialog, which stays open with what was typed and is live again",
  async run(env) {
    const { page, stub } = env;
    await atGstr3bRows(env);
    const re = /gst-workspace\/gstr3b\/g3-appr\/status$/;
    stub.route({ method: "PATCH", re, ...notJson() });
    await page.getByRole("button", { name: "Mark as filed", exact: true }).click();
    await page.getByLabel("ARN from the portal", { exact: true }).fill("AA2710260000003");
    const box = page.locator("#gst-mark-filed-date");
    await box.fill("");
    await box.pressSequentially("01/10/2026");
    await box.press("Tab");
    stub.forgetWrites();
    const record = page.getByRole("button", { name: "Record as filed", exact: true });
    await record.click();
    const says = page.getByRole("alert").filter({ hasText: exactly(NOT_OURS_WRITE) }).first();
    await says.waitFor({ timeout: 4000 }).catch(() => { throw new Error("Record as filed: the request threw and the dialog did not say it"); });
    await stub.quiet();
    assert.equal(stub.writesTo(re).length, 1, "Record as filed: expected the one failed request");
    assert.equal(await page.getByRole("button", { name: "Recording…", exact: true }).count(), 0, "Record as filed: the dialog stayed on \"Recording…\"");
    assert.equal(await record.isDisabled(), false, "Record as filed: the button stayed held after the request failed");
    assert.equal(await page.getByLabel("ARN from the portal", { exact: true }).inputValue(), "AA2710260000003", "Record as filed: the ARN typed was lost");
    assert.equal(await box.inputValue(), "01/10/2026", "Record as filed: the date typed was lost");
    await noBrowserWords(page, "Record as filed");
  },
};

const gstr3bRecompute = {
  id: "a-gstr3b-recompute-from-books-that-fails-outright-says-so-and-lets-go-of-the-row",
  title: "A client's GST > GSTR-3B > Recheck, then Recompute from books: a page that is not JSON is said above the table in the product's words and the button is live again",
  async run(env) {
    const { page, stub } = env;
    await atGstr3bRows(env);
    // the check answers properly and says the books have moved, which is what offers the button
    stub.route({ method: "POST", re: /gst-workspace\/gstr3b\/g3-draft\/recompute\?dry_run=true$/, reply: () => ok({
      stale: true, differences: { tax_liability_paise: { saved_paise: 180000, books_paise: 200000, difference_paise: 20000 } } }) });
    await page.getByRole("button", { name: "Recheck", exact: true }).first().click();
    const recompute = page.getByRole("button", { name: "Recompute from books", exact: true });
    await recompute.waitFor();
    const re = /gst-workspace\/gstr3b\/g3-draft\/recompute\?dry_run=false$/;
    stub.route({ method: "POST", re, ...notJson() });
    stub.forgetWrites();
    await recompute.click();
    await saysIt(page, NOT_OURS_WRITE, "Recompute from books: the request threw and was not said");
    await stub.quiet();
    assert.equal(stub.writesTo(re).length, 1, "Recompute from books: expected the one failed request");
    assert.equal(await page.getByRole("button", { name: "Recomputing…", exact: true }).count(), 0, "Recompute from books: the row stayed held");
    assert.equal(await recompute.isDisabled(), false, "Recompute from books: the button stayed disabled after the request failed");
    await noBrowserWords(page, "Recompute from books");
  },
};

// ── a list, a compute and a refusal ──────────────────────────────────────────────────────────────────────────

const aTdsList = {
  id: "a-tds-list-that-fails-outright-says-so-in-the-products-words",
  title: "A client's TDS > Returns: a list that comes back as a page that is not JSON says that no result came back, in the product's words",
  async run(env) {
    const { page, stub } = env;
    stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { tds: ["read", "write", "compute", "approve"] } }) });
    stub.route({ method: "GET", re: /api\/tds-workspace\/returns\?/, ...notJson() });
    await page.goto(env.at("/compliance/tds/"), { waitUntil: "networkidle" });
    await page.getByRole("button", { name: "Returns", exact: true }).click();
    await saysIt(page, NOT_OURS_READ, "TDS returns: the list could not be read and the tab did not say it in the product's words");
    await noBrowserWords(page, "TDS returns");
    // a gateway's error page under a failed status is an error page, not markup on the screen
    stub.route({ method: "GET", re: /api\/tds-workspace\/returns\?/, status: 502, raw: "<html><body><h1>502 Bad Gateway</h1></body></html>", reply: () => ({}) });
    await page.getByRole("button", { name: "Deductions", exact: true }).click();
    await page.getByRole("button", { name: "Returns", exact: true }).click();
    await saysIt(page, ERROR_PAGE_502, "TDS returns: a gateway's error page was not said as one");
    assert.equal(await page.getByText(/<html>|Bad Gateway/).count(), 0, "TDS returns: the markup of the error page is on the screen");
  },
};

const anIncomeTaxCompute = {
  id: "an-income-tax-compute-says-the-servers-refusal-and-a-page-that-is-not-json-in-the-products-words",
  title: "Income tax > Advance tax: a compute refused with a sentence shows the sentence (not \"Unprocessable Entity\"), and a page that is not JSON says that no result came back",
  async run(env) {
    const { page, stub } = env;
    const REFUSAL = "The paid-on date of an instalment cannot be after today.";
    const compute = /api\/income-tax\/advance-tax\/compute$/;
    stub.route({ method: "POST", re: compute, ...refuse(REFUSAL, 422) });
    await page.goto(`${env.base}/income-tax/advance-tax/?client_id=${CLIENT_ID}`, { waitUntil: "networkidle" });
    const amount = page.getByPlaceholder("Enter tax amount");
    await amount.fill("100000");
    await saysIt(page, REFUSAL, "Advance tax compute: the server's refusal was not said");
    await noBrowserWords(page, "Advance tax compute");
    assert.equal(await page.getByText(/Advance tax compute failed/).count(), 0, "Advance tax compute: the status line stood in for the server's sentence");
    // a request model's own refusal is a list of {loc, msg} and its sentence arrives with the framework's label in front ("Value error, …"), which is not said (POST-A-392).
    // Its sentence is a DIFFERENT one from the step before, and the request is waited for: the screen still shows the last refusal until the estimate is asked for again (a debounce
    // of about 400 ms), and a check that the label is gone read before that proves nothing.
    const MODEL_REFUSAL = "The estimated tax cannot be negative.";
    stub.route({ method: "POST", re: compute, status: 422, reply: () => ({ detail: [{ loc: ["body", "estimated_tax_paise"], msg: `Value error, ${MODEL_REFUSAL}`, type: "value_error" }] }) });
    stub.forgetWrites();
    await amount.fill("100002");
    await until(() => stub.writesTo(compute).length >= 1, "Advance tax compute: the estimate was not asked for again after the box changed");
    await saysIt(page, MODEL_REFUSAL, "Advance tax compute: the model's refusal was not said as its sentence");
    assert.equal(await page.getByText(/Value error/).count(), 0, "Advance tax compute: the framework's label is on the screen");
    stub.route({ method: "POST", re: compute, ...notJson() });
    stub.forgetWrites();
    await amount.fill("100001");
    await until(() => stub.writesTo(compute).length >= 1, "Advance tax compute: the estimate was not asked for after the last change");
    await saysIt(page, NOT_OURS_READ, "Advance tax compute: a page that is not JSON was not said in the product's words");
    await noBrowserWords(page, "Advance tax compute");
  },
};

// ── the public page a client opens to sign an engagement letter (no sign-in; the client is not the CA)

const LETTER = {
  engagement_number: "EL-2026-0001", title: "Engagement letter", content: "<p>Terms of the engagement.</p>", status: "Sent", recipient_name: "Asha Rao",
  firm_name: "Rao & Co", signed_at: null, signed_by_name: null, rejected_at: null, expired: false,
};
const LETTER_ROUTE = /api\/public\/engagement-letters\/abc$/;

const signingPageLoad = {
  id: "the-signing-page-says-a-gateways-page-is-not-an-invalid-link",
  title: "The public signing page: a gateway's page when the letter loads says that it could not be loaded and offers Try again, never that the link is invalid or has expired; a link the server refuses still says so",
  async run(env) {
    const { page, stub } = env;
    stub.route({ method: "GET", re: LETTER_ROUTE, ...notJson() });
    await page.goto(`${env.base}/sign/?t=abc`, { waitUntil: "networkidle" });
    await saysIt(page, NOT_OURS_READ, "Signing page: a gateway's page was not said in the product's words");
    await page.getByRole("heading", { name: "The letter could not be loaded", exact: true }).waitFor({ timeout: 4000 });
    await page.getByRole("button", { name: "Try again", exact: true }).waitFor({ timeout: 4000 });
    assert.equal(await page.getByText(/invalid or has expired/).count(), 0, "Signing page: a client with a valid link was told that it is invalid or has expired");
    assert.equal(await page.getByText("Link unavailable", { exact: true }).count(), 0, "Signing page: a client with a valid link was told that it is unavailable");
    await noBrowserWords(page, "Signing page");
    // a link the server really does refuse says so, with the heading it always had
    stub.route({ method: "GET", re: LETTER_ROUTE, status: 404, reply: () => ({ success: false, error: "This engagement letter link is invalid or has expired." }) });
    await page.reload({ waitUntil: "networkidle" });
    await page.getByRole("heading", { name: "Link unavailable", exact: true }).waitFor({ timeout: 4000 });
    await saysIt(page, "This engagement letter link is invalid or has expired.", "Signing page: a refused link was not said");
    assert.equal(await page.getByRole("button", { name: "Try again", exact: true }).count(), 0, "Signing page: a link that is refused offers Try again");
  },
};

const signingPageAccept = {
  id: "the-signing-page-says-it-is-not-known-whether-the-letter-was-accepted",
  title: "The public signing page: a gateway's page when Accept & Sign is pressed says that it is not known whether the request went through (not \"try again\"), the button is live again and the name typed is kept",
  async run(env) {
    const { page, stub } = env;
    stub.route({ method: "GET", re: LETTER_ROUTE, reply: () => ok(LETTER) });
    await page.goto(`${env.base}/sign/?t=abc`, { waitUntil: "networkidle" });
    const name = page.getByLabel("Full name (your electronic signature)", { exact: true });
    await name.fill("Asha Rao");
    await page.getByRole("checkbox").check();
    const sign = /api\/public\/engagement-letters\/abc\/sign$/;
    stub.route({ method: "POST", re: sign, ...notJson() });
    stub.forgetWrites();
    const accept = page.getByRole("button", { name: "Accept & Sign", exact: true });
    await accept.click();
    await page.getByRole("alert").filter({ hasText: exactly(NOT_OURS_WRITE) }).first().waitFor({ timeout: 4000 }).catch(() => { throw new Error("Signing page: Accept & Sign met a page that is not JSON and the client was not told in the product's words"); });
    await stub.quiet();
    assert.equal(stub.writesTo(sign).length, 1, "Signing page: expected the one failed request");
    assert.equal(await accept.isDisabled(), false, "Signing page: Accept & Sign stayed held after the request failed");
    assert.equal(await name.inputValue(), "Asha Rao", "Signing page: the name typed was lost");
    assert.equal(await page.getByText(/Something went wrong/).count(), 0, "Signing page: the client was told to try again over a letter that may have been accepted");
    await noBrowserWords(page, "Signing page");
  },
};

export const scenarios = [...gstr3bRowActions, gstr3bMarkFiled, gstr3bRecompute, aTdsList, anIncomeTaxCompute, signingPageLoad, signingPageAccept];
