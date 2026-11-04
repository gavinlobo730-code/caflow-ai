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
 * The second slice (4-11-2026) added Mark as Filed (the one prompt Deadlines, a client's Compliance tab and Practice Compliance
 * share), the fee engagement and fee receipt forms, a customer receipt, the retainer, the payroll disbursement prompt, an asset's
 * purchase and disposal dates, the three Work in Progress forms, an opening invoice or bill, a Bill of Entry and the sales and
 * purchase cycle forms. Each is one row in `EDITORS`, because the claims are the same; the ones not here are listed on ledger
 * line PRE-A-015. The TDS deduction and challan forms, the advance-tax register's paid-on date and the section 140A challan's
 * deposit date were rows before it.
 *
 * A prompt may HOLD its button while the text is unreadable instead of refusing the click in a sentence (`heldWhileUnreadable`):
 * Mark as Filed does, so the claim there is a disabled button, the field's own sentence, and no write.
 */
import assert from "node:assert/strict";
import { TZ_MATRIX, pick, sameTickDouble, expectWrites, until } from "../kit.mjs";
import { openBillDrawer, openInvoiceDrawer, openTdsChallanForm, openTdsDeductionForm } from "../flows.mjs";
import { ok } from "../stub.mjs";
import { CLIENT_ID, CLIENT_ROW, PAYROLL_RUN } from "../fixtures.mjs";

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

/** The Add Asset drawer on the register, its categories loaded and the name and cost typed, so only the date is left. */
async function openAddAsset(env) {
  const { page, stub } = env;
  stub.setTable("fixed_assets", []);
  stub.route({ method: "GET", re: /fixed-assets\/categories/, reply: () => ok([{
    category: "Computers and data processing", depreciable: true, residual_value_cap_percent: 5,
    classes: [{ label: "Laptops and desktops", useful_life_years: 3, wdv_rate_percent: 63.16 }],
  }]) });
  stub.route({ method: "POST", re: /api\/fixed-assets$/, reply: () => ok({ id: "fa-1" }) });
  await page.goto(env.at("/fixed-assets/"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Add Asset" }).first().click();
  const name = page.getByPlaceholder("e.g. Dell Laptop SN12345");
  await name.waitFor();
  // The category list lands after the drawer opens; the form is not ready until it has chosen the first one.
  await page.locator("select", { has: page.locator("option", { hasText: "Computers and data processing" }) })
    .and(page.locator("select")).first().waitFor();
  await name.fill("Dell Laptop");
  await page.getByPlaceholder("100000").fill("125000");
}

/** The Disposal tab with one live asset chosen and the proceeds typed, so only the date is left. */
async function openDisposal(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /api\/fixed-assets\?client_id=/, reply: () => ok([{
    id: "fa-9", asset_code: "FA-0009", asset_name: "Dell Laptop", asset_category: "Computers and data processing",
    purchase_date: "2025-04-01", purchase_cost_paise: 12500000, salvage_value_paise: 0, depreciation_method: "WDV",
    wdv_rate_percent: 63.16, accumulated_depreciation_paise: 2000000, is_disposed: false, current_wdv_paise: 10500000,
  }]) });
  stub.route({ method: "PATCH", re: /api\/fixed-assets\/fa-9\/dispose$/, reply: () => ok({ gain_loss_paise: 0, part_month_depreciation_not_charged: false }) });
  await page.goto(env.at("/fixed-assets/"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Disposal", exact: true }).click();
  await page.getByRole("button", { name: "Dispose", exact: true }).first().click();
  await page.getByText("Dispose: Dell Laptop").waitFor();
  await page.locator("label:has-text('Sale Proceeds') input").fill("90000");
}

/** The Monthly Retainer Tracker with the "Set retainer" form open, the fee and the service chosen, so only the date is left. */
async function openRetainer(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /billing\/schedules/, reply: () => ok([]) });
  stub.route({ method: "GET", re: /billing\/service-options$/, reply: () => ok({
    internal_client_id: CLIENT_ID,
    services: [{ id: "sv-1", name: "Monthly retainer", hsn_sac: "998221", default_rate_paise: 1500000, gst_rate_bps: 1800 }],
  }) });
  stub.route({ method: "POST", re: /billing\/schedules$/, reply: () => ok({ id: "bs-1" }) });
  await page.goto(`${env.base}/accounting/retainer/`, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: /Set retainer/ }).first().click();
  await page.locator("#retainer-fee").fill("15000");
  await page.locator("#retainer-service").selectOption("sv-1");
}

