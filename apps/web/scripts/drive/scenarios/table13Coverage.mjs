/**
 * GSTR-1's TABLE 13 SAYS WHAT IT DID NOT LOOK AT, DRIVEN IN A BROWSER (POST-A-415, slice 1).
 *
 * The form lists twelve natures of document and the builder reads three. The from-books reply now carries `table_13_coverage`: the standing sentence about the other nine natures, and a count of the
 * delivery challans issued in the window. On a client's GST > GSTR-1 > Compute from Books, against a stubbed server, in Chromium:
 *
 *   1. a return whose books hold three issued delivery challans shows BOTH sentences as the server wrote them, the challan one under its own heading in the attention tone and the standing one under
 *      "Table 13 — what this build looked at";
 *   2. a register that could not be read says so (the challan sentence is asked about, never a zero);
 *   3. a client with no challan sees the standing note carrying the settled zero, and no heading asking about challans;
 *   4. a server that sent nothing (an older one) draws neither heading, because the screen makes no sentence up.
 *
 * The sentences are the server's, word for word (tests/test_gstr1_table_13_says_what_it_did_not_look_at.py reads the constants below out of this file and compares them with what the rule produces).
 * No scenario has a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { ok } from "../stub.mjs";

export const group = "table-thirteen-coverage";

const GSTIN_OF_THE_CLIENT = "27AAACA1234A1ZK";
const STANDING_HEADING = "Table 13 — what this build looked at";
const CHALLAN_HEADING = "Delivery challans and Table 13";

const NOTE = "This build reads 3 natures of document for Table 13: Invoices for outward supply, Debit Note and Credit Note. It did not look for the other 9 natures the form lists: Invoices for inward supply from unregistered person; Revised Invoice; Receipt Voucher; Payment Voucher; Refund Voucher; Delivery Challan for job work; Delivery Challan for supply on approval; Delivery Challan in case of liquid gas; Delivery Challan in case other than by way of supply (excluding at S no. 9 to 11). If this client issued any of them in the period, they are not in this return. Whether they fall to be declared is for the CA to settle against the form.";
const CHALLANS_THREE = "3 delivery challans were issued in this period and are not in this return's Table 13: 2 for Job work (Rule 55(1)(b), Rule 45, s.143); 1 for Sent on approval for sale or return (s.31(7)). This build does not declare delivery challans, and which row of the table each belongs in is for the CA to settle against the form. Drafts and cancelled challans are not counted.";
const CHALLANS_UNREAD = "The delivery challans issued in this period could not be read, so whether any of them is missing from Table 13 is not known.";
const CHALLANS_NONE = "The books record no delivery challan issued in this period. Drafts and cancelled challans are not counted.";

const NATURES = [
  "Invoices for outward supply", "Debit Note", "Credit Note",
];
const NOT_READ = [
  "Invoices for inward supply from unregistered person", "Revised Invoice", "Receipt Voucher", "Payment Voucher", "Refund Voucher",
  "Delivery Challan for job work", "Delivery Challan for supply on approval", "Delivery Challan in case of liquid gas",
  "Delivery Challan in case other than by way of supply (excluding at S no. 9 to 11)",
];

const coverage = (challans) => ({ declared_natures: NATURES, not_read_natures: NOT_READ, note: NOTE, challans });

const THREE = coverage({ read: true, count: 3, by_reason: [
  { reason: "job_work", label: "Job work (Rule 55(1)(b), Rule 45, s.143)", count: 2 },
  { reason: "sale_on_approval", label: "Sent on approval for sale or return (s.31(7))", count: 1 }], note: CHALLANS_THREE });
const UNREAD = coverage({ read: false, count: null, by_reason: [], note: CHALLANS_UNREAD });
const NONE = coverage({ read: true, count: 0, by_reason: [], note: CHALLANS_NONE });

const RESULT = {
  payload: {}, summary: {}, invoice_count: 3, taxable_total_paise: 1000000, tax_total_paise: 180000, total_igst_paise: 0, total_cgst_paise: 90000, total_sgst_paise: 90000, total_cess_paise: 0,
  validation_errors: [], validation_warnings: [], payload_gaps: [], reconciliation: { reconciled: true, net_output_gst: { books_paise: 180000, ledger_paise: 180000, difference_paise: 0 } },
};

/** The client's GST tab with the GSTR-1 compute dialog open, the stub answering the compute with `result`. */
async function computeWith(env, result) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { gst: ["read", "write", "approve", "compute"] } }) });
  stub.route({ method: "GET", re: /api\/gst-workspace\/returns\?/, reply: () => ok({ gstr1: [], gstr3b: [] }) });
  stub.route({ method: "GET", re: /client-gst-registrations\/kinds$/, reply: () => ok({
    registration_types: [{ value: "regular", files_gstr1_and_3b: true, files_cmp08: false, files_gstr8: false, files_gstr4_annual: false, other_return_form: null }],
    composition_categories: [], filing_frequencies: ["monthly", "quarterly"], composition_rates_verified: false }) });
  stub.route({ method: "GET", re: /client-gst-registrations\?/, reply: () => ok([
    { id: null, gstin: GSTIN_OF_THE_CLIENT, state_code: "27", registration_type: "regular", filing_frequency: "monthly", is_primary: true, trade_name: null,
      effective_from: null, effective_to: null, label: "Maharashtra (primary)", files_gstr1_and_3b: true, files_cmp08: false, files_gstr8: false, files_gstr4_annual: false }]) });
  stub.route({ method: "POST", re: /api\/gst\/gstr1\/from-books$/, reply: (_req, raw) => ok({ ...result, period: JSON.parse(raw).period, gstin: GSTIN_OF_THE_CLIENT }) });
  await page.goto(env.at("/compliance/gst/"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "GSTR-1", exact: true }).click();
  await page.getByRole("button", { name: "Compute from Books", exact: true }).first().click();
  await page.getByLabel("GSTR-1 return period to compute (MMYYYY)", { exact: true }).fill("092026");
  await page.getByRole("button", { name: "Compute", exact: true }).click();
  await page.getByRole("button", { name: "Save as Draft", exact: true }).waitFor({ timeout: 4000 });
}

