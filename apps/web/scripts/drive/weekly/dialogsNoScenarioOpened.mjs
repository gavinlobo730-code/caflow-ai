/**
 * THE CONVERTED DIALOGS NO SCENARIO OPENED FOR THEIR OWN SAKE (POST-A-555, the last part), driven in a browser.
 *
 * POST-A-130 moved every hand-built pop-up onto the shared dialog, side sheet or row menu. Most were driven for the shared piece's promises
 * (a name a screen reader announces, Tab kept inside, the page behind it still, Escape, focus handed back); some were read and type-checked
 * and left standing on the shared piece's own drive. Several of THOSE are opened every night by the date checks, which type a date into them
 * and save, and that is not this check: a dialog can take a date and still have no name. This file holds each of them to the promises.
 *
 * WHAT IS DRIVEN. One scenario per dialog. Each opens the dialog the way a person does (the opener is the date checks' own, so the two cannot
 * disagree about how a screen is reached), and asserts:
 *   - one dialog is open, it has the name the row gives, it says it is modal, and the page behind it cannot scroll;
 *   - Tab and Shift+Tab stay inside it;
 *   - Escape closes it, the page can scroll again, NOTHING was sent, and the keyboard is on a control of the page and not at the top of the
 *     document (the button that opened it, or the page's main region where that button has gone).
 * The openers type into the form on the way (they are the date checks'), so "nothing was sent" is asked of a form somebody had begun.
 *
 * WHAT IS NOT. That a dialog is held while its request is out and shows a refusal inside is driven where each dialog's own file drives it
 * (the nightly `second-click` and `dialog-leftovers` groups and the weekly files of each step); this file does not repeat it. The dialogs
 * still driven by nothing are named on the ledger line.
 *
 * No scenario asserts a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { pick, until } from "../kit.mjs";
import { ok } from "../stub.mjs";
import { CLIENT_ID, CLIENT_ROW, CUSTOMER, ITEM, VENDOR, invoiceRow } from "../fixtures.mjs";
import {
  RECURRING_BILL, RECURRING_INVOICE,
  openRetainer, openRecurringJournalTemplate, openEditRecurringJournal, openEditRecurringBill, openRecurringBillTemplate,
  openRecurringInvoiceTemplate, openEditRecurringInvoice, openApplyStructure, openTaskFromTemplate, openDisbursement, openClientGstr3bCompute,
} from "../scenarios/dates.mjs";

export const group = "dialogs-no-scenario-opened";

const WRITES = ["POST", "PUT", "PATCH", "DELETE"];

/** The dialog on top: is the keyboard inside it? */
const focusInsideTheTopDialog = (page) => page.evaluate(() => {
  const all = [...document.querySelectorAll('[role="dialog"]')];
  const top = all[all.length - 1];
  return !!top && top.contains(document.activeElement);
});

async function tabStaysInside(page, n, what) {
  try {
    await until(() => focusInsideTheTopDialog(page), `the keyboard to be inside ${what}`, 4000);
  } catch (e) {
    const seen = await page.evaluate(() => ({
      dialogs: [...document.querySelectorAll('[role="dialog"]')].map((d) => (d.getAttribute("aria-labelledby") ? document.getElementById(d.getAttribute("aria-labelledby"))?.textContent : d.getAttribute("aria-label")) ?? "(no name)"),
      focus: document.activeElement === document.body ? "the top of the document" : `${document.activeElement?.tagName} ${(document.activeElement?.textContent ?? "").trim().slice(0, 40)}`,
    }));
    throw new Error(`${e.message}; dialogs open: ${JSON.stringify(seen.dialogs)}; the keyboard is on ${seen.focus}`);
  }
  for (let i = 0; i < n; i += 1) {
    await page.keyboard.press("Tab");
    assert.equal(await focusInsideTheTopDialog(page), true, `Tab number ${i + 1} left ${what}`);
  }
  for (let i = 0; i < n; i += 1) {
    await page.keyboard.press("Shift+Tab");
    assert.equal(await focusInsideTheTopDialog(page), true, `Shift+Tab number ${i + 1} left ${what}`);
  }
}

/** Where the keyboard is: "top" for the document itself (the defect), otherwise a few words that say which control. */
const whereTheKeyboardIs = (page) => page.evaluate(() => {
  const el = document.activeElement;
  if (!el || el === document.body || el === document.documentElement) return "top";
  return `${el.tagName.toLowerCase()}${el.id ? `#${el.id}` : ""} ${(el.getAttribute("aria-label") ?? el.textContent ?? "").trim().slice(0, 40)}`;
});