/** The client's payroll Release tab with a finalised run and the "Record payment" prompt open on a linked bank account. */
async function openDisbursement(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /payroll\/runs\?/, reply: () => ok([{ ...PAYROLL_RUN, client_id: CLIENT_ID }]) });
  stub.route({ method: "GET", re: /banking\/accounts/, reply: () => ok([
    { id: "ba-1", bank_name: "HDFC Bank", account_no: "50100012345678", coa_account_id: "a1", is_active: true },
  ]) });
  stub.route({ method: "POST", re: /payroll\/runs\/run1\/disburse$/, reply: () => ok({ id: "run1", status: "paid" }) });
  await page.goto(env.at("/payroll/?tab=release"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Record payment", exact: true }).first().click();
  await page.locator("#disburse-date").waitFor();
}

/** The Opening Balances tab with the "Add a document" drawer open on a customer, a number and an amount, so only the dates are left. */
async function openOpeningDocument(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /api\/customers/, reply: () => ok([{ id: "cu1", name: "Beta Stores" }]) });
  stub.route({ method: "POST", re: /api\/opening-documents$/, reply: () => ok({ id: "od-1" }) });
  await page.goto(env.at("/accounting/?tab=opening-balances"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Add a document" }).first().click();
  await page.getByText("Add an opening invoice").waitFor();
  await page.locator("label:has-text('Customer') select").selectOption("cu1");
  await page.locator("label:has-text('Invoice number') input").fill("OLD/2025/0042");
  await page.locator("label:has-text('Still outstanding') input").fill("15000");
}

/** The Bills of Entry tab with "Record a Bill of Entry" open, the number and the assessable value typed, so only the date is left. */
async function openBillOfEntry(env) {
  const { page, stub } = env;
  stub.route({ method: "POST", re: /api\/bills-of-entry$/, reply: () => ok({ id: "be-1" }) });
  await page.goto(env.at("/purchases/?tab=bills-of-entry"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Record a Bill of Entry" }).first().click();
  await page.getByPlaceholder("e.g. 1234567").fill("1234567");
  await page.locator("label:has-text('Assessable value') input").fill("100000");
}

/** The Work in Progress tab with one live project, for the three forms that carry a date (new project, a cost on it, capitalising it). */
async function atCwip(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /api\/cwip\?client_id=/, reply: () => ok({
    does_not_depreciate: "Capital work in progress is not depreciated.",
    projects: [{ id: "p1", project_code: "BLD-1", project_name: "Warehouse", started_on: "2026-04-10", approved_cost_paise: 500000000,
      status: "in_progress", incurred_paise: 120000000, over_approved_cost: false }],
  }) });
  stub.route({ method: "GET", re: /api\/cwip\/schedules/, reply: () => ok({
    ageing: { as_of: "2026-10-08", bucket_order: [], bucket_labels: {}, row_order: [], row_labels: {}, rows: {}, total_paise: 0, notes: [] },
    completion_schedule: { bucket_labels: {}, rows: [], gaps: [] },
    does_not_depreciate: "Capital work in progress is not depreciated.",
  }) });
  await page.goto(env.at("/fixed-assets/"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Work in Progress", exact: true }).click();
  await page.getByText("Warehouse").first().waitFor();
}
async function openCwipProject(env) {
  env.stub.route({ method: "POST", re: /api\/cwip$/, reply: () => ok({ id: "p2" }) });
  await atCwip(env);
  await env.page.getByRole("button", { name: "New project" }).click();
  await modalOf(env.page).getByRole("button", { name: "Create", exact: true }).waitFor();
  await modalOf(env.page).locator("label:has-text('Project name') input").fill("Showroom");
}
async function openCwipCost(env) {
  env.stub.route({ method: "POST", re: /api\/cwip\/p1\/costs$/, reply: () => ok({ id: "c1" }) });
  await atCwip(env);
  await env.page.getByRole("button", { name: "Add cost", exact: true }).click();
  await modalOf(env.page).getByRole("button", { name: "Record", exact: true }).waitFor();
  await modalOf(env.page).getByPlaceholder("Contractor running bill").fill("Running bill 4");
  await modalOf(env.page).locator("label:has-text('Amount (₹)') input").fill("250000");
}
async function openCwipCapitalise(env) {
  env.stub.route({ method: "POST", re: /api\/cwip\/p1\/capitalise$/, reply: () => ok({ id: "fa-5" }) });
  await atCwip(env);
  await env.page.getByRole("button", { name: /Capitalise/ }).first().click();
  await modalOf(env.page).getByRole("button", { name: "Capitalise", exact: true }).waitFor();
}

/** The Orders & Goods Receipts tab with the "New" form open on a supplier, a number and one line. `tab` is "orders" or "receipts". */
function openPurchaseCycleForm(tab) {
  return async (env) => {
    const { page, stub } = env;
    stub.route({ method: "GET", re: /api\/vendors/, reply: () => ok([{ id: "v1", name: "Gamma Supplies" }]) });
    stub.route({ method: "POST", re: /api\/purchase-cycle\/(orders|receipts)$/, reply: () => ok({ id: "pc-1" }) });
    await page.goto(env.at("/purchases/?tab=purchase-cycle"), { waitUntil: "networkidle" });
    if (tab === "receipts") await page.getByRole("button", { name: "Goods Receipts", exact: true }).click();
    await page.getByRole("button", { name: "New", exact: true }).click();
    await page.locator("label:has-text('Supplier') select").first().selectOption("v1");
    await page.locator("label:has-text('Number') input").first().fill(tab === "orders" ? "PO/2026-27/0001" : "GRN/2026-27/0001");
    await page.getByLabel("Line 1 description").fill("Paper");
  };
}

/** The Quotes, Orders & Challans tab with "New" open on a customer, a number and one line. `tab` is the tab's own label. */
function openSalesCycleForm(tab, number) {
  return async (env) => {
    const { page, stub } = env;
    stub.route({ method: "GET", re: /api\/customers/, reply: () => ok([{ id: "cu1", name: "Beta Stores" }]) });
    stub.route({ method: "GET", re: /sales-cycle\/vocabulary$/, reply: () => ok({
      quote_kinds: [{ value: "quotation", label: "Quotation" }, { value: "proforma", label: "Proforma invoice" }],
      quote_statuses: [], order_statuses: [], challan_statuses: [],
      challan_reasons: [{ value: "supply", label: "Supply of goods", is_a_supply: true }],
      goods_kinds: [{ value: "inputs", label: "Inputs" }],
      not_a_tax_invoice: "This is not a tax invoice.", no_tax_on_a_non_supply: "No tax is charged on a non-supply.",
      job_work_exclusion: "", rule_55_5_steps: [], copies: [], itc_04: { decided: false, readings: [], refusal: "" },
    }) });
    stub.route({ method: "POST", re: /api\/sales-cycle\/(quotations|orders|challans)$/, reply: () => ok({ id: "sc-1" }) });
    await page.goto(env.at("/sales/?tab=sales-cycle"), { waitUntil: "networkidle" });
    await page.getByRole("button", { name: tab, exact: true }).click();
    await page.getByRole("button", { name: "New", exact: true }).click();
    await page.getByText("Number", { exact: true }).waitFor();
    await page.locator("select:has(option[value='cu1'])").first().selectOption("cu1");
    await page.locator("label:has-text('Number') input").first().fill(number);
    await page.getByLabel("Line 1 description").fill("Consulting");
  };
}

/** The client's Receipts tab with "Record Receipt" open on a customer and an amount, so only the date is left. */
async function openCustomerReceipt(env) {
  const { page, stub } = env;
  stub.route({ method: "POST", re: /api\/receipts\/$/, reply: () => ok({ id: "r-new" }) });
  await page.goto(env.at("/sales/?tab=receipts"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Record Receipt" }).first().click();
  await page.locator("#receipt-date").waitFor();
  await pick(page, page.locator('button[aria-label="Customer"]'), "Beta Stores");
  await page.getByLabel("Amount (₹)").fill("25000");
}

/** One of the four note editors, opened on a new note with the party and one line chosen so only the date is left. */
function openNoteEditor({ path, party, write }) {
  return async (env) => {
    const { page, stub } = env;
    stub.route({ method: "POST", re: write, reply: () => ok({ id: "note-new" }) });
    await page.goto(env.at(path), { waitUntil: "networkidle" });
    await pick(page, page.locator(`button[aria-label="${party.label}"]`), party.name);
    await pick(page, page.locator('button[aria-label="Line 1 product or service"]'), "Consulting");
    await page.getByLabel("Reason").fill("Rate correction");
  };
}

/** Loans & Fixed Deposits: the "Add Loan" or "Add FD" form open on a client and the amounts, so only the dates are left. */
function openLoanOrDeposit(kind) {
  return async (env) => {
    const { page } = env;
    await page.goto(`${env.base}/accounting/loans/`, { waitUntil: "networkidle" });
    if (kind === "fd") await page.getByRole("button", { name: /Fixed Deposits/ }).first().click();
    await page.getByRole("button", { name: kind === "loan" ? "Add Loan" : "Add FD", exact: true }).first().click();
    const form = page.locator("div.fixed").filter({ has: page.getByRole("heading", { name: kind === "loan" ? "Add Loan" : "Add Fixed Deposit" }) });
    await form.waitFor();
    await pick(page, form.locator('button[aria-label="Client"]'), "Acme Traders Pvt Ltd");
    const amounts = form.locator('input[type="number"]');
    if (kind === "loan") {
      await form.getByPlaceholder("e.g. HDFC Bank").fill("HDFC Bank");
      await amounts.nth(0).fill("1000000");   // principal
      await amounts.nth(1).fill("900000");    // outstanding
      await amounts.nth(2).fill("10.5");      // rate
    } else {
      await form.getByPlaceholder("e.g. State Bank of India").fill("State Bank of India");
      await amounts.nth(0).fill("500000");    // principal
      await amounts.nth(1).fill("7");         // rate
    }
  };
}

/** The client's Inventory tab with one stocked item, and a row's "Adjust" or "Write down" form open with its quantity or value typed. */
function openStockForm(kind) {
  return async (env) => {
    const { page, stub } = env;
    stub.route({ method: "GET", re: /api\/inventory\/items\?/, reply: () => ok([{
      id: "sc1", name: "Copier paper", description: null, hsn_sac: "4802", unit: "NOS", is_active: true,
      stock_qty_units: 40, avg_cost_paise: 25000, stock_value_paise: 1000000,
    }]) });
    stub.route({ method: "POST", re: /api\/inventory\/items\/sc1\/(adjust|writedown)$/, reply: () => ok({ id: "mv-1" }) });
    await page.goto(env.at("/inventory/"), { waitUntil: "networkidle" });
    await page.getByRole("button", { name: kind === "adjust" ? "Adjust" : "Write down", exact: true }).first().click();
    if (kind === "adjust") await page.getByLabel("Quantity", { exact: true }).fill("2");
    else await page.getByLabel("Net realisable value / unit (₹)").fill("200");
  };
}

/** The client's payroll Inputs tab with "Add Employee" open on a name and a basic salary, so only the dates are left. */
async function openEmployeeForm(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { payroll: ["read", "write", "approve"] } }) });
  stub.route({ method: "POST", re: /api\/payroll\/employees$/, reply: () => ok({ id: "emp-1" }) });
  await page.goto(env.at("/payroll/?tab=inputs"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Add Employee" }).first().click();
  await page.getByRole("heading", { name: "Add Employee" }).waitFor();
  await page.getByLabel("Name", { exact: true }).fill("Asha Rao");
  await page.getByLabel("Basic Salary (Rs/month)").fill("40000");
}

/** An employee's drawer (Profile, Full & final, Salary revisions, Loans & advances) on the client's payroll screen, open at one tab, for a person who may finalise. */
function openEmployeeDrawer(tab) {
  return async (env) => {
    const { page, stub } = env;
    stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { payroll: ["read", "write", "approve", "finalize"] } }) });
    stub.route({ method: "GET", re: /api\/payroll\/employees\?/, reply: () => ok([{
      id: "emp-1", name: "Asha Rao", designation: "Accountant", basic_paise: 40_000_00, hra_percent: 40, pf_applicable: true, esi_applicable: false,
      pt_applicable: true, status: "active" }]) });   // no joining date recorded: a short date in a box that already holds one is read in THAT date's year (DateInput's anchor), so a stored one would change what 15/1 means
    stub.route({ method: "GET", re: /employees\/emp-1\/salary-revisions\?/, reply: () => ok({ revisions: [] }) });
    stub.route({ method: "GET", re: /employees\/emp-1\/loans\?/, reply: () => ok({ loans: [] }) });
    stub.route({ method: "PATCH", re: /api\/payroll\/employees\/emp-1$/, reply: () => ok({ id: "emp-1" }) });
    stub.route({ method: "POST", re: /employees\/emp-1\/salary-revisions$/, reply: () => ok({ id: "rev-1" }) });
    stub.route({ method: "POST", re: /employees\/emp-1\/loans$/, reply: () => ok({ loan: { id: "loan-1" }, notes: [] }) });
    stub.route({ method: "POST", re: /employees\/emp-1\/settlement$/, reply: () => ok({ employee_id: "emp-1", components: [], deductions: [], totals: { gross_paise: 0, taxable_paise: 0, net_payable_paise: 0 }, gaps: [], problems: [] }) });
    await page.goto(env.at("/payroll/?tab=inputs"), { waitUntil: "networkidle" });
    await page.getByRole("button", { name: "Open", exact: true }).first().click();
    if (tab) await page.getByRole("button", { name: tab, exact: true }).click();
  };
}

