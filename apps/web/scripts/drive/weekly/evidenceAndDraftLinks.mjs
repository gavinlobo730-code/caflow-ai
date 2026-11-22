/**
 * EVIDENCE TAKEN OUT OF ITS BOX IS REFUSED, AND A DRAFT NOTE'S EMPTIED LINK IS SENT AS A CLEAR (POST-A-399, the sixth slice), driven in a browser.
 *
 * The last two shapes of "the box was emptied, nothing was sent, and the screen said saved". Against a stubbed server, in Chromium:
 *
 *   1. an export invoice with its shipping bill on file: the number taken out and Save pressed is refused beside the button in the box's words and sends nothing; put back, and the port code
 *      taken out, the same in the port code's words; both back, the save goes and carries both;
 *   2. a draft bill with the supplier's own invoice number on file: the number taken out is refused and sends nothing; put back, the save goes and carries it;
 *   3. a draft bill from a payee under section 195 with its Form 15CA acknowledgement number and Form 15CB UDIN on file: each taken out is refused in its own words and sends nothing;
 *   4. each of the four notes as a DRAFT raised against a document, with a reason: the "Against" box cleared and the reason emptied, the edit carries both as null (the server clears them on a
 *      draft), with the note's lines;
 *   5. a draft note that was raised against nothing and carries no reason sends neither key, and one whose boxes were not touched sends both as they were.
 *
 * No scenario has a date of its own that depends on the clock, so none has a zone.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";
import { ok } from "../stub.mjs";
import { VENDOR, billRow, invoiceDetail } from "../fixtures.mjs";
import { NOTE_KINDS } from "../flows.mjs";

export const group = "evidence-and-draft-links";

const sentenceFor = (what, noun) => `${what} on file can be corrected but not removed: enter the corrected ${noun}.`;

async function emptyIt(locator) {
  await locator.fill("");
  await locator.blur();
}

/** Save pressed over evidence taken out: the sentence is on the screen where the person can reach it, and nothing was sent. */
async function refusedAndNothingSent(page, stub, save, writes, sentence, what) {
  for (const press of ["first", "second"]) {
    await save.click();
    const said = page.locator("[data-removed-evidence]").getByText(sentence);
    await said.waitFor({ timeout: 5000 }).catch(() => { throw new Error(`${what}: pressing Save (${press} time) did not say "${sentence}"`); });
    await until(async () => {
      const at = await said.boundingBox();
      const height = page.viewportSize()?.height ?? 0;
      return !!at && at.y >= 0 && at.y + at.height <= height;
    }, `${what}: the sentence to be inside the window`, 4000);
    await stub.quiet();
    assert.equal(stub.writesTo(writes).length, 0, `${what}: a Save (${press} time) over evidence taken out SENT A WRITE, and the screen would have said it saved`);
  }
}

async function theOneEdit(stub, re, what) {
  await until(() => stub.writesTo(re, "PATCH").length >= 1, `${what}: the edit to be sent`, 8000);
  await stub.quiet();
  const sent = stub.writesTo(re, "PATCH");
  assert.equal(sent.length, 1, `${what}: expected ONE edit, saw ${sent.length}`);
  return JSON.parse(sent[0].body);
}

/** What the server previews for a payee under section 195: it is what makes the bill editor draw its Form 15CA / 15CB block. */
const TDS_195_PREVIEW = {
  taxable_amount_paise: 100000, total_paise: 118000, total_gst_paise: 18000, tds_paise: 20800, tds_rate_bps: 2000, tds_section: "195", tds_surcharge_paise: 0, tds_cess_paise: 800,
  tds_nature_of_income: "Fees for technical services", tds_basis: "Part II of the First Schedule", tds_citation: "s.195", tds_shortfall_paise: 0, net_payable_paise: 97200,
  txn_currency: "INR", txn_total: 1180, txn_net_payable: 972 };