async function heldToTheSharedDialogsPromises(env, c) {
  const { page, stub } = env;
  await c.open(env);
  const dialog = page.getByRole("dialog", { name: c.name });
  await dialog.waitFor();
  assert.equal(await page.getByRole("dialog").count(), 1, `${c.what}: more than one dialog is open`);
  assert.equal(await dialog.getAttribute("aria-modal"), "true", `${c.what} does not say it is modal`);
  assert.equal(await page.evaluate(() => document.body.style.overflow), "hidden", `the page behind ${c.what} can still scroll`);
  await tabStaysInside(page, c.tabs ?? 8, c.what);
  await stub.quiet({ quietMs: 300 }).catch(() => {});
  stub.forgetWrites();
  await page.keyboard.press("Escape");
  await dialog.waitFor({ state: "detached" });
  assert.equal(await page.evaluate(() => document.body.style.overflow), "", `the page is still locked after ${c.what} closed`);
  for (const method of WRITES) {
    assert.equal(stub.writesTo(/./, method).length, 0, `Escape on ${c.what} sent a ${method}`);
  }
  await until(async () => (await whereTheKeyboardIs(page)) !== "top", `the keyboard to be handed back to the page after ${c.what} closed`, 3000);
}

// ── the ways to the dialogs the date checks do not open (they hold no date) ───────────────────────────────────────────────────────────────────

const asPartner = (permissions) => ({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions }) });
const BOOKS = { accounting: ["read", "write", "approve"], sales: ["read", "write"] };

async function openRecurringInvoiceHistory(env) {
  const { page, stub } = env;
  stub.route(asPartner(BOOKS));
  stub.route({ method: "GET", re: /api\/recurring-invoices\?/, reply: () => ok([RECURRING_INVOICE]) });
  stub.setTable("service_catalogue", [{ ...ITEM, kind: "service" }]);
  await page.goto(env.at("/sales/?tab=recurring"), { waitUntil: "networkidle" });
  await page.locator('button[title="History & upcoming"]').first().click();
}

async function openRecurringBillHistory(env) {
  const { page, stub } = env;
  stub.route(asPartner(BOOKS));
  stub.route({ method: "GET", re: /api\/recurring-purchase-bills\?/, reply: () => ok([RECURRING_BILL]) });
  stub.setTable("service_catalogue", [{ ...ITEM, kind: "service" }]);
  await page.goto(env.at("/purchases/?tab=recurring"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "History", exact: true }).first().click();
}

const LEAD = { id: "lead-1", contact_name: "Meera Iyer", phone: "9820012345", email: "meera@example.in", company_name: "Iyer Textiles", entity_type: "Private Limited",
  source: "referral", estimated_value_paise: 1500000, notes: "", stage: "Lead", created_at: "2026-10-01T05:00:00Z" };
const leads = (rows) => ({ method: "GET", re: /api\/lifecycle\/leads\?/, reply: () => ok({ leads: rows, returned: rows.length, has_more: false, limit: 500, max_limit: 500 }) });