/** Settings > Multi-currency with the firm entitled, so the Exchange rates panel under the register is drawn; a rate typed, only its date left. */
async function openFxRates(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { settings: ["read", "write"] } }) });
  stub.route({ method: "GET", re: /api\/currencies\/entitlement$/, reply: () => ok({ platform: { on: true }, firm: { on: true } }) });
  stub.route({ method: "GET", re: /api\/currencies\/rate-types$/, reply: () => ok({ rate_types: ["booking", "gst_notified", "customs", "closing"].map((code) => ({ code, meaning: `The ${code} rate.` })) }) });   // the four codes the fx_rates CHECK admits
  stub.route({ method: "GET", re: /api\/currencies\/rates\?/, reply: () => ok({ rates: [] }) });
  stub.route({ method: "PUT", re: /api\/currencies\/rates$/, reply: () => ok({ rate: "83.42", replaced: false }) });
  await page.goto(`${env.base}/settings/multi-currency/`, { waitUntil: "networkidle" });
  await page.locator("#fx-rate").fill("83.42");
}

/** The Overdue Interest tab with one customer that owes interest, so "Prepare draft invoice" is offered; only the as-at date is left to type. */
async function openOverdueInterest(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { sales: ["read", "write"] } }) });
  stub.route({ method: "GET", re: /api\/late-interest\/preview\?/, reply: () => ok({
    as_of: "2026-10-08", convention: { statement: "stub", day_count: "stub", as_of: "2026-10-08" },
    statutory_reading: { section: "stub", grade: "S", text: "stub" }, caveats: [], gaps: [],
    totals: { interest_paise: 1_200_00, parties_with_interest: 1, parties_without_terms: 0, overdue_outstanding_paise: 50_000_00 },
    parties: [{ customer_id: "c-beta", customer_name: "Beta Stores", terms_set: true, terms: { rate_bps: 1800, grace_days: 0, basis: "simple" },
      overdue_outstanding_paise: 50_000_00, interest_paise: 1_200_00, documents: [] }] }) });
  stub.route({ method: "GET", re: /api\/late-interest\/terms\?/, reply: () => ok({ customers: [] }) });
  stub.route({ method: "POST", re: /api\/late-interest\/drafts$/, reply: () => ok({ drafts: [], not_drafted: [], failed: [], caveats: [] }) });
  await page.goto(env.at("/sales/?tab=interest"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Prepare draft invoice" }).first().waitFor();
}

/** Inventory with the cost formula panel above the register, its "Record" form open on a formula; only the effective date is left. */
async function openCostFormula(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { inventory: ["read", "write"], accounting: ["read", "write"] } }) });
  const policy = { client_id: CLIENT_ID, method: "moving_average", label: "Moving average", is_recorded: false, unrecorded_means: "Not recorded.",
    methods: [{ value: "moving_average", label: "Moving average" }, { value: "fifo", label: "First in, first out" }],
    standard_cost_refused: "Standard cost is not offered.", as5_disclosure: "stub", earliest_date_a_change_can_take_effect: null, methods_used: [] };
  stub.route({ method: "GET", re: /api\/inventory\/costing-policy\?/, reply: () => ok(policy) });
  stub.route({ method: "PUT", re: /api\/inventory\/costing-policy$/, reply: () => ok({ ...policy, is_recorded: true }) });
  await page.goto(env.at("/inventory/"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Record", exact: true }).first().click();
  await page.locator("#cost-formula-from").waitFor();
}

/** Payroll > Inputs with one salary structure and one employee, "Apply to employees" open with the employee ticked and a gross typed; only the date is left. */
async function openApplyStructure(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { payroll: ["read", "write", "approve", "finalize"] } }) });
  stub.route({ method: "GET", re: /api\/payroll\/employees\?/, reply: () => ok([{
    id: "emp-1", name: "Asha Rao", designation: "Accountant", basic_paise: 40_000_00, hra_percent: 40, pf_applicable: true, esi_applicable: false, pt_applicable: true, status: "active" }]) });
  stub.route({ method: "GET", re: /api\/payroll\/salary-structures\?/, reply: () => ok([{
    id: "st-1", name: "Grade A", basic_percent: 50, hra_percent: 40, pf_applicable: true, esi_applicable: false }]) });
  stub.route({ method: "POST", re: /salary-structures\/st-1\/apply$/, reply: () => ok({ applied: 0, preview: true, employees: [], notes: [] }) });
  await page.goto(env.at("/payroll/?tab=inputs"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Apply to employees" }).first().click();
  await page.getByLabel("Apply to Asha Rao").check();
  await page.getByLabel("Gross salary (₹) — Asha Rao").fill("80000");
}

/** Opens a form on a 1440 by 720 screen, a smaller laptop's, so that a dialog taller than 720 pixels must scroll to keep its Save in reach. */
const onAShortScreen = (open) => async (env) => {
  await env.page.setViewportSize({ width: 1440, height: 720 });
  await open(env);
};

/** The Billing screen for a person who may write on it, with one fee invoice that is owed (so a receipt can be recorded against it). */
async function atBilling(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { billing: ["read", "write"] } }) });
  stub.route({ method: "GET", re: /api\/engagements(\?|$)/, reply: () => ok({ engagements: [], total: 0 }) });
  stub.setTable("fee_invoices", [{
    id: "fi-1", firm_id: "f1", client_id: CLIENT_ID, invoice_no: "FEE-0001", invoice_date: "2026-09-01",
    amount_paise: 1000000, gst_paise: 180000, total_paise: 1180000, status: "Issued",
  }]);
  stub.setTable("fee_receipts", []);
  await page.goto(`${env.base}/billing/`, { waitUntil: "networkidle" });
}