/** The document each kind of note is raised against, as the editor's picker reads it. */
const AGAINST = {
  sales_invoice_id: { table: "client_sales_invoices", label: "Against Invoice (optional)", shown: "CL-0042",
    row: { id: "inv-42", invoice_no: "CL-0042", total_paise: 1180000, paid_paise: 0, credited_paise: 0, debit_note_paise: 0, status: "issued" } },
  purchase_bill_id: { table: "purchase_bills", label: "Against Bill (optional)", shown: "GS/114",
    row: { ...billRow("received", "b42"), bill_no: "GS/114" } },
};
const NOTE_EDIT_PATHS = ["/sales/credit-notes/n9/edit/", "/sales/debit-notes/n9/edit/", "/purchases/debit-notes/n9/edit/", "/purchases/credit-notes/n9/edit/"];
const LINE = { id: "nl1", description: "Paper", hsn_sac: "4802", quantity: 1, unit: "NOS", rate_paise: 100000, gst_rate_bps: 1800, taxable_amount_paise: 100000,
  cgst_paise: 9000, sgst_paise: 9000, igst_paise: 0, line_total_paise: 118000, service_catalogue_id: "it1", itc_eligible: true };

/** A draft note of this kind opened on its editor. `over` is what the stored note carries beyond the fixture's row. */
async function openDraftNote(env, kind, path, over) {
  const { page, stub } = env;
  const key = "sales_invoice_id" in kind.row ? "sales_invoice_id" : "purchase_bill_id";
  const against = AGAINST[key];
  const note = { ...kind.row, status: "draft", notes: null, ...over };
  stub.setTable(kind.table, [note]);
  stub.setTable(against.table, [against.row]);
  if (key === "purchase_bill_id") stub.setTable("vendors", [VENDOR]);
  stub.route({ method: "GET", re: new RegExp(`/api/${kind.api}/n9$`), reply: () => ok({ ...note, lines: [LINE], is_interstate: false, journal_entry_id: null }) });
  stub.route({ method: "PATCH", re: new RegExp(`/api/${kind.api}/n9$`), reply: () => ok({ id: "n9" }) });
  await page.goto(env.at(path), { waitUntil: "networkidle" });
  await page.getByLabel("Reason").waitFor({ timeout: 10000 });
  const field = page.locator("div").filter({ has: page.getByText(against.label, { exact: true }) }).last();
  return { key, against, field, writes: new RegExp(`/api/${kind.api}/n9$`) };
}

