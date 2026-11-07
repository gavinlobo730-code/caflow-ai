/**
 * AN EMPTIED SOFT BOX ON AN EDIT CLEARS THE STORED VALUE (POST-A-399, first slice), driven in a browser.
 *
 * An edit screen sent a soft box as `value || undefined`; JSON drops an undefined key, so a note or a reference the person emptied reached the server as nothing, the stored value stayed, and
 * the screen said the document was updated. The invoice, the purchase bill and the four notes now send an emptied box that had a value on file as null (the server clears it), a box that was
 * empty and is empty as nothing, and leave a date and the evidence of the document alone. Against a stubbed server, in Chromium, what each edit REQUEST carries:
 *
 *   1. an issued sales invoice, its note and reference taken out: the PATCH carries `notes: null` and `reference_no: null`, the due date and the credit days it was opened with, and nothing locked;
 *   2. an issued sales invoice with NO note and NO reference on file: a note typed and taken out again, nothing else touched, sends neither key;
 *   3. a DRAFT sales invoice, its note and reference taken out: the PATCH (the other request body) carries both as null too;
 *   4. a purchase bill that has been received, its reference and note taken out: both are null in the PATCH, the due date and the attached copy of the supplier's invoice are sent as they were;
 *   5. each of the four notes once issued, its note taken out: the PATCH carries `notes: null`, and on the two purchase notes the attached copy as it was, and nothing else;
 *   6. a note typed on a NEW sales credit note and a NEW sales debit note reaches the server (the box was always there and the create used to leave it out).
 *
 * A due date taken out is not here: it is refused beside the button and sends nothing (the `a-date-on-file-is-replaced-and-not-emptied-*due-date` rows of the dates group).
 *
 * No scenario has a date of its own that depends on the clock, so none has a zone.
 */
import assert from "node:assert/strict";
import { pick, until } from "../kit.mjs";
import { ok } from "../stub.mjs";
import { ITEM, VENDOR, billRow, invoiceDetail } from "../fixtures.mjs";
import { NOTE_KINDS } from "../flows.mjs";

export const group = "cleared-boxes";

/** The one PATCH a scenario waits for, parsed. */
async function theEdit(stub, re, what) {
  await until(() => stub.writesTo(re, "PATCH").length >= 1, `${what}: the edit to be sent`, 8000);
  await stub.quiet();
  const sent = stub.writesTo(re, "PATCH");
  assert.equal(sent.length, 1, `${what}: expected ONE edit, saw ${sent.length}`);
  return JSON.parse(sent[0].body);
}

/** An invoice with a note, a reference and the terms on file, opened on its editor. */
async function openInvoiceToEdit(env, status, over = {}) {
  const { page, stub } = env;
  const detail = { ...invoiceDetail(status, "inv-9"), notes: "Pay by cheque", reference_no: "PO-77", credit_days: 30, ...over };
  stub.route({ method: "GET", re: /sales-invoices\/inv-9$/, reply: () => ok(detail) });
  stub.route({ method: "PATCH", re: /sales-invoices\/inv-9$/, reply: () => ok({ id: "inv-9" }) });
  await page.goto(env.at("/sales/invoices/inv-9/edit/"), { waitUntil: "networkidle" });
  await page.getByLabel("Notes", { exact: true }).waitFor({ timeout: 10000 });
  return detail;
}

async function emptyIt(locator) {
  await locator.fill("");
  await locator.blur();
}

/** Where each note kind is edited, and what its issued PATCH carries besides the note. */
const NOTE_EDITS = [
  { kind: NOTE_KINDS[0], path: "/sales/credit-notes/n9/edit/", attached: false },
  { kind: NOTE_KINDS[1], path: "/sales/debit-notes/n9/edit/", attached: false },
  { kind: NOTE_KINDS[2], path: "/purchases/debit-notes/n9/edit/", attached: true },
  { kind: NOTE_KINDS[3], path: "/purchases/credit-notes/n9/edit/", attached: true },
];