/** "Add Fee Engagement" with the client chosen by default, the fee typed and everything else as it opens. */
async function openFeeEngagement(env) {
  const { page, stub } = env;
  stub.route({ method: "POST", re: /api\/engagements$/, reply: () => ok({ engagement: { id: "en-1", client_id: CLIENT_ID, service_type: "GST Filing", fee_paise: 500000, billing_cycle: "Monthly", start_date: "2026-07-15", status: "Active" } }) });
  await atBilling(env);
  await page.getByRole("button", { name: "Engagements", exact: true }).first().click();
  await page.getByRole("button", { name: "Add Engagement" }).first().click();
  await page.getByRole("heading", { name: "Add Fee Engagement" }).waitFor();
  await page.getByLabel("Fee (₹)").fill("5000");
}

/** "Record Receipt" against the owed fee invoice, with the amount typed. */
async function openFeeReceipt(env) {
  const { page, stub } = env;
  stub.route({ method: "POST", re: /billing\/fee-invoices\/fi-1\/receipts$/, reply: () => ok({ id: "fr-1", invoice_id: "fi-1", receipt_date: "2026-07-15", amount_paise: 100000, payment_mode: "NEFT", reference_no: "" }) });
  await atBilling(env);
  await page.getByRole("button", { name: "Receipts", exact: true }).first().click();
  await page.getByRole("button", { name: "Record Receipt" }).first().click();
  await page.getByRole("heading", { name: "Record Receipt" }).waitFor();
  await page.getByLabel("Amount (₹)").fill("1000");
}

/**
 * The Deadlines screen with one obligation that is ready to file and the "Mark as Filed" prompt open on it. The prompt is the
 * one shared by Deadlines (single and bulk), a client's Compliance tab and Practice → Compliance, so this one row drives all of them.
 */
async function openMarkFiled(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { compliance: ["read", "write", "approve"] } }) });
  stub.route({ method: "GET", re: /compliance\/reopenable-types$/, reply: () => ok({ obligation_types: [], max_reason_chars: 500 }) });
  stub.route({
    method: "GET", re: /compliance\/obligations(\?|$)/,
    reply: () => ok({ obligations: [{
      id: "ob-1", client_id: CLIENT_ID, compliance_type: "GSTR-3B", obligation_type: "GSTR3B", status: "Ready To File",
      period_start: "2026-09-01", period_end: "2026-09-30", due_date: "2026-10-20", filed_date: null, acknowledgement_no: null,
      notes: null, period_label: "GSTR-3B September 2026",
    }], total: 1 }),
  });
  stub.route({ method: "POST", re: /compliance\/obligations\/ob-1\/mark-filed$/, reply: () => ok({ id: "ob-1", status: "Filed" }) });
  await page.goto(`${env.base}/deadlines/`, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Mark Filed", exact: true }).first().click();
  await modalOf(page).getByRole("button", { name: "Confirm Filed", exact: true }).waitFor();
}

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
/** What the capital-gains estimator answers: every key the register's preview and the calculator's panel read. A figure here is a stub's, not a tax claim. */
const CG_RESULT = {
  holding_months: 20, is_long_term: false, gain_type: "STCG", gain_paise: 1_000_00, indexed_cost_paise: 0, gain_with_indexation_paise: 0,
  tax_rate_percent: 20, tax_with_indexation_percent: null, tax_without_indexation_paise: 200_00, tax_with_indexation_paise: null,
  tax_liability_paise: 200_00, section_ref: "stub", note: "", is_slab_rate_estimate: false, gaps: [], caveats: [],
};

/** The capital-gains screen on its Register tab with a client chosen (the screen opens on the calculator, and the register is a client's). */
async function openCapitalGainsRegisterTab(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /api\/clients$/, reply: () => ok({ clients: [CLIENT_ROW], total: 1 }) });
  await page.goto(`${env.base}/income-tax/capital-gains/`, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Register", exact: true }).click();
  await pick(page, page.locator('button[aria-label="Client"]'), "Acme Traders");
  await page.waitForLoadState("networkidle");
}

/** The capital-gains screen's Register tab with the Add Transaction dialog open and everything but the two dates filled. */
async function openCapitalGainsRegister(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /api\/income-tax\/capital-gains\?/, reply: () => ok([]) });
  stub.route({ method: "POST", re: /api\/income-tax\/capital-gains\/compute$/, reply: () => ok(CG_RESULT) });
  stub.route({ method: "POST", re: /api\/income-tax\/capital-gains$/, reply: () => ok({ id: "cg-1" }) });
  await openCapitalGainsRegisterTab(env);
  await page.getByRole("button", { name: "Add Transaction" }).first().click();
  await page.getByLabel("Asset Description").fill("Equity shares of Alpha Ltd");
  await page.getByLabel("Purchase Cost (₹)").fill("100000");
  await page.getByLabel("Sale Value (₹)").fill("150000");
}