async function openEditLead(env) {
  const { page, stub } = env;
  stub.route(leads([LEAD]));
  await page.goto(`${env.base}/pipeline/`, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Edit", exact: true }).first().click();
}

async function openConvertToClient(env) {
  const { page, stub } = env;
  stub.route(leads([{ ...LEAD, stage: "Onboarding" }]));
  await page.goto(`${env.base}/pipeline/`, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Convert to Client", exact: true }).first().click();
}

const OVERDUE = { ...invoiceRow("issued", "inv-9"), due_date: "2026-01-05", is_overdue: true };

async function atAnOverdueInvoicesMenu(env) {
  const { page, stub } = env;
  stub.setTable("client_sales_invoices", [OVERDUE]);
  stub.setTable("customers", [{ ...CUSTOMER, email: "accounts@beta.example.in" }]);
  stub.route({ method: "GET", re: /api\/sales-invoices\/inv-9\/deliveries$/, reply: () => ok([]) });
  await page.goto(env.at("/sales/"), { waitUntil: "networkidle" });
  await page.getByLabel(`Actions for invoice ${OVERDUE.invoice_no}`).click();
}

async function openSendPaymentReminder(env) {
  await atAnOverdueInvoicesMenu(env);
  await env.page.getByRole("button", { name: "Remind", exact: true }).click();
}

async function openDeliveryHistory(env) {
  await atAnOverdueInvoicesMenu(env);
  await env.page.getByRole("button", { name: "Delivery history", exact: true }).click();
}

async function openEditClient(env) {
  const { page } = env;
  await page.goto(`${env.base}/clients/`, { waitUntil: "networkidle" });
  const edit = page.locator('button[title="Edit client"]').first();
  await edit.waitFor({ state: "attached" });
  await edit.hover();
  await edit.click();
}

const EMPLOYEE = { id: "emp-1", client_id: CLIENT_ID, name: "Asha Rao", designation: "Accountant", status: "active", portal_enabled: false,
  basic_paise: 4000000, hra_percent: 40, pf_applicable: true, esi_applicable: false, pt_applicable: true };

async function openPayslipPortal(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /\/api\/clients$/, reply: () => ok({ clients: [CLIENT_ROW], total: 1 }) });
  stub.route({ method: "GET", re: /\/api\/payroll\/employees(\?|$)/, reply: () => ok([EMPLOYEE]) });
  stub.route({ method: "GET", re: /\/api\/payroll\/employees\/emp-1\/portal-status$/, reply: () => ok({ employee_id: "emp-1", email: null, portal_enabled: false,
    activated: false, invite_pending: false, invited_at: null, invite_expires_at: null, activated_at: null }) });
  await page.goto(`${env.base}/payroll/people/`, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Give access" }).first().click();
}

const LETTER = { id: "en-1", engagement_number: "ENG-0001", title: "GST Compliance — FY 2026-27", status: "Draft", fee_amount_paise: 1500000, recipient_name: "Meera Iyer",
  recipient_email: "meera@example.in", lead_id: null, client_id: null, template_id: null, content: "Scope of work.", start_date: "2026-04-01", expiry_date: "2027-03-31", sent_at: null,
  last_sent_at: null, resend_count: 0, signed_at: null, signed_by_name: null, rejected_at: null, rejection_notes: null, sign_token: null, created_at: "2026-10-08T05:00:00Z" };

async function atTheEngagements(env, letters) {
  const { page, stub } = env;
  stub.route(asPartner({ engagements: ["read", "write"], engagement: ["read", "write"], billing: ["read", "write"] }));
  stub.route({ method: "GET", re: /api\/engagement-letters$/, reply: () => ok({ engagements: letters }) });
  stub.route({ method: "GET", re: /api\/engagement-letters\/templates$/, reply: () => ok({ templates: [] }) });
  await page.goto(`${env.base}/engagements/`, { waitUntil: "networkidle" });
}

async function openEngagementTemplateForm(env) {
  await atTheEngagements(env, []);
  await env.page.getByRole("button", { name: "Templates", exact: true }).first().click();
  await env.page.getByRole("button", { name: "New Template", exact: true }).first().click();
}

async function openEngagementLetterDetail(env) {
  await atTheEngagements(env, [LETTER]);
  await env.page.getByText(LETTER.title, { exact: true }).first().click();
}

const STATEMENT = { customer: { id: CUSTOMER.id, name: CUSTOMER.name, email: "accounts@beta.example.in", gstin: null }, period: { start_date: "2026-04-01", end_date: "2026-10-31" },
  opening_balance_paise: 0, closing_balance_paise: 1180000, transactions: [], totals: { invoiced_paise: 1180000, received_paise: 0, credited_paise: 0, transaction_count: 0 } };

async function atACustomersStatement(env) {
  const { page, stub } = env;
  stub.route(asPartner(BOOKS));
  stub.route({ method: "GET", re: /api\/customers\/\?client_id=/, reply: () => ok([{ ...CUSTOMER, email: "accounts@beta.example.in" }]) });
  stub.route({ method: "GET", re: /api\/customer-statements\?/, reply: () => ok(STATEMENT) });
  stub.route({ method: "GET", re: /api\/party-credits\/customer\//, reply: () => ok({ party_type: "customer", party_id: CUSTOMER.id, balance_paise: 500000, entries: [] }) });
  stub.route({ method: "GET", re: /api\/sales-invoices\/\?client_id=.*customer_id=/, reply: () => ok([]) });
  await page.goto(env.at("/sales/?tab=statements"), { waitUntil: "networkidle" });
  await pick(page, page.locator('button[aria-label="Customer"]').first(), CUSTOMER.name);
  await page.getByRole("button", { name: "Generate", exact: true }).first().click();
  await page.getByRole("button", { name: "Email", exact: true }).waitFor();
}

async function openStatementEmail(env) {
  await atACustomersStatement(env);
  await env.page.getByRole("button", { name: "Email", exact: true }).click();
}

async function openStatementApplyCredit(env) {
  await atACustomersStatement(env);
  await env.page.getByRole("button", { name: "Apply", exact: true }).click();
}

const BANK_ACCOUNT = { id: "ba-1", bank_name: "HDFC Bank", account_no: "50100012345678", is_active: true, ledger_account_id: "acc-bank" };
const NO_ENTRIES = { needs_you: 0, proposed: 0, ready: 0, covered: 0, passed: 0, set_aside: 0, to_do: 0, undrafted: 0, trusted_pending: 0, tds_decision_pending: 0 };
const STATEMENT_CSV = "Date,Description,Debit,Credit,Balance\n02/04/2026,Rent,5000.00,,5000.00\n04/04/2026,Receipt,,2000.00,7000.00\n";

async function openTheColumnMapper(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /api\/banking\/accounts/, reply: () => ok([BANK_ACCOUNT]) });
  stub.route({ method: "GET", re: /api\/banking\/entries\/counts/, reply: () => ok(NO_ENTRIES) });
  stub.route({ method: "GET", re: /api\/banking\/entries\?/, reply: () => ok({ rows: [], total: 0, ledger_order: [] }) });
  stub.route({ method: "POST", re: /api\/banking\/statements\/inspect$/, reply: () => ok({
    headers: ["Date", "Description", "Debit", "Credit", "Balance"], sample_rows: [["02/04/2026", "Rent", "5000.00", "", "5000.00"]], total_rows: 2,
    detected_format: "generic", detected_fits: true, proposed_mapping: { date: 0, desc: 1, debit: 2, credit: 3, balance: 4 }, saved_mapping: null, saved_mapping_scope: null,
    header_fingerprint: "fp-1" }) });
  await page.goto(env.at("/bank/"), { waitUntil: "networkidle" });
  const openImport = page.getByRole("button", { name: /Import statement/ }).first();
  await until(async () => (await openImport.count()) > 0 && await openImport.isEnabled(), "Import statement to be offered", 20000);
  await openImport.click();
  await page.getByText("Import Bank Statement").waitFor();
  await page.locator('input[aria-label="Statement File * (.csv, .xlsx or .pdf)"]').setInputFiles({ name: "statement-apr.csv", mimeType: "text/csv", buffer: Buffer.from(STATEMENT_CSV) });
  await page.getByRole("button", { name: /^Map columns$/ }).click();
  await page.getByText("Map the statement columns").waitFor({ timeout: 10000 });
}

const PAYMENT = { id: "pp-1", client_id: CLIENT_ID, vendor_id: VENDOR.id, payment_no: "PAY/2026-27/0001", payment_date: "2026-10-05", amount_paise: 2500000,
  allocated_paise: 0, unallocated_paise: 2500000, tds_paise: 0, payment_mode: "bank", bank_account_id: null, bill_id: null, is_reversed: false, reference_no: null,
  notes: null, vendors: { name: VENDOR.name } };

async function atASupplierPaymentsRow(env) {
  const { page, stub } = env;
  stub.route(asPartner(BOOKS));
  stub.setTable("purchase_payments", [PAYMENT]);
  stub.route({ method: "GET", re: /rcm-documents\/preview\/payment-voucher/, reply: () => ok({ kind: "payment_voucher", section: "CGST Act s.31(3)(g)", rule: "Rule 52", due: false,
    reasons: ["The supplier is registered, so the Act does not ask for a payment voucher on this payment."], gaps: [], vendor_registration: "registered", existing: null, particulars: null }) });
  await page.goto(env.at("/purchases/?tab=payments"), { waitUntil: "networkidle" });
  await page.getByText(PAYMENT.payment_no).first().waitFor();
}

async function openPaymentVoucher(env) {
  await atASupplierPaymentsRow(env);
  await env.page.getByRole("button", { name: "Payment voucher", exact: true }).first().click();
}

async function openApplyPaymentToBills(env) {
  await atASupplierPaymentsRow(env);
  await env.page.getByRole("button", { name: "Apply", exact: true }).first().click();
}

/** The GSTR-3B computed from the books, and the first of its lines that has documents behind it opened as a sheet. */
async function openTheGstDrillThrough(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /api\/gst\/gstr3b\/detail\?/, reply: () => ok({ rows: [], total_taxable_paise: 0, total_igst_paise: 0, total_cgst_paise: 0,
    total_sgst_paise: 0, total_tax_paise: 0 }) });
  await openClientGstr3bCompute(env);
  await page.getByRole("button", { name: "Compute", exact: true }).click();
  // The tables are folded under one line until a person opens them.
  await page.locator("details > summary").first().click();
  const line = page.locator("button", { hasText: "3.1(a) Outward taxable supplies" }).first();
  try { await line.waitFor({ timeout: 6000 }); } catch (e) {
    const seen = await page.evaluate(() => ({ buttons: [...document.querySelectorAll("button")].map((b) => (b.textContent ?? "").trim()).filter(Boolean).slice(0, 40),
      text: (document.querySelector("main")?.innerText ?? "").replace(/\s+/g, " ").slice(0, 600) }));
    throw new Error(`no line with documents behind it is offered || ${JSON.stringify(seen)}`);
  }
  await line.click();
}