/** A callout by its heading: the `<div>` that holds the `<h4>` carrying it. */
const callout = (page, heading) => page.locator("div", { has: page.locator("h4", { hasText: heading }) }).last();
const sentenceIn = async (box, sentence) => (await box.getByText(sentence, { exact: true }).count()) === 1;

export const scenarios = [
  {
    id: "a-gstr1-compute-whose-books-hold-challans-shows-both-sentences-as-the-server-wrote-them",
    title: "A client's GST > GSTR-1 > Compute from Books: three issued delivery challans — the challan sentence under its own heading and the standing note under the Table 13 heading, each word for word",
    async run(env) {
      const { page } = env;
      await computeWith(env, { ...RESULT, table_13_coverage: THREE });
      assert.equal(await page.getByRole("heading", { name: CHALLAN_HEADING }).count(), 1, "the challan sentence was not drawn under its heading");
      assert.equal(await page.getByRole("heading", { name: STANDING_HEADING }).count(), 1, "the standing note was not drawn under its heading");
      assert.ok(await sentenceIn(callout(page, CHALLAN_HEADING), CHALLANS_THREE), "the challan sentence is not the server's, word for word");
      const standing = callout(page, STANDING_HEADING);
      assert.ok(await sentenceIn(standing, NOTE), "the standing note is not the server's, word for word");
      assert.equal(await standing.getByText(CHALLANS_THREE).count(), 0, "the challan sentence was drawn twice");
    },
  },
  {
    id: "a-gstr1-compute-whose-challan-register-could-not-be-read-says-so",
    title: "A client's GST > GSTR-1 > Compute from Books: a challan register that could not be read is asked about with the server's sentence and is never drawn as a nil",
    async run(env) {
      const { page } = env;
      await computeWith(env, { ...RESULT, table_13_coverage: UNREAD });
      assert.ok(await sentenceIn(callout(page, CHALLAN_HEADING), CHALLANS_UNREAD), "the unread sentence was not drawn under the challan heading");
      assert.equal(await page.getByText(CHALLANS_NONE).count(), 0, "an unread register was drawn as 'no challan issued'");
      assert.ok(await sentenceIn(callout(page, STANDING_HEADING), NOTE), "the standing note was dropped");
    },
  },
  {
    id: "a-gstr1-compute-with-no-challan-shows-the-settled-zero-inside-the-standing-note",
    title: "A client's GST > GSTR-1 > Compute from Books: no challan issued — the zero is a reading inside the standing note and nothing asks about challans",
    async run(env) {
      const { page } = env;
      await computeWith(env, { ...RESULT, table_13_coverage: NONE });
      assert.equal(await page.getByRole("heading", { name: CHALLAN_HEADING }).count(), 0, "a settled zero was drawn as a question");
      const standing = callout(page, STANDING_HEADING);
      assert.ok(await sentenceIn(standing, NOTE), "the standing note is missing");
      assert.ok(await sentenceIn(standing, CHALLANS_NONE), "the settled zero is not inside the standing note");
    },
  },
  {
    id: "a-gstr1-compute-from-a-server-that-sent-no-coverage-draws-neither-heading",
    title: "A client's GST > GSTR-1 > Compute from Books: a server that sent no coverage (an older one, or a build that was not asked for it) draws neither heading — the screen makes no sentence up",
    async run(env) {
      const { page } = env;
      await computeWith(env, RESULT);
      assert.equal(await page.getByRole("heading", { name: STANDING_HEADING }).count(), 0, "the standing heading was drawn with nothing to say");
      assert.equal(await page.getByRole("heading", { name: CHALLAN_HEADING }).count(), 0, "the challan heading was drawn with nothing to say");
      assert.equal(await page.getByText("did not look for").count(), 0, "a sentence about natures was drawn that the server never sent");
    },
  },
];
