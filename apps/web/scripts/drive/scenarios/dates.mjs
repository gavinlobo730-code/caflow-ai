/**
 * Group D: a date a person types is read by one rule, in every money editor, in any browser locale and zone
 * (frontend_ux-19).
 *
 * `<input type="date">` is drawn by the browser, in the browser's locale, and nobody can type 15/03/2026 into a
 * US-locale one. `DateInput` replaced all 172 of them with a text box read by `lib/dates/typedDate`, and the
 * claim that matters, that the date a CA typed is the date the server receives, was driven once, on the journal
 * editor, by a script nobody kept. This drives the same claims on every editor of slice one, under three
 * browser contexts (en-US in Los Angeles, en-IN in Kolkata, en-GB on Kiritimati at UTC+14) with the clock pinned
 * to one instant, so a date read through the browser's own zone arithmetic is a day out in at least one of them.
 *
 * FOR EACH EDITOR, THE SAME SIX CLAIMS
 *   1. there is no native date input on the screen;
 *   2. `15/1` is 15 January of the NEXT year: the short form is read inside the financial year the field is in
 *      (FY 2026-27 at the pinned clock), and `150326` is 15/03/2026;
 *   3. `31/02/2026` is refused, in words, at the field (`aria-invalid` and a `role=alert` sentence);
 *   4. pressing Save over unreadable text sends NOTHING and says so in the form's own sentence, naming the
 *      field (`Payment date: Feb 2026 has only 28 days.`), which is a different sentence from the field's own;
 *   5. a date typed in full reaches the request body as the ISO date typed, whatever the locale or zone.
 *
 * The editors not here (billing, mark-as-filed, payroll disbursement, asset acquisition and the rest) are
 * the second slice: each is one more row in `EDITORS`, because the claims are the same. The TDS deduction and challan
 * forms, the advance-tax register's paid-on date and the section 140A challan's deposit date are rows already.
 */
import assert from "node:assert/strict";
import { TZ_MATRIX, pick, sameTickDouble, expectWrites } from "../kit.mjs";
import { openBillDrawer, openInvoiceDrawer, openTdsChallanForm, openTdsDeductionForm } from "../flows.mjs";
import { ok } from "../stub.mjs";
import { CLIENT_ID } from "../fixtures.mjs";

export const group = "dates";

const FEB_SENTENCE = "Feb 2026 has only 28 days.";

/** Type into a date box the way a person does, and leave it: the value is committed on blur. */
async function typeAndLeave(box, text) {
  await box.fill("");
  await box.pressSequentially(text);
  await box.press("Tab");
  // A committed date can make its parent work out another field (an invoice date re-derives the due date and
  // asks the server for the next number), and that lands after the blur. Typing into the next box before it
  // has landed races it: the derived value is written over, or under, what is being typed. A person is slower
  // than the answer; the script is not, so it waits for the page to go quiet.
  await box.page().waitForLoadState("networkidle");
  await box.page().waitForTimeout(150);
}

// ── how each editor is opened and made otherwise valid ─────────────────────────────────────────────────

async function openJournal(env) {
  env.stub.route({ method: "POST", re: /accounting\/journal$/, reply: () => ok({ id: "j-1" }) });
  const { page } = env;
  await page.goto(env.at("/accounting/journal/new/edit/"), { waitUntil: "networkidle" });
  await page.waitForSelector("#je-narration");
  await page.fill("#je-narration", "Being cash sale");
  await pick(page, page.locator("#je-account-l0"), "Cash in Hand");
  await page.locator('input[aria-label="Debit"]').first().fill("125000");
  await pick(page, page.locator("#je-account-l1"), "Sales");
}

async function openInvoice(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /next-number/, reply: () => ok({ suggested_number: "INV-0001", series_head: "INV-" }) });
  stub.route({ method: "POST", re: /sales-invoices\/$/, reply: () => ok({ id: "inv-1", invoice_no: "INV-0001" }) });
  await page.goto(env.at("/sales/invoices/new/edit/"), { waitUntil: "networkidle" });
  await page.click('button:has-text("Select customer")');
  await page.locator("[role=listbox] [role=option]", { hasText: "Beta Stores" }).first().click();
  await page.click('button[aria-label="Line 1 product or service"]');
  await page.locator("[role=listbox] [role=option]", { hasText: "Consulting" }).first().click();
}