const ENTITY = { id: "en-1", full_name: "Asha Rao", entity_type: "Individual", pan: "ABCPR1234K", gstin: null, email: null, phone: null, is_active: true,
  roles: [], relationships: [] };

/** An entity's own page, reached by its address the way a link from the registry reaches it. */
async function openEditEntity(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /\/api\/relationships\/entities\/en-1$/, reply: () => ok(ENTITY) });
  stub.route({ method: "GET", re: /\/api\/relationships\/cross-client-matches\?/, reply: () => ok([]) });
  await page.goto(`${env.base}/relationships/en-1/`, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Edit", exact: true }).first().click();
}

const MEMBER = { user_id: "u-2", user_name: "Asha Rao", user_email: "asha@example.in", role: "Executive", active_tasks: 3, overdue_tasks: 0, due_this_week: 1,
  completed_this_week: 2, weekly_capacity_hours: 40, max_concurrent_tasks: 8, minutes_logged_this_week: 600, utilisation_pct: 25, is_overloaded: false,
  is_underutilised: false, estimated_open_minutes: 0, open_tasks_without_estimate: 3, open_tasks: [] };

async function openEditCapacity(env) {
  const { page, stub } = env;
  stub.route(asPartner({ team: ["read", "write"], task: ["read", "write"], report: ["read"] }));
  stub.route({ method: "GET", re: /\/api\/workload$/, reply: () => ok({ members: [MEMBER], total_active_tasks: 3, total_overdue_tasks: 0, overloaded_count: 0,
    underutilised_count: 0, avg_utilisation_pct: 25 }) });
  await page.goto(`${env.base}/team/workload/`, { waitUntil: "networkidle" });
  await page.locator('button[title="Edit capacity"]').first().click();
}