/** The reinvestment-claim panel of one register row, with what was bought filled. */
async function openReinvestmentClaim(env) {
  const { page, stub } = env;
  const record = {
    id: "cg-1", client_id: CLIENT_ID, asset_description: "Flat 402", asset_type: "property", purchase_date: "2019-04-01", sale_date: "2026-05-10",
    purchase_cost_paise: 50_00_000_00, improvement_cost_paise: 0, sale_value_paise: 90_00_000_00, indexed_cost_paise: null, gain_type: "LTCG",
    tax_rate_percent: 12.5, transferred_asset_nature: null, is_listed_security: null, fmv_31_01_2018_paise: null, created_at: "2026-10-31T00:00:00Z",
  };
  stub.route({ method: "GET", re: /api\/income-tax\/capital-gains\?/, reply: () => ok([record]) });
  stub.route({ method: "GET", re: /api\/income-tax\/capital-gains\/sections$/, reply: () => ok({ sections: [], asset_natures: [], acquisition_kinds: [] }) });
  stub.route({ method: "GET", re: /api\/income-tax\/capital-gains\/cg-1\/exemption$/, reply: () => ok({
    gain_paise: 40_00_000_00, total_exemption_paise: 0, taxable_gain_paise: 40_00_000_00, claims: [], gaps: [], caveats: [] }) });
  stub.route({ method: "POST", re: /api\/income-tax\/capital-gains\/cg-1\/reinvestments$/, reply: () => ok({ id: "ri-1" }) });
  await openCapitalGainsRegisterTab(env);
  await page.getByRole("button", { name: "Exemption", exact: true }).first().click();
  await page.getByLabel("What was bought").waitFor();
  await page.getByLabel("What was bought").fill("Flat 90, Kalyani Heights");
}

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
    open: onAShortScreen(openTdsChallanForm), saveInView: true,
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
    id: "mark-as-filed", title: "Mark as Filed prompt (Deadlines)", open: openMarkFiled, heldWhileUnreadable: true,
    fields: [{ box: (p) => modalOf(p).locator("#mark-filed-date"), label: "Filed on", key: "filed_date", full: "15/07/2026", iso: "2026-07-15" }],
    save: (p) => modalOf(p).getByRole("button", { name: "Confirm Filed", exact: true }), write: /compliance\/obligations\/ob-1\/mark-filed$/,
  },
  {
    id: "fee-engagement", title: "fee engagement form (Billing)", open: openFeeEngagement,
    fields: [{ box: (p) => p.locator("#engagement-start"), label: "Start date", key: "start_date", full: "15/07/2026", iso: "2026-07-15" }],
    save: (p) => p.getByRole("button", { name: "Save Engagement", exact: true }), write: /api\/engagements$/,
  },
  {
    id: "fee-receipt", title: "fee receipt form (Billing)", open: openFeeReceipt,
    fields: [{ box: (p) => p.locator("#fee-receipt-date"), label: "Receipt date", key: "receipt_date", full: "15/07/2026", iso: "2026-07-15" }],
    save: (p) => p.getByRole("button", { name: "Record Receipt", exact: true }).last(), write: /billing\/fee-invoices\/fi-1\/receipts$/,
  },
  {
    id: "add-asset", title: "Add Asset drawer (purchase date)", open: openAddAsset,
    fields: [{ box: (p) => p.getByLabel("Purchase date"), label: "Purchase date", key: "purchase_date", full: "15/07/2026", iso: "2026-07-15" }],
    save: (p) => p.getByRole("button", { name: "Add Asset", exact: true }).last(), write: /api\/fixed-assets$/,
  },
  {
    id: "asset-disposal", title: "asset disposal form (Disposal tab)", open: openDisposal,
    fields: [{ box: (p) => p.getByLabel("Disposal date"), label: "Disposal date", key: "disposal_date", full: "15/07/2026", iso: "2026-07-15" }],
    save: (p) => p.getByRole("button", { name: "Confirm Disposal", exact: true }), write: /api\/fixed-assets\/fa-9\/dispose$/,
  },
  {
    id: "retainer", title: "retainer form (next invoice due)", open: openRetainer,
    fields: [{ box: (p) => p.locator("#retainer-next"), label: "Next invoice due", key: "next_run_date", full: "15/07/2026", iso: "2026-07-15" }],
    save: (p) => p.getByRole("button", { name: "Save Retainer", exact: true }), write: /billing\/schedules$/,
  },
  {
    id: "payroll-disbursement", title: "payroll disbursement prompt (Record payment)", open: openDisbursement,
    fields: [{ box: (p) => p.locator("#disburse-date"), label: "Payment date", key: "payment_date", full: "15/07/2026", iso: "2026-07-15" }],
    save: (p) => p.getByRole("button", { name: "Confirm Payment", exact: true }), write: /payroll\/runs\/run1\/disburse$/,
  },
  {
    id: "opening-document", title: "opening invoice form (Opening Balances)", open: openOpeningDocument,
    fields: [
      { box: (p) => p.locator("#opening-doc-date"), label: "Document date", key: "document_date", full: "15/07/2025", iso: "2025-07-15" },
      { box: (p) => p.locator("#opening-doc-due"), label: "Due date", key: "due_date", full: "14/08/2025", iso: "2025-08-14" },
    ],
    save: (p) => p.getByRole("button", { name: "Record", exact: true }), write: /api\/opening-documents$/,
  },
  {
    id: "bill-of-entry", title: "Bill of Entry form (Purchases)", open: openBillOfEntry,
    fields: [{ box: (p) => p.locator("#boe-date"), label: "Bill of Entry date", key: "be_date", full: "15/07/2026", iso: "2026-07-15" }],
    save: (p) => p.getByRole("button", { name: "Save", exact: true }), write: /api\/bills-of-entry$/,
  },
  {
    id: "cwip-project", title: "new project under construction (Work in Progress)", open: openCwipProject,
    fields: [
      { box: (p) => modalOf(p).locator('input[aria-label="Started on"]'), label: "Started on", key: "started_on", full: "15/07/2026", iso: "2026-07-15" },
      { box: (p) => modalOf(p).locator('input[aria-label="Approved completion date"]'), label: "Approved completion date", key: "approved_completion_date", full: "14/08/2026", iso: "2026-08-14" },
      { box: (p) => modalOf(p).locator('input[aria-label="Now expected to complete on"]'), label: "Now expected to complete on", key: "expected_completion_date", full: "20/08/2026", iso: "2026-08-20" },
    ],
    save: (p) => modalOf(p).getByRole("button", { name: "Create", exact: true }), write: /api\/cwip$/,
  },
  {
    id: "cwip-cost", title: "cost on a project (Work in Progress)", open: openCwipCost,
    fields: [{ box: (p) => modalOf(p).locator('input[aria-label="Incurred on"]'), label: "Incurred on", key: "incurred_on", full: "15/07/2026", iso: "2026-07-15" }],
    save: (p) => modalOf(p).getByRole("button", { name: "Record", exact: true }), write: /api\/cwip\/p1\/costs$/,
  },
  {
    id: "cwip-capitalise", title: "capitalise a project (Work in Progress)", open: openCwipCapitalise,
    fields: [{ box: (p) => modalOf(p).locator('input[aria-label="Ready for use on"]'), label: "Ready for use on", key: "put_to_use_date", full: "15/07/2026", iso: "2026-07-15" }],
    save: (p) => modalOf(p).getByRole("button", { name: "Capitalise", exact: true }), write: /api\/cwip\/p1\/capitalise$/,
  },
  {
    id: "purchase-order", title: "purchase order form (Orders & Goods Receipts)", open: openPurchaseCycleForm("orders"),
    fields: [
      { box: (p) => p.locator("#po-date"), label: "Order date", key: "document_date", full: "15/07/2026", iso: "2026-07-15" },
      { box: (p) => p.locator("#po-expected"), label: "Expected by", key: "expected_date", full: "14/08/2026", iso: "2026-08-14" },
    ],
    save: (p) => p.getByRole("button", { name: "Save", exact: true }), write: /api\/purchase-cycle\/orders$/,
  },
  {
    id: "goods-receipt", title: "goods receipt form (Orders & Goods Receipts)", open: openPurchaseCycleForm("receipts"),
    fields: [{ box: (p) => p.locator("#grn-received"), label: "Goods arrived on", key: "received_on", full: "15/07/2026", iso: "2026-07-15" }],
    save: (p) => p.getByRole("button", { name: "Save", exact: true }), write: /api\/purchase-cycle\/receipts$/,
  },
  {
    id: "sales-quotation", title: "quotation form (Quotes, Orders & Challans)", open: openSalesCycleForm("Quotations & Proforma", "QT/2026-27/0001"),
    fields: [
      { box: (p) => p.locator("#sc-date"), label: "Date", key: "document_date", full: "15/07/2026", iso: "2026-07-15" },
      { box: (p) => p.locator("#sc-valid-until"), label: "Valid until", key: "valid_until", full: "14/08/2026", iso: "2026-08-14" },
    ],
    save: (p) => p.getByRole("button", { name: "Save", exact: true }), write: /api\/sales-cycle\/quotations$/,
  },
  {
    id: "sales-order", title: "sales order form (Quotes, Orders & Challans)", open: openSalesCycleForm("Sales Orders", "SO/2026-27/0001"),
    fields: [
      { box: (p) => p.locator("#sc-date"), label: "Date", key: "document_date", full: "15/07/2026", iso: "2026-07-15" },
      { box: (p) => p.locator("#sc-expected-delivery"), label: "Expected delivery", key: "expected_delivery_date", full: "14/08/2026", iso: "2026-08-14" },
    ],
    save: (p) => p.getByRole("button", { name: "Save", exact: true }), write: /api\/sales-cycle\/orders$/,
  },
  {
    id: "delivery-challan", title: "delivery challan form (Quotes, Orders & Challans)", open: openSalesCycleForm("Delivery Challans", "DC/2026-27/0001"),
    fields: [{ box: (p) => p.locator("#sc-date"), label: "Date", key: "document_date", full: "15/07/2026", iso: "2026-07-15" }],
    save: (p) => p.getByRole("button", { name: "Save", exact: true }), write: /api\/sales-cycle\/challans$/,
  },
  {
    id: "customer-receipt", title: "customer receipt form (Receipts tab)", open: openCustomerReceipt,
    fields: [{ box: (p) => p.locator("#receipt-date"), label: "Receipt date", key: "receipt_date", full: "15/07/2026", iso: "2026-07-15" }],
    save: (p) => p.getByRole("button", { name: "Record Receipt", exact: true }).last(), write: /api\/receipts\/$/,
  },
  ...[
    { id: "sales-credit-note-editor", title: "sales credit note editor", path: "/sales/credit-notes/new/edit/", party: { label: "Customer", name: "Beta Stores" },
      box: "#sales-cn-date", label: "Credit note date", key: "credit_note_date", write: /\/api\/credit-notes\/$/ },
    { id: "sales-debit-note-editor", title: "sales debit note editor", path: "/sales/debit-notes/new/edit/", party: { label: "Customer", name: "Beta Stores" },
      box: "#sales-dn-date", label: "Debit note date", key: "debit_note_date", write: /\/api\/sales-debit-notes\/$/ },
    { id: "purchase-debit-note-editor", title: "purchase debit note editor", path: "/purchases/debit-notes/new/edit/", party: { label: "Vendor", name: "Gamma Supplies" },
      box: "#purchase-dn-date", label: "Debit note date", key: "debit_note_date", write: /\/api\/debit-notes\/$/ },
    { id: "purchase-credit-note-editor", title: "purchase credit note editor", path: "/purchases/credit-notes/new/edit/", party: { label: "Vendor", name: "Gamma Supplies" },
      box: "#purchase-cn-date", label: "Credit note date", key: "credit_note_date", write: /\/api\/purchase-credit-notes\/$/ },
  ].map((n) => ({
    id: n.id, title: n.title, open: openNoteEditor(n),
    fields: [{ box: (p) => p.locator(n.box), label: n.label, key: n.key, full: "15/07/2026", iso: "2026-07-15" }],
    save: (p) => p.getByRole("button", { name: "Save Draft", exact: true }), write: n.write,
  })),
  {
    id: "loan", title: "loan form (Loans & Fixed Deposits)", open: openLoanOrDeposit("loan"),
    fields: [
      { box: (p) => p.getByLabel("Disbursement date"), label: "Disbursement date", key: "disbursement_date", full: "15/07/2026", iso: "2026-07-15" },
      { box: (p) => p.getByLabel("Loan maturity date"), label: "Maturity date", key: "maturity_date", full: "14/07/2029", iso: "2029-07-14" },
    ],
    save: (p) => p.getByRole("button", { name: "Add Loan", exact: true }).last(), write: /rest\/v1\/loans/,
  },
  {
    id: "fixed-deposit", title: "fixed deposit form (Loans & Fixed Deposits)", open: openLoanOrDeposit("fd"),
    fields: [
      { box: (p) => p.getByLabel("Fixed deposit start date"), label: "Start date", key: "start_date", full: "15/07/2026", iso: "2026-07-15" },
      { box: (p) => p.getByLabel("Fixed deposit maturity date"), label: "Maturity date", key: "maturity_date", full: "14/07/2027", iso: "2027-07-14" },
    ],
    save: (p) => p.getByRole("button", { name: "Add FD", exact: true }).last(), write: /rest\/v1\/fixed_deposits/,
  },
  {
    id: "stock-adjustment", title: "stock adjustment form (Inventory)", open: openStockForm("adjust"),
    fields: [{ box: (p) => p.locator("#stock-adjust-date"), label: "Date", key: "adjustment_date", full: "15/07/2026", iso: "2026-07-15" }],
    save: (p) => p.getByRole("button", { name: "Save Adjustment", exact: true }), write: /api\/inventory\/items\/sc1\/adjust$/,
  },
  {
    id: "stock-writedown", title: "NRV write-down form (Inventory)", open: openStockForm("writedown"),
    fields: [{ box: (p) => p.locator("#writedown-date"), label: "Date", key: "writedown_date", full: "15/07/2026", iso: "2026-07-15" }],
    save: (p) => p.getByRole("button", { name: "Save Write-down", exact: true }), write: /api\/inventory\/items\/sc1\/writedown$/,
  },
  {
    id: "employee-form", title: "employee form (payroll Inputs)", open: onAShortScreen(openEmployeeForm), saveInView: true,
    fields: [
      { box: (p) => p.locator("#employee-joining-date"), label: "Joining date", key: "joining_date", full: "15/07/2025", iso: "2025-07-15" },
      { box: (p) => p.locator("#date-of-birth"), label: "Date of Birth", key: "date_of_birth", full: "20/03/1990", iso: "1990-03-20" },
    ],
    save: (p) => modalOf(p).getByRole("button", { name: "Add Employee", exact: true }), write: /api\/payroll\/employees$/,
  },
  {
    id: "employee-pf-election", title: "employee form: PF on actual wages takes effect from (payroll Inputs)", saveInView: true,
    open: onAShortScreen(async (env) => {
      await openEmployeeForm(env);
      const { page } = env;
      await page.getByLabel(/PF Applicable/).check();
      await page.locator("#pf-actual").check();
    }),
    fields: [{ box: (p) => p.locator("#pf-actual-from"), label: "PF on actual wages takes effect from", key: "pf_on_actual_wages_from", full: "15/07/2025", iso: "2025-07-15" }],
    save: (p) => modalOf(p).getByRole("button", { name: "Add Employee", exact: true }), write: /api\/payroll\/employees$/,
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
  // The fifth slice (4-11-2026).
  {
    id: "capital-gains-register", title: "capital gains register: Add Transaction", open: onAShortScreen(openCapitalGainsRegister), saveInView: true,
    fields: [
      { box: (p) => p.locator("#cg-reg-purchase-date"), label: "Purchase date", key: "purchase_date", full: "15/07/2024", iso: "2024-07-15" },
      { box: (p) => p.locator("#cg-reg-sale-date"), label: "Sale date", key: "sale_date", full: "20/03/2026", iso: "2026-03-20" },
    ],
    save: (p) => p.getByRole("button", { name: "Save Transaction", exact: true }), write: /api\/income-tax\/capital-gains$/,
  },
  {
    id: "capital-gains-reinvestment-claim", title: "capital gains register: record a reinvestment claim", open: onAShortScreen(openReinvestmentClaim), saveInView: true,
    fields: [
      { box: (p) => p.getByLabel("Acquisition date"), label: "Acquisition date", key: "acquisition_date", full: "15/07/2026", iso: "2026-07-15" },
      { box: (p) => p.getByLabel("CGAS deposit date"), label: "CGAS deposit date", key: "cgas_deposit_date", full: "20/08/2026", iso: "2026-08-20" },
    ],
    save: (p) => p.getByRole("button", { name: "Record claim", exact: true }), write: /api\/income-tax\/capital-gains\/cg-1\/reinvestments$/,
  },
  // The sixth slice (4-11-2026): an employee's drawer.
  {
    id: "employee-drawer-joining-date", title: "employee drawer, Profile: joining date", open: openEmployeeDrawer(null),
    fields: [{ box: (p) => p.locator("#drawer-joining-date"), label: "Joining date", key: "joining_date", full: "15/07/2025", iso: "2025-07-15" }],
    save: (p) => p.getByRole("button", { name: "Save", exact: true }), write: /api\/payroll\/employees\/emp-1$/,
  },
  {
    id: "employee-drawer-salary-revision", title: "employee drawer, Salary revisions: effective from", open: async (env) => {
      await openEmployeeDrawer("Salary revisions")(env);
      await env.page.getByLabel("Basic", { exact: true }).fill("45000");
    },
    heldWhileUnreadable: true,
    fields: [{ box: (p) => p.locator("#drawer-revision-effective-from"), label: "Effective from", key: "effective_from", full: "01/04/2026", iso: "2026-04-01" }],
    save: (p) => p.getByRole("button", { name: "Record revision", exact: true }), write: /employees\/emp-1\/salary-revisions$/,
  },
  {
    id: "employee-drawer-loan", title: "employee drawer, Loans & advances: started on", open: async (env) => {
      await openEmployeeDrawer("Loans & advances")(env);
      await env.page.getByLabel("Principal", { exact: true }).fill("50000");
      await env.page.getByLabel("Monthly instalment", { exact: true }).fill("5000");
    },
    fields: [{ box: (p) => p.locator("#drawer-loan-started-on"), label: "Started on", key: "started_on", full: "15/07/2026", iso: "2026-07-15" }],
    save: (p) => p.getByRole("button", { name: "Record loan", exact: true }), write: /employees\/emp-1\/loans$/,
  },
  {
    id: "employee-drawer-settlement-payment-date", title: "employee drawer, Full & final: the date the settlement is paid (the confirming click)", open: async (env) => {
      const { page, stub } = env;
      await openEmployeeDrawer("Full & final")(env);
      stub.route({ method: "POST", re: /employees\/emp-1\/settlement\/record$/, reply: () => ok({
        employee_id: "emp-1", components: [], deductions: [], totals: { gross_paise: 0, taxable_paise: 0, net_payable_paise: 0 }, gaps: [], problems: [], settlement_id: "s-1" }) });
      // The payment date is read after the last working day (its anchor), so the last working day is in FY 2026-27 here as the short-form claim expects.
      await typeAndLeave(page.locator("#drawer-last-working-day"), "30/06/2026");
      await page.getByRole("button", { name: "Compute", exact: true }).click();
      await page.locator("#settlement-payment-date").waitFor();
      await page.getByRole("button", { name: "Record settlement", exact: true }).click();
    },
    fields: [{ box: (p) => p.locator("#settlement-payment-date"), label: "Payment date", key: "payment_date", full: "05/07/2026", iso: "2026-07-05" }],
    save: (p) => p.getByRole("button", { name: "Yes, record it", exact: true }), write: /employees\/emp-1\/settlement\/record$/,
  },
  {
    id: "employee-drawer-last-working-day", title: "employee drawer, Full & final: last working day", open: openEmployeeDrawer("Full & final"),
    heldWhileUnreadable: true,
    fields: [{ box: (p) => p.locator("#drawer-last-working-day"), label: "Last working day", key: "leaving_date", full: "31/03/2026", iso: "2026-03-31" }],
    save: (p) => p.getByRole("button", { name: "Compute", exact: true }), write: /employees\/emp-1\/settlement$/,
  },
  // The seventh slice (4-11-2026): single-purpose panels.
  {
    id: "exchange-rate", title: "Settings > Multi-currency: record an exchange rate", open: openFxRates,
    fields: [{ box: (p) => p.locator("#fx-date"), label: "For the date", key: "rate_date", full: "15/07/2026", iso: "2026-07-15" }],
    save: (p) => p.getByRole("button", { name: "Record rate", exact: true }), write: /api\/currencies\/rates$/,
  },
  {
    id: "overdue-interest", title: "Sales > Overdue Interest: the as-at date a draft interest invoice is prepared for", open: openOverdueInterest,
    fields: [{ box: (p) => p.locator("#overdue-as-at"), label: "As at", key: "as_of_date", full: "15/09/2026", iso: "2026-09-15" }],
    save: (p) => p.getByRole("button", { name: "Prepare draft invoice" }).first(), write: /api\/late-interest\/drafts$/,
  },
  {
    id: "cost-formula", title: "Inventory: the date a cost formula takes effect", open: openCostFormula,
    fields: [{ box: (p) => p.locator("#cost-formula-from"), label: "Takes effect from", key: "effective_from", full: "01/04/2027", iso: "2027-04-01" }],
    save: (p) => p.getByRole("button", { name: "Record", exact: true }).last(), write: /api\/inventory\/costing-policy$/,
  },
  {
    id: "apply-salary-structure", title: "Payroll > Inputs: the date a salary structure is applied from", open: openApplyStructure, heldWhileUnreadable: true,
    fields: [{ box: (p) => p.locator("#apply-structure-effective-from"), label: "Effective from", key: "effective_from", full: "01/10/2026", iso: "2026-10-01" }],
    save: (p) => p.getByRole("button", { name: "Preview", exact: true }), write: /salary-structures\/st-1\/apply$/,
  },
];