async function openBill(env) {
  const { page, stub } = env;
  stub.route({ method: "POST", re: /purchase-bills\/$/, reply: () => ok({ id: "b-new" }) });
  await page.goto(env.at("/purchases/bills/new/edit/"), { waitUntil: "networkidle" });
  await pick(page, page.locator('button[aria-label="Vendor"]'), "Gamma Supplies");
  await page.fill('input[placeholder="INV-001"]', "GS/2026/114");
  await pick(page, page.locator('button[aria-label="Line 1 product or service"]'), "Consulting");
}

/** The advance-tax register with an estimate typed, so the four instalments (and their paid-on dates) are drawn. */
async function openAdvanceTaxRegister(env) {
  const { page, stub } = env;
  stub.route({ method: "POST", re: /api\/income-tax\/advance-tax(\?|$)/, reply: () => ok({ installments: [], compliance_obligations: [] }) });
  await page.goto(`${env.base}/income-tax/advance-tax/?client_id=${CLIENT_ID}`, { waitUntil: "networkidle" });
  await page.getByPlaceholder("Enter tax amount").fill("100000");
  await page.getByLabel("Instalment 1 paid on").waitFor();
}

/** The §140A challan form on the same screen, filled with everything the server needs but the date. */
async function openSelfAssessmentChallan(env) {
  const { page, stub } = env;
  stub.route({ method: "POST", re: /api\/income-tax\/self-assessment$/, reply: () => ok({ id: "sa-1" }) });
  await page.goto(`${env.base}/income-tax/advance-tax/?client_id=${CLIENT_ID}`, { waitUntil: "networkidle" });
  await page.getByPlaceholder("7 digits").fill("0510001");
  await page.getByPlaceholder("e.g. 00123").fill("00045");
  await page.locator("label:has-text('Tax (₹)') input").first().fill("125000");
}