export const scenarios = [
  {
    id: "an-export-invoices-shipping-bill-number-or-port-code-taken-out-is-refused-and-sends-nothing",
    title: "Sales > an export invoice > Edit: the shipping bill number, and then the port code, taken out and Save pressed is refused beside the button and sends nothing; put back, the save goes and carries both",
    async run(env) {
      const { page, stub } = env;
      const detail = { ...invoiceDetail("issued", "inv-9"), supply_type: "zero_rated", invoice_type: "Regular", shipping_bill_no: "SB-0042", shipping_bill_date: "2026-07-15", port_code: "INMAA1" };
      stub.route({ method: "GET", re: /sales-invoices\/inv-9$/, reply: () => ok(detail) });
      stub.route({ method: "PATCH", re: /sales-invoices\/inv-9$/, reply: () => ok({ id: "inv-9" }) });
      await page.goto(env.at("/sales/invoices/inv-9/edit/"), { waitUntil: "networkidle" });
      const number = page.locator("#inv-sb-no");
      const port = page.locator("#inv-port-code");
      await number.waitFor({ timeout: 10000 });
      assert.equal(await number.inputValue(), "SB-0042", "the shipping bill number on file was not loaded");
      assert.equal(await port.inputValue(), "INMAA1", "the port code on file was not loaded");
      const save = page.getByRole("button", { name: "Save Changes", exact: true });
      const writes = /sales-invoices\/inv-9$/;

      await emptyIt(number);
      await refusedAndNothingSent(page, stub, save, writes, sentenceFor("The shipping bill number", "number"), "the shipping bill number taken out");
      await number.fill("SB-0042");
      await until(async () => (await page.locator("[data-removed-evidence]").count()) === 0, "the sentence to go once the number was put back", 5000);

      await emptyIt(port);
      await refusedAndNothingSent(page, stub, save, writes, sentenceFor("The port code", "code"), "the port code taken out");
      await port.fill("INMAA1");
      await until(async () => (await page.locator("[data-removed-evidence]").count()) === 0, "the sentence to go once the port code was put back", 5000);

      await save.click();
      const body = await theOneEdit(stub, writes, "saving the export invoice with its evidence back");
      assert.equal(body.shipping_bill_no, "SB-0042");
      assert.equal(body.port_code, "INMAA1");
    },
  },
  {
    id: "a-draft-bills-own-invoice-number-taken-out-is-refused-and-sends-nothing",
    title: "Purchases > a draft bill > Edit: the vendor's invoice number taken out and Save pressed is refused beside the button and sends nothing; put back, the save goes and carries it",
    async run(env) {
      const { page, stub } = env;
      stub.setTable("vendors", [VENDOR]);
      stub.route({ method: "GET", re: /purchase-bills\/b9$/, reply: () => ok(billRow("draft", "b9")) });
      stub.route({ method: "PATCH", re: /purchase-bills\/b9$/, reply: () => ok({ id: "b9" }) });
      await page.goto(env.at("/purchases/bills/b9/edit/"), { waitUntil: "networkidle" });
      const number = page.getByLabel("Vendor Invoice No.");
      await number.waitFor({ timeout: 10000 });
      assert.equal(await number.inputValue(), "GS/114", "the number on file was not loaded");
      const save = page.getByRole("button", { name: "Save Changes", exact: true });
      await emptyIt(number);
      await refusedAndNothingSent(page, stub, save, /purchase-bills\/b9$/, sentenceFor("The vendor invoice number", "number"), "the vendor's invoice number taken out");
      await number.fill("GS/114-A");
      await until(async () => (await page.locator("[data-removed-evidence]").count()) === 0, "the sentence to go once a number was typed", 5000);
      await save.click();
      const body = await theOneEdit(stub, /purchase-bills\/b9$/, "saving the draft bill with a corrected number");
      assert.equal(body.bill_no, "GS/114-A", `the corrected number was not sent: ${JSON.stringify(body)}`);
    },
  },
  {
    id: "a-bills-form-15ca-acknowledgement-number-or-form-15cb-udin-taken-out-is-refused-and-sends-nothing",
    title: "Purchases > a draft bill from a payee under section 195 > Edit: the Form 15CA acknowledgement number, and then the Form 15CB UDIN, taken out is refused in its own words and sends nothing",
    async run(env) {
      const { page, stub } = env;
      stub.setTable("vendors", [{ ...VENDOR, tds_applicable: true, tds_section: "195", tds_rate_bps: 2000 }]);
      stub.route({ method: "POST", re: /purchase-bills\/tds-preview/, reply: () => ok(TDS_195_PREVIEW) });
      const bill = { ...billRow("draft", "b9"), form_15ca_ack_no: "ACK-0042", form_15ca_filed_on: "2026-07-15", form_15cb_udin: "24012345ABCDEF1234" };
      stub.route({ method: "GET", re: /purchase-bills\/b9$/, reply: () => ok(bill) });
      stub.route({ method: "PATCH", re: /purchase-bills\/b9$/, reply: () => ok({ id: "b9" }) });
      await page.goto(env.at("/purchases/bills/b9/edit/"), { waitUntil: "networkidle" });
      const ack = page.getByLabel("Form 15CA acknowledgement no.");
      const udin = page.getByLabel("Form 15CB UDIN");
      await ack.waitFor({ timeout: 10000 });
      assert.equal(await ack.inputValue(), "ACK-0042");
      assert.equal(await udin.inputValue(), "24012345ABCDEF1234");
      const save = page.getByRole("button", { name: "Save Changes", exact: true });

      await emptyIt(ack);
      await refusedAndNothingSent(page, stub, save, /purchase-bills\/b9$/, sentenceFor("The Form 15CA acknowledgement number", "number"), "the Form 15CA acknowledgement number taken out");
      await ack.fill("ACK-0042");
      await emptyIt(udin);
      await refusedAndNothingSent(page, stub, save, /purchase-bills\/b9$/, sentenceFor("The Form 15CB UDIN", "UDIN"), "the Form 15CB UDIN taken out");
    },
  },
  ...NOTE_KINDS.map((kind, i) => ({
    id: `a-draft-${kind.name.replace(/ /g, "-")}-with-its-against-box-cleared-and-its-reason-emptied-sends-both-as-null`,
    title: `${kind.name[0].toUpperCase()}${kind.name.slice(1)}s > a draft note > Edit: the "Against" box cleared and the reason emptied are sent as null (the server clears them on a draft), with the note's lines`,
    async run(env) {
      const { page, stub } = env;
      const key = "sales_invoice_id" in kind.row ? "sales_invoice_id" : "purchase_bill_id";
      const opened = await openDraftNote(env, kind, NOTE_EDIT_PATHS[i], { [key]: AGAINST[key].row.id, reason: "Rate correction" });
      await until(async () => (await opened.field.innerText()).includes(opened.against.shown), `the document the note was raised against (${opened.against.shown}) to be shown in its box`, 8000);
      await opened.field.getByRole("button", { name: "Clear" }).click();
      await emptyIt(page.getByLabel("Reason"));
      await page.getByRole("button", { name: "Save Changes", exact: true }).click();
      const body = await theOneEdit(stub, opened.writes, `saving a draft ${kind.name} with its link and reason taken out`);
      assert.equal(body[key], null, `the cleared "Against" box was not sent as null: ${JSON.stringify(body)}`);
      assert.equal(body.reason, null, `the emptied reason was not sent as null: ${JSON.stringify(body)}`);
      assert.ok(Array.isArray(body.lines) && body.lines.length === 1, `the draft's lines were not sent with its edit: ${JSON.stringify(body)}`);
    },
  })),
  {
    id: "a-draft-note-raised-against-nothing-sends-no-link-and-one-left-alone-sends-what-it-had",
    title: "Sales credit notes > a draft note > Edit: a note raised against nothing and with no reason sends neither key; a note whose boxes were not touched sends the document and the reason it had",
    async run(env) {
      const { page, stub } = env;
      const kind = NOTE_KINDS[0];
      let opened = await openDraftNote(env, kind, NOTE_EDIT_PATHS[0], { sales_invoice_id: null, reason: null });
      await page.getByLabel("Notes", { exact: true }).fill("checked");
      await page.getByRole("button", { name: "Save Changes", exact: true }).click();
      let body = await theOneEdit(stub, opened.writes, "saving a draft credit note raised against nothing");
      assert.ok(!("sales_invoice_id" in body), `a link nobody chose was sent: ${JSON.stringify(body)}`);
      assert.ok(!("reason" in body), `a reason nobody typed was sent: ${JSON.stringify(body)}`);

      stub.clearWrites?.();
      opened = await openDraftNote(env, kind, NOTE_EDIT_PATHS[0], { sales_invoice_id: "inv-42", reason: "Rate correction" });
      await until(async () => (await opened.field.innerText()).includes("CL-0042"), "the invoice the note was raised against to be shown", 8000);
      await page.getByLabel("Notes", { exact: true }).fill("checked again");
      const before = stub.writesTo(opened.writes, "PATCH").length;
      await page.getByRole("button", { name: "Save Changes", exact: true }).click();
      await until(() => stub.writesTo(opened.writes, "PATCH").length === before + 1, "the second edit to be sent", 8000);
      body = JSON.parse(stub.writesTo(opened.writes, "PATCH").at(-1).body);
      assert.equal(body.sales_invoice_id, "inv-42", `the invoice it was raised against was not sent as it was: ${JSON.stringify(body)}`);
      assert.equal(body.reason, "Rate correction", `the reason was not sent as it was: ${JSON.stringify(body)}`);
    },
  },
];
