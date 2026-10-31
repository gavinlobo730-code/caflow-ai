/**
 * The ways a person gets to the screen a scenario is about, written once.
 *
 * A scenario that opens an invoice drawer, a bill drawer or a note drawer should say WHAT it opens and not how
 * the product spells the route to it, because the route is the part that changes when a list is redesigned and
 * the claim being driven is not. Each flow sets the tables and the API replies the screen needs, goes there the
 * way a person does (a row click, or a row's Actions menu and View details), and returns the open dialog.
 *
 * Documents are opened THROUGH THE UI and not by a `?doc=` deep link: that parameter only highlights a row on
 * the purchases tab, and a drive that opened a document some other way than a person does would be driving a
 * path nobody takes.
 */
import { ok } from "./stub.mjs";
import { VENDOR, CUSTOMER, CLIENT_ROW, billRow, invoiceDetail, invoiceRow } from "./fixtures.mjs";
import { pick } from "./kit.mjs";

/** The sales invoice drawer for one invoice in the given status. */
export async function openInvoiceDrawer(env, status = "issued", id = "inv-9") {
  const { page, stub, at } = env;
  stub.setTable("client_sales_invoices", [invoiceRow(status, id)]);
  stub.route({ method: "GET", re: new RegExp(`sales-invoices/${id}$`), reply: () => ok(invoiceDetail(status, id)) });
  await page.goto(at("/sales/"), { waitUntil: "networkidle" });
  await page.locator("tr[data-row-clickable]").first().click();
  const drawer = page.getByRole("dialog");
  // "Edit" on a draft, "Edit Details" once it is issued: either says the drawer has loaded its invoice.
  await drawer.getByRole("button", { name: /^Edit/ }).first().waitFor();
  return drawer;
}

/** The purchase bill drawer for one bill in the given status. */
export async function openBillDrawer(env, status = "draft", id = "b9") {
  const { page, stub, at } = env;
  stub.setTable("purchase_bills", [billRow(status, id)]);
  stub.route({ method: "GET", re: new RegExp(`purchase-bills/${id}$`), reply: () => ok(billRow(status, id)) });
  await page.goto(at("/purchases/?tab=bills"), { waitUntil: "networkidle" });
  await page.getByLabel(/Actions for bill/).first().click();
  await page.getByRole("button", { name: "View details" }).click();
  const drawer = page.getByRole("dialog");
  await drawer.getByRole("button", { name: "Edit", exact: true }).first().waitFor();
  return drawer;
}

/**
 * The four note drawers. Each is a list tab over a PostgREST table, a row's Actions menu, View details, and a
 * drawer that reads the note from the API and offers Issue while the note is a draft.
 */
export const NOTE_KINDS = [
  {
    name: "sales credit note", tab: "/sales/?tab=credit-notes", table: "credit_notes", api: "credit-notes",
    row: {
      id: "n9", credit_note_no: "CN-0009", credit_note_date: "2026-10-02", customer_id: CUSTOMER.id,
      sales_invoice_id: null, reason: "Returned goods", taxable_amount_paise: 100000, cgst_paise: 9000,
      sgst_paise: 9000, igst_paise: 0, total_paise: 118000, status: "draft", customers: { name: CUSTOMER.name },
      client_sales_invoices: null,
    },
  },
  {
    name: "sales debit note", tab: "/sales/?tab=debit-notes", table: "sales_debit_notes", api: "sales-debit-notes",
    row: {
      id: "n9", debit_note_no: "DN-0009", debit_note_date: "2026-10-02", customer_id: CUSTOMER.id,
      sales_invoice_id: null, reason: "Late fee", taxable_amount_paise: 100000, cgst_paise: 9000,
      sgst_paise: 9000, igst_paise: 0, total_paise: 118000, status: "draft", customers: { name: CUSTOMER.name },
      client_sales_invoices: null,
    },
  },
  {
    name: "purchase debit note", tab: "/purchases/?tab=debit-notes", table: "debit_notes", api: "debit-notes",
    row: {
      id: "n9", debit_note_no: "PDN-0009", debit_note_date: "2026-10-02", vendor_id: VENDOR.id,
      purchase_bill_id: null, reason: "Short supply", taxable_amount_paise: 100000, cgst_paise: 9000,
      sgst_paise: 9000, igst_paise: 0, total_paise: 118000, status: "draft", purchase_bills: null,
    },
  },
  {
    name: "purchase credit note", tab: "/purchases/?tab=credit-notes", table: "purchase_credit_notes",
    api: "purchase-credit-notes",
    row: {
      id: "n9", credit_note_no: "PCN-0009", credit_note_date: "2026-10-02", vendor_id: VENDOR.id,
      purchase_bill_id: null, reason: "Rate difference", taxable_amount_paise: 100000, cgst_paise: 9000,
      sgst_paise: 9000, igst_paise: 0, total_paise: 118000, status: "draft", purchase_bills: null,
    },
  },
];

export async function openNoteDrawer(env, kind) {
  const { page, stub, at } = env;
  stub.setTable(kind.table, [kind.row]);
  stub.route({
    method: "GET", re: new RegExp(`/api/${kind.api}/n9$`),
    reply: () => ok({ ...kind.row, lines: [], notes: null, is_interstate: false, journal_entry_id: null }),
  });
  stub.route({ method: "POST", re: new RegExp(`/api/${kind.api}/n9/issue$`), reply: () => ok({ id: "n9" }) });
  await page.goto(at(kind.tab), { waitUntil: "networkidle" });
  await page.getByLabel(/Actions for/).first().click();
  await page.getByRole("button", { name: "View details" }).click();
  const drawer = page.getByRole("dialog");
  await drawer.getByRole("button", { name: "Issue", exact: true }).waitFor();
  return drawer;
}

/** The TDS screen with a client chosen, for a person who may record on it. */
async function atTheTdsScreen(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { tds: ["read", "compute", "write"] } }) });
  await page.goto(`${env.base}/tds/`, { waitUntil: "networkidle" });
  await pick(page, page.locator('button:has-text("Select client")').first(), CLIENT_ROW.client_name);
}

/** The "Add TDS Deduction" form, open and filled with everything the server needs but the date. These forms are overlays, not
 *  dialog roles, so the form is found by its heading. Returns the form's locator. */
export async function openTdsDeductionForm(env) {
  const { page } = env;
  await atTheTdsScreen(env);
  await page.getByRole("button", { name: "Add Deduction" }).first().click();
  const form = page.locator("div.fixed").filter({ has: page.getByRole("heading", { name: "Add TDS Deduction" }) });
  await form.waitFor();
  await form.getByPlaceholder("Vendor name").fill("ABC Consulting");
  await form.locator("label:has-text('Gross Payment') + input").fill("100000");
  return form;
}

/** The "Add Challan 281" form, open and filled with everything the server needs but the date. */
export async function openTdsChallanForm(env) {
  const { page } = env;
  await atTheTdsScreen(env);
  await page.getByRole("button", { name: "Challans", exact: true }).click();
  await page.getByRole("button", { name: "Add Challan" }).first().click();
  const form = page.locator("div.fixed").filter({ has: page.getByRole("heading", { name: "Add Challan 281" }) });
  await form.waitFor();
  await form.getByPlaceholder("7-digit BSR code").fill("0510001");
  await form.getByPlaceholder("00001").fill("00045");
  await form.locator("label:has-text('Amount (₹)') + input").fill("125000");
  return form;
}