/** The post-dated cheque form on the sales screen's cheques tab, with the party, the number and the amount filled. */
async function openPostDatedCheque(env) {
  const { page, stub } = env;
  const register = { as_of: "2026-10-31", cheques: [], notes: [], includes_finished: false, summary: {
    received: { due: { count: 0, amount_paise: 0 }, not_due: { count: 0, amount_paise: 0 }, converted: { count: 0, amount_paise: 0 }, cancelled: { count: 0, amount_paise: 0 } },
    issued: { due: { count: 0, amount_paise: 0 }, not_due: { count: 0, amount_paise: 0 }, converted: { count: 0, amount_paise: 0 }, cancelled: { count: 0, amount_paise: 0 } },
  } };
  stub.route({ method: "GET", re: /post-dated-cheques\/options/, reply: () => ok({
    parties: [{ id: "c-beta", name: "Beta Stores", gstin: null }], bank_accounts: [], documents: [],
  }) });
  stub.route({ method: "GET", re: /post-dated-cheques\?/, reply: () => ok(register) });
  stub.route({ method: "POST", re: /post-dated-cheques$/, reply: () => ok({ id: "pdc-1" }) });
  await page.goto(env.at("/sales/?tab=post-dated-cheques"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Record a cheque" }).click();
  await pick(page, page.locator('button[aria-label="Customer"]'), "Beta Stores");
  await page.getByLabel("Cheque number").fill("000451");
  await page.getByLabel("Amount (₹)").fill("25000");
}

/** A modal over a drawer: the open dialog is the last one. */
const modalOf = (page) => page.getByRole("dialog").last();

async function openInvoicePayment(env) {
  const drawer = await openInvoiceDrawer(env, "issued");
  env.stub.route({ method: "POST", re: /receipts\/$/, reply: () => ok({ id: "r1" }) });
  await drawer.getByRole("button", { name: "Record Payment" }).first().click();
  await modalOf(env.page).getByRole("button", { name: "Record Payment", exact: true }).waitFor();
}
async function openBillPayment(env) {
  const drawer = await openBillDrawer(env, "received");
  env.stub.route({ method: "POST", re: /purchase-payments$/, reply: () => ok({ id: "pp1" }) });
  await drawer.getByRole("button", { name: "Record Payment" }).first().click();
  await modalOf(env.page).getByRole("button", { name: "Record Payment", exact: true }).waitFor();
}
/** The invoice drawer for an issued invoice that has a DRAFT e-invoice record and a DRAFT e-way bill record, which is when it offers Record. */
const IRN_RECORD = { id: "ei-1", sales_invoice_id: "inv-9", status: "draft", irn: null, created_at: "2026-10-01T00:00:00Z" };
const EWAY_RECORD = { id: "ew-1", sales_invoice_id: "inv-9", status: "draft", ewb_number: null, created_at: "2026-10-01T00:00:00Z" };
const recordsWindow = (rows) => ok({ records: rows, returned: rows.length, has_more: false, limit: 100, max_limit: 500 });
async function openInvoiceWithDraftRecords(env) {
  env.stub.route({ method: "GET", re: /einvoice\/records\?/, reply: () => recordsWindow([IRN_RECORD]) });
  env.stub.route({ method: "GET", re: /eway-bill\/records\?/, reply: () => recordsWindow([EWAY_RECORD]) });
  env.stub.route({
    method: "GET", re: /eway-bill\/records\/ew-1\/validity/,
    reply: () => ok({ valid_upto: null, days: null, slab_km: null, source: null, caveat: null, gap: null }),
  });
  return openInvoiceDrawer(env, "issued");
}
async function openRecordIrn(env) {
  env.stub.route({ method: "POST", re: /einvoice\/records\/ei-1\/irn-generated$/, reply: () => ok({ id: "ei-1" }) });
  const drawer = await openInvoiceWithDraftRecords(env);
  await drawer.getByRole("button", { name: "Record IRN", exact: true }).click();
  const modal = modalOf(env.page);
  await modal.getByRole("button", { name: "Record IRN", exact: true }).waitFor();
  await modal.getByPlaceholder("64-char IRN").fill("a".repeat(64));
  await modal.locator("label:has-text('Acknowledgement no.') input").fill("112600000001");
}
async function openRecordEway(env) {
  env.stub.route({ method: "POST", re: /eway-bill\/records\/ew-1\/generated$/, reply: () => ok({ id: "ew-1" }) });
  const drawer = await openInvoiceWithDraftRecords(env);
  await drawer.getByRole("button", { name: "Record E-Way Bill", exact: true }).click();
  const modal = modalOf(env.page);
  await modal.getByRole("button", { name: "Record E-Way Bill", exact: true }).waitFor();
  await modal.getByPlaceholder("12-digit EWB no.").fill("141000000001");
}
/** A "Create … Note" modal over an issued invoice (sales) or a received bill (purchase). */
function openNoteModal(side, opener) {
  return async (env) => {
    const drawer = side === "sales"
      ? await openInvoiceDrawer(env, "issued")
      : await openBillDrawer(env, "received");
    await drawer.getByRole("button", { name: opener.action, exact: true }).first().click();
    await modalOf(env.page).getByRole("button", { name: opener.submit, exact: true }).waitFor();
    env.stub.route({ method: "POST", re: opener.write, reply: () => ok({ id: "n1" }) });
  };
}

/**
 * The editors. `fields[0]` is the PRIMARY date: the one whose anchor is today, so `15/1` resolves against the
 * pinned financial year. A later field is anchored to the first (a due date to its invoice date) and is held to
 * the claims that do not depend on the anchor.
 */
const EDITORS = [
  {
    id: "journal", title: "journal editor", open: openJournal,
    fields: [{ box: (p) => p.locator("#je-date"), label: "Date", key: "entry_date", full: "15/07/2026", iso: "2026-07-15" }],
    save: (p) => p.getByRole("button", { name: "Post Entry" }), write: /accounting\/journal$/,
  },
  {
    id: "sales-invoice", title: "sales invoice editor", open: openInvoice,
    fields: [
      { box: (p) => p.locator("#inv-date"), label: "Invoice date", key: "invoice_date", full: "15/07/2026", iso: "2026-07-15" },
      { box: (p) => p.locator("#inv-due-date"), label: "Due date", key: "due_date", full: "14/08/2026", iso: "2026-08-14" },
    ],
    save: (p) => p.getByRole("button", { name: "Save Draft" }), write: /sales-invoices\/$/,
  },
  {
    id: "purchase-bill", title: "purchase bill editor", open: openBill,
    fields: [
      { box: (p) => p.locator("#bill-date"), label: "Bill date", key: "bill_date", full: "15/07/2026", iso: "2026-07-15" },
      { box: (p) => p.locator("#bill-due-date"), label: "Due date", key: "due_date", full: "14/08/2026", iso: "2026-08-14" },
    ],
    save: (p) => p.getByRole("button", { name: "Save Draft" }), write: /purchase-bills\/$/,
  },
  {
    id: "sales-record-payment", title: "Record Payment on an invoice", open: openInvoicePayment,
    fields: [{ box: (p) => modalOf(p).locator('input[aria-label="Payment date"]'), label: "Payment date", key: "receipt_date", full: "15/07/2026", iso: "2026-07-15" }],
    save: (p) => modalOf(p).getByRole("button", { name: "Record Payment", exact: true }), write: /receipts\/$/,
  },
  {
    id: "purchase-record-payment", title: "Record Payment on a bill", open: openBillPayment,
    fields: [{ box: (p) => modalOf(p).locator('input[aria-label="Payment date"]'), label: "Payment date", key: "payment_date", full: "15/07/2026", iso: "2026-07-15" }],
    save: (p) => modalOf(p).getByRole("button", { name: "Record Payment", exact: true }), write: /purchase-payments$/,
  },
  {
    id: "record-irn", title: "Record IRN on an issued invoice", open: openRecordIrn,
    fields: [{ box: (p) => modalOf(p).locator('input[aria-label="Acknowledgement date"]'), label: "Acknowledgement date", key: "ack_date", full: "15/07/2026", iso: "2026-07-15" }],
    save: (p) => modalOf(p).getByRole("button", { name: "Record IRN", exact: true }), write: /einvoice\/records\/ei-1\/irn-generated$/,
  },
  {
    id: "record-eway-bill", title: "Record E-Way Bill on an issued invoice", open: openRecordEway,
    fields: [
      { box: (p) => modalOf(p).locator('input[aria-label="EWB date"]'), label: "EWB date", key: "ewb_date", full: "15/07/2026", iso: "2026-07-15" },
      { box: (p) => modalOf(p).locator('input[aria-label="Valid upto"]'), label: "Valid upto", key: "ewb_valid_upto", full: "16/07/2026", iso: "2026-07-16" },
    ],
    save: (p) => modalOf(p).getByRole("button", { name: "Record E-Way Bill", exact: true }), write: /eway-bill\/records\/ew-1\/generated$/,
  },
  {
    id: "tds-deduction", title: "TDS deduction form",
    open: openTdsDeductionForm,
    fields: [{ box: (p) => p.locator("#tds-payment-date"), label: "Payment date", key: "transaction_date", full: "15/07/2026", iso: "2026-07-15" }],
    save: (p) => p.locator("div.fixed").getByRole("button", { name: "Add Deduction", exact: true }), write: /tds-workspace\/deductions$/,
  },
  {
    id: "tds-challan", title: "TDS challan form",
    open: openTdsChallanForm,
    fields: [{ box: (p) => p.locator("#tds-challan-date"), label: "Challan date", key: "challan_date", full: "15/07/2026", iso: "2026-07-15" }],
    save: (p) => p.locator("div.fixed").getByRole("button", { name: "Add", exact: true }), write: /tds-workspace\/challans$/,
  },
  {
    id: "advance-tax-register", title: "advance-tax register",
    open: openAdvanceTaxRegister,
    fields: [{
      box: (p) => p.getByLabel("Instalment 1 paid on"), label: "Instalment 1 paid on", key: "installments[0].paid_date",
      read: (b) => b.installments?.[0]?.paid_date, full: "15/07/2026", iso: "2026-07-15",
    }],
    save: (p) => p.getByRole("button", { name: "Save", exact: true }), write: /api\/income-tax\/advance-tax(\?|$)/,
  },
  {
    id: "self-assessment-challan", title: "§140A challan form",
    open: openSelfAssessmentChallan,
    fields: [{ box: (p) => p.locator("#sa-deposit-date"), label: "Deposited on", key: "deposit_date", full: "15/07/2026", iso: "2026-07-15" }],
    save: (p) => p.getByRole("button", { name: "Record challan" }), write: /api\/income-tax\/self-assessment$/,
  },
  {
    id: "post-dated-cheque", title: "post-dated cheque form", open: openPostDatedCheque,
    fields: [{ box: (p) => p.getByLabel("Cheque date"), label: "Cheque date", key: "cheque_date", full: "15/11/2026", iso: "2026-11-15" }],
    save: (p) => p.getByRole("button", { name: "Record cheque", exact: true }), write: /post-dated-cheques$/,
  },
  ...[
    { side: "sales", name: "sales credit note", action: "Credit Note", submit: "Create Credit Note", label: "Credit note date", key: "credit_note_date", write: /\/api\/credit-notes\/$/ },
    { side: "sales", name: "sales debit note", action: "Debit Note", submit: "Create Debit Note", label: "Debit note date", key: "debit_note_date", write: /\/api\/sales-debit-notes\/$/ },
    { side: "purchase", name: "purchase debit note", action: "Debit Note", submit: "Create Debit Note", label: "Debit note date", key: "debit_note_date", write: /\/api\/debit-notes\/$/ },
    { side: "purchase", name: "purchase credit note", action: "Credit Note", submit: "Create Credit Note", label: "Credit note date", key: "credit_note_date", write: /\/api\/purchase-credit-notes\/$/ },
  ].map((n) => ({
    id: n.name.replace(/ /g, "-"), title: `${n.name} modal`, open: openNoteModal(n.side, n),
    fields: [{ box: (p) => modalOf(p).locator(`input[aria-label="${n.label}"]`), label: n.label, key: n.key, full: "15/07/2026", iso: "2026-07-15" }],
    save: (p) => modalOf(p).getByRole("button", { name: n.submit, exact: true }), write: n.write,
  })),
];

async function driveEditor(env, spec) {
  const { page, stub } = env;
  await spec.open(env);

  // 1. No native date input anywhere on the screen.
  assert.equal(await page.locator('input[type="date"]').count(), 0,
    `${spec.title}: a native <input type="date"> is on the screen (it is drawn in the browser's locale)`);

  const primary = spec.fields[0].box(page);
  // 2. The short form is read inside the financial year the field is in.
  await typeAndLeave(primary, "15/1");
  assert.equal(await primary.inputValue(), "15/01/2027", `${spec.title}: 15/1 in FY 2026-27 is 15 January 2027`);
  await typeAndLeave(primary, "150326");
  assert.equal(await primary.inputValue(), "15/03/2026", `${spec.title}: 150326 is 15/03/2026`);
  assert.notEqual(await primary.getAttribute("aria-invalid"), "true", `${spec.title}: a readable date is marked invalid`);

  // 3. A day that does not exist is refused, in words, at the field.
  for (const field of spec.fields) {
    const box = field.box(page);
    await typeAndLeave(box, "31/02/2026");
    assert.equal(await box.getAttribute("aria-invalid"), "true", `${spec.title} / ${field.label}: 31/02/2026 is not marked invalid`);
    const alerts = (await page.locator("[role=alert]").allInnerTexts()).join(" | ");
    assert.ok(alerts.includes(FEB_SENTENCE), `${spec.title} / ${field.label}: the field's own sentence is missing (alerts: ${alerts.slice(0, 200)})`);
    await typeAndLeave(box, "15/03/2026"); // put it right again, so the next field is judged alone
  }

  // 4. Save over unreadable text sends nothing and names the field.
  const first = spec.fields[0];
  await typeAndLeave(primary, "31/02/2026");
  await spec.save(page).click();
  await page.getByText(`${first.label}: ${FEB_SENTENCE}`).first().waitFor({ timeout: 4000 }).catch(() => {
    throw new Error(`${spec.title}: Save over an unreadable date did not say "${first.label}: ${FEB_SENTENCE}"`);
  });
  await stub.quiet();
  assert.equal(stub.writesTo(spec.write).length, 0, `${spec.title}: Save over an unreadable date SENT A WRITE`);

  // 5. The date typed in full is the ISO date the server receives.
  for (const field of spec.fields) await typeAndLeave(field.box(page), field.full);
  for (const field of spec.fields) {
    assert.equal(await field.box(page).inputValue(), field.full, `${spec.title} / ${field.label}: ${field.full} did not stay as typed`);
  }
  await spec.save(page).click();
  await stub.quiet();
  const writes = stub.writesTo(spec.write);
  assert.equal(writes.length, 1, `${spec.title}: expected one write, saw ${writes.length} (${stub.allWrites().map((w) => w.method + " " + w.path).join(", ") || "none"})`);
  const body = JSON.parse(writes[0].body);
  for (const field of spec.fields) {
    const got = field.read ? field.read(body) : body[field.key];
    assert.equal(got, field.iso, `${spec.title}: ${field.key} should reach the server as ${field.iso}, was ${JSON.stringify(got)}`);
  }
}

export const scenarios = [
  ...EDITORS.map((spec) => ({
    id: spec.id,
    title: `${spec.title}: typed dates are read by the one rule and reach the server as ISO`,
    contexts: TZ_MATRIX,
    run: (env) => driveEditor(env, spec),
  })),
  // The two Record modals hand the write's promise back to the shared Button, which is what holds the second click of a double click.
  ...[
    { id: "record-irn", open: openRecordIrn, name: "Record IRN", write: /einvoice\/records\/ei-1\/irn-generated$/ },
    { id: "record-eway-bill", open: openRecordEway, name: "Record E-Way Bill", write: /eway-bill\/records\/ew-1\/generated$/ },
  ].map((m) => ({
    id: `${m.id}-sends-one-request-for-two-clicks-in-the-same-moment`,
    title: `${m.name}: a same-tick double click on the modal's button sends ONE request`,
    async run(env) {
      await m.open(env);
      await sameTickDouble(modalOf(env.page).getByRole("button", { name: m.name, exact: true }));
      await expectWrites(env.stub, m.write, 1, `two same-tick clicks on ${m.name}`);
    },
  })),
  // A date that belongs AFTER another is read after it. The anchor's financial year decides the year of a short form, so a valid-upto typed `2/4`
  // beside a bill dated 31/03/2027 (the last day of FY 2026-27) came out as 02/04/2026, a year BEFORE the bill, and the field showed it without a word.
  {
    id: "record-eway-bill-a-short-valid-upto-is-read-after-the-bill-date",
    title: "Record E-Way Bill: a short valid-upto beside a bill dated on the last day of the financial year is read in the NEXT year, and a typed year is left alone",
    contexts: TZ_MATRIX,
    async run(env) {
      const { page, stub } = env;
      await openRecordEway(env);
      const bill = modalOf(page).locator('input[aria-label="EWB date"]');
      const valid = modalOf(page).locator('input[aria-label="Valid upto"]');
      await typeAndLeave(bill, "31/03/2027");
      await typeAndLeave(valid, "2/4");
      assert.equal(await valid.inputValue(), "02/04/2027", "2/4 beside a bill of 31/03/2027 was read before the bill");
      await typeAndLeave(valid, "0204");
      assert.equal(await valid.inputValue(), "02/04/2027", "the four-digit short form moved differently");
      await typeAndLeave(valid, "2/4/2026");
      assert.equal(await valid.inputValue(), "02/04/2026", "a year the person typed was moved");
      await modalOf(page).getByText(/is before 31 Mar 2027/).waitFor({ timeout: 4000 }).catch(() => {
        throw new Error("a valid-upto typed in full before the bill's date was shown no hint");
      });
      await typeAndLeave(valid, "2/4");
      await modalOf(page).getByRole("button", { name: "Record E-Way Bill", exact: true }).click();
      await stub.quiet();
      const writes = stub.writesTo(/eway-bill\/records\/ew-1\/generated$/);
      assert.equal(writes.length, 1, `expected one write, saw ${writes.length}`);
      const body = JSON.parse(writes[0].body);
      assert.equal(body.ewb_date, "2027-03-31");
      assert.equal(body.ewb_valid_upto, "2027-04-02", "the valid-upto that reached the server is the one before the bill");
    },
  },
  // A required date that is CLEARED reports "empty", not a problem, so a gate over unreadable text alone sends a blank (the server takes it into a
  // timestamp column and answers with a database error). The Record modals refuse it in a sentence of their own and send nothing.
  ...[
    { id: "record-irn-ack-date", open: openRecordIrn, name: "Record IRN", write: /einvoice\/records\/ei-1\/irn-generated$/,
      box: (p) => modalOf(p).locator('input[aria-label="Acknowledgement date"]'), sentence: "Acknowledgement date: enter the date from the IRP portal." },
    { id: "record-eway-bill-ewb-date", open: openRecordEway, name: "Record E-Way Bill", write: /eway-bill\/records\/ew-1\/generated$/,
      box: (p) => modalOf(p).locator('input[aria-label="EWB date"]'), sentence: "EWB date: enter the date from the NIC portal." },
    { id: "record-eway-bill-valid-upto", open: openRecordEway, name: "Record E-Way Bill", write: /eway-bill\/records\/ew-1\/generated$/,
      box: (p) => modalOf(p).locator('input[aria-label="Valid upto"]'), sentence: "Valid upto: enter the date from the NIC portal." },
  ].map((c) => ({
    id: `${c.id}-cleared-is-refused-in-a-sentence-and-sends-nothing`,
    title: `${c.name}: a cleared ${c.sentence.split(":")[0]} is refused in its own sentence and nothing is sent`,
    async run(env) {
      const { page, stub } = env;
      await c.open(env);
      await typeAndLeave(c.box(page), "");
      await modalOf(page).getByRole("button", { name: c.name, exact: true }).click();
      await page.getByText(c.sentence).first().waitFor({ timeout: 4000 }).catch(() => {
        throw new Error(`${c.name} over a cleared date did not say "${c.sentence}"`);
      });
      await stub.quiet();
      assert.equal(stub.writesTo(c.write).length, 0, `${c.name} over a cleared date SENT A WRITE`);
    },
  })),
  // A screen that is about ONE financial year says so to its date boxes. Every row above leaves the screen on the current year, where
  // "the year of today" and "the year of the screen" are the same year and a box that forgot to be told would still pass.
  {
    id: "a-short-date-is-read-inside-the-year-the-screen-is-about",
    title: "on the advance-tax register set to the previous year, 15/3 in a paid-on box is 15 March of THAT year",
    contexts: TZ_MATRIX,
    async run(env) {
      const { page } = env;
      await page.goto(`${env.base}/income-tax/advance-tax/?client_id=${CLIENT_ID}`, { waitUntil: "networkidle" });
      // The year picker is the one select that offers the previous year; the clock is pinned in FY 2026-27, so 2025-26 is the previous.
      await page.locator("select").filter({ has: page.locator('option[value="2025-26"]') }).first().selectOption("2025-26");
      await page.getByPlaceholder("Enter tax amount").fill("100000");
      const box = page.getByLabel("Instalment 1 paid on");
      await box.waitFor();
      await typeAndLeave(box, "15/3");
      assert.equal(await box.inputValue(), "15/03/2026", "15/3 on the 2025-26 screen was read inside the year of today, not the screen's year");
    },
  },
];