export const scenarios = [
  {
    id: "an-issued-invoice-with-its-note-and-reference-taken-out-sends-both-as-null-and-nothing-locked",
    title: "Sales > an issued invoice > Edit: the note and the reference taken out are sent as null (the server clears them), the due date and the credit days it opened with are sent as they were, and no locked field is sent",
    async run(env) {
      const { page, stub } = env;
      await openInvoiceToEdit(env, "issued");
      assert.equal(await page.getByLabel("Notes", { exact: true }).inputValue(), "Pay by cheque", "the note on file was not loaded");
      assert.equal(await page.getByLabel("Reference", { exact: true }).inputValue(), "PO-77", "the reference on file was not loaded");
      await emptyIt(page.getByLabel("Notes", { exact: true }));
      await emptyIt(page.getByLabel("Reference", { exact: true }));
      await page.getByRole("button", { name: "Save Changes", exact: true }).click();
      const body = await theEdit(stub, /sales-invoices\/inv-9$/, "saving an issued invoice with its note and reference taken out");
      assert.equal(body.notes, null, `the note taken out was not sent as null: ${JSON.stringify(body)}`);
      assert.equal(body.reference_no, null, `the reference taken out was not sent as null: ${JSON.stringify(body)}`);
      assert.equal(body.due_date, "2026-10-31", "the due date it opened with was not sent as it was");
      assert.equal(body.credit_days, 30, "the credit days it opened with were not sent as they were");
      for (const locked of ["customer_id", "invoice_no", "invoice_date", "lines", "supply_state_code", "is_inter_state"]) {
        assert.ok(!(locked in body), `a locked field (${locked}) was sent on an issued invoice`);
      }
    },
  },
  {
    id: "an-issued-invoice-with-nothing-on-file-sends-no-note-and-no-reference-even-when-a-box-was-typed-in-and-emptied",
    title: "Sales > an issued invoice > Edit: a note typed into a box that was empty and emptied again, and a reference never touched, send neither key (a field the screen never showed is never erased)",
    async run(env) {
      const { page, stub } = env;
      await openInvoiceToEdit(env, "issued", { notes: null, reference_no: null });
      const notes = page.getByLabel("Notes", { exact: true });
      await notes.fill("a thought");
      await emptyIt(notes);
      await page.getByRole("button", { name: "Save Changes", exact: true }).click();
      const body = await theEdit(stub, /sales-invoices\/inv-9$/, "saving an issued invoice with nothing in the note and the reference");
      assert.ok(!("notes" in body), `a note that was empty before and after was sent: ${JSON.stringify(body)}`);
      assert.ok(!("reference_no" in body), `a reference nobody touched was sent: ${JSON.stringify(body)}`);
    },
  },
  {
    id: "a-draft-invoice-with-its-note-and-reference-taken-out-sends-both-as-null",
    title: "Sales > a draft invoice > Edit: the note and the reference taken out are sent as null in the draft's PATCH as well, with the due date it opened with",
    async run(env) {
      const { page, stub } = env;
      await openInvoiceToEdit(env, "draft");
      assert.equal(await page.getByLabel("Notes", { exact: true }).inputValue(), "Pay by cheque", "the note on file was not loaded");
      await emptyIt(page.getByLabel("Notes", { exact: true }));
      await emptyIt(page.getByLabel("Reference", { exact: true }));
      await page.getByRole("button", { name: "Save Draft", exact: true }).click();
      const body = await theEdit(stub, /sales-invoices\/inv-9$/, "saving a draft invoice with its note and reference taken out");
      assert.equal(body.notes, null, `the note taken out was not sent as null: ${JSON.stringify(body)}`);
      assert.equal(body.reference_no, null, `the reference taken out was not sent as null: ${JSON.stringify(body)}`);
      assert.equal(body.due_date, "2026-10-31", "the due date it opened with was not sent as it was");
      assert.ok(Array.isArray(body.lines) && body.lines.length === 1, `the draft's lines were not sent with its edit: ${JSON.stringify(body)}`);
    },
  },
  {
    id: "a-received-bill-with-its-reference-and-note-taken-out-sends-both-as-null-and-leaves-the-due-date-and-the-attached-copy-alone",
    title: "Purchases > a received bill > Edit: the reference and the note taken out are sent as null; the due date and the attached copy of the supplier's invoice are sent as they were, and no locked field is sent",
    async run(env) {
      const { page, stub } = env;
      const bill = { ...billRow("received", "b9"), our_reference: "OUR-1", notes: "Came with the goods", document_url: "bills/scan-0042.pdf" };
      stub.setTable("vendors", [VENDOR]);
      stub.route({ method: "GET", re: /purchase-bills\/b9$/, reply: () => ok(bill) });
      stub.route({ method: "PATCH", re: /purchase-bills\/b9$/, reply: () => ok({ id: "b9" }) });
      await page.goto(env.at("/purchases/bills/b9/edit/"), { waitUntil: "networkidle" });
      await page.getByLabel("Notes", { exact: true }).waitFor({ timeout: 10000 });
      await emptyIt(page.getByLabel("Our Reference", { exact: true }));
      await emptyIt(page.getByLabel("Notes", { exact: true }));
      await page.getByRole("button", { name: "Save Changes", exact: true }).click();
      const body = await theEdit(stub, /purchase-bills\/b9$/, "saving a received bill with its reference and note taken out");
      assert.equal(body.our_reference, null, `the reference taken out was not sent as null: ${JSON.stringify(body)}`);
      assert.equal(body.notes, null, `the note taken out was not sent as null: ${JSON.stringify(body)}`);
      assert.equal(body.due_date, "2026-11-01", `the due date it opened with was not sent as it was: ${JSON.stringify(body)}`);
      assert.equal(body.document_url, "bills/scan-0042.pdf", "the attached copy of the supplier's invoice was not sent as it was");
      for (const locked of ["bill_no", "bill_date", "lines"]) assert.ok(!(locked in body), `a locked field (${locked}) was sent on a received bill`);
    },
  },
  ...NOTE_EDITS.map(({ kind, path, attached }) => ({
    id: `an-issued-${kind.name.replace(/ /g, "-")}-with-its-note-taken-out-sends-the-note-as-null`,
    title: `${kind.name[0].toUpperCase()}${kind.name.slice(1)}s > an issued note > Edit: the note taken out is sent as null in the PATCH (the server clears it)${attached ? ", with the attached copy as it was," : ""} and nothing else is sent`,
    async run(env) {
      const { page, stub } = env;
      const issued = { ...kind.row, status: "issued", notes: "Wrong size delivered", ...(attached ? { document_url: "notes/scan-7.pdf" } : {}) };
      stub.setTable(kind.table, [issued]);
      // One valid line: the two purchase editors ask the line check of an issued note as well (POST-A-425), so a note with none could not be saved on them whatever it said.
      const line = { id: "nl1", description: "Paper", hsn_sac: "4802", quantity: 1, unit: "NOS", rate_paise: 100000, gst_rate_bps: 1800, taxable_amount_paise: 100000,
        cgst_paise: 9000, sgst_paise: 9000, igst_paise: 0, line_total_paise: 118000, service_catalogue_id: ITEM.id };
      stub.route({ method: "GET", re: new RegExp(`/api/${kind.api}/n9$`), reply: () => ok({ ...issued, lines: [line], is_interstate: false, journal_entry_id: "j3" }) });
      stub.route({ method: "PATCH", re: new RegExp(`/api/${kind.api}/n9$`), reply: () => ok({ id: "n9" }) });
      await page.goto(env.at(path), { waitUntil: "networkidle" });
      const notes = page.getByLabel("Notes", { exact: true });
      await notes.waitFor({ timeout: 10000 });
      assert.equal(await notes.inputValue(), "Wrong size delivered", "the note on file was not loaded");
      await emptyIt(notes);
      await page.getByRole("button", { name: "Save Changes", exact: true }).click();
      const body = await theEdit(stub, new RegExp(`/api/${kind.api}/n9$`), `saving an issued ${kind.name} with its note taken out`);
      assert.equal(body.notes, null, `the note taken out was not sent as null: ${JSON.stringify(body)}`);
      assert.deepEqual(Object.keys(body).sort(), attached ? ["document_url", "notes"] : ["notes"], `an issued note sent more than its note${attached ? " and its attached copy" : ""}: ${JSON.stringify(body)}`);
      if (attached) assert.equal(body.document_url, "notes/scan-7.pdf", "the attached copy of the note was not sent as it was");
    },
  })),
  ...[
    { name: "sales credit note", path: "/sales/credit-notes/new/edit/", write: /\/api\/credit-notes\/$/ },
    { name: "sales debit note", path: "/sales/debit-notes/new/edit/", write: /\/api\/sales-debit-notes\/$/ },
  ].map((row) => ({
    id: `a-new-${row.name.replace(/ /g, "-")}-sends-the-note-typed-on-it`,
    title: `Sales > a new ${row.name}: the note typed in its Notes box reaches the server (the create used to leave the box out)`,
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "POST", re: row.write, reply: () => ok({ id: "n1" }) });
      await page.goto(env.at(row.path), { waitUntil: "networkidle" });
      await pick(page, page.locator('button[aria-label="Customer"]'), "Beta Stores");
      await pick(page, page.locator('button[aria-label="Line 1 product or service"]'), "Consulting");
      await page.getByLabel("Reason").fill("Rate correction");
      await page.getByLabel("Notes", { exact: true }).fill("  Agreed on the phone  ");
      await page.getByRole("button", { name: "Save Draft", exact: true }).click();
      await until(() => stub.writesTo(row.write, "POST").length >= 1, `the new ${row.name} to be sent`, 8000);
      await stub.quiet();
      const sent = stub.writesTo(row.write, "POST");
      assert.equal(sent.length, 1, `expected one create, saw ${sent.length}`);
      assert.equal(JSON.parse(sent[0].body).notes, "Agreed on the phone", `the note typed on the new ${row.name} did not reach the server: ${sent[0].body}`);
    },
  })),
];