const DIALOGS = [
  { id: "set-retainer", what: "Set Retainer", where: "Accounting > Retainer > Set retainer", open: openRetainer, name: /^Set Retainer — / },
  { id: "new-recurring-journal", what: "New recurring journal", where: "Accounting > Recurring > New template", open: openRecurringJournalTemplate, name: "New recurring journal" },
  { id: "edit-recurring-journal", what: "Edit recurring journal", where: "Accounting > Recurring > a template's Edit", open: openEditRecurringJournal, name: "Edit recurring journal" },
  { id: "new-recurring-bill", what: "New recurring bill", where: "Purchases > Recurring > New Template", open: openRecurringBillTemplate, name: "New recurring bill", tabs: 12 },
  { id: "edit-recurring-bill", what: "Edit recurring bill", where: "Purchases > Recurring > a template's Edit", open: openEditRecurringBill, name: "Edit recurring bill", tabs: 12 },
  { id: "new-recurring-invoice", what: "New Recurring Template", where: "Sales > Recurring > New Template", open: openRecurringInvoiceTemplate, name: "New Recurring Template", tabs: 12 },
  { id: "edit-recurring-invoice", what: "Edit Recurring Template", where: "Sales > Recurring > a template's Edit", open: openEditRecurringInvoice, name: "Edit Recurring Template", tabs: 12 },
  { id: "recurring-invoice-history", what: "a recurring invoice's history", where: "Sales > Recurring > a template's History & upcoming", open: openRecurringInvoiceHistory, name: RECURRING_INVOICE.title, tabs: 4 },
  { id: "recurring-bill-history", what: "a recurring bill's history", where: "Purchases > Recurring > a template's History", open: openRecurringBillHistory, name: `History of ${RECURRING_BILL.title}`, tabs: 4 },
  { id: "edit-lead", what: "Edit Lead", where: "Pipeline > a lead's Edit", open: openEditLead, name: "Edit Lead", tabs: 12 },
  { id: "convert-to-client", what: "Convert to Client", where: "Pipeline > a lead in Onboarding > Convert to Client", open: openConvertToClient, name: "Convert to Client", tabs: 8 },
  { id: "send-payment-reminder", what: "Send Payment Reminder", where: "Sales > an overdue invoice's menu > Remind", open: openSendPaymentReminder, name: "Send Payment Reminder", tabs: 5 },
  { id: "delivery-history", what: "Delivery History", where: "Sales > an invoice's menu > Delivery history", open: openDeliveryHistory, name: /^Delivery History — /, tabs: 4 },
  { id: "edit-client", what: "Edit Client", where: "Clients > a client's Edit", open: openEditClient, name: "Edit Client", tabs: 14 },
  { id: "mark-payroll-paid", what: "Mark Payroll Paid", where: "Payroll > Release > a released run's Record payment", open: openDisbursement, name: /^Mark Payroll Paid — /, tabs: 8 },
  { id: "payslip-portal", what: "the payslip portal dialog", where: "Payroll people > an employee's Give access", open: openPayslipPortal, name: /^Payslip portal — /, tabs: 5 },
  { id: "engagement-template-form", what: "the engagement template form", where: "Engagements > Templates > New Template", open: openEngagementTemplateForm, name: "New Template", tabs: 8 },
  { id: "engagement-letter-detail", what: "an engagement letter's detail", where: "Engagements > a letter", open: openEngagementLetterDetail, name: LETTER.title, tabs: 6 },
  { id: "statement-email", what: "Email statement to customer", where: "Sales > Statements > Email", open: openStatementEmail, name: "Email statement to customer", tabs: 5 },
  { id: "statement-apply-credit", what: "Apply credit to an invoice", where: "Sales > Statements > a customer with a credit > Apply", open: openStatementApplyCredit, name: "Apply credit to an invoice", tabs: 5 },
  { id: "bank-import-column-mapper", what: "the bank import's column mapper", where: "Bank > Import statement > Map columns", open: openTheColumnMapper, name: "Map the statement columns", tabs: 8 },
  { id: "payment-voucher", what: "the Payment voucher sheet", where: "Purchases > Payments > a payment's Payment voucher", open: openPaymentVoucher, name: "Payment voucher", tabs: 6 },
  { id: "apply-payment-to-bills", what: "applying a supplier payment to bills", where: "Purchases > Payments > a payment with an unallocated balance > Apply", open: openApplyPaymentToBills, name: /^Apply /, tabs: 6 },
  { id: "gst-drill-through", what: "the GST drill-through sheet", where: "Client GST > GSTR-3B > Compute from Books > a line with documents behind it", open: openTheGstDrillThrough, name: "3.1(a) Outward taxable supplies", tabs: 4 },
  { id: "edit-entity", what: "Edit Entity", where: "Relationships > an entity's own page > Edit", open: openEditEntity, name: "Edit Entity", tabs: 10 },
  { id: "edit-capacity", what: "Edit Capacity", where: "Team > Workload > a member's Edit capacity", open: openEditCapacity, name: /^Edit Capacity — /, tabs: 6 },
  { id: "apply-salary-structure", what: "Apply a salary structure", where: "Payroll > Inputs > Apply to employees", open: openApplyStructure, name: /^Apply “Grade A”$/, tabs: 10 },
  { id: "create-task-from-template", what: "Create Task from Template", where: "Tasks > Templates > a template's Create task", open: openTaskFromTemplate, name: "Create Task from Template" },
];

export const scenarios = DIALOGS.map((c) => ({
  id: `${c.id}-is-a-named-modal-dialog-that-keeps-the-keyboard-sends-nothing-on-escape-and-hands-focus-back`,
  title: `${c.where}: a named modal dialog, the page behind it still, Tab and Shift+Tab kept inside, Escape closes it with nothing sent and the keyboard handed back to the page`,
  run: (env) => heldToTheSharedDialogsPromises(env, c),
}));