async function driveEditor(env, spec) {
  const { page, stub } = env;
  await spec.open(env);

  // 0. A dialog's save control can be brought onto the screen. A hand-built overlay taller than the screen has no scroll, so
  //    its heading and its Save button were out of reach (the Add Employee dialog, found by driving it); the shared dialog limits its height,
  //    scrolls its body and keeps its buttons in view. Opt-in per row (`saveInView`): the rows of dialogs that hold it.
  if (spec.saveInView || process.env.PROBE_DIALOG_FIT) {
    // REACHABLE, not merely visible: a dialog or page that scrolls brings its Save into view (the browser does it for a person who
    // tabs or scrolls), so the control is scrolled to first. One that cannot scroll leaves it where it was, below the bottom.
    await spec.save(page).scrollIntoViewIfNeeded({ timeout: 2000 }).catch(() => undefined);
    const box = await spec.save(page).boundingBox();
    const height = page.viewportSize()?.height ?? 0;
    const fits = !!box && box.y >= 0 && box.y + box.height <= height;
    if (process.env.PROBE_DIALOG_FIT) { console.log(`FIT ${fits ? "yes" : "NO "} ${spec.id}  save at y=${box ? Math.round(box.y) : "?"}..${box ? Math.round(box.y + box.height) : "?"} of ${height}`); return; }
    assert.ok(fits, `${spec.title}: the Save button cannot be brought onto the screen (it is at ${box ? Math.round(box.y) + ".." + Math.round(box.y + box.height) : "nowhere"} of a ${height}-pixel screen)`);
  }

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

  // 4. Save over unreadable text sends nothing and names the field. A prompt may instead HOLD its button while the text is unreadable
  //    (`heldWhileUnreadable`): then the button is disabled, which is the same refusal said by the control and the field's own sentence stays.
  const first = spec.fields[0];
  await typeAndLeave(primary, "31/02/2026");
  if (spec.heldWhileUnreadable) {
    assert.equal(await spec.save(page).isDisabled(), true, `${spec.title}: the button was live over an unreadable date`);
    await page.getByText(FEB_SENTENCE).first().waitFor({ timeout: 4000 }).catch(() => {
      throw new Error(`${spec.title}: the field did not say "${FEB_SENTENCE}" beside the held button`);
    });
  } else {
    await spec.save(page).click();
    await page.getByText(`${first.label}: ${FEB_SENTENCE}`).first().waitFor({ timeout: 4000 }).catch(() => {
      throw new Error(`${spec.title}: Save over an unreadable date did not say "${first.label}: ${FEB_SENTENCE}"`);
    });
  }
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
  // The capital-gains CALCULATOR has no Save: it asks the server for an estimate by itself, a moment after the last keystroke, so its
  // "write" is the estimate request. The claims are the same ones, with that request standing where Save does: over an unreadable date it
  // is NOT asked, and over the dates typed in full it is asked with the ISO dates.
  {
    id: "capital-gains-calculator",
    title: "capital gains calculator: typed dates are read by the one rule, no estimate is asked over an unreadable one, and the ISO dates reach the server",
    contexts: TZ_MATRIX,
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "POST", re: /api\/income-tax\/capital-gains\/compute$/, reply: () => ok(CG_RESULT) });
      await page.goto(`${env.base}/income-tax/capital-gains/`, { waitUntil: "networkidle" });
      assert.equal(await page.locator('input[type="date"]').count(), 0, "a native <input type=\"date\"> is on the screen");
      const purchase = page.locator("#cg-calc-purchase-date");
      const sale = page.locator("#cg-calc-sale-date");
      await typeAndLeave(purchase, "15/1");
      assert.equal(await purchase.inputValue(), "15/01/2027", "15/1 in FY 2026-27 is 15 January 2027");
      await typeAndLeave(purchase, "150326");
      assert.equal(await purchase.inputValue(), "15/03/2026", "150326 is 15/03/2026");
      for (const [box, label] of [[purchase, "Purchase date"], [sale, "Sale date"]]) {
        await typeAndLeave(box, "31/02/2026");
        assert.equal(await box.getAttribute("aria-invalid"), "true", `${label}: 31/02/2026 is not marked invalid`);
        const alerts = (await page.locator("[role=alert]").allInnerTexts()).join(" | ");
        assert.ok(alerts.includes(FEB_SENTENCE), `${label}: the field's own sentence is missing (alerts: ${alerts.slice(0, 200)})`);
        await typeAndLeave(box, "15/03/2026");
      }
      // Over an unreadable date, with everything else in place, the estimate is not asked for and the screen says why.
      await typeAndLeave(purchase, "31/02/2026");
      await page.getByLabel("Purchase Price (₹)").fill("100000");
      await page.getByLabel("Sale Price (₹)").fill("150000");
      await page.getByText(`Purchase date: ${FEB_SENTENCE}`).first().waitFor({ timeout: 4000 }).catch(() => {
        throw new Error(`the calculator did not say "Purchase date: ${FEB_SENTENCE}" over an unreadable date`);
      });
      await stub.quiet();
      assert.equal(stub.writesTo(/capital-gains\/compute$/).length, 0, "the estimate was asked for over an unreadable date");
      // Typed in full, the dates are asked for as the ISO dates typed.
      await typeAndLeave(purchase, "15/07/2024");
      await typeAndLeave(sale, "20/03/2026");
      await until(() => stub.writesTo(/capital-gains\/compute$/).some((w) => JSON.parse(w.body).sale_date === "2026-03-20"), "an estimate asked for the dates typed");
      const last = JSON.parse(stub.writesTo(/capital-gains\/compute$/).at(-1).body);
      assert.equal(last.purchase_date, "2024-07-15", `purchase_date reached the server as ${JSON.stringify(last.purchase_date)}`);
      assert.equal(last.sale_date, "2026-03-20", `sale_date reached the server as ${JSON.stringify(last.sale_date)}`);
    },
  },
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
