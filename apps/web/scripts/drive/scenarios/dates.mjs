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
 * The editors not here (billing, TDS, mark-as-filed, payroll disbursement, asset acquisition and the rest) are
 * the second slice: each is one more row in `EDITORS`, because the claims are the same.
 */
import assert from "node:assert/strict";
import { TZ_MATRIX, pick } from "../kit.mjs";
import { openBillDrawer, openInvoiceDrawer } from "../flows.mjs";
import { ok } from "../stub.mjs";

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
    assert.equal(body[field.key], field.iso, `${spec.title}: ${field.key} should reach the server as ${field.iso}, was ${JSON.stringify(body[field.key])}`);
  }
}

export const scenarios = EDITORS.map((spec) => ({
  id: spec.id,
  title: `${spec.title}: typed dates are read by the one rule and reach the server as ISO`,
  contexts: TZ_MATRIX,
  run: (env) => driveEditor(env, spec),
}));
