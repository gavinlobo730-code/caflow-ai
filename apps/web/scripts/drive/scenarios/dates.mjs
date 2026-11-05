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
import { ok, refuse } from "../stub.mjs";
import { CLIENT_ID, CLIENT_ROW, ITEM, PAYROLL_RUN } from "../fixtures.mjs";

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

/** The client's payroll File tab (the statutory handoff) for a finalised run, with ONE obligation to record: ESI/professional tax record a remittance, EPF an ECR filing. */
function openStatutoryHandoff(scheme, { twoMonths = false } = {}) {
  return async (env) => {
    const { page, stub } = env;
    stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { payroll: ["read", "write", "approve", "finalize"] } }) });
    stub.route({ method: "GET", re: /payroll\/runs\?/, reply: () => ok([{ ...PAYROLL_RUN, client_id: CLIENT_ID }, ...(twoMonths ? [{ ...PAYROLL_RUN, id: "run0", month: "2026-08", client_id: CLIENT_ID }] : [])]) });
    stub.route({ method: "GET", re: /payroll\/clients\/[^/]+\/remittance-reconciliation$/, reply: () => ok({ client_id: CLIENT_ID, window_days: 30, unmatched: [], stale_links: [] }) });
    // The obligation's key is the SAME in every month ("epf", "esic", "professional_tax:<state>": domain/payroll/handoff.py), which is what a card is keyed by.
    const handoffOf = (id, month, label) => ok({
      run_id: id, client_id: CLIENT_ID, month, unattributed_pt_paise: 0,
      obligations: [{
        scheme, key: scheme, title: scheme === "epf" ? "EPF: Electronic Challan cum Return" : "ESI: monthly contribution",
        authority: scheme === "epf" ? "EPFO" : "ESIC", portal: "the portal", portal_host: "", wage_month: month, period_label: label,
        state: null, due_date: null, due_note: null, statute: null, identity: [], confirm: [],
        artefact: { available: false, filename: null, endpoint: null, why_not: "Not built for this drive." },
        blocking: [], warnings: [], record_back: scheme === "epf" ? "the TRRN" : "the challan", record_options: scheme === "epf" ? ["regular"] : [], recorded: null,
      }],
    });
    stub.route({ method: "GET", re: /payroll\/runs\/run1\/handoff$/, reply: () => handoffOf("run1", "2026-09", "September 2026") });
    if (twoMonths) stub.route({ method: "GET", re: /payroll\/runs\/run0\/handoff$/, reply: () => handoffOf("run0", "2026-08", "August 2026") });
    stub.route({ method: "POST", re: /payroll\/clients\/[^/]+\/remittances$/, reply: () => ok({ client_id: CLIENT_ID, remittance: { id: "rem-1" }, compliance_obligations: [] }) });
    stub.route({ method: "POST", re: /payroll\/runs\/run1\/ecr\/filed$/, reply: () => ok({ id: "ecr-1" }) });
    await page.goto(env.at("/payroll/?tab=file"), { waitUntil: "networkidle" });
    await page.getByRole("button", { name: "Record it", exact: true }).waitFor();
  };
}

/** The Tax Computation screen with the house-property worksheet open on one SELF-OCCUPIED property, whose loan and completion dates are the two boxes. */
async function openHousePropertyWorksheet(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { income_tax: ["read", "compute", "write"] } }) });
  stub.route({ method: "GET", re: /income-tax\/financial-years$/,
               reply: () => ok({ financial_years: [{ fy: "2026-27", verified: true }, { fy: "2025-26", verified: true }], current_fy: "2026-27" }) });
  stub.route({ method: "GET", re: /income-tax\/worksheets\/house_property\?/, reply: () => ok({ payload: {}, result: null, saved: false }) });
  stub.route({ method: "PUT", re: /income-tax\/worksheets\/house_property$/, reply: () => ok({
    payload: {}, saved: true, result: { properties: [], head_income_paise: 0, is_loss: false, gaps: [], caveats: [] } }) });
  await page.goto(`${env.base}/clients/${CLIENT_ID}/tax/computation/`, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: /Working papers/ }).click();
  await page.getByRole("button", { name: "Add a property" }).click();
  await page.getByLabel("Use", { exact: true }).first().selectOption("self_occupied");
  await page.getByLabel("Loan taken on").waitFor();
}

/** Sales > Quotes, Orders & Challans, FORM GST ITC-04 panel: one challan line still with a job worker, and "Record a lot" open on it with a quantity typed, so only the dates are left. */
async function openItc04Lot(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /api\/customers/, reply: () => ok([{ id: "cu1", name: "Beta Stores" }]) });
  stub.route({ method: "GET", re: /sales-cycle\/vocabulary$/, reply: () => ok({
    quote_kinds: [], quote_statuses: [], order_statuses: [], challan_statuses: [], challan_reasons: [], goods_kinds: [],
    not_a_tax_invoice: "", no_tax_on_a_non_supply: "", job_work_exclusion: "", rule_55_5_steps: [], copies: [], itc_04: { decided: false, readings: [], refusal: "" },
  }) });
  stub.route({ method: "GET", re: /sales-cycle\/itc-04\?/, reply: () => ok({
    client_id: CLIENT_ID, financial_year: "2026-27", as_of: "2026-10-08",
    period: { decided: true, readings: [], refusal: "", preceding_year_aato_paise: null, verified: false },
    readings: [], selected_window: null, table_4: null, table_5a: null,
    table_5b: { derived: false, reason: "" }, table_5c: { derived: false, reason: "" },
    outstanding: [{
      challan_id: "ch-1", challan_no: "JW/001", challan_date: "2026-06-01", job_worker: { name: "Gamma Works" }, goods_kind: "inputs",
      lines: [{ challan_line_id: "cl-1", description: "Steel sheet", uqc: "KGS", sent: "5", returned: "0", lost_or_wasted: "0", outstanding: "5", taxable_value_at_stake_paise: 100000 }],
      taxable_value_at_stake_paise: 100000,
      clock: { applies: true, due_back_by: "2027-06-01", days_remaining: 236, overdue: false, consequence: "", gaps: [] },
    }],
    gaps: [], nothing_is_filed: true, verified: false, ca_review_required: true,
  }) });
  stub.route({ method: "POST", re: /sales-cycle\/challans\/ch-1\/returns$/, reply: () => ok({ id: "ret-1", challan_marked_received_back: false }) });
  await page.goto(env.at("/sales/?tab=sales-cycle"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Delivery Challans", exact: true }).click();
  await page.getByRole("button", { name: "Record a lot", exact: true }).click();
  await page.getByText("Quantity returned", { exact: true }).waitFor();
  await page.locator("label:has-text('Quantity returned') input").first().fill("2");
}

/** The ITR tracker (Income Tax) with one pending return listed: `how` is "single" (its own Mark Filed prompt), "batch" (the bulk prompt, one row ticked) or "add" (the Add ITR Deadline prompt on a chosen client). */
function openItrTracker(how) {
  return async (env) => {
    const { page, stub } = env;
    stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { compliance_record: ["read", "write", "approve"], income_tax: ["read", "write"] } }) });
    stub.route({ method: "GET", re: /income-tax\/financial-years$/, reply: () => ok({ financial_years: [{ fy: "2026-27", verified: true }, { fy: "2025-26", verified: true }], current_fy: "2026-27", current_fy_advance_tax: [] }) });
    const dueDateAsks = { n: 0 };
    stub.route({ method: "GET", re: /compliance\/itr-due-date\?/, reply: () => { dueDateAsks.n += 1; return ok({
      due_date: "2026-07-31", decided: true, basis: "Stubbed: IT Act s.139(1).", statutory_gaps: [] }); } });
    stub.route({ method: "PATCH", re: /compliance\/calendar\/itr-1\/filed$/, reply: () => ok({
      record: { id: "itr-1", filing_status: "filed" }, filing_recorded: true, filing_not_recorded_reason: null,
      period_locked_from: null, period_locked_to: null, workspace_return: null }) });
    stub.setTable("compliance_calendar", [{
      id: "itr-1", firm_id: "00000000-0000-4000-8000-0000000000f1", client_id: CLIENT_ID, compliance_type: "ITR", period_start: "2025-04-01", period_end: "2026-03-31",
      due_date: "2026-07-31", filing_status: "pending", filed_date: null, arn_number: null, notes: "ITR-3",
      clients: { client_name: "Acme Traders Pvt Ltd", pan: "AAACA1234A", entity_type: "Company" },
    }]);
    await page.goto(`${env.base}/income-tax/`, { waitUntil: "networkidle" });
    if (how === "add") {
      await page.getByRole("button", { name: /Add ITR Deadline/ }).first().click();
      await page.locator("select[aria-label='Client']").selectOption({ index: 1 });
      await page.locator("#itr-add-due-date").waitFor();
      await page.getByText("Stubbed: IT Act s.139(1).").waitFor();
      // The listed return is for FY 2025-26, the form's default, and a second ITR row for the same client and period is refused by the table's
      // unique key (client, type, period start): add the next year's.
      await page.getByRole("combobox", { name: "Financial year" }).last().selectOption("2026-27");
      await until(() => dueDateAsks.n >= 2, "the due date asked for again for the year chosen");
      await page.getByText("Stubbed: IT Act s.139(1).").waitFor();
      return;
    }
    if (how === "batch") {
      await page.locator("tr", { hasText: "Acme Traders" }).locator("input[type=checkbox]").first().check();
      await page.getByRole("button", { name: "Mark Filed", exact: true }).first().click();
      await page.getByLabel(/Acknowledgement number \(ARN\) — /).fill("123456789012345");
      return;
    }
    await page.getByRole("button", { name: "Mark Filed", exact: true }).first().click();
    await page.getByLabel("Acknowledgement number (ARN)", { exact: true }).fill("123456789012345");
  };
}

/** The GST filing tracker with one pending GSTR-3B listed: `how` is "single" (its own Mark Filed prompt), "batch" (the bulk prompt, one row ticked), "add" (the Add GST Filing prompt, with the engine's due date in the box) or "add-filed" (the same prompt with Status set to Filed, which asks the day it was filed). */
function openGstTracker(how) {
  return async (env) => {
    const { page, stub } = env;
    stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { compliance_record: ["read", "write", "approve"], gst: ["read", "write"] } }) });
    stub.route({ method: "GET", re: /compliance\/due-dates\/calculate\?/, reply: () => ok({
      gstr1_due_date: "2026-10-11", gstr3b_due_date: "2026-10-20", gstr9_due_date: "2026-12-31" }) });
    // The reply the real route sends (routers/compliance.py): the record and what became of the period lock and the workspace return.
    stub.route({ method: "PATCH", re: /compliance\/calendar\/gst-1\/filed$/, ...answersAnEarlyFilingDate({
      door: "422", dateKey: "filed_date", endOf: () => "2026-09-30", sentence: (e) => GSTR_BEFORE_PERIOD_SENTENCE(e.filed, e.end),
      okBody: ok({ record: { id: "gst-1", filing_status: "filed" }, filing_recorded: true, filing_not_recorded_reason: null,
        period_locked_from: "2026-09-01", period_locked_to: "2026-09-30", workspace_return: null }) }) });
    stub.setTable("compliance_calendar", [{
      id: "gst-1", firm_id: "00000000-0000-4000-8000-0000000000f1", client_id: CLIENT_ID, compliance_type: "GSTR3B", period_start: "2026-09-01", period_end: "2026-09-30",
      due_date: "2026-10-20", filing_status: "pending", filed_date: null, created_at: "2026-10-01T00:00:00Z",
      clients: { client_name: "Acme Traders Pvt Ltd", gstin: "27AAACA1234A1ZK" },
    }]);
    await page.goto(`${env.base}/gst/`, { waitUntil: "networkidle" });
    if (how === "add" || how === "add-filed") {
      // The new row is answered as PostgREST answers an insert that asks for it back, so the page can record the filing against its id.
      // The door reads the period the NEW row declares, as the real one does (the default period is the month of the pinned today, which cannot have ended).
      let inserted = null;
      stub.answerInserts("compliance_calendar", (row) => (inserted = { ...row, id: "gst-new", created_at: "2026-10-08T00:00:00Z" }));
      stub.route({ method: "PATCH", re: /compliance\/calendar\/gst-new\/filed$/, ...answersAnEarlyFilingDate({
        door: "422", dateKey: "filed_date", endOf: () => inserted?.period_end ?? null, sentence: (e) => GSTR_BEFORE_PERIOD_SENTENCE(e.filed, e.end),
        okBody: ok({ record: { id: "gst-new", filing_status: "filed" }, filing_recorded: true, filing_not_recorded_reason: null,
          period_locked_from: "2026-09-01", period_locked_to: "2026-09-30", workspace_return: null }) }) });
      await page.getByRole("button", { name: /Add GST Filing/ }).first().click();
      await page.locator("#gst-add-filing-due-date").waitFor();
      await until(async () => (await page.locator("#gst-add-filing-due-date").inputValue()) !== "", "the engine's due date in the box");
      if (how === "add-filed") {
        // A return can be recorded as filed only for a period that has ended: the previous month, at the pinned clock.
        await page.locator("select[aria-label='Period']").last().selectOption({ label: "Sep 2026" });
        await until(async () => (await page.locator("#gst-add-filing-due-date").inputValue()) !== "", "the due date for the period chosen");
        await page.locator("select[aria-label='Status']").last().selectOption("Filed");   // the dialog's, after the page's own filter
        await page.locator("#gst-add-filing-filed-on").waitFor();
        await page.getByLabel("Acknowledgement number (ARN)", { exact: true }).fill("AA270125001234A");
      }
      return;
    }
    if (how === "batch") {
      await page.locator("tr", { hasText: "Acme Traders" }).locator("input[type=checkbox]").first().check();
      await page.getByRole("button", { name: "Mark Filed", exact: true }).first().click();
      await page.getByLabel(/Acknowledgement number \(ARN\) — /).fill("AA270125001234A");
      return;
    }
    await page.getByRole("button", { name: "Mark as Filed", exact: true }).first().click();
    await page.getByLabel("Acknowledgement number (ARN)", { exact: true }).fill("AA270125001234A");
  };
}

/** The MCA tracker's Filings tab with one pending AOC-4 listed: `how` is "single" (its own Mark Filed prompt, an SRN typed), "batch" (the bulk prompt, one row ticked, an SRN typed), "add" (the Add Filing form with a client and the CIN typed: only the due date is left) or "add-filed" (the same form with a due date, Status Filed and an SRN: only the day it was filed is left). */
function openMcaTracker(how) {
  return async (env) => {
    const { page, stub } = env;
    stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { mca: ["read", "write", "approve"], compliance_record: ["read", "write", "approve"] } }) });
    // The reply the real route sends for a status change (routers/mca_workspace.py): the filing, and what became of the compliance calendar.
    // The door judges a date against the year the filing declares (the tracker's rows are FY 2025-26; the Add form's new row declares the period typed into it).
    let inserted = null;
    stub.route({ method: "PATCH", re: /mca-workspace\/filings\/m-1\/status$/, ...answersAnEarlyFilingDate({
      door: "200", dateKey: "filing_date", endOf: () => "2026-03-31", sentence: () => MCA_BEFORE_YEAR_SENTENCE, okBody: ok({ id: "m-1", status: "filed" }) }) });
    stub.route({ method: "PATCH", re: /mca-workspace\/filings\/m-new\/status$/, ...answersAnEarlyFilingDate({
      door: "200", dateKey: "filing_date", endOf: () => yearEndOfFy(inserted?.period), sentence: () => MCA_BEFORE_YEAR_SENTENCE, okBody: ok({ id: "m-new", status: "filed" }) }) });
    stub.answerInserts("mca_filings", (row) => (inserted = { ...row, id: "m-new" }));
    stub.setTable("mca_filings", [{
      id: "m-1", firm_id: "00000000-0000-4000-8000-0000000000f1", client_id: CLIENT_ID, client_name: "Acme Traders Pvt Ltd", company_cin: "U12345MH2020PTC123456",
      form_type: "AOC-4", period: "FY 2025-26", due_date: "2026-10-30", filed_date: null, srn: null, status: "not_started", notes: null,
    }]);
    await page.goto(`${env.base}/mca/`, { waitUntil: "networkidle" });
    await page.getByRole("button", { name: "Filings", exact: true }).click();
    await page.locator("tr", { hasText: "Acme Traders" }).first().waitFor();
    if (how === "add" || how === "add-filed") {
      await page.getByRole("button", { name: /Add Filing/ }).first().click();
      await pick(page, page.locator('button[aria-label="Client"]'), "Acme Traders");
      await page.getByLabel("CIN / LLPIN", { exact: true }).fill("U12345MH2020PTC123456");
      // The default period is the CURRENT financial year, which has not ended: a form cannot be recorded as filed for it, so the form is for the last one.
      await page.locator("input[aria-label='Period']").last().fill("FY 2025-26");
      if (how === "add") return;
      await typeAndLeave(page.locator("#mca-due-date"), "30/10/2026");
      await page.locator("select[aria-label='Status']").last().selectOption("Filed");   // the dialog's, after the page's own filter
      await page.getByLabel("SRN (if filed)", { exact: true }).fill("SRN12345678");
      await page.locator("#mca-filed-on").waitFor();
      return;
    }
    if (how === "batch") {
      await page.locator("tr", { hasText: "Acme Traders" }).locator("input[type=checkbox]").first().check();
      await page.getByRole("button", { name: "Mark Filed", exact: true }).first().click();
      await page.getByLabel(/SRN \(Service Request Number\) — /).fill("SRN12345678");
      return;
    }
    await page.getByRole("button", { name: "Mark Filed", exact: true }).first().click();
    await page.getByLabel("SRN (Service Request Number)", { exact: true }).fill("SRN12345678");
  };
}

/** A client's MCA compliance page, Annual Filings tab, with one AOC-4 in progress and its "Mark Filed (CA)" panel open on an SRN: only the day it was filed is left. */
async function openClientMcaConfirm(env, { two = false } = {}) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { mca: ["read", "write", "approve"] } }) });
  stub.route({ method: "GET", re: /mca-workspace\/filings\?client_id=/, reply: () => ok([{
    id: "mf-1", client_id: CLIENT_ID, category: "annual", form_type: "AOC-4", financial_year: "2025-26", due_date: "2026-10-30", status: "in_progress" },
    ...(two ? [{ id: "mf-2", client_id: CLIENT_ID, category: "annual", form_type: "MGT-7", financial_year: "2025-26", due_date: "2026-11-29", status: "in_progress" }] : [])]) });
  stub.route({ method: "PATCH", re: /mca-workspace\/filings\/mf-1\/status$/, ...answersAnEarlyFilingDate({
    door: "200", dateKey: "filing_date", endOf: () => "2026-03-31", sentence: () => MCA_BEFORE_YEAR_SENTENCE, okBody: ok({ id: "mf-1", status: "filed" }) }) });
  await page.goto(`${env.base}/clients/${CLIENT_ID}/compliance/mca/`, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Annual Filings", exact: true }).click();
  await page.getByRole("button", { name: "Mark Filed (CA)", exact: true }).first().click();
  await page.getByLabel("SRN (required)", { exact: true }).fill("SRN12345678");
}

/** A client's MCA compliance page, ready for a tab to be clicked. The lists it reads answer with what the forms below have made so far (`env.made`), so a record that
 *  was saved can be looked for in its list. The four forms are the page's own (not the tracker's). */
async function atClientMca(env) {
  const { page, stub } = env;
  const made = { filings: [], directors: [] };
  env.made = made;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { mca: ["read", "write", "approve"] } }) });
  stub.route({ method: "GET", re: /mca-workspace\/filings\?client_id=/, reply: () => ok(made.filings) });
  stub.route({ method: "GET", re: /mca-workspace\/directors\?client_id=/, reply: () => ok(made.directors) });
  stub.setTable("mca_companies", []);
  await page.goto(`${env.base}/clients/${CLIENT_ID}/compliance/mca/`, { waitUntil: "networkidle" });
}

/** A client's MCA page, Company Master tab, "+ Add Company" open on a CIN, a name and the two capitals: only the incorporation date is left. */
async function openClientMcaCompany(env) {
  const { page, stub } = env;
  stub.route({ method: "POST", re: /mca-workspace\/companies$/, reply: (_req, raw) => {
    const b = JSON.parse(raw);
    stub.setTable("mca_companies", [{ id: "mc-1", company_name: b.company_name, cin: b.cin, incorp_date: b.incorporation_date, company_category: "Private Limited",
      authorized_capital_paise: b.authorized_capital_paise, paid_up_capital_paise: b.paid_up_capital_paise, registered_office: b.registered_address }]);
    return ok({ id: "mc-1" });
  } });
  await atClientMca(env);
  await page.getByRole("button", { name: "+ Add Company" }).click();
  await page.getByLabel("CIN (e.g. U74999MH2020PTC123456)", { exact: true }).fill("U74999MH2020PTC123456");
  await page.getByLabel("Company Name", { exact: true }).fill("Acme Traders Pvt Ltd");
  await page.getByLabel("Authorised Capital (₹)", { exact: true }).fill("2500000");
  await page.getByLabel("Paid-up Capital (₹)", { exact: true }).fill("1000000");
}

/** A client's MCA page, Annual Filings tab, "+ New Filing" open on a form and a year: only the due date is left. */
async function openClientMcaNewFiling(env) {
  const { page, stub } = env;
  stub.route({ method: "POST", re: /mca-workspace\/filings$/, reply: (_req, raw) => {
    const b = JSON.parse(raw);
    const row = { id: "mf-new", client_id: CLIENT_ID, category: "annual", form_type: b.form_type, financial_year: b.financial_year, due_date: b.due_date, status: "not_started" };
    env.made.filings.push(row);
    return ok(row);
  } });
  await atClientMca(env);
  await page.getByRole("button", { name: "Annual Filings", exact: true }).click();
  await page.getByRole("button", { name: "+ New Filing" }).click();
  await page.getByLabel("Form", { exact: true }).selectOption("AOC-4");
  await page.getByLabel("Financial year (for example 2025-26)", { exact: true }).fill("2025-26");
}

/** A client's MCA page, Directors tab, "+ Add Director" open on a DIN and a name: only the date of appointment is left. */
async function openClientMcaDirector(env) {
  const { page, stub } = env;
  stub.route({ method: "POST", re: /mca-workspace\/directors$/, reply: (_req, raw) => {
    const b = JSON.parse(raw);
    // The door stores the name as `director_name` (the column), which is what the table prints.
    const row = { id: "md-1", client_id: CLIENT_ID, din: b.din, director_name: b.name, designation: b.designation, date_of_appointment: b.date_of_appointment, kyc_status: "pending" };
    env.made.directors.push(row);
    return ok(row);
  } });
  await atClientMca(env);
  await page.getByRole("button", { name: "Directors", exact: true }).click();
  await page.getByRole("button", { name: "+ Add Director" }).click();
  await page.getByLabel("DIN (8 digits)", { exact: true }).fill("01234567");
  await page.getByLabel("Full Name", { exact: true }).fill("Asha Rao");
}

/** A client's TDS compliance page, Challans tab, "+ New Challan" open on a number, a BSR code, a section, an amount and a year: only the date is left. The list answers
 *  with the challans the form has recorded; `env.challanAnswer` is what the door says about the compliance calendar (`compliance_obligations`). */
async function openClientTdsChallan(env) {
  const { page, stub } = env;
  const made = [];
  env.challanAnswer = [];
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { tds: ["read", "write", "compute"] } }) });
  stub.route({ method: "GET", re: /api\/tds-workspace\/challans\?/, reply: () => ok({ challans: made, has_more: false, limit: 200, max_limit: 200 }) });
  stub.route({ method: "POST", re: /api\/tds-workspace\/challans$/, reply: (_req, raw) => {
    const b = JSON.parse(raw);
    const row = { id: "tc-1", challan_no: b.challan_no, payment_date: b.challan_date, bsr_code: b.bsr_code, section: b.section, total_paise: b.amount_paise, tds_paise: b.amount_paise, quarter: b.quarter, minor_head: "200" };
    made.push(row);
    return ok({ ...row, compliance_obligations: env.challanAnswer });
  } });
  await page.goto(env.at("/compliance/tds/"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Challans", exact: true }).click();
  await page.getByRole("button", { name: "+ New Challan" }).click();
  await page.getByLabel("Challan No.", { exact: true }).fill("00123");
  await page.getByLabel("BSR Code (7 digits)", { exact: true }).fill("0510308");
  await page.getByLabel("TDS Section (e.g. 194C)", { exact: true }).fill("194C");
  await page.getByLabel("Amount (₹)", { exact: true }).fill("12345");
  await page.getByLabel("FY (e.g. 2025-26)", { exact: true }).fill("2026-27");
}

/** Settings > Statutory values, "Record a notification" open on a state, a reference and one band's tax: only the two dates are left. The write is answered with the state, the day and the
 *  number of bands, as the real route answers it; the list the page reads again afterwards is a stub that always says no set is recorded (the real list would show the set stored). */
async function openStatutoryValues(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { payroll: ["read", "write"], settings: ["read", "write"] } }) });
  stub.route({ method: "GET", re: /api\/payroll\/statutory-values$/, reply: () => ok({
    pt_slabs: [], pt_levying_states: { GJ: "Gujarat", KL: "Kerala" }, pt_modelled_states: [], pt_recorded_states: [], pt_conflicts: [] }) });
  stub.route({ method: "PUT", re: /api\/payroll\/statutory-values\/pt$/, reply: (_req, raw) => { const b = JSON.parse(raw); return ok({ state: b.state, effective_from: b.effective_from, bands: b.bands.length }); } });
  await page.goto(`${env.base}/settings/statutory-values/`, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Record a notification" }).click();
  await page.getByLabel("State code", { exact: true }).fill("GJ");
  await page.getByLabel("Notification reference", { exact: true }).fill("PFT/2026/12");
  await page.getByLabel("Band 1: tax (₹)", { exact: true }).fill("200");
}

/** The "New Engagement Letter" dialog (the page's column chooser also has a "Title" box, so every locator is scoped to the dialog). */
const engagementDialog = (page) => page.locator("div.fixed").filter({ has: page.getByRole("heading", { name: "New Engagement Letter" }) });

/** Engagements with "New Engagement" open on a title: only the two dates (both optional) are left. */
async function openNewEngagementLetter(env) {
  const { page, stub } = env;
  const made = [];
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { engagements: ["read", "write"], billing: ["read", "write"] } }) });
  stub.route({ method: "GET", re: /api\/engagement-letters$/, reply: () => ok({ engagements: made }) });
  stub.route({ method: "GET", re: /api\/engagement-letters\/templates$/, reply: () => ok({ templates: [] }) });
  stub.route({ method: "POST", re: /api\/engagement-letters$/, reply: (_req, raw) => {
    const b = JSON.parse(raw);
    const row = { id: "en-1", engagement_number: "ENG-0001", title: b.title, status: "Draft", fee_amount_paise: b.fee_amount_paise ?? 0, recipient_name: b.recipient_name, recipient_email: b.recipient_email,
      lead_id: null, client_id: null, template_id: b.template_id, content: "", start_date: b.start_date, expiry_date: b.expiry_date, sent_at: null, last_sent_at: null, resend_count: 0,
      signed_at: null, signed_by_name: null, rejected_at: null, rejection_notes: null, sign_token: null, created_at: "2026-10-08T05:00:00Z" };
    made.push(row);
    return ok({ engagement: row });
  } });
  await page.goto(`${env.base}/engagements/`, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "New Engagement" }).first().click();
  await engagementDialog(page).waitFor();
  await engagementDialog(page).getByLabel("Title", { exact: true }).fill("GST Compliance — FY 2026-27");
}

/** The "Record a notification" overlay on the statutory values screen. */
const statutoryDialog = (page) => page.locator("div.fixed").filter({ has: page.getByRole("heading", { name: "Record a notification" }) });
/** The New lot dialog on the stock locations block. */
const lotDialog = (page) => page.locator("div.fixed").filter({ has: page.getByRole("heading", { name: "New lot" }) });
/** The Move stock panel, and its date box found by the caption above it (a span reading "Date"; the label's own text also holds the box's sentence once the text is unreadable): the
 *  previous product left that box unnamed, and a scenario that needs the name would fail there on the name and not on the behaviour it is about. The name is held by the table row
 *  `stock-transfer-date`. */
const transferPanel = (page) => page.locator("div.rounded-xl.overflow-hidden").filter({ has: page.getByRole("heading", { name: /Move stock between godowns/ }) }).last();
const transferDateBox = (page) => transferPanel(page).locator("label").filter({ has: page.locator("span").filter({ hasText: /^Date$/ }) }).locator("input").first();

/** The inventory page's stock-locations block with two godowns and one item held in the first. `how` is "transfer" (the Move stock panel, with the item and a quantity typed)
 *  or "lot" (the New lot dialog, with the item and a lot number typed). The stub is LIGHTER than the real routes (routers/inventory.py): the reads leave out default_godown_id, kind,
 *  as_of, total_value_paise, same_registration and gaps, the transfer and lot writes answer {id} and not the real body, and the routes' own refusals (for example "Only X is held…") are not driven. */
function openStockLocations(how) {
  return async (env) => {
    const { page, stub } = env;
    stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { inventory: ["read", "write"], accounting: ["read", "write"] } }) });
    stub.route({ method: "GET", re: /api\/inventory\/items\?/, reply: () => ok([{
      id: "sc1", name: "Copier paper", description: null, hsn_sac: "4802", unit: "NOS", is_active: true, stock_qty_units: 40, avg_cost_paise: 25000, stock_value_paise: 1000000 }]) });
    stub.route({ method: "GET", re: /api\/inventory\/godowns\?/, reply: () => ok({ unallocated_means: "Stock not yet placed in a godown.", godowns: [
      { id: "g1", name: "Main godown", code: "MAIN", state_code: "27", gstin: null, is_default: true, is_active: true },
      { id: "g2", name: "Pune godown", code: "PUN", state_code: "27", gstin: null, is_default: false, is_active: true }] }) });
    stub.route({ method: "GET", re: /api\/inventory\/position-detail\?/, reply: () => ok({ rows: [{
      service_catalogue_id: "sc1", item_name: "Copier paper", unit: "NOS", godown_id: "g1", godown_name: "Main godown", batch_id: null, batch_no: null, expiry_date: null, qty_units: "40", value_paise: 1000000 }] }) });
    stub.route({ method: "GET", re: /api\/inventory\/expiry\?/, reply: () => ok({ bucket_order: [], bucket_labels: {}, buckets: {}, rows: [], notes: [] }) });
    stub.route({ method: "GET", re: /api\/inventory\/batches\?/, reply: () => ok([]) });
    stub.route({ method: "GET", re: /api\/inventory\/transfer-preview\?/, reply: () => ok({ is_supply: false, reason: "Both godowns are in the same state, so this is not a supply." }) });
    stub.route({ method: "POST", re: /api\/inventory\/transfer$/, reply: () => ok({ id: "tr-1" }) });
    stub.route({ method: "POST", re: /api\/inventory\/batches$/, reply: () => ok({ id: "b-1" }) });
    await page.goto(env.at("/inventory/"), { waitUntil: "networkidle" });
    if (how === "transfer") {
      const panel = transferPanel(page);
      await panel.waitFor();
      await panel.locator("select").nth(2).selectOption("sc1");
      await panel.locator("input[inputmode=decimal]").fill("5");
      return;
    }
    await page.getByRole("button", { name: /Add lot/ }).first().click();
    const dialog = lotDialog(page);
    await dialog.waitFor();
    await dialog.locator("select").selectOption("sc1");
    await dialog.getByPlaceholder("As printed on the carton").fill("L-2026-001");
  };
}

/** A client's GST > Registrations tab with the primary registration and one other listed: `how` is "add" (the Add a registration prompt, with a GSTIN typed) or "close" (the Cancelled… date box on the other registration). */
function openGstRegistrations(how) {
  return async (env) => {
    const { page, stub } = env;
    stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { gst: ["read", "write", "approve"], client: ["read", "write"] } }) });
    stub.route({ method: "GET", re: /client-gst-registrations\/kinds$/, reply: () => ok({
      registration_types: [{ value: "regular", files_gstr1_and_3b: true, files_cmp08: false, files_gstr8: false, files_gstr4_annual: false, other_return_form: null }],
      composition_categories: [], filing_frequencies: ["monthly", "quarterly"], composition_rates_verified: false }) });
    stub.route({ method: "GET", re: /client-gst-registrations\/turnover\?/, reply: () => ok({ client_id: CLIENT_ID, governing_financial_year: "2025-26", governing_turnover_paise: null, note: "No aggregate turnover is recorded for this year.", years: [] }) });
    stub.route({ method: "GET", re: /client-gst-registrations\?/, reply: () => ok([
      { id: null, gstin: "27AAACA1234A1ZK", state_code: "27", registration_type: "regular", filing_frequency: "monthly", is_primary: true, trade_name: null,
        effective_from: null, effective_to: null, label: "Maharashtra (primary)", files_gstr1_and_3b: true, files_cmp08: false, files_gstr8: false, files_gstr4_annual: false },
      { id: "reg-2", gstin: "29AAACA1234A1ZG", state_code: "29", registration_type: "regular", filing_frequency: "monthly", is_primary: false, trade_name: "Bengaluru depot",
        effective_from: "2025-04-01", effective_to: null, label: "Karnataka", files_gstr1_and_3b: true, files_cmp08: false, files_gstr8: false, files_gstr4_annual: false },
    ]) });
    stub.route({ method: "POST", re: /api\/client-gst-registrations$/, reply: () => ok({ id: "reg-3" }) });
    stub.route({ method: "POST", re: /client-gst-registrations\/reg-2\/close$/, reply: () => ok({ id: "reg-2" }) });
    await page.goto(env.at("/compliance/gst/"), { waitUntil: "networkidle" });
    await page.getByRole("button", { name: "Registrations", exact: true }).click();
    if (how === "add") {
      await page.getByRole("button", { name: "Add a registration" }).click();
      await page.locator("#gst-reg-registered-from").waitFor();
      await page.getByPlaceholder("29AABCU9603R1ZJ").fill("29AABCU9603R1ZJ"); // a valid GSTIN the client does not hold yet
      return;
    }
    await page.getByRole("button", { name: "Cancelled…" }).click();
    await page.getByLabel(/was cancelled or surrendered/).waitFor();
  };
}

/** The bank screen's Entries tab with the Accounts panel open on "Add Bank Account", a bank, an account number and an opening balance typed, so only the date is left. */
async function openBankAccountForm(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { banking: ["read", "write", "approve"] } }) });
  stub.route({ method: "GET", re: /api\/banking\/accounts\/deletable\?/, reply: () => ok({}) });
  stub.route({ method: "GET", re: /api\/banking\/accounts\?/, reply: () => ok([]) });
  stub.route({ method: "POST", re: /api\/banking\/accounts$/, reply: () => ok({ id: "ba-new" }) });
  await page.goto(env.at("/bank/?tab=entries"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Accounts", exact: true }).click();
  await page.getByRole("button", { name: "Add Account" }).first().click();
  await page.getByLabel("Bank Name", { exact: true }).fill("Axis Bank");
  await page.getByLabel("Account Number", { exact: true }).fill("918020033445566");
  await page.getByLabel(/^Opening balance/i).first().fill("100000");
}

/** The bank screen's Reconcile tab with "New Reconciliation" open on a bank account, so only the statement dates and balances are left. */
async function openNewReconciliation(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { banking: ["read", "write", "approve"] } }) });
  stub.route({ method: "GET", re: /api\/banking\/accounts(\?|$)/, reply: () => ok([
    { id: "ba-1", client_id: CLIENT_ID, bank_name: "Axis Bank", account_no: "918020033445566", ifsc: "UTIB0000915", account_type: "Current", is_active: true,
      opening_balance_paise: 0, opening_balance_date: null, coa_account_id: null, currency: "INR" }]) });
  stub.route({ method: "GET", re: /api\/banking\/reconciliations\/opening-suggestion\?/, reply: () => ok({
    suggested_opening_paise: 0, source: "bank_account_opening", previous_reconciliation: null, matches: true, reconciled_book_balance_paise: 0, mismatch_paise: 0 }) });
  stub.route({ method: "GET", re: /api\/banking\/reconciliations(\?|$)/, reply: () => ok([]) });
  stub.route({ method: "POST", re: /api\/banking\/reconciliations$/, reply: () => ok({ id: "rec-1", status: "in_progress" }) });
  await page.goto(env.at("/bank/?tab=reconcile"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "New Reconciliation", exact: true }).click();
  await page.locator("select").filter({ has: page.locator("option[value='ba-1']") }).first().selectOption("ba-1");
  await page.locator("#recon-start").waitFor();
  await page.getByLabel("Opening balance (₹)").fill("0");
  await page.getByLabel("Closing balance (₹)").fill("100000");
}

/** The received cheques register (Sales > Post-dated cheques) with one cheque that has fallen due, so "Convert to receipt" and the "Presented on" box beside it are live. */
async function openChequeToConvert(env) {
  const { page, stub } = env;
  const count = { count: 0, amount_paise: 0 };
  const cheque = {
    id: "pdc-9", direction: "received", customer_id: "c-beta", vendor_id: null, party_name: "Beta Stores", cheque_no: "000451", cheque_date: "2026-10-01",
    amount_paise: 2_500_000, drawee_bank: "HDFC Bank", bank_account_id: "ba-1", allocations: [], status: "held", state: "due", is_due: true, is_stale: false,
    stale_note: null, stale_after: null, notes: null, converted_receipt_id: null, converted_payment_id: null, cancel_reason: null, posting_account_notice: null,
  };
  stub.route({ method: "GET", re: /post-dated-cheques\/options/, reply: () => ok({ parties: [{ id: "c-beta", name: "Beta Stores", gstin: null }], bank_accounts: [], documents: [] }) });
  stub.route({ method: "GET", re: /post-dated-cheques\?/, reply: () => ok({ as_of: "2026-10-08", cheques: [cheque], notes: [], includes_finished: false, summary: {
    received: { due: { count: 1, amount_paise: 2_500_000 }, not_due: count, converted: count, cancelled: count },
    issued: { due: count, not_due: count, converted: count, cancelled: count } } }) });
  stub.route({ method: "POST", re: /post-dated-cheques\/pdc-9\/convert$/, reply: () => ok({
    cheque: { ...cheque, status: "converted", state: "converted", is_due: false },
    document: { kind: "receipt", id: "r-1", number: "RCT/0001", date: "2026-10-05", amount_paise: 2_500_000, journal_entry_id: "j-1", unallocated_paise: 2_500_000, posting_account_notice: null },
    stale_note: null }) });
  await page.goto(env.at("/sales/?tab=post-dated-cheques"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Convert to receipt", exact: true }).waitFor();
}

/** A client's Income Tax > Filing screen with one ITR-3 ready for filing, selected, and "Record Acknowledgement" open with the acknowledgement number typed, so only the date is left. */
async function openRecordItrAcknowledgement(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { income_tax: ["read", "write", "approve"] } }) });
  stub.route({ method: "POST", re: /api\/itr\/filings\/itr-f1\/acknowledge$/, reply: () => ok({
    id: "itr-f1", client_id: CLIENT_ID, status: "filed", brought_forward_losses: { losses: [] },
    compliance_obligation: { state: "closed", closed: true, obligation_id: "ob-itr", message: "The compliance calendar's ITR obligation for FY 2025-26 is closed." } }) });
  stub.setTable("itr_filings", [{
    id: "itr-f1", client_id: CLIENT_ID, itr_form: "ITR-3", financial_year: "2025-26", assessment_year: "2026-27", status: "ready_for_filing",
    acknowledgement_number: null, filing_date: null, created_at: "2026-10-01T00:00:00Z", return_type: "original",
    original_acknowledgement_number: null, original_filing_date: null, computation_snapshot_id: null }]);
  await page.goto(env.at("/tax/filing/"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: /ITR-3/ }).first().click();
  await page.getByRole("button", { name: "Record Acknowledgement", exact: true }).click();
  await page.getByLabel("Acknowledgement Number", { exact: true }).fill("123456789012345");
}

/** Income Tax > Tax Audit with "Add Audit" open on a client, so only the audit and filing dates are left. */
async function openAddTaxAudit(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { income_tax: ["read", "write", "approve"] } }) });
  stub.setTable("tax_audits", []);
  await page.goto(`${env.base}/income-tax/tax-audit/`, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Add Audit", exact: true }).first().click();
  await pick(page, page.locator('button[aria-label="Client"]'), "Acme Traders Pvt Ltd");
  await page.locator("#tax-audit-date").waitFor();
}

/** A client's Income Tax > Filing screen with "New Filing" open on a REVISED return, whose earlier return's acknowledgement number is typed, so only that return's filing date is left. */
/** The same screen with TWO returns ready for filing (an ITR-3 and an ITR-4), the first selected and its acknowledgement panel open. */
async function openAcknowledgementOfTwoReturns(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { income_tax: ["read", "write", "approve"] } }) });
  stub.route({ method: "POST", re: /api\/itr\/filings\/itr-f[12]\/acknowledge$/, reply: () => ok({ id: "itr-f1", client_id: CLIENT_ID, status: "filed", brought_forward_losses: { losses: [] } }) });
  const row = (id, form) => ({ id, client_id: CLIENT_ID, itr_form: form, financial_year: "2025-26", assessment_year: "2026-27", status: "ready_for_filing",
    acknowledgement_number: null, filing_date: null, created_at: "2026-10-01T00:00:00Z", return_type: "original", original_acknowledgement_number: null,
    original_filing_date: null, computation_snapshot_id: null });
  stub.setTable("itr_filings", [row("itr-f1", "ITR-3"), row("itr-f2", "ITR-4")]);
  await page.goto(env.at("/tax/filing/"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: /ITR-3/ }).first().click();
  await page.getByRole("button", { name: "Record Acknowledgement", exact: true }).click();
}
async function openNewRevisedReturn(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { income_tax: ["read", "write", "compute", "approve"] } }) });
  stub.route({ method: "POST", re: /api\/itr\/filings$/, reply: () => ok({ id: "itr-f2", status: "draft" }) });
  stub.setTable("itr_filings", []);
  await page.goto(env.at("/tax/filing/"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "New Filing" }).first().click();
  await page.getByLabel("Kind of return", { exact: true }).selectOption("revised");
  await page.getByLabel("Earlier return's acknowledgement number").fill("123456789012345");
}

/** Income Tax > Notices with "Add Notice" open on a client, so only the date received and the response due date are left. */
async function openAddIncomeTaxNotice(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { income_tax: ["read", "write", "approve"] } }) });
  stub.setTable("it_notices", []);
  await page.goto(`${env.base}/income-tax/notices/`, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Add Notice", exact: true }).first().click();
  await pick(page, page.locator('button[aria-label="Client"]'), "Acme Traders Pvt Ltd");
  await page.locator("#notice-date-received").waitFor();
}

/** A client's Compliance screen with one government notice awaiting review, and "Correct" open on it. */
async function openCorrectNoticeReading(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { compliance: ["read", "write", "approve"] } }) });
  stub.route({ method: "PATCH", re: /document-intelligence-v2\/notices\/gn-1\/reading$/, reply: () => ok({ id: "gn-1" }) });
  stub.setTable("government_notices", [{
    id: "gn-1", client_id: CLIENT_ID, authority: "Income Tax Department", notice_type: "income_tax_notice", reference_no: "ITBA/AST/S/143(2)/2026-27/1", issue_date: "2026-09-20",
    response_due_date: "2026-10-20", description: "Details of expenses claimed", status: "open", ca_approved: false, created_at: "2026-09-21T00:00:00Z" }]);
  await page.goto(env.at("/compliance/"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Correct", exact: true }).first().click();
  await modalOf(page).locator("#notice-issued").waitFor();
}

/** A client's TDS compliance screen on its §197 Certificates tab, with "Record Certificate" open and a vendor, a certificate number, a rate and an amount typed, so only the validity dates are left. */
async function openRecordLowerDeductionCertificate(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { tds: ["read", "compute", "write"] } }) });
  stub.route({ method: "GET", re: /tds-workspace\/lower-deduction-certificates\?/, reply: () => ok({
    lower_deduction_certificates: [], has_more: false, limit: 200, max_limit: 200, vendors: [{ id: "v1", name: "Gamma Supplies" }] }) });
  stub.route({ method: "GET", re: /api\/tds\/sections$/, reply: () => ok({ sections: [{ section: "194C", section_197_eligible: true }], section_197_not_priced: [] }) });
  stub.route({ method: "POST", re: /tds-workspace\/lower-deduction-certificates$/, reply: () => ok({ id: "ldc-1" }) });
  await page.goto(env.at("/compliance/tds/"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "§197 Certificates", exact: true }).click();
  await page.getByRole("button", { name: "+ Record Certificate" }).click();
  await page.getByLabel("Vendor", { exact: true }).selectOption("v1");
  await page.getByLabel("Certificate number").fill("LDC/2025/0042");
  await page.getByLabel("Certified rate in percent (0 for nil)").fill("0.5");
  await page.getByLabel("Amount the certificate applies up to, in rupees").fill("500000");
}

/** Accounting > Recurring journals with "New template" open on a client, a name, two different accounts and an amount typed, so only the dates are left. */
async function openRecurringJournalTemplate(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { accounting: ["read", "write", "approve"] } }) });
  stub.route({ method: "GET", re: /api\/recurring-journals(\?|$)/, reply: () => ok([]) });
  stub.route({ method: "POST", re: /api\/recurring-journals$/, reply: () => ok({ id: "rj-1" }) });
  stub.setTable("chart_of_accounts", [
    { id: "ca-1", firm_id: "00000000-0000-4000-8000-0000000000f1", client_id: CLIENT_ID, account_code: "5010", account_name: "Rent expense", account_type: "Expense", is_active: true },
    { id: "ca-2", firm_id: "00000000-0000-4000-8000-0000000000f1", client_id: CLIENT_ID, account_code: "2010", account_name: "Rent payable", account_type: "Liability", is_active: true },
  ]);
  await page.goto(`${env.base}/accounting/recurring/`, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "New template", exact: true }).first().click();
  await pick(page, page.locator('button[aria-label="Client"]'), "Acme Traders Pvt Ltd");
  await page.locator("#rj-name").fill("Monthly office rent");
  await page.locator("#rj-dr").selectOption("ca-1");
  await page.locator("#rj-cr").selectOption("ca-2");
  await page.locator("#rj-amount").fill("125000");
}

const GSTIN_OF_THE_CLIENT = "27AAACA1234A1ZK";
const GSTR_FILED_SENTENCE = (form) => `Say the date this ${form} was filed on the portal. Recording it closes the period for new entries, and the lock message quotes the date — so it is asked for, not assumed.`;

/** A refusal as the GST workspace gives one: a 200 with `success: false` and a sentence. */
const refusal = (error) => ({ success: false, data: null, error });
/** The sentence the route says for a date filed before the period it declares had ended (`checked_filed_date`). Pinned to the Python by
 *  tests/test_the_drives_filing_sentences_are_the_servers.py, so a reworded server sentence fails there and not in a browser nobody runs. */
const GSTR_BEFORE_PERIOD_SENTENCE = (filed, end) => `A return cannot have been filed on ${filed}, before the period it declares ended on ${end}.`;
/** The MCA door's answer to a filing date before the financial year it declares has ended (routers/mca_workspace.py); an HTTP 200 with success:false. */
const MCA_BEFORE_YEAR_SENTENCE = "An AOC-4 for FY 2025-26 cannot have been filed before the year ended on 2026-03-31. Check the filing date. Nothing was changed.";
/** What the MCA door says when its insert fails (routers/mca_workspace.py, create_company and create_filing): an HTTP 200 with success:false. */
const MCA_COULD_NOT_SENTENCE = "Unable to complete MCA operation. Please try again.";
/** What `assert_client_access` raises (HTTP 404, core/authz.py) for a client the caller is not assigned to; the create doors of the client MCA and TDS tabs re-raise it. */
const CLIENT_NOT_FOUND_SENTENCE = "Not found";
/** What the statutory-values door says for a slab set with a hole in it (routers/payroll.py `put_pt_slabs`): an HTTP 422 whose detail is this sentence. */
const PT_UNCOVERED_SENTENCE = "These slabs do not cover every wage. They must start at 0, each band's upper bound must be the next band's lower bound, and the highest band must be left open ('and above'). A wage falling in a hole would come out as nil, which is indistinguishable from a state saying nothing is due.";
/** What the statutory-values screen says itself, before anything is sent. */
const PT_STATE_CODE_SENTENCE = 'State must be the two-letter code, e.g. "GJ".';
const PT_BAND_COMMA_SENTENCE = "Band 1: the amounts must be plain figures in rupees, without commas.";
/** What the MCA door says for the one refusal a CA meets in the ordinary course, adding a director twice (routers/mca_workspace.py `create_director`, migration 038's UNIQUE (client_id, din)): an HTTP 200 with success:false. */
const MCA_DUPLICATE_DIN_SENTENCE = "This DIN is already recorded for this client.";
/** What the TDS door says for a failure nobody anticipated, here the challan (routers/tds_workspace.py `_could_not`): an HTTP 200 with success:false. */
const TDS_COULD_NOT_CHALLAN_SENTENCE = "Could not record the TDS challan. The cause has been logged; please try again, and report it if it keeps failing.";
/** What a box that refuses a date after today says about 15 October 2026 at the pinned clock (8 October 2026). */
const AFTER_TODAY_SENTENCE = "15 Oct 2026 is after 08 Oct 2026.";
/** What the statutory-values screen says, derived from its boxes, when a notification names no source or one of its two days (the start of the sentence is enough to find it). */
const STATUTORY_REQUIRED_SENTENCE = "The notification reference, its date and the effective-from date are all required";
/** What the new-letter modal says while its Expiry box is before its Start box. */
const ENGAGEMENT_ORDER_SENTENCE = "Expiry date: it cannot be before the start date.";
/** What the lot dialog says while its Expires box is before its Manufactured box. */
const LOT_ORDER_SENTENCE = "Expires: it cannot be before the manufacture date.";
/** What the Move stock panel says of a quantity the server could not read. */
const TRANSFER_QUANTITY_SENTENCE = "Quantity: enter a number, like 5 or 12.5 (up to three decimals).";

/**
 * A route that answers a status change as the real filing doors do: a date before the period or year the filing declares ended is refused in the door's own
 * words, and any other date is accepted with `okBody`. The stubs used to answer success for every date, so a drive could record as filed a combination the server
 * refuses (found by an independent read of the thirteenth slice). `door` "422" is the calendar and obligation doors (HTTP 422, the sentence as `detail`, which the
 * API client RAISES); "200" is the MCA door (HTTP 200 with success false). `endOf(request body)` is the day the period or year ended, or null where there is none.
 */
function answersAnEarlyFilingDate({ door, dateKey, endOf, sentence, okBody }) {
  const early = (raw) => {
    let b;
    try { b = JSON.parse(raw); } catch { return null; }
    const end = endOf(b);
    return end && b[dateKey] && b[dateKey] < end ? { filed: b[dateKey], end } : null;
  };
  return door === "422"
    ? { status: (_req, raw) => (early(raw) ? 422 : 200), reply: (_req, raw) => { const e = early(raw); return e ? { detail: sentence(e) } : okBody; } }
    : { reply: (_req, raw) => { const e = early(raw); return e ? refusal(sentence(e)) : okBody; } };
}
/** The last day of the financial year a period "FY 2025-26" names (the MCA door reads a filing's year from it), or null. */
const yearEndOfFy = (period) => { const m = /FY (\d{4})-\d{2}/.exec(period ?? ""); return m ? `${Number(m[1]) + 1}-03-31` : null; };

/** The GST workspace's answer to a status change: a blank date on the move to submitted, and a date before the period ended, are refused in the
 *  route's own words. (A date after today is refused by the box before anything is sent, so the route's wording for it is never reached from here.) */
function gstStatusReply(form, periodEnd = "2026-09-30") {
  return (_req, raw) => {
    const b = JSON.parse(raw);
    if (b.status === "submitted") {
      if (!String(b.filed_date ?? "").trim()) return refusal(GSTR_FILED_SENTENCE(form));
      if (b.filed_date < periodEnd) return refusal(GSTR_BEFORE_PERIOD_SENTENCE(b.filed_date, periodEnd));
    }
    return ok({ status: b.status });
  };
}

/** GST > GSTR-1 built for a client and period, approved, with "Mark as Filed" open on an ARN: only the date is left. The opener's own writes
 *  (the build's save, the approval) are forgotten, so a row counts what the prompt writes. */
async function openGstr1MarkFiled(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { gst: ["read", "approve", "compute"] } }) });
  stub.setTable("clients", [{ ...CLIENT_ROW, name: CLIENT_ROW.client_name, gstin: GSTIN_OF_THE_CLIENT }]);
  stub.route({ method: "POST", re: /api\/gst\/gstr1\/from-books$/, reply: (_req, raw) => ok({
    period: JSON.parse(raw).period, gstin: GSTIN_OF_THE_CLIENT, payload: { gstin: GSTIN_OF_THE_CLIENT, fp: JSON.parse(raw).period, b2b: [] },
    summary: { counts: { b2b: 3, b2cs_rate_groups: 1, b2cl: 0, credit_notes_registered: 0, credit_notes_unregistered: 0 },
      totals_rupees: { taxable: 10000, cgst: 900, sgst: 900, igst: 0 } },
    invoice_count: 4, taxable_total_paise: 1000000, tax_total_paise: 180000, reconciliation: {},
    validation_errors: [], validation_warnings: [], payload_gaps: [] }) });
  // The saved row the approval and the filing look up (the build's own save is a PostgREST write the stub answers, and reads answer these rows).
  stub.setTable("gstr1_returns", [{ id: "g1-1", firm_id: "00000000-0000-4000-8000-0000000000f1", client_id: CLIENT_ID, period: "092026", gstin: GSTIN_OF_THE_CLIENT, status: "validated" }]);
  stub.route({ method: "PATCH", re: /gst-workspace\/gstr1\/g1-1\/status$/, reply: gstStatusReply("GSTR-1") });
  await page.goto(`${env.base}/gst/gstr1/`, { waitUntil: "networkidle" });
  await pick(page, page.locator('button[aria-label="Client"]'), "Acme Traders Pvt Ltd");
  await page.getByRole("button", { name: "Build GSTR-1", exact: true }).click();
  await page.getByRole("button", { name: "CA Approve", exact: true }).click();
  await page.getByRole("button", { name: "Mark as Filed", exact: true }).click();
  await page.getByLabel("ARN (Acknowledgment Reference Number)", { exact: true }).fill("AA2710260000001");
  await page.locator("#gstr1-filed-date").waitFor();
  await stub.quiet();
  stub.forgetWrites();
}

/** GST > GSTR-3B computed for a client and period, approved, with "Mark as Filed" open on an ARN: only the date is left. */
async function openGstr3bMarkFiled(env) {
  const { page, stub } = env;
  const zero = { igst_paise: 0, cgst_paise: 0, sgst_paise: 0 };
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { gst: ["read", "approve", "compute"] } }) });
  stub.setTable("clients", [{ ...CLIENT_ROW, name: CLIENT_ROW.client_name, gstin: GSTIN_OF_THE_CLIENT }]);
  stub.route({ method: "POST", re: /api\/gst\/gstr3b\/from-books$/, reply: (_req, raw) => ok({
    period: JSON.parse(raw).period, gstin: GSTIN_OF_THE_CLIENT, payload: { gstin: GSTIN_OF_THE_CLIENT, ret_period: JSON.parse(raw).period },
    working: {
      outward: { taxable_value_paise: 1800000, taxable_igst_paise: 0, taxable_cgst_paise: 900000, taxable_sgst_paise: 900000, zero_rated_paise: 0, zero_rated_igst_paise: 0, nil_exempt_paise: 0 },
      rcm_inward: { ...zero },
      itc: { ...zero, avail_igst_paise: 0, avail_cgst_paise: 100000, avail_sgst_paise: 100000, net_igst_paise: 0, net_cgst_paise: 100000, net_sgst_paise: 100000 },
      itc_reversal: { permanent_paise: { ...zero, cess_paise: 0 }, reclaimable_paise: { ...zero, cess_paise: 0 }, reasons: [] },
      net_payable: { ...zero, cgst_paise: 800000, sgst_paise: 800000, total_paise: 1600000, rcm_cash_paise: 0, challan_total_paise: 1600000 },
      rule_36_4: { gstr2a_record_count: 0, gstr2a_igst_paise: 0, gstr2a_cgst_paise: 0, gstr2a_sgst_paise: 0, cap_applied: false, compared: false,
        self_assessed_igst_paise: 0, self_assessed_cgst_paise: 0, self_assessed_sgst_paise: 0,
        per_document: { applied: false, allowed_igst_paise: 0, allowed_cgst_paise: 0, allowed_sgst_paise: 0, allowed_cess_paise: 0,
          withheld_igst_paise: 0, withheld_cgst_paise: 0, withheld_sgst_paise: 0, withheld_cess_paise: 0, withheld_total_paise: 0, withheld: [], not_assessed: [], notes: [] } },
      itc_utilisation: { available_paise: 200000, consumed_paise: 200000, carried_forward_paise: 0 },
    },
    validation_warnings: [], late_filing: { available: false, reason: "No filing date was given." }, undeclarable_rows: [], bank_line_caveats: [],
    registration_caveat: null, gstr1_tie_out: null, reconciliation: { reconciled: true }, months_without_gstr2b: [] }) });
  // The three side reports (Rule 37, 37A and 43) are asked for after the build and may fail without failing the return: they are refused here,
  // which the page shows as "not checked" beside the figures, so no fixture of their large shapes is carried.
  stub.route({ method: "GET", re: /gst-workspace\/itc\/rule/, ...refuse("The ITC working is not worked in this drive.") });
  stub.setTable("gstr3b_returns", [{ id: "g3-1", firm_id: "00000000-0000-4000-8000-0000000000f1", client_id: CLIENT_ID, period: "092026", gstin: GSTIN_OF_THE_CLIENT, status: "validated" }]);
  stub.route({ method: "PATCH", re: /gst-workspace\/gstr3b\/g3-1\/status$/, reply: gstStatusReply("GSTR-3B") });
  await page.goto(`${env.base}/gst/gstr3b/`, { waitUntil: "networkidle" });
  await pick(page, page.locator('button[aria-label="Client"]'), "Acme Traders Pvt Ltd");
  await page.getByRole("button", { name: "Compute GSTR-3B", exact: true }).click();
  await page.getByRole("button", { name: "CA Approve", exact: true }).click();
  await page.getByRole("button", { name: "Mark as Filed", exact: true }).click();
  await page.getByLabel("ARN (Acknowledgment Reference Number)", { exact: true }).fill("AA2710260000002");
  await page.locator("#gstr3b-filed-date").waitFor();
  await stub.quiet();
  stub.forgetWrites();
}

/** A client's GST page (compliance) on its GSTR-1 or GSTR-3B tab with one approved return, "Mark as filed" open: the dialog that records a filing and locks the period. */
function openClientGstFiling(tab, { second = false } = {}) {
  const [label, route, id] = tab === "gstr1" ? ["GSTR-1", "gstr1", "g1-1"] : ["GSTR-3B", "gstr3b", "g3-1"];
  return async (env) => {
    const { page, stub } = env;
    stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { gst: ["read", "approve", "compute"] } }) });
    const row = { id, period: "092026", gstin: GSTIN_OF_THE_CLIENT, status: "ca_approved", total_taxable_paise: 1000000,
      tax_liability_paise: 180000, itc_claimed_paise: 100000, net_tax_paise: 80000, cash_payable_paise: 80000 };
    // `second`: a second approved return (the month before) is listed too, and the dialog is left closed for the scenario to open.
    const rows = second ? [row, { ...row, id: id.replace("-1", "-0"), period: "082026" }] : [row];
    stub.route({ method: "GET", re: /api\/gst-workspace\/returns\?/, reply: () => ok({ gstr1: tab === "gstr1" ? rows : [], gstr3b: tab === "gstr3b" ? rows : [] }) });
    for (const r of rows) stub.route({ method: "PATCH", re: new RegExp(`gst-workspace\\/${route}\\/${r.id}\\/status$`), reply: gstStatusReply(label, r.period === "092026" ? "2026-09-30" : "2026-08-31") });
    await page.goto(env.at("/compliance/gst/"), { waitUntil: "networkidle" });
    await page.getByRole("button", { name: label, exact: true }).click();
    if (second) { await page.getByRole("button", { name: "Mark as filed", exact: true }).nth(1).waitFor(); return; }
    await page.getByRole("button", { name: "Mark as filed", exact: true }).click();
    await page.getByLabel("ARN from the portal", { exact: true }).fill("AA2710260000003");
    await page.locator("#gst-mark-filed-date").waitFor();
    await stub.quiet();
    stub.forgetWrites();
  };
}

/** The client's GSTR-3B tab with "Compute from Books" open on a period: the optional "Date filed" box (it adds the section 50 interest). */
async function openClientGstr3bCompute(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { gst: ["read", "approve", "compute"] } }) });
  stub.route({ method: "GET", re: /api\/gst-workspace\/returns\?/, reply: () => ok({ gstr1: [], gstr3b: [] }) });
  stub.route({ method: "POST", re: /api\/gst\/gstr3b\/from-books$/, reply: (_req, raw) => ok({
    period: JSON.parse(raw).period, gstin: GSTIN_OF_THE_CLIENT, payload: {}, working: {}, tax_liability_paise: 180000, itc_claimed_paise: 100000,
    net_tax_paise: 80000, cash_payable_paise: 80000, itc_carried_forward_paise: 0,
    reconciliation: { reconciled: true, output_gst: { ledger_paise: 180000, computed_paise: 180000 }, itc: { ledger_paise: 100000, computed_paise: 100000 } } }) });
  await page.goto(env.at("/compliance/gst/"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "GSTR-3B", exact: true }).click();
  await page.getByRole("button", { name: "Compute from Books", exact: true }).first().click();   // the header's; the empty list offers one too
  await page.getByLabel("GSTR-3B return period to compute (MMYYYY)", { exact: true }).fill("092026");
}

const TDS_BEFORE_QUARTER_SENTENCE = "A statement for Q2 FY 2026-27 cannot have been filed before the quarter ended on 2026-09-30. Check the date on the receipt.";

/** TDS > Returns computed for a client and quarter, approved, with "Mark as Filed" open on a PRN: only the date is left. */
async function openTdsReturnMarkFiled(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { tds: ["read", "write", "approve", "compute"] } }) });
  stub.route({ method: "POST", re: /api\/tds\/26q\/from-books$/, reply: (_req, raw) => ok({
    form: "26Q", tan: "MUMA12345B", deductor_name: "Acme Traders Pvt Ltd", financial_year: JSON.parse(raw).financial_year, quarter: JSON.parse(raw).quarter,
    quarter_end_date: "2026-09-30", total_tds_deducted_paise: 1000000, total_tds_deposited_paise: 1000000, deductee_count: 1,
    deductees: [], challans: [], validation_errors: [], warnings: [] }) });
  stub.route({ method: "POST", re: /api\/tds-workspace\/returns$/, reply: () => ok({ id: "tr-1" }) });
  // The route's own refusal of a date earlier than the end of the quarter the statement reports on (routers/tds_workspace.py).
  stub.route({ method: "PATCH", re: /api\/tds-workspace\/returns\/tr-1\/status$/, reply: (_req, raw) => {
    const b = JSON.parse(raw);
    if (b.status === "filed" && b.filing_date < "2026-09-30") return refusal(TDS_BEFORE_QUARTER_SENTENCE);
    return ok({ id: "tr-1", status: b.status });
  } });
  await page.goto(`${env.base}/tds/returns/`, { waitUntil: "networkidle" });
  await pick(page, page.locator('button[aria-label="Client"]'), "Acme Traders Pvt Ltd");
  // Q2 of FY 2026-27 has ended at the pinned 8 October 2026; the page's default quarter (Q3) has not, and the route refuses to approve it.
  await page.getByLabel("Quarter", { exact: true }).selectOption("Q2");
  await page.getByRole("button", { name: "Compute 26Q", exact: true }).click();
  await page.getByRole("button", { name: "CA Approve", exact: true }).click();
  await page.getByRole("button", { name: "Mark as Filed", exact: true }).click();
  await page.getByLabel("PRN (Provisional Receipt Number)", { exact: true }).fill("PRN0000000001");
  await page.locator("#tds-filing-date").waitFor();
  await stub.quiet();
  stub.forgetWrites();
}

/** Tax > Computation for an individual on the old regime, the Run Computation section open: the "Loan sanctioned on" claim date (it alone decides section 80EE or 80EEA). */
async function openComputationLoanDate(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { income_tax: ["read", "write", "approve", "compute"] } }) });
  stub.setTable("clients", [{ ...CLIENT_ROW, entity_type: "Individual" }]);
  stub.route({ method: "GET", re: /api\/income-tax\/financial-years$/, reply: () => ok({ financial_years: [{ fy: "2026-27", verified: true }], current_fy: "2026-27" }) });
  stub.route({ method: "GET", re: /api\/income-tax\/assessee-kind\?/, reply: () => ok({ kind: "individual", refusal: null, implies_business_income: false, unavailable_reliefs: [], basis_note: null, asks_about_members: false }) });
  // The engine is the server's: the request is the thing under test, and the answer is a refusal the page shows.
  stub.route({ method: "POST", re: /api\/income-tax\/compute$/, ...refuse("The computation is not run in this drive.") });
  await page.goto(env.at("/tax/computation/"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Run Computation" }).click();
  await page.getByLabel("Tax regime", { exact: true }).selectOption("old");
  await page.locator("#computation-loan-sanctioned-on").waitFor();
}

const YEAR_END_DEBIT = "00000000-0000-4000-8000-0000000000a1";
const YEAR_END_CREDIT = "00000000-0000-4000-8000-0000000000a2";

/** Year-end > Adjustments for an engagement of the given FY, "New Adjustment" open with the description, accounts and amount typed: the adjusting entry's date is left. */
const openYearEndAdjustment = (fy) => async (env) => {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { year_end: ["read", "write", "approve"], accounting: ["read", "write"] } }) });
  stub.route({ method: "GET", re: /api\/year-end\/engagements\/eng-1$/, reply: () => ok({ id: "eng-1", client_id: CLIENT_ID, financial_year: fy, status: "draft", version: 1, created_at: "2026-04-05T00:00:00Z", updated_at: "2026-04-05T00:00:00Z" }) });
  stub.setTable("year_end_adjustments", []);
  stub.setTable("chart_of_accounts", [
    { id: YEAR_END_DEBIT, account_code: "5010", account_name: "Rent expense", account_type: "Expense", is_active: true, client_id: null },
    { id: YEAR_END_CREDIT, account_code: "2010", account_name: "Rent payable", account_type: "Liability", is_active: true, client_id: CLIENT_ID },
  ]);
  // The route answers the CREATED row, which the page puts at the end of its list.
  stub.route({ method: "POST", re: /api\/year-end\/eng-1\/adjustments$/, reply: (_req, raw) => ok({
    id: "adj-1", engagement_id: "eng-1", reference_no: null, status: "draft", created_at: "2026-10-08T08:00:00Z", ...JSON.parse(raw) }) });
  await page.goto(env.at("/year-end/eng-1/?tab=adjustments"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "New Adjustment" }).first().click();
  await page.getByLabel("Description", { exact: true }).fill("Accrual for outstanding rent - March");
  // The two account columns hold a ledger account's id (uuid, migration 293), so the form PICKS an account from the client's chart (its own and the
  // firm-level ones: what migration 570 accepts) and sends the id.
  await pick(page, page.locator('button[aria-label="Debit Account"]'), "Rent expense");
  await pick(page, page.locator('button[aria-label="Credit Account"]'), "Rent payable");
  await page.getByLabel("Amount (₹)", { exact: true }).fill("125000");
};

const RECURRING_JOURNAL = {
  id: "rjt-1", client_id: CLIENT_ID, name: "Monthly office rent", frequency: "monthly", day_of_month: 1, narration: null,
  start_date: "2026-11-01", end_date: "2027-10-31", next_run_date: "2026-11-01", status: "active",
  lines: [
    { id: "rjl-1", template_id: "rjt-1", account_id: "ca-1", debit_paise: 12500000, credit_paise: 0, narration: null, sort_order: 0 },
    { id: "rjl-2", template_id: "rjt-1", account_id: "ca-2", debit_paise: 0, credit_paise: 12500000, narration: null, sort_order: 1 },
  ],
};

/** Accounting > Recurring journals with one template that stops on 31/10/2027, "Edit" open on it: the stop date is the box to clear. */
async function openEditRecurringJournal(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { accounting: ["read", "write", "approve"] } }) });
  stub.route({ method: "GET", re: /api\/recurring-journals(\?|$)/, reply: () => ok([RECURRING_JOURNAL]) });
  stub.route({ method: "PATCH", re: /api\/recurring-journals\/rjt-1$/, reply: () => ok(RECURRING_JOURNAL) });
  stub.setTable("chart_of_accounts", [
    { id: "ca-1", firm_id: "00000000-0000-4000-8000-0000000000f1", client_id: CLIENT_ID, account_code: "5010", account_name: "Rent expense", account_type: "Expense", is_active: true },
    { id: "ca-2", firm_id: "00000000-0000-4000-8000-0000000000f1", client_id: CLIENT_ID, account_code: "2010", account_name: "Rent payable", account_type: "Liability", is_active: true },
  ]);
  await page.goto(`${env.base}/accounting/recurring/`, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Edit", exact: true }).first().click();
  await page.locator("#rj-end").waitFor();
}

const RECURRING_BILL = {
  id: "rb-1", client_id: CLIENT_ID, vendor_id: "ven-1", title: "Office rent", description: null, frequency: "monthly",
  start_date: "2026-11-01", end_date: "2027-10-31", next_run_date: "2026-11-01", notes: null, is_inter_state: false, is_reverse_charge: false, status: "active",
  lines: [{ id: "rbl-1", service_catalogue_id: ITEM.id, description: "Consulting", hsn_sac: null, unit: null, quantity: 1, rate_paise: 5000000,
    gst_rate_bps: 1800, is_service: true, itc_eligible: true, blocked_credit_reason: null, tds_applicable: false, expense_account_id: null }],
};

/** Purchases > Recurring bills with one template that stops on 31/10/2027, "Edit" open on it. */
async function openEditRecurringBill(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { accounting: ["read", "write", "approve"] } }) });
  stub.route({ method: "GET", re: /api\/recurring-purchase-bills\?/, reply: () => ok([RECURRING_BILL]) });
  stub.route({ method: "PUT", re: /api\/recurring-purchase-bills\/rb-1$/, reply: () => ok(RECURRING_BILL) });
  stub.setTable("service_catalogue", [{ ...ITEM, kind: "service" }]);
  await page.goto(env.at("/purchases/?tab=recurring"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Edit", exact: true }).first().click();
  await page.locator("#rec-bill-end").waitFor();
}

/** Purchases > Recurring bills with "New Template" open on a vendor, a name and one product line, so only the dates are left. */
async function openRecurringBillTemplate(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { accounting: ["read", "write", "approve"] } }) });
  stub.route({ method: "GET", re: /api\/recurring-purchase-bills\?/, reply: () => ok([]) });
  stub.route({ method: "POST", re: /api\/recurring-purchase-bills$/, reply: () => ok({ id: "rb-1" }) });
  stub.setTable("service_catalogue", [{ ...ITEM, kind: "service" }]);
  await page.goto(env.at("/purchases/?tab=recurring"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "New Template" }).first().click();
  await pick(page, page.locator('button[aria-label="Vendor"]'), "Gamma Supplies");
  await page.getByLabel("Name", { exact: true }).fill("Office rent");
  await pick(page, page.locator('button[aria-label="Product or service for line 1"]'), "Consulting");
  await page.getByLabel("Rate (₹)", { exact: true }).fill("50000");
}

/** Accounting > Trial balance import taken to its Review step with a small balanced CSV and a client chosen, so only the opening date is left. */
async function openTrialBalanceImport(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { accounting: ["read", "write", "approve"] } }) });
  // The real service echoes the date it posted as (the typed one, or the client's financial year start for a blank box) and reports the lines it wrote.
  stub.route({ method: "POST", re: /api\/accounting\/trial-balance\/import$/, reply: (_req, raw) => ok({
    posted: true, journal_entry_id: "j-tb", opening_date: JSON.parse(raw).opening_date ?? "2026-04-01", accounts: 2, adjustment_lines: 2,
    total_debit_paise: 10000000, total_credit_paise: 10000000 }) });
  await page.goto(`${env.base}/accounting/trial-balance-import/`, { waitUntil: "networkidle" });
  await pick(page, page.locator('button[aria-label="Client"]'), "Acme Traders Pvt Ltd");
  await page.locator('input[aria-label="Trial balance CSV file to upload"]').setInputFiles({
    name: "tb.csv", mimeType: "text/csv", buffer: Buffer.from("Account name,Debit,Credit\nCash at bank,100000,\nShare capital,,100000\n") });
  await page.getByRole("button", { name: "Next: Review", exact: true }).click();
  await page.getByRole("button", { name: /^Import \d+ Accounts$/ }).waitFor();
}

/** Purchases > Payments with "Record Payment" open on a vendor and an amount, so only the date is left. */
async function openVendorPayment(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { accounting: ["read", "write", "approve"] } }) });
  stub.route({ method: "POST", re: /api\/purchase-payments\/?$/, reply: () => ok({ id: "pp-1" }) });
  await page.goto(env.at("/purchases/?tab=payments"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Record Payment" }).first().click();
  await pick(page, page.locator('button[aria-label="Vendor"]'), "Gamma Supplies");
  await page.getByLabel("Amount (₹)", { exact: true }).fill("25000");
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
  stub.route({ method: "POST", re: /compliance\/obligations\/ob-1\/mark-filed$/, ...answersAnEarlyFilingDate({
    door: "422", dateKey: "filed_date", endOf: () => "2026-09-30", sentence: (e) => GSTR_BEFORE_PERIOD_SENTENCE(e.filed, e.end), okBody: ok({ id: "ob-1", status: "Filed" }) }) });
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
    open: onAShortScreen(openTdsChallanForm), saveInView: true, cleared: "Challan date: enter the date on the challan.",
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
    id: "mark-as-filed", shortForm: "15/01/2026", title: "Mark as Filed prompt (Deadlines)", open: openMarkFiled, heldWhileUnreadable: true,
    fields: [{ box: (p) => modalOf(p).locator("#mark-filed-date"), label: "Filed on", key: "filed_date", full: "05/10/2026", iso: "2026-10-05" }],
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
    id: "post-dated-cheque", title: "post-dated cheque form", open: openPostDatedCheque, cleared: "Cheque date: enter the date written on the cheque.",
    fields: [{ box: (p) => p.locator("#cheque-date"), label: "Cheque date", key: "cheque_date", full: "15/11/2026", iso: "2026-11-15" }],
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
    id: "statutory-handoff-esi-remittance", shortForm: "15/01/2026", title: "Payroll > File: the date an ESI payment was made (the portal's challan)", open: openStatutoryHandoff("esic"), cleared: "Date: enter the date of the payment or filing.",
    fields: [{ box: (p) => p.getByLabel("Date of the payment or filing"), label: "Date", key: "paid_on", full: "07/10/2026", iso: "2026-10-07" }],
    save: (p) => p.getByRole("button", { name: "Record it", exact: true }), write: /payroll\/clients\/[^/]+\/remittances$/,
  },
  {
    id: "statutory-handoff-epf-ecr", shortForm: "15/01/2026", title: "Payroll > File: the date an EPF return was filed (the ECR record)", open: openStatutoryHandoff("epf"), cleared: "Date: enter the date of the payment or filing.",
    fields: [{ box: (p) => p.getByLabel("Date of the payment or filing"), label: "Date", key: "submitted_on", full: "07/10/2026", iso: "2026-10-07" }],
    save: (p) => p.getByRole("button", { name: "Record it", exact: true }), write: /payroll\/runs\/run1\/ecr\/filed$/,
  },
  {
    id: "house-property-worksheet", title: "Income tax > Computation > house-property worksheet: the loan and completion dates", open: openHousePropertyWorksheet, eachField: true,
    fields: [
      { box: (p) => p.getByLabel("Loan taken on"), label: "Loan taken on", key: "loan_taken_on", full: "12/05/2019", iso: "2019-05-12", read: (b) => b.payload.properties[0].loan_taken_on },
      { box: (p) => p.getByLabel("House completed on"), label: "House completed on", key: "completed_on", full: "30/06/2021", iso: "2021-06-30", read: (b) => b.payload.properties[0].completed_on },
    ],
    // the salary worksheet below it has a button of the same name; the house-property one is the first on the screen
    save: (p) => p.getByRole("button", { name: "Save and work out", exact: true }).first(), write: /income-tax\/worksheets\/house_property$/,
  },
  {
    id: "itc04-lot", title: "Sales > Challans > FORM GST ITC-04: the date a lot came back and the job worker's challan date", open: openItc04Lot, eachField: true, cleared: "Give the date the goods came back.",
    fields: [
      { box: (p) => p.locator("#itc04-came-back-on"), label: "Came back on", key: "returned_on", full: "12/09/2026", iso: "2026-09-12" },
      { box: (p) => p.locator("#itc04-challan-date"), label: "Job worker's challan date", key: "job_worker_challan_date", full: "10/09/2026", iso: "2026-09-10" },
    ],
    save: (p) => p.getByRole("button", { name: "Record this lot", exact: true }), write: /sales-cycle\/challans\/ch-1\/returns$/,
  },
  {
    id: "itr-mark-filed", shortForm: "15/01/2026", title: "Income Tax > ITR tracker: the date a return was filed (Mark ITR as Filed)", open: openItrTracker("single"), cleared: "Filing date is required",
    fields: [{ box: (p) => p.locator("#itr-filed-modal-date"), label: "Date of filing", key: "filed_date", full: "28/07/2026", iso: "2026-07-28" }],
    save: (p) => p.getByRole("button", { name: "Confirm Filing", exact: true }), write: /compliance\/calendar\/itr-1\/filed$/,
  },
  {
    id: "itr-batch-mark-filed", shortForm: "15/01/2026", title: "Income Tax > ITR tracker: the one date a batch of returns was filed on", open: openItrTracker("batch"), heldWhileUnreadable: true, cleared: "held",
    fields: [{ box: (p) => p.locator("#itr-batch-filed-date"), label: "Date of filing", key: "filed_date", full: "28/07/2026", iso: "2026-07-28" }],
    save: (p) => p.getByRole("button", { name: /^Confirm Filing \(/ }), write: /compliance\/calendar\/itr-1\/filed$/,
  },
  {
    id: "itr-add-deadline", title: "Income Tax > ITR tracker: the due date of a new ITR deadline", open: openItrTracker("add"), cleared: "No due date yet — pick a client so the due date can be computed.",
    fields: [{ box: (p) => p.locator("#itr-add-due-date"), label: "Due date", key: "due_date", full: "05/08/2026", iso: "2026-08-05" }],
    save: (p) => p.getByRole("button", { name: "Add Deadline", exact: true }), write: /rest\/v1\/compliance_calendar/,
  },
  {
    id: "gst-mark-filed", shortForm: "15/01/2026", title: "GST > filing tracker: the date a return was filed (Mark as Filed)", open: openGstTracker("single"), cleared: "Filing date is required",
    fields: [{ box: (p) => p.locator("#gst-filed-modal-date"), label: "Date of filing", key: "filed_date", full: "05/10/2026", iso: "2026-10-05" }],
    save: (p) => p.getByRole("button", { name: "Confirm Filing", exact: true }), write: /compliance\/calendar\/gst-1\/filed$/,
  },
  {
    id: "gst-batch-mark-filed", shortForm: "15/01/2026", title: "GST > filing tracker: the one date a batch of returns was filed on", open: openGstTracker("batch"), heldWhileUnreadable: true, cleared: "held",
    fields: [{ box: (p) => p.locator("#gst-batch-filed-date"), label: "Date of filing", key: "filed_date", full: "05/10/2026", iso: "2026-10-05" }],
    save: (p) => p.getByRole("button", { name: /^Confirm \d+ Filings?$/ }), write: /compliance\/calendar\/gst-1\/filed$/,
  },
  {
    id: "gst-add-filing", title: "GST > filing tracker: the due date of a new filing", open: openGstTracker("add"), cleared: "Due date: enter the date this return is due.",
    fields: [{ box: (p) => p.locator("#gst-add-filing-due-date"), label: "Due date", key: "due_date", full: "05/11/2026", iso: "2026-11-05" }],
    save: (p) => p.getByRole("button", { name: "Save Filing", exact: true }), write: /rest\/v1\/compliance_calendar/,
  },
  {
    // A filing added as Filed used to be recorded as filed TODAY, with no date box and no question (the period lock quotes the date).
    id: "gst-add-filing-filed-on", shortForm: "15/01/2026", title: "GST > filing tracker > Add GST Filing recorded as Filed: the day it was filed on the portal", open: openGstTracker("add-filed"),
    cleared: "Filed on: enter the date this return was filed on the portal.",
    fields: [{ box: (p) => p.locator("#gst-add-filing-filed-on"), label: "Filed on", key: "filed_date", full: "05/10/2026", iso: "2026-10-05" }],
    save: (p) => p.getByRole("button", { name: "Save Filing", exact: true }), write: /compliance\/calendar\/gst-new\/filed$/,
  },
  {
    id: "mca-filed-modal-date", shortForm: "15/01/2026", title: "MCA > Filings > Mark Filed: the day a form was filed on MCA21", open: openMcaTracker("single"), cleared: "Filing date is required",
    fields: [{ box: (p) => p.locator("#mca-filed-modal-date"), label: "Date of filing", key: "filing_date", full: "05/10/2026", iso: "2026-10-05" }],
    save: (p) => p.getByRole("button", { name: "Confirm Filing", exact: true }), write: /mca-workspace\/filings\/m-1\/status$/,
  },
  {
    id: "mca-batch-filed-date", shortForm: "15/01/2026", title: "MCA > Filings > Mark Filed (several): the one day a batch of forms was filed on MCA21", open: openMcaTracker("batch"), heldWhileUnreadable: true, cleared: "held",
    fields: [{ box: (p) => p.locator("#mca-batch-filed-date"), label: "Date of filing", key: "filing_date", full: "05/10/2026", iso: "2026-10-05" }],
    save: (p) => p.getByRole("button", { name: /^Confirm \d+ Filings?$/ }), write: /mca-workspace\/filings\/m-1\/status$/,
  },
  {
    id: "mca-add-filing-filed-on", shortForm: "15/01/2026", title: "MCA > Filings > Add Filing recorded as Filed: the day it was filed on MCA21", open: openMcaTracker("add-filed"),
    cleared: "A filing marked Filed needs its SRN and the date it was filed on MCA21.",
    fields: [{ box: (p) => p.locator("#mca-filed-on"), label: "Filed on MCA21 on", key: "filing_date", full: "05/10/2026", iso: "2026-10-05" }],
    save: (p) => p.getByRole("button", { name: "Add Filing", exact: true }).last(), write: /mca-workspace\/filings\/m-new\/status$/,
  },
  {
    id: "mca-add-filing-due-date", title: "MCA > Filings > Add Filing: the date a form is due", open: openMcaTracker("add"), cleared: "Client, CIN and Due Date are required.",
    fields: [{ box: (p) => p.locator("#mca-due-date"), label: "Due date", key: "due_date", full: "30/10/2026", iso: "2026-10-30" }],
    save: (p) => p.getByRole("button", { name: "Add Filing", exact: true }).last(), write: /rest\/v1\/mca_filings/,
  },
  {
    id: "mca-confirm-filing-date", shortForm: "15/01/2026", title: "A client's MCA filings > Mark Filed (CA): the day the form was filed on MCA21", open: openClientMcaConfirm, cleared: "Filing date is required",
    fields: [{ box: (p) => p.locator("#mca-confirm-filing-date"), label: "Filing date", key: "filing_date", full: "05/10/2026", iso: "2026-10-05" }],
    save: (p) => p.getByRole("button", { name: "Confirm Filing", exact: true }), write: /mca-workspace\/filings\/mf-1\/status$/,
  },
  // The fourteenth slice (5-11-2026): the three forms on a client's compliance tabs that took a date as plain typed text and closed as though they had saved.
  {
    id: "client-mca-company-incorporated", shortForm: "15/01/2026", title: "A client's MCA > Company Master > Add Company: the day the company was incorporated", open: openClientMcaCompany,
    fields: [{ box: (p) => p.locator("#mca-company-incorporated"), label: "Incorporation date", key: "incorporation_date", full: "12/06/2019", iso: "2019-06-12" }],
    save: (p) => p.getByRole("button", { name: "Save", exact: true }), write: /mca-workspace\/companies$/,
  },
  {
    id: "client-mca-new-filing-due-date", title: "A client's MCA > Annual Filings > New Filing: the date a form is due", open: openClientMcaNewFiling,
    cleared: "Due date: enter the date this form is due.",
    fields: [{ box: (p) => p.locator("#mca-new-filing-due-date"), label: "Due date", key: "due_date", full: "30/10/2026", iso: "2026-10-30" }],
    save: (p) => p.getByRole("button", { name: "Save", exact: true }), write: /mca-workspace\/filings$/,
  },
  {
    id: "client-mca-director-appointment", title: "A client's MCA > Directors > Add Director: the date of appointment", open: openClientMcaDirector,
    fields: [{ box: (p) => p.locator("#mca-director-appointment"), label: "Date of appointment", key: "date_of_appointment", full: "01/04/2025", iso: "2025-04-01" }],
    save: (p) => p.getByRole("button", { name: "Save", exact: true }), write: /mca-workspace\/directors$/,
  },
  {
    id: "client-tds-challan-date", title: "A client's TDS > Challans > New Challan: the date on the challan", open: openClientTdsChallan,
    cleared: "Challan date: enter the date on the challan.",
    fields: [{ box: (p) => p.locator("#tds-client-challan-date"), label: "Challan date", key: "challan_date", full: "07/10/2026", iso: "2026-10-07" }],
    save: (p) => p.getByRole("button", { name: "Save", exact: true }), write: /api\/tds-workspace\/challans$/,
  },
  // The fifteenth slice (6-11-2026): the statutory values screen, the engagement letter form and the stock transfer and lot forms.
  {
    id: "statutory-values-pt-notification", title: "Settings > Statutory values > Record a notification: when a professional-tax notice takes effect and when it was issued",
    open: openStatutoryValues, saveInView: true, eachField: true,
    cleared: "The notification reference, its date and the effective-from date are all required", clearedFields: [1],
    fields: [
      { box: (p) => p.locator("#sv-effective-from"), label: "Effective from", key: "effective_from", full: "01/04/2026", iso: "2026-04-01" },
      { box: (p) => p.locator("#sv-notified-on"), label: "Notification date", key: "notification_date", full: "10/03/2026", iso: "2026-03-10" },
    ],
    save: (p) => p.getByRole("button", { name: "Record", exact: true }), write: /api\/payroll\/statutory-values\/pt$/,
  },
  {
    id: "new-engagement-letter-dates", title: "Engagements > New Engagement: when a letter starts and when it lapses", open: openNewEngagementLetter, eachField: true,
    fields: [
      { box: (p) => engagementDialog(p).getByLabel("Start date", { exact: true }), label: "Start date", key: "start_date", full: "01/04/2026", iso: "2026-04-01" },
      { box: (p) => engagementDialog(p).getByLabel("Expiry date", { exact: true }), label: "Expiry date", key: "expiry_date", full: "31/03/2027", iso: "2027-03-31" },
    ],
    save: (p) => engagementDialog(p).getByRole("button", { name: "Create Engagement", exact: true }), write: /api\/engagement-letters$/,
  },
  {
    id: "stock-transfer-date", title: "Inventory > Locations > Move stock between godowns: the day the stock moved", open: openStockLocations("transfer"),
    cleared: "Date: enter the date the stock moved.",
    fields: [{ box: (p) => p.getByLabel("Date the stock moved", { exact: true }), label: "Date", key: "movement_date", full: "07/10/2026", iso: "2026-10-07" }],
    save: (p) => p.getByRole("button", { name: "Move stock", exact: true }), write: /api\/inventory\/transfer$/,
  },
  {
    id: "stock-lot-dates", title: "Inventory > Locations > New lot: when a lot was manufactured and when it expires", open: openStockLocations("lot"), eachField: true, shortForm: "15/01/2026",
    fields: [
      { box: (p) => p.getByLabel("Manufactured (optional)"), label: "Manufactured", key: "manufactured_on", full: "01/09/2026", iso: "2026-09-01" },
      { box: (p) => p.getByLabel("Expires (optional)"), label: "Expires", key: "expiry_date", full: "31/08/2028", iso: "2028-08-31" },
    ],
    save: (p) => p.locator("div.fixed").getByRole("button", { name: "Create", exact: true }), write: /api\/inventory\/batches$/,
  },
  {
    id: "gst-registration-add", title: "GST > Registrations: the date a registration took effect (Add a registration)", open: openGstRegistrations("add"),
    fields: [{ box: (p) => p.locator("#gst-reg-registered-from"), label: "Registered from", key: "effective_from", full: "01/07/2017", iso: "2017-07-01" }],
    save: (p) => p.getByRole("button", { name: "Add", exact: true }), write: /api\/client-gst-registrations$/,
  },
  {
    id: "gst-registration-cancelled", title: "GST > Registrations: the date a registration was cancelled or surrendered", open: openGstRegistrations("close"), cleared: "Enter the date the registration was cancelled or surrendered.",
    fields: [{ box: (p) => p.getByLabel(/was cancelled or surrendered/), label: "Date cancelled or surrendered", key: "effective_to", full: "31/03/2026", iso: "2026-03-31" }],
    // the registration table's own Record: the turnover panel above it has a button of the same name
    save: (p) => p.getByRole("table").getByRole("button", { name: "Record", exact: true }), write: /client-gst-registrations\/reg-2\/close$/,
  },
  {
    id: "bank-account-opening-date", title: "Bank > Accounts > Add Bank Account: the date the opening balance is as at", open: openBankAccountForm,
    cleared: "An opening balance needs the date it is the balance as at",
    fields: [{ box: (p) => p.locator("#bank-opening-date"), label: "Opening balance date", key: "opening_balance_date", full: "01/04/2025", iso: "2025-04-01" }],
    save: (p) => p.getByRole("button", { name: "Add Account", exact: true }).last(), write: /api\/banking\/accounts$/,
  },
  {
    id: "bank-reconciliation-statement-dates", title: "Bank > Reconcile > New Reconciliation: the statement's start and end dates", open: openNewReconciliation, eachField: true, cleared: "Bank account and statement dates are required.", clearedFields: [1],
    fields: [
      { box: (p) => p.locator("#recon-start"), label: "Statement start", key: "statement_start_date", full: "01/09/2026", iso: "2026-09-01" },
      { box: (p) => p.locator("#recon-end"), label: "Statement end", key: "statement_end_date", full: "30/09/2026", iso: "2026-09-30" },
    ],
    save: (p) => p.getByRole("button", { name: "Open Reconciliation", exact: true }), write: /api\/banking\/reconciliations$/,
  },
  {
    id: "cheque-presented-on", title: "Sales > Post-dated cheques: the day a due cheque was presented (Convert to receipt posts a receipt on it)", open: openChequeToConvert,
    fields: [{ box: (p) => p.locator("#cheque-presented-on"), label: "Presented on", key: "presented_on", full: "05/10/2026", iso: "2026-10-05" }],
    save: (p) => p.getByRole("button", { name: "Convert to receipt", exact: true }), write: /post-dated-cheques\/pdc-9\/convert$/,
    afterSave: (p) => p.getByRole("alertdialog").or(p.getByRole("dialog")).getByRole("button", { name: "Convert to receipt", exact: true }).click(),
  },
  {
    id: "itr-filing-acknowledgement", shortForm: "15/01/2026", title: "Income Tax > Filing: the date on the acknowledgement (Record as Filed)", open: openRecordItrAcknowledgement, heldWhileUnreadable: true, cleared: "held",
    fields: [{ box: (p) => p.locator("#itr-ack-filing-date"), label: "Filing date", key: "filing_date", full: "24/07/2026", iso: "2026-07-24" }],
    save: (p) => p.getByRole("button", { name: "Record as Filed", exact: true }), write: /api\/itr\/filings\/itr-f1\/acknowledge$/,
  },
  {
    id: "tax-audit-dates", title: "Income Tax > Tax Audit > Add Audit: the audit date and the filing date", open: openAddTaxAudit, eachField: true,
    fields: [
      { box: (p) => p.locator("#tax-audit-date"), label: "Audit date", key: "audit_date", full: "30/09/2026", iso: "2026-09-30" },
      { box: (p) => p.locator("#tax-audit-filing-date"), label: "Filing date", key: "filing_date", full: "07/10/2026", iso: "2026-10-07" },
    ],
    save: (p) => p.getByRole("button", { name: "Add Audit", exact: true }).last(), write: /rest\/v1\/tax_audits/,
  },
  {
    id: "itr-new-revised-return", shortForm: "15/01/2026", title: "Income Tax > Filing > New Filing (revised): the earlier return's filing date", open: openNewRevisedReturn, cleared: "Earlier return's filing date: enter the date on the earlier return's receipt.",
    fields: [{ box: (p) => p.locator("#itr-original-filing-date"), label: "Earlier return's filing date", key: "original_filing_date", full: "20/07/2026", iso: "2026-07-20" }],
    save: (p) => p.getByRole("button", { name: "Create", exact: true }), write: /api\/itr\/filings$/,
  },
  {
    id: "income-tax-notice-dates", title: "Income Tax > Notices > Add Notice: the date received and the response due date", open: openAddIncomeTaxNotice, eachField: true,
    cleared: "Client and date received are required",
    fields: [
      { box: (p) => p.locator("#notice-date-received"), label: "Date received", key: "date_received", full: "03/10/2026", iso: "2026-10-03" },
      { box: (p) => p.locator("#notice-response-due"), label: "Response due date", key: "response_due_date", full: "02/11/2026", iso: "2026-11-02" },
    ],
    save: (p) => p.getByRole("button", { name: "Add Notice", exact: true }).last(), write: /rest\/v1\/it_notices/,
  },
  {
    id: "notice-reading-correction-dates", title: "Compliance > a government notice > Correct the reading: the date it was issued and the response due date", open: openCorrectNoticeReading,
    heldWhileUnreadable: true, eachField: true,
    fields: [
      { box: (p) => p.locator("#notice-issued"), label: "Issued on", key: "issue_date", full: "22/09/2026", iso: "2026-09-22" },
      { box: (p) => p.locator("#notice-due"), label: "Response due on", key: "response_due_date", full: "21/10/2026", iso: "2026-10-21" },
    ],
    save: (p) => modalOf(p).getByRole("button", { name: "Save correction", exact: true }), write: /document-intelligence-v2\/notices\/gn-1\/reading$/,
  },
  {
    id: "tds-lower-deduction-certificate", title: "TDS > §197 Certificates > Record Certificate: the validity period (valid from and to)", open: openRecordLowerDeductionCertificate, eachField: true, clearedFields: [1],
    cleared: "Enter the validity period.",
    fields: [
      { box: (p) => p.getByLabel("Valid from", { exact: true }), label: "Valid from", key: "valid_from", full: "01/04/2025", iso: "2025-04-01" },
      { box: (p) => p.getByLabel("Valid to", { exact: true }), label: "Valid to", key: "valid_to", full: "31/03/2026", iso: "2026-03-31" },
    ],
    save: (p) => p.getByRole("button", { name: "Save", exact: true }).last(), write: /tds-workspace\/lower-deduction-certificates$/,
  },
  {
    id: "recurring-journal-template", title: "Accounting > Recurring journals > New template: the start and end dates (it raises a draft journal every month)", open: openRecurringJournalTemplate,
    eachField: true, cleared: "Start date is required",
    fields: [
      { box: (p) => p.locator("#rj-start"), label: "Start date", key: "start_date", full: "01/11/2026", iso: "2026-11-01" },
      { box: (p) => p.locator("#rj-end"), label: "End date", key: "end_date", full: "31/10/2027", iso: "2027-10-31" },
    ],
    save: (p) => p.getByRole("button", { name: "Save template", exact: true }), write: /api\/recurring-journals$/,
  },
  {
    id: "recurring-bill-template", title: "Purchases > Recurring bills > New Template: the first bill's date and the date to stop after", open: openRecurringBillTemplate,
    eachField: true, cleared: "First bill on: enter the date of the first bill.",
    fields: [
      { box: (p) => p.locator("#rec-bill-start"), label: "First bill on", key: "start_date", full: "01/11/2026", iso: "2026-11-01" },
      { box: (p) => p.locator("#rec-bill-end"), label: "Stop after", key: "end_date", full: "31/10/2027", iso: "2027-10-31" },
    ],
    save: (p) => p.getByRole("button", { name: "Create template", exact: true }), write: /api\/recurring-purchase-bills$/,
  },
  {
    id: "trial-balance-import-opening-date", title: "Accounting > Trial balance import: the opening date the balances are posted as at", open: openTrialBalanceImport,
    fields: [{ box: (p) => p.locator("#tb-opening-date"), label: "Opening date", key: "opening_date", full: "01/04/2026", iso: "2026-04-01" }],
    save: (p) => p.getByRole("button", { name: /^Import \d+ Accounts$/ }), write: /api\/accounting\/trial-balance\/import$/,
  },
  {
    id: "vendor-payment-date", title: "Purchases > Payments > Record Payment: the date a payment to a vendor was made (it posts to the books)", open: openVendorPayment,
    cleared: "Date: enter the date the payment was made.",
    fields: [{ box: (p) => p.locator("#vendor-payment-date"), label: "Payment date", key: "payment_date", full: "05/10/2026", iso: "2026-10-05" }],
    save: (p) => p.getByRole("button", { name: "Record Payment", exact: true }).first(), write: /api\/purchase-payments\/?$/,   // the form's own button comes first; the filter bar's and the empty state's only open the form
  },
  {
    id: "gstr1-mark-filed", title: "GST > GSTR-1 > Mark as Filed: the date the return was filed on the portal (recording it locks the period)", open: openGstr1MarkFiled,
    heldWhileUnreadable: true, cleared: { serverSays: "Say the date this GSTR-1 was filed on the portal." },
    shortForm: "15/01/2026",
    fields: [{ box: (p) => p.locator("#gstr1-filed-date"), label: "Date filed", key: "filed_date", full: "07/10/2026", iso: "2026-10-07" }],
    save: (p) => p.getByRole("button", { name: "Confirm Filed", exact: true }), write: /gst-workspace\/gstr1\/g1-1\/status$/,
  },
  {
    id: "gstr3b-mark-filed", title: "GST > GSTR-3B > Mark as Filed: the date the return was filed on the portal (recording it locks the period)", open: openGstr3bMarkFiled,
    heldWhileUnreadable: true, cleared: { serverSays: "Say the date this GSTR-3B was filed on the portal." },
    shortForm: "15/01/2026",
    fields: [{ box: (p) => p.locator("#gstr3b-filed-date"), label: "Date filed", key: "filed_date", full: "07/10/2026", iso: "2026-10-07" }],
    save: (p) => p.getByRole("button", { name: "Confirm Filed", exact: true }), write: /gst-workspace\/gstr3b\/g3-1\/status$/,
  },
  {
    id: "client-gstr1-record-filing", title: "Client GST > GSTR-1 > Mark as filed: the date filed on the portal (recording it locks the period; it starts empty)", open: openClientGstFiling("gstr1"),
    heldWhileUnreadable: true, cleared: "held",
    shortForm: "15/01/2026",
    fields: [{ box: (p) => p.locator("#gst-mark-filed-date"), label: "Date filed", key: "filed_date", full: "07/10/2026", iso: "2026-10-07" }],
    save: (p) => p.getByRole("button", { name: "Record as filed", exact: true }), write: /gst-workspace\/gstr1\/g1-1\/status$/,
  },
  {
    id: "client-gstr3b-record-filing", title: "Client GST > GSTR-3B > Mark as filed: the date filed on the portal (recording it locks the period; it starts empty)", open: openClientGstFiling("gstr3b"),
    heldWhileUnreadable: true, cleared: "held",
    shortForm: "15/01/2026",
    fields: [{ box: (p) => p.locator("#gst-mark-filed-date"), label: "Date filed", key: "filed_date", full: "07/10/2026", iso: "2026-10-07" }],
    save: (p) => p.getByRole("button", { name: "Record as filed", exact: true }), write: /gst-workspace\/gstr3b\/g3-1\/status$/,
  },
  {
    id: "client-gstr3b-compute-date-filed", title: "Client GST > GSTR-3B > Compute from Books: the optional date filed (it adds the section 50 interest to the working)", open: openClientGstr3bCompute,
    fields: [{ box: (p) => p.locator("#gstr3b-compute-filed-on"), label: "Date filed", key: "filed_on", full: "07/10/2026", iso: "2026-10-07" }],
    save: (p) => p.getByRole("button", { name: "Compute", exact: true }), write: /api\/gst\/gstr3b\/from-books$/,
  },
  {
    id: "tds-return-mark-filed", title: "TDS > Returns > Mark as Filed: the date the statement was filed on the portal", open: openTdsReturnMarkFiled,
    heldWhileUnreadable: true, cleared: "held",
    shortForm: "15/01/2026",
    fields: [{ box: (p) => p.locator("#tds-filing-date"), label: "Date filed", key: "filing_date", full: "07/10/2026", iso: "2026-10-07" }],
    save: (p) => p.getByRole("button", { name: "Confirm Filed", exact: true }), write: /api\/tds-workspace\/returns\/tr-1\/status$/,
  },
  {
    id: "computation-loan-sanctioned-on", title: "Tax > Computation: the date the housing loan was sanctioned (it decides section 80EE or 80EEA; blank claims nothing)", open: openComputationLoanDate,
    fields: [{ box: (p) => p.locator("#computation-loan-sanctioned-on"), label: "Loan sanctioned on", key: "housing_loan_sanctioned_on", full: "15/03/2019", iso: "2019-03-15", read: (b) => b.chapter_vi_a.housing_loan_sanctioned_on }],
    save: (p) => p.getByRole("button", { name: "Compute & Save Snapshot", exact: true }), write: /api\/income-tax\/compute$/,
  },
  {
    id: "year-end-adjustment-date", title: "Year-end > Adjustments > New Adjustment: the date an adjusting entry is posted at (it posts to the audited books)", open: openYearEndAdjustment("2026-27"),
    cleared: "Date is required",
    fields: [{ box: (p) => p.getByLabel("Adjustment date", { exact: true }), label: "Date", key: "adjustment_date", full: "31/03/2027", iso: "2027-03-31" }],
    save: (p) => p.getByRole("button", { name: "Create Adjustment", exact: true }), write: /api\/year-end\/eng-1\/adjustments$/,
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
  // A box whose date can never be later than today (the day a return was filed) reads a short form as the last such day, not the next one: `shortForm`.
  const short = spec.shortForm ?? "15/01/2027";
  assert.equal(await primary.inputValue(), short, `${spec.title}: 15/1 is ${short}`);
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

  // 4b. A CLEARED box is not an unreadable one and reports no problem; what it does is the row's `cleared` sentence (or, `cleared: "held"`, a held
  //     button) and sends nothing. A row whose date is optional leaves `cleared` out; the rows of earlier slices have not been given this step.
  if (spec.cleared) {
    await typeAndLeave(primary, "");
    if (spec.cleared === "held") {
      assert.equal(await spec.save(page).isDisabled(), true, `${spec.title}: the button was live over a cleared date`);
    } else if (typeof spec.cleared === "object") {
      // `cleared: { serverSays }`: the screen leaves a blank date to the server, which answers it in words (the stub speaks the route's own
      // sentence). ONE request goes out carrying "", the sentence is shown in the dialog, and the form is still open for the date.
      await spec.save(page).click();
      assert.ok(!spec.clearedFields, `${spec.title}: cleared { serverSays } cannot be combined with clearedFields`);
      await shownInTheDialog(page, spec.cleared.serverSays, `${spec.title}: the server's answer to a cleared date was not shown`);
      await stub.quiet();
      const sent = stub.writesTo(spec.write);
      assert.equal(sent.length, 1, `${spec.title}: a cleared date should send ONE request for the server to answer, saw ${sent.length}`);
      assert.equal(JSON.parse(sent[0].body)[spec.fields[0].key], "", `${spec.title}: a cleared date should reach the server as "", was ${JSON.stringify(JSON.parse(sent[0].body)[spec.fields[0].key])}`);
      stub.forgetWrites();
    } else {
      await spec.save(page).click();
      await page.getByText(spec.cleared).first().waitFor({ timeout: 4000 }).catch(() => {
        throw new Error(`${spec.title}: Save over a cleared date did not say "${spec.cleared}"`);
      });
    }
    await stub.quiet();
    if (typeof spec.cleared !== "object") assert.equal(stub.writesTo(spec.write).length, 0, `${spec.title}: Save over a cleared date SENT A WRITE`);
  }
  // 4b'. Where a form needs more than one date, each of the others is cleared in turn with the rest valid (`clearedFields`: indexes into `fields`).
  for (const k of spec.clearedFields ?? []) {
    const field = spec.fields[k];
    for (const other of spec.fields) await typeAndLeave(other.box(page), "15/03/2026");
    await typeAndLeave(field.box(page), "");
    await spec.save(page).click();
    await page.getByText(spec.cleared).first().waitFor({ timeout: 4000 }).catch(() => {
      throw new Error(`${spec.title} / ${field.label}: Save over this box cleared did not say "${spec.cleared}"`);
    });
    await stub.quiet();
    assert.equal(stub.writesTo(spec.write).length, 0, `${spec.title} / ${field.label}: Save over this box cleared SENT A WRITE`);
  }

  // 4c. A form with more than one date refuses an unreadable text in ANY of them, not only the first: each box has its own key and label.
  if (spec.eachField) {
    for (const field of spec.fields.slice(1)) {
      await typeAndLeave(primary, "15/03/2026");
      await typeAndLeave(field.box(page), "31/02/2026");
      if (spec.heldWhileUnreadable) {
        assert.equal(await spec.save(page).isDisabled(), true, `${spec.title} / ${field.label}: the button was live over an unreadable date in this box`);
        await page.getByText(FEB_SENTENCE).first().waitFor({ timeout: 4000 }).catch(() => {
          throw new Error(`${spec.title} / ${field.label}: the box did not say "${FEB_SENTENCE}" beside the held button`);
        });
      } else {
        await spec.save(page).click();
        await page.getByText(`${field.label}: ${FEB_SENTENCE}`).first().waitFor({ timeout: 4000 }).catch(() => {
          throw new Error(`${spec.title} / ${field.label}: Save over an unreadable date in this box did not say "${field.label}: ${FEB_SENTENCE}"`);
        });
      }
      await stub.quiet();
      assert.equal(stub.writesTo(spec.write).length, 0, `${spec.title} / ${field.label}: Save over an unreadable date in this box SENT A WRITE`);
      await typeAndLeave(field.box(page), "15/03/2026");
    }
  }

  // 5. The date typed in full is the ISO date the server receives.
  for (const field of spec.fields) await typeAndLeave(field.box(page), field.full);
  for (const field of spec.fields) {
    assert.equal(await field.box(page).inputValue(), field.full, `${spec.title} / ${field.label}: ${field.full} did not stay as typed`);
  }
  await spec.save(page).click();
  if (spec.afterSave) await spec.afterSave(page); // a confirmation the screen asks between the click and the write
  await stub.quiet();
  const writes = stub.writesTo(spec.write);
  assert.equal(writes.length, 1, `${spec.title}: expected one write, saw ${writes.length} (${stub.allWrites().map((w) => w.method + " " + w.path).join(", ") || "none"})`);
  const body = JSON.parse(writes[0].body);
  for (const field of spec.fields) {
    const got = field.read ? field.read(body) : body[field.key];
    assert.equal(got, field.iso, `${spec.title}: ${field.key} should reach the server as ${field.iso}, was ${JSON.stringify(got)}`);
  }
}

/** A sentence the person can SEE and REACH: waited for, then asked of the browser with a trial click, which fails if an overlay covers it (a message
 *  line drawn behind a dialog is "visible" to a locator and unseen by the person). For an answer a dialog says about itself. */
async function shownInTheDialog(page, sentence, what) {
  const loc = page.getByText(sentence).first();
  await loc.waitFor({ timeout: 4000 }).catch(() => { throw new Error(`${what}: "${sentence}"`); });
  await loc.click({ trial: true, timeout: 1500 }).catch((e) => {
    throw new Error(`${what} where the person can reach it: "${sentence}" is drawn behind something (${String(e.message).split("\n")[0].slice(0, 120)})`);
  });
}

/** The four forms on a client's compliance tabs (fourteenth slice): three used to take a date as plain text and ignore the answer, and the fourth (a director) had been
 *  fixed for that but kept its typed values through Cancel. `refusal` is the sentence the door gives when its insert fails (`Unable to complete MCA operation…` in
 *  routers/mca_workspace.py, `_could_not` in routers/tds_workspace.py), `httpRefusal` the 404 `assert_client_access` raises for a client the caller is not assigned to;
 *  tests/test_the_drives_filing_sentences_are_the_servers.py holds all three to the routers. `listShows` is text the saved record puts in its list; `optionalDate` is
 *  whether a blank date is allowed (and then sent as null), which the database decides: `mca_companies.incorp_date` and `mca_directors.date_of_appointment` are
 *  nullable, `mca_filings.due_date` and `tds_challans.payment_date` are NOT NULL. */
const CLIENT_COMPLIANCE_FORMS = [
  { id: "client-mca-company", name: "A client's MCA > Company Master > Add Company", open: openClientMcaCompany, add: "+ Add Company", write: /mca-workspace\/companies$/,
    dateBox: "#mca-company-incorporated", dateKey: "incorporation_date", typedDate: "12/06/2019", typedLabel: "Company Name", typedValue: "Acme Traders Pvt Ltd", listShows: "Acme Traders Pvt Ltd", optionalDate: true,
    refusal: MCA_COULD_NOT_SENTENCE, httpRefusal: CLIENT_NOT_FOUND_SENTENCE },
  { id: "client-mca-director", name: "A client's MCA > Directors > Add Director", open: openClientMcaDirector, add: "+ Add Director", write: /mca-workspace\/directors$/,
    dateBox: "#mca-director-appointment", dateKey: "date_of_appointment", typedDate: "01/04/2025", typedLabel: "Full Name", typedValue: "Asha Rao", listShows: "Asha Rao", optionalDate: true,
    refusal: MCA_DUPLICATE_DIN_SENTENCE, httpRefusal: CLIENT_NOT_FOUND_SENTENCE },
  { id: "client-mca-new-filing", name: "A client's MCA > Annual Filings > New Filing", open: openClientMcaNewFiling, add: "+ New Filing", write: /mca-workspace\/filings$/,
    dateBox: "#mca-new-filing-due-date", dateKey: "due_date", typedDate: "30/10/2026", typedLabel: "Financial year (for example 2025-26)", typedValue: "2025-26", listShows: "2026-10-30", optionalDate: false,
    askedFor: "Due date: enter the date this form is due.",
    refusal: MCA_COULD_NOT_SENTENCE, httpRefusal: CLIENT_NOT_FOUND_SENTENCE },
  { id: "client-tds-challan", name: "A client's TDS > Challans > New Challan", open: openClientTdsChallan, add: "+ New Challan", write: /api\/tds-workspace\/challans$/,
    dateBox: "#tds-client-challan-date", dateKey: "challan_date", typedDate: "07/10/2026", typedLabel: "Challan No.", typedValue: "00123", listShows: "00123", optionalDate: false,
    askedFor: "Challan date: enter the date on the challan.",
    refusal: TDS_COULD_NOT_CHALLAN_SENTENCE, httpRefusal: CLIENT_NOT_FOUND_SENTENCE },
];

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
  // The customer STATEMENT window. Its two boxes fed Generate, the PDF and the Email modal's Send, which posted start_date and end_date as typed
  // (an outward mail): a window that was not two dates went out as "" and the server refused it in words about a field the person never saw. And
  // the Email and the PDF read the customer picker and the boxes as they were NOW, so after Generate for one customer, choosing another and pressing
  // Email mailed the second customer's statement to the first one's address (found by two independent reads of the seventh and eighth slices). Now
  // Generate refuses a window that is not two dates in order, in the field's own sentence, the picker clears the statement, and the Email and the
  // PDF send the statement SHOWN. The dates are typed on the page and Send is pressed in the modal that covers the boxes.
  {
    id: "customer-statement-email-window",
    title: "Sales > Statements: Generate refuses a window that is not two dates in order, the Email sends the statement shown (its customer and its ISO period) whatever the boxes say",
    contexts: TZ_MATRIX,
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { sales: ["read", "write"], accounting: ["read", "write"] } }) });
      stub.route({ method: "GET", re: /api\/customers\/\?/, reply: () => ok([
        { id: "c-beta", name: "Beta Stores", email: "accounts@beta.example.invalid" },
        { id: "c-gamma", name: "Gamma Traders", email: "accounts@gamma.example.invalid" }]) });
      let statementsAsked = 0;   // the stub's log holds writes only, so a refused Generate is shown by a statement that was never asked for
      stub.route({ method: "GET", re: /api\/customer-statements\?/, reply: () => { statementsAsked += 1; return ok({
        customer: { id: "c-beta", name: "Beta Stores", email: "accounts@beta.example.invalid", gstin: null },
        period: { start_date: "2026-04-01", end_date: "2026-09-30" }, opening_balance_paise: 0, closing_balance_paise: 0, transactions: [],
        totals: { invoiced_paise: 0, received_paise: 0, credited_paise: 0, transaction_count: 0 } }); } });
      stub.route({ method: "POST", re: /api\/customer-statements\/email$/, reply: () => ok({ sent: true }) });
      await page.goto(env.at("/sales/?tab=statements"), { waitUntil: "networkidle" });
      assert.equal(await page.locator('input[type="date"]').count(), 0, "a native <input type=\"date\"> is on the screen");
      const from = page.locator("#statement-from");
      const to = page.locator("#statement-to");
      const generate = page.getByRole("button", { name: "Generate", exact: true });
      const email = page.getByRole("button", { name: "Email", exact: true });
      const refusedWith = async (sentence, what) => {
        await generate.click();
        await page.getByText(sentence).first().waitFor({ timeout: 4000 }).catch(() => { throw new Error(`${what} did not say "${sentence}"`); });
        assert.equal(statementsAsked, 0, `${what} still asked the server for a statement`);
      };
      await pick(page, page.locator('button[aria-label="Customer"]'), "Beta Stores");
      await typeAndLeave(from, "15/1");
      assert.equal(await from.inputValue(), "15/01/2027", "15/1 in a box holding a date of FY 2026-27 is 15 January 2027");
      for (const [box, label] of [[from, "Statement from"], [to, "Statement to"]]) {
        await typeAndLeave(box, "31/02/2026");
        assert.equal(await box.getAttribute("aria-invalid"), "true", `${label}: 31/02/2026 is not marked invalid`);
        const alerts = (await page.locator("[role=alert]").allInnerTexts()).join(" | ");
        assert.ok(alerts.includes(FEB_SENTENCE), `${label}: the field's own sentence is missing (alerts: ${alerts.slice(0, 200)})`);
        await typeAndLeave(box, box === from ? "01/04/2026" : "30/09/2026");
      }
      // Generate over a window that is not two dates in order says so, in words, and asks for nothing.
      await typeAndLeave(from, "31/02/2026");
      await refusedWith(`Statement from: ${FEB_SENTENCE}`, "Generate over an unreadable window");
      await typeAndLeave(from, "");
      await refusedWith("Statement period: enter both dates.", "Generate over a cleared start");
      await typeAndLeave(from, "01/10/2026");
      // A reversed window: the To box says so itself ("30 Sep 2026 is before 01 Oct 2026."), and Generate asks for nothing.
      await refusedWith(/is before/, "Generate over a reversed window");
      // A good window, and the statement shown.
      await typeAndLeave(from, "01/04/2026");
      await generate.click();
      await email.waitFor();
      // Choosing another customer takes the statement off the screen, so nothing of the first customer's can be mailed under the second's name.
      await pick(page, page.locator('button[aria-label="Customer"]'), "Gamma Traders");
      assert.equal(await email.count(), 0, "the Email button stayed on the screen after another customer was chosen");
      await pick(page, page.locator('button[aria-label="Customer"]'), "Beta Stores");
      await generate.click();
      await email.waitFor();
      // The window spoilt after Generate, then a valid different one: the mail is still for the statement shown.
      const modal = page.locator("div.fixed").filter({ has: page.getByRole("heading", { name: "Email statement to customer" }) });
      const send = async () => {
        await email.click();
        await modal.getByRole("button", { name: "Send", exact: true }).click();
        await stub.quiet();
      };
      await typeAndLeave(to, "31/02/2026");
      await send();
      await typeAndLeave(to, "31/08/2026");
      await email.waitFor();
      await send();
      const writes = stub.writesTo(/customer-statements\/email$/);
      assert.equal(writes.length, 2, `expected two mails, saw ${writes.length}`);
      for (const w of writes) {
        const body = JSON.parse(w.body);
        assert.equal(body.customer_id, "c-beta", `customer_id was ${JSON.stringify(body.customer_id)}`);
        assert.equal(body.start_date, "2026-04-01", `start_date was ${JSON.stringify(body.start_date)}: the mail must be for the period SHOWN`);
        assert.equal(body.end_date, "2026-09-30", `end_date was ${JSON.stringify(body.end_date)}: the mail must be for the period SHOWN, not what the box says now`);
      }
    },
  },
  // The fixed-asset register's "Reclassify as at" (accumulated amortisation moved to its own ledger). Its Prepare is a READ (the preview), and the
  // post that follows sends the PREVIEW's own date, never the box, so the claims are about the preview request: not asked over a date that is not a
  // date or over a blank one, and asked with the ISO date typed otherwise.
  {
    id: "amortisation-reclassification-as-at",
    title: "Fixed assets > Reclassify as at: the preview is not asked for over a date that is not a date, and the ISO date is what it is asked for",
    contexts: TZ_MATRIX,
    async run(env) {
      const { page, stub } = env;
      const asked = [];
      stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { accounting: ["read", "write", "approve"], fixed_assets: ["read", "write"] } }) });
      stub.route({ method: "GET", re: /amortisation-reclassification\/summary\?/, reply: () => ok({
        unmoved: 1, moved: 0, unfinished: 0, excluded: 0, moved_assets: [], refusal: null, own_ledger: null }) });
      stub.route({ method: "GET", re: /amortisation-reclassification\?/, reply: (_req, _body, url) => { asked.push(String(url?.search ?? url)); return ok({
        as_at: "2026-09-30", ready: false, refusals: [], assets: [], excluded: [], reclassified: [], carried_over_candidates: [], entry_dates: [], later_dates: [],
        financial_years: [], total_to_move_paise: 0, journals_to_post: 0, pointed_only_count: 0, moves_count: 0 }); } });
      await page.goto(env.at("/fixed-assets/?tab=depreciation"), { waitUntil: "networkidle" });
      assert.equal(await page.locator('input[type="date"]').count(), 0, "a native <input type=\"date\"> is on the screen");
      const box = page.getByLabel("Reclassify as at");
      await box.waitFor();
      const prepare = page.getByRole("button", { name: "Prepare the reclassification", exact: true });
      await typeAndLeave(box, "15/1");
      assert.equal(await box.inputValue(), "15/01/2027", "15/1 in FY 2026-27 is 15 January 2027");
      await typeAndLeave(box, "150326");
      assert.equal(await box.inputValue(), "15/03/2026", "150326 is 15/03/2026");
      await typeAndLeave(box, "31/02/2026");
      assert.equal(await box.getAttribute("aria-invalid"), "true", "31/02/2026 is not marked invalid");
      const alerts = (await page.locator("[role=alert]").allInnerTexts()).join(" | ");
      assert.ok(alerts.includes(FEB_SENTENCE), `the field's own sentence is missing (alerts: ${alerts.slice(0, 200)})`);
      await prepare.click();
      await page.getByText(`As-at date: ${FEB_SENTENCE}`).first().waitFor({ timeout: 4000 }).catch(() => {
        throw new Error(`Prepare over an unreadable date did not say "As-at date: ${FEB_SENTENCE}"`);
      });
      await typeAndLeave(box, "");
      await prepare.click();
      await page.getByText("Say the date the reclassification is as at: a month end.").first().waitFor({ timeout: 4000 }).catch(() => {
        throw new Error("Prepare over a cleared date did not say its own sentence");
      });
      await stub.quiet();
      assert.deepEqual(asked, [], "the preview was asked for over a date that is not a date");
      await typeAndLeave(box, "30/09/2026");
      await prepare.click();
      await until(() => asked.length >= 1, "a preview asked for the date typed");
      assert.match(asked.at(-1), /as_at=2026-09-30/, `the preview was asked for ${asked.at(-1)}`);
    },
  },
  // The interest panel's refusal of a CLEARED As at has a sentence of its own (the row above it types an impossible date, which takes the other
  // refusal): a cleared box reads as blank with no problem to report, so only the second line of prepare() stops it.
  {
    id: "overdue-interest-a-cleared-as-at-is-refused-in-a-sentence-and-sends-nothing",
    title: "Sales > Overdue Interest: a cleared As at is refused in its own sentence and nothing is sent",
    contexts: TZ_MATRIX,
    async run(env) {
      const { page, stub } = env;
      await openOverdueInterest(env);
      await typeAndLeave(page.locator("#overdue-as-at"), "");
      await page.getByRole("button", { name: "Prepare draft invoice" }).first().click();
      await page.getByText("As at: enter the date the interest is worked out to.").first().waitFor({ timeout: 4000 }).catch(() => {
        throw new Error("Prepare draft invoice over a cleared As at did not say \"As at: enter the date the interest is worked out to.\"");
      });
      await stub.quiet();
      assert.equal(stub.writesTo(/api\/late-interest\/drafts$/).length, 0, "Prepare draft invoice over a cleared As at SENT A WRITE");
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
  // The §234C(1) proviso's "Date the income arose" (advance-tax screen). It has no Save: the working is a stateless estimate the server is asked
  // for a moment after the last keystroke, and the figure it returns is shown, never stored. So the claims are about that request: it is NOT
  // asked over a date that is not a date (or a blank one), the date's own sentence is what the screen says instead, and over the date typed
  // in full it is asked with the ISO date. The stub answers any date; the real engine refuses one outside the year the screen is on with a sentence
  // (so the 15/03/2026 passed through on the way to the final date is answered OK here and is not asserted).
  {
    id: "unforeseen-income-date-arose",
    title: "Advance tax > income that arose after an instalment: the estimate is not asked for over a date that is not a date, and the ISO date is what it is asked for",
    contexts: TZ_MATRIX,
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "POST", re: /api\/income-tax\/advance-tax\/compute$/, reply: () => ok({
        fy: "2026-27", estimated_tax_paise: 10000000, total_interest_paise: 0, section_ref: "Section 234C(1)(a)", is_presumptive_44ad_44ada: false,
        basis: "stub", installments: [], unforeseen_income: [], caveats: [] }) });
      await page.goto(`${env.base}/income-tax/advance-tax/?client_id=${CLIENT_ID}`, { waitUntil: "networkidle" });
      assert.equal(await page.locator('input[type="date"]').count(), 0, "a native <input type=\"date\"> is on the screen");
      await page.getByPlaceholder("Enter tax amount").fill("100000");
      await page.getByRole("button", { name: "Add an income", exact: true }).click();
      await page.getByLabel("Tax on the income (₹)").fill("109375");
      const box = page.getByLabel("Date the income arose");
      await box.waitFor();
      await typeAndLeave(box, "15/1");
      assert.equal(await box.inputValue(), "15/01/2027", "15/1 in FY 2026-27 is 15 January 2027");
      await typeAndLeave(box, "150326");
      assert.equal(await box.inputValue(), "15/03/2026", "150326 is 15/03/2026");
      assert.notEqual(await box.getAttribute("aria-invalid"), "true", "a readable date is marked invalid");
      await typeAndLeave(box, "31/02/2026");
      assert.equal(await box.getAttribute("aria-invalid"), "true", "31/02/2026 is not marked invalid");
      const alerts = (await page.locator("[role=alert]").allInnerTexts()).join(" | ");
      assert.ok(alerts.includes(FEB_SENTENCE), `the field's own sentence is missing (alerts: ${alerts.slice(0, 200)})`);
      // The estimate is asked for a moment after the last keystroke: give any request already on its way time to arrive, then count.
      await stub.quiet();
      const before = stub.writesTo(/advance-tax\/compute$/).length;
      await typeAndLeave(box, "31/02/2026");
      await page.getByText(`Date the income arose: ${FEB_SENTENCE}`).first().waitFor({ timeout: 4000 }).catch(() => {
        throw new Error(`the working over an unreadable date did not say "Date the income arose: ${FEB_SENTENCE}"`);
      });
      await stub.quiet();
      assert.equal(stub.writesTo(/advance-tax\/compute$/).length, before, "the estimate was asked for over a date that is not a date");
      await typeAndLeave(box, "");
      await page.getByText("Every income needs the date it arose.").first().waitFor({ timeout: 4000 }).catch(() => {
        throw new Error("a cleared date did not say \"Every income needs the date it arose.\"");
      });
      await stub.quiet();
      assert.equal(stub.writesTo(/advance-tax\/compute$/).length, before, "the estimate was asked for over a cleared date");
      await typeAndLeave(box, "12/09/2026");
      await until(() => stub.writesTo(/advance-tax\/compute$/).some((w) => {
        try { return JSON.parse(w.body).unforeseen_income?.[0]?.arose_on === "2026-09-12"; } catch { return false; }
      }), "an estimate asked for with the date typed in full");
      const last = JSON.parse(stub.writesTo(/advance-tax\/compute$/).at(-1).body);
      assert.equal(last.unforeseen_income[0].arose_on, "2026-09-12", `arose_on was ${JSON.stringify(last.unforeseen_income[0].arose_on)}`);
      assert.equal(last.unforeseen_income[0].tax_paise, 10937500, `tax_paise was ${JSON.stringify(last.unforeseen_income[0].tax_paise)}`);
    },
  },
  // The Add ITR Deadline prompt kept its refusal through Cancel, so it opened again showing the last sentence over a box that no longer held it.
  {
    id: "itr-add-deadline-a-refusal-does-not-outlive-the-prompt",
    title: "Income Tax > Add ITR Deadline: a refusal said in the prompt is gone when the prompt is opened again",
    contexts: TZ_MATRIX,
    async run(env) {
      const { page } = env;
      await openItrTracker("add")(env);
      await typeAndLeave(page.locator("#itr-add-due-date"), "31/02/2026");
      await page.getByRole("button", { name: "Add Deadline", exact: true }).click();
      await page.getByText(`Due date: ${FEB_SENTENCE}`).first().waitFor({ timeout: 4000 }).catch(() => {
        throw new Error(`Add Deadline over an unreadable date did not say "Due date: ${FEB_SENTENCE}"`);
      });
      await page.getByRole("button", { name: "Cancel", exact: true }).click();
      await page.getByRole("button", { name: /Add ITR Deadline/ }).first().click();
      await page.locator("#itr-add-due-date").waitFor();
      assert.equal(await page.getByText(`Due date: ${FEB_SENTENCE}`).count(), 0, "the prompt opened again with the last refusal still on it");
    },
  },
  // A form that keeps state through Cancel kept its last refusal too: the bank reconciliation, the new-return and the §197 certificate forms each showed an old
  // "<box>: Feb 2026 has only 28 days." over boxes that no longer held it. Opening the form again starts it clean.
  ...[
    { id: "bank-reconciliation", name: "Bank > Reconcile > New Reconciliation", open: openNewReconciliation, box: "#recon-start", label: "Statement start",
      save: (p) => p.getByRole("button", { name: "Open Reconciliation", exact: true }),
      close: (p) => p.getByRole("button", { name: "Cancel", exact: true }), reopen: (p) => p.getByRole("button", { name: "New Reconciliation", exact: true }) },
    { id: "new-itr-return", name: "Income Tax > Filing > New Filing (revised)", open: openNewRevisedReturn, box: "#itr-original-filing-date", label: "Earlier return's filing date",
      save: (p) => p.getByRole("button", { name: "Create", exact: true }),
      close: (p) => p.getByRole("button", { name: "Cancel", exact: true }), reopen: (p) => p.getByRole("button", { name: "New Filing" }) },
    { id: "vendor-payment", name: "Purchases > Payments > Record Payment", open: openVendorPayment, box: "#vendor-payment-date", label: "Payment date",
      save: (p) => p.getByRole("button", { name: "Record Payment", exact: true }).first(),
      close: (p) => p.getByRole("button", { name: "Cancel", exact: true }), reopen: (p) => p.getByRole("button", { name: "Record Payment", exact: true }) },   // with the form closed, the first is the toolbar's
    { id: "lower-deduction-certificate", name: "TDS > §197 Certificates > Record Certificate", open: openRecordLowerDeductionCertificate, box: "Valid from", label: "Valid from",
      save: (p) => p.getByRole("button", { name: "Save", exact: true }).last(),
      close: (p) => p.getByRole("button", { name: "Cancel", exact: true }), reopen: (p) => p.getByRole("button", { name: "+ Record Certificate" }) },
  ].map((f) => ({
    id: `${f.id}-a-refusal-does-not-outlive-the-form`,
    title: `${f.name}: a refusal said in the form is gone when the form is opened again`,
    contexts: TZ_MATRIX,
    async run(env) {
      const { page } = env;
      await f.open(env);
      const box = f.box.startsWith("#") ? page.locator(f.box) : page.getByLabel(f.box, { exact: true });
      await typeAndLeave(box, "31/02/2026");
      await f.save(page).click();
      await page.getByText(`${f.label}: ${FEB_SENTENCE}`).first().waitFor({ timeout: 4000 }).catch(() => {
        throw new Error(`Save over an unreadable date did not say "${f.label}: ${FEB_SENTENCE}"`);
      });
      await f.close(page).first().click();
      await f.reopen(page).first().click();
      await page.waitForTimeout(300);
      assert.equal(await page.getByText(`${f.label}: ${FEB_SENTENCE}`).count(), 0, "the form opened again with the last refusal still on it");
    },
  })),
  // The two GST filing prompts leave a blank date to the server and show its sentence inside the dialog. Closing the dialog starts it clean: the
  // sentence, the ARN and any date are gone when "Mark as Filed" is pressed again (a person must not meet an old refusal over a form that no longer holds it).
  ...[
    { id: "gstr1", name: "GST > GSTR-1 > Mark as Filed", open: openGstr1MarkFiled, box: "#gstr1-filed-date", form: "GSTR-1" },
    { id: "gstr3b", name: "GST > GSTR-3B > Mark as Filed", open: openGstr3bMarkFiled, box: "#gstr3b-filed-date", form: "GSTR-3B" },
  ].map((f) => ({
    id: `${f.id}-mark-filed-a-refusal-does-not-outlive-the-dialog`,
    title: `${f.name}: the server's answer to a blank date is gone, with the ARN and the date, when the dialog is opened again`,
    contexts: TZ_MATRIX,
    async run(env) {
      const { page } = env;
      await f.open(env);
      const sentence = `Say the date this ${f.form} was filed on the portal.`;
      await page.getByRole("button", { name: "Confirm Filed", exact: true }).click();
      await shownInTheDialog(page, sentence, `${f.name}: a blank date was not answered`);
      // A date typed AFTER the refusal is still in the box when the dialog is closed: the reset has to clear it (a cleared box would pass without one).
      await typeAndLeave(page.locator(f.box), "07/10/2026");
      await page.getByRole("button", { name: "Cancel", exact: true }).click();
      await page.getByRole("button", { name: "Mark as Filed", exact: true }).click();
      await page.locator(f.box).waitFor();
      assert.equal(await page.getByText(sentence).count(), 0, `${f.name}: the dialog opened again with the last refusal still on it`);
      assert.equal(await page.getByLabel("ARN (Acknowledgment Reference Number)", { exact: true }).inputValue(), "", `${f.name}: the ARN typed for the last attempt was still in the box`);
      assert.equal(await page.locator(f.box).inputValue(), "", `${f.name}: a date was still in the box`);
    },
  })),
  // The per-client "Mark as filed" dialog offered today's date, filled in: the date a return was filed on the portal is the CA's statement and is what
  // the period lock quotes, and a filing recorded days late (the usual case) was stamped with the day the button was pressed unless the CA noticed.
  // It starts empty, holds its button until a date is typed, and a typed date is what is sent.
  ...["gstr1", "gstr3b"].map((tab) => ({
    id: `client-${tab}-record-filing-starts-with-no-date`,
    title: `Client GST > ${tab === "gstr1" ? "GSTR-1" : "GSTR-3B"} > Mark as filed: the date box starts empty and the button waits for a date`,
    contexts: TZ_MATRIX,
    async run(env) {
      const { page } = env;
      await openClientGstFiling(tab)(env);
      assert.equal(await page.locator("#gst-mark-filed-date").inputValue(), "", "the dialog offered a date the CA had not stated");
      assert.equal(await page.getByRole("button", { name: "Record as filed", exact: true }).isDisabled(), true, "the button was live with no date");
      await typeAndLeave(page.locator("#gst-mark-filed-date"), "07/10/2026");
      assert.equal(await page.getByRole("button", { name: "Record as filed", exact: true }).isDisabled(), false, "the button stayed held over a typed date");
    },
  })),
  // The optional date on Compute from Books: left blank it is not sent at all (an empty string would be refused by the server), and an unreadable one is refused first.
  {
    id: "client-gstr3b-compute-a-blank-date-filed-is-not-sent",
    title: "Client GST > GSTR-3B > Compute from Books: with no date filed the request carries none",
    contexts: TZ_MATRIX,
    async run(env) {
      const { page, stub } = env;
      await openClientGstr3bCompute(env);
      await page.getByRole("button", { name: "Compute", exact: true }).click();
      await stub.quiet();
      const writes = stub.writesTo(/api\/gst\/gstr3b\/from-books$/);
      assert.equal(writes.length, 1, `expected one compute request, saw ${writes.length}`);
      const body = JSON.parse(writes[0].body);
      assert.equal("filed_on" in body, false, `a blank optional date was sent as ${JSON.stringify(body.filed_on)}`);
    },
  },
  // The loan's sanctioned-on date is a CLAIM and optional: left blank it is sent as null (no section is claimed and the server names the gap), never as "".
  {
    id: "computation-loan-sanctioned-on-a-blank-claims-nothing",
    title: "Tax > Computation: with no sanction date the claim goes as null",
    contexts: TZ_MATRIX,
    async run(env) {
      const { page, stub } = env;
      await openComputationLoanDate(env);
      await page.getByRole("button", { name: "Compute & Save Snapshot", exact: true }).click();
      await stub.quiet();
      const writes = stub.writesTo(/api\/income-tax\/compute$/);
      assert.equal(writes.length, 1, `expected one compute request, saw ${writes.length}`);
      assert.equal(JSON.parse(writes[0].body).chapter_vi_a.housing_loan_sanctioned_on, null, "a blank sanction date did not go as null");
    },
  },
  // A year-end stage is about ONE engagement's year, which is usually not the current one: a short date typed there is read inside THAT year (POST-A-126).
  {
    id: "year-end-adjustment-a-short-date-is-read-inside-the-engagements-year",
    title: "Year-end > Adjustments: in an engagement of the previous year, 15/1 and 15/3 are January and March of that year's books",
    contexts: TZ_MATRIX,
    async run(env) {
      const { page } = env;
      await openYearEndAdjustment("2025-26")(env);
      const box = page.getByLabel("Adjustment date", { exact: true });
      await typeAndLeave(box, "15/1");
      assert.equal(await box.inputValue(), "15/01/2026", "15/1 in an FY 2025-26 engagement is 15 January 2026");
      await typeAndLeave(box, "15/3");
      assert.equal(await box.inputValue(), "15/03/2026", "15/3 in an FY 2025-26 engagement is 15 March 2026");
    },
  },
  // A year-end engagement is worked after its year has closed, so a date offered from the clock was in the NEXT year's books. The adjusting entry's date starts empty.
  {
    id: "year-end-adjustment-starts-with-no-date",
    title: "Year-end > Adjustments > New Adjustment: the date starts empty, and saving without one is refused in a sentence",
    contexts: TZ_MATRIX,
    async run(env) {
      const { page, stub } = env;
      await openYearEndAdjustment("2025-26")(env);
      assert.equal(await page.getByLabel("Adjustment date", { exact: true }).inputValue(), "", "the form offered a date the CA had not stated");
      await page.getByRole("button", { name: "Create Adjustment", exact: true }).click();
      await page.getByText("Date is required").first().waitFor({ timeout: 4000 }).catch(() => { throw new Error('saving with no date did not say "Date is required"'); });
      await stub.quiet();
      assert.equal(stub.writesTo(/api\/year-end\/eng-1\/adjustments$/).length, 0, "an adjustment with no date was sent");
    },
  },
  // The four filing prompts: the date a return was filed on the portal can never be later than today and cannot precede the period it declares. A date after
  // today was only HINTED at by the box (the server's own wording for it, "filed_date cannot be in the future", names a column), so it is refused in a
  // sentence before anything is sent; a date before the period ended is the server's to refuse and its sentence is shown INSIDE the dialog.
  ...[
    { id: "gstr1", name: "GST > GSTR-1 > Mark as Filed", open: openGstr1MarkFiled, box: "#gstr1-filed-date", save: "Confirm Filed", held: true,
      write: /gst-workspace\/gstr1\/g1-1\/status$/, before: GSTR_BEFORE_PERIOD_SENTENCE("2026-09-15", "2026-09-30") },
    { id: "gstr3b", name: "GST > GSTR-3B > Mark as Filed", open: openGstr3bMarkFiled, box: "#gstr3b-filed-date", save: "Confirm Filed", held: true,
      write: /gst-workspace\/gstr3b\/g3-1\/status$/, before: GSTR_BEFORE_PERIOD_SENTENCE("2026-09-15", "2026-09-30") },
    { id: "client-gstr1", name: "Client GST > GSTR-1 > Mark as filed", open: openClientGstFiling("gstr1"), box: "#gst-mark-filed-date", save: "Record as filed", held: true,
      write: /gst-workspace\/gstr1\/g1-1\/status$/, before: GSTR_BEFORE_PERIOD_SENTENCE("2026-09-15", "2026-09-30") },
    { id: "client-gstr3b", name: "Client GST > GSTR-3B > Mark as filed", open: openClientGstFiling("gstr3b"), box: "#gst-mark-filed-date", save: "Record as filed", held: true,
      write: /gst-workspace\/gstr3b\/g3-1\/status$/, before: GSTR_BEFORE_PERIOD_SENTENCE("2026-09-15", "2026-09-30") },
    { id: "tds-return", name: "TDS > Returns > Mark as Filed", open: openTdsReturnMarkFiled, box: "#tds-filing-date", save: "Confirm Filed", held: false,
      write: /api\/tds-workspace\/returns\/tr-1\/status$/, before: TDS_BEFORE_QUARTER_SENTENCE },
  ].map((f) => ({
    id: `${f.id}-filing-date-after-today-is-refused-and-before-the-period-is-answered`,
    title: `${f.name}: a date after today is refused in a sentence and sends nothing; one before the period ended gets the server's sentence inside the dialog`,
    contexts: TZ_MATRIX,
    async run(env) {
      const { page, stub } = env;
      await f.open(env);
      const box = page.locator(f.box);
      const save = page.getByRole("button", { name: f.save, exact: true });
      // After today (the clock is pinned at 8 October 2026).
      await typeAndLeave(box, "15/10/2026");
      const after = "15 Oct 2026 is after 08 Oct 2026.";
      if (f.held) {
        assert.equal(await save.isDisabled(), true, `${f.name}: the button was live over a date after today`);
        await page.getByText(after).first().waitFor({ timeout: 4000 }).catch(() => { throw new Error(`${f.name}: the box did not say "${after}"`); });
      } else {
        await save.click();
        await shownInTheDialog(page, `Date filed: ${after}`, `${f.name}: a date after today was not refused in a sentence`);
      }
      await stub.quiet();
      assert.equal(stub.writesTo(f.write).length, 0, `${f.name}: a date after today SENT A WRITE`);
      // Before the period it declares ended: the server's to refuse, said inside the dialog.
      await typeAndLeave(box, "15/09/2026");
      await save.click();
      await shownInTheDialog(page, f.before, `${f.name}: the server's answer to a date before the period ended was not shown`);
      await stub.quiet();
      assert.equal(stub.writesTo(f.write).length, 1, `${f.name}: a date before the period ended should send ONE request for the server to answer`);
    },
  })),
  // The per-client dialog is about ONE return. Opened on a second one it kept the first one's ARN and date, so "Record as filed" recorded the FIRST
  // return's date against the SECOND (and locked its period on it).
  ...["gstr1", "gstr3b"].map((tab) => ({
    id: `client-${tab}-record-filing-a-second-return-does-not-inherit-the-firsts-answers`,
    title: `Client GST > ${tab === "gstr1" ? "GSTR-1" : "GSTR-3B"}: opening the dialog on another return starts it empty`,
    contexts: TZ_MATRIX,
    async run(env) {
      const { page } = env;
      await openClientGstFiling(tab, { second: true })(env);
      const mark = page.getByRole("button", { name: "Mark as filed", exact: true });
      await mark.nth(0).click();
      await page.getByText("Record the filing of 092026").waitFor({ timeout: 4000 });
      await page.getByLabel("ARN from the portal", { exact: true }).fill("AA2710260000009");
      await typeAndLeave(page.locator("#gst-mark-filed-date"), "07/10/2026");
      await mark.nth(1).click();
      await page.getByText("Record the filing of 082026").waitFor({ timeout: 4000 }).catch(() => { throw new Error("the dialog did not name the second return"); });
      assert.equal(await page.getByLabel("ARN from the portal", { exact: true }).inputValue(), "", "the first return's ARN was still in the box for the second");
      assert.equal(await page.locator("#gst-mark-filed-date").inputValue(), "", "the first return's date was still in the box for the second");
    },
  })),
  // The optional "Date filed" of Compute from Books belongs to the period it was typed for: it survived Cancel and a saved draft and was sent with the next compute.
  ...[
    { id: "cancel", name: "Cancel", leave: async (page) => { await page.getByRole("button", { name: "Cancel", exact: true }).click(); } },
    { id: "save-as-draft", name: "Save as Draft", leave: async (page) => { await page.getByRole("button", { name: "Save as Draft", exact: true }).click(); } },
  ].map((c) => ({
    id: `client-gstr3b-compute-date-filed-does-not-outlive-the-panel-after-${c.id}`,
    title: `Client GST > GSTR-3B > Compute from Books: after ${c.name}, the date filed is empty when the panel is opened again`,
    contexts: TZ_MATRIX,
    async run(env) {
      const { page } = env;
      await openClientGstr3bCompute(env);
      await typeAndLeave(page.locator("#gstr3b-compute-filed-on"), "07/10/2026");
      if (c.id === "save-as-draft") await page.getByRole("button", { name: "Compute", exact: true }).click();
      if (c.id === "save-as-draft") await page.getByRole("button", { name: "Save as Draft", exact: true }).waitFor({ timeout: 6000 });
      await c.leave(page);
      // The panel closes when the draft is saved (the write is held for a moment by the stub): reopening before it has closed would read the old box.
      await page.locator("#gstr3b-compute-filed-on").waitFor({ state: "detached", timeout: 8000 });
      await page.getByRole("button", { name: "Compute from Books", exact: true }).first().click();
      await page.locator("#gstr3b-compute-filed-on").waitFor();
      assert.equal(await page.locator("#gstr3b-compute-filed-on").inputValue(), "", `the date filed typed for the last period was still in the box after ${c.name}`);
    },
  })),
  // A computed statement belongs to the form, year and quarter it was computed for: a changed selector left the 26Q return approved and ready to be marked
  // filed under a "Mark 24Q as Filed" heading.
  {
    id: "tds-return-a-changed-form-clears-the-computed-statement",
    title: "TDS > Returns: changing the return type after a compute clears the statement, so nothing can be recorded as filed under another form",
    contexts: TZ_MATRIX,
    async run(env) {
      const { page } = env;
      await openTdsReturnMarkFiled(env);
      await page.getByRole("button", { name: "Cancel", exact: true }).click();
      assert.equal(await page.getByRole("button", { name: "Mark as Filed", exact: true }).count(), 1, "the approved statement should offer Mark as Filed before the change");
      await page.getByLabel("Return Type", { exact: true }).selectOption("24Q");
      await until(async () => (await page.getByRole("button", { name: "Mark as Filed", exact: true }).count()) === 0, "the 26Q statement cleared by the changed return type");
      assert.equal(await page.getByRole("button", { name: "CA Approve", exact: true }).count(), 0, "an approval was still offered for the statement computed under the other form");
    },
  },
  // The adjustment's two accounts are PICKED from the client's chart and sent as ids (the columns are uuids; the form used to take free text that the
  // database refuses), and the list names them.
  {
    id: "year-end-adjustment-accounts-are-picked-and-sent-as-ids",
    title: "Year-end > Adjustments > New Adjustment: the debit and credit accounts are chosen from the chart, reach the server as ids and are named in the list",
    contexts: TZ_MATRIX,
    async run(env) {
      const { page, stub } = env;
      await openYearEndAdjustment("2025-26")(env);
      await typeAndLeave(page.getByLabel("Adjustment date", { exact: true }), "31/03/2026");
      await page.getByRole("button", { name: "Create Adjustment", exact: true }).click();
      await stub.quiet();
      const writes = stub.writesTo(/api\/year-end\/eng-1\/adjustments$/);
      assert.equal(writes.length, 1, `expected one write, saw ${writes.length}`);
      const body = JSON.parse(writes[0].body);
      assert.equal(body.debit_account_id, YEAR_END_DEBIT, `debit_account_id reached the server as ${JSON.stringify(body.debit_account_id)}`);
      assert.equal(body.credit_account_id, YEAR_END_CREDIT, `credit_account_id reached the server as ${JSON.stringify(body.credit_account_id)}`);
      await page.getByText("5010 Rent expense").first().waitFor({ timeout: 4000 }).catch(() => { throw new Error("the list did not name the debit account"); });
      await page.getByText("2010 Rent payable").first().waitFor({ timeout: 4000 }).catch(() => { throw new Error("the list did not name the credit account"); });
    },
  },
  // A date outside the engagement's own year is HINTED at (the box says so) and not refused: an entry dated just outside it, a reversal on 1 April, is
  // a thing a CA does, and the choice is theirs (PRE-A-019). It posts into that other year's books, so the screen says so where the date is typed.
  {
    id: "year-end-adjustment-a-date-outside-the-engagements-year-is-hinted-not-refused",
    title: "Year-end > Adjustments > New Adjustment: a date after the engagement's year says so in the box and is still sent",
    contexts: TZ_MATRIX,
    async run(env) {
      const { page, stub } = env;
      await openYearEndAdjustment("2025-26")(env);
      await typeAndLeave(page.getByLabel("Adjustment date", { exact: true }), "01/04/2026");
      await page.getByText("01 Apr 2026 is after 31 Mar 2026.").first().waitFor({ timeout: 4000 }).catch(() => { throw new Error("the box did not say the date is outside the engagement's year"); });
      await page.getByRole("button", { name: "Create Adjustment", exact: true }).click();
      await stub.quiet();
      const writes = stub.writesTo(/api\/year-end\/eng-1\/adjustments$/);
      assert.equal(writes.length, 1, "a hint must not stop the save");
      assert.equal(JSON.parse(writes[0].body).adjustment_date, "2026-04-01");
    },
  },
  // The reconciliation's end box only HINTS when it is before the start; the window reached the server reversed and was refused there in schema words.
  {
    id: "bank-reconciliation-a-reversed-window-is-refused-in-a-sentence",
    title: "Bank > Reconcile > New Reconciliation: an end before the start is refused in a sentence and nothing is sent",
    contexts: TZ_MATRIX,
    async run(env) {
      const { page, stub } = env;
      await openNewReconciliation(env);
      await typeAndLeave(page.locator("#recon-start"), "30/09/2026");
      await typeAndLeave(page.locator("#recon-end"), "01/09/2026");
      await page.getByRole("button", { name: "Open Reconciliation", exact: true }).click();
      await page.getByText("Statement end: it is before the statement start.").first().waitFor({ timeout: 4000 }).catch(() => {
        throw new Error("a reversed statement window did not say \"Statement end: it is before the statement start.\"");
      });
      await stub.quiet();
      assert.equal(stub.writesTo(/api\/banking\/reconciliations$/).length, 0, "a reversed window SENT A WRITE");
    },
  },
  // The recurring templates' stop date is OPTIONAL, and clearing it on an edit saved "successfully" and changed nothing: the journal service dropped the
  // null and the bill screen left the key out. The request now says so, and the stored stop date goes.
  ...[
    { id: "recurring-journal", name: "Accounting > Recurring journals > Edit", open: openEditRecurringJournal, box: "#rj-end", write: /api\/recurring-journals\/rjt-1$/,
      save: (p) => p.getByRole("button", { name: "Save template", exact: true }) },
    { id: "recurring-bill", name: "Purchases > Recurring bills > Edit", open: openEditRecurringBill, box: "#rec-bill-end", write: /api\/recurring-purchase-bills\/rb-1$/,
      save: (p) => p.getByRole("button", { name: "Save changes", exact: true }) },
  ].map((f) => ({
    id: `${f.id}-edit-an-untouched-stop-date-is-sent-back`,
    title: `${f.name}: an edit that leaves the stop date alone sends the stored date back`,
    contexts: TZ_MATRIX,
    async run(env) {
      const { page, stub } = env;
      await f.open(env);
      const box = page.locator(f.box);
      assert.equal(await box.inputValue(), "31/10/2027", "the stored stop date was not shown in the box");
      // Left alone, the stored date goes back as it was.
      await f.save(page).click();
      await stub.quiet();
      const writes = stub.writesTo(f.write);
      assert.equal(writes.length, 1, `${f.name}: expected one write for the untouched edit, saw ${writes.length}`);
      assert.equal(JSON.parse(writes[0].body).end_date, "2027-10-31", "an edit that left the stop date alone did not send it back");
    },
  })),
  ...[
    { id: "recurring-journal", name: "Accounting > Recurring journals > Edit", open: openEditRecurringJournal, box: "#rj-end", write: /api\/recurring-journals\/rjt-1$/,
      save: (p) => p.getByRole("button", { name: "Save template", exact: true }) },
    { id: "recurring-bill", name: "Purchases > Recurring bills > Edit", open: openEditRecurringBill, box: "#rec-bill-end", write: /api\/recurring-purchase-bills\/rb-1$/,
      save: (p) => p.getByRole("button", { name: "Save changes", exact: true }) },
  ].map((f) => ({
    id: `${f.id}-edit-a-cleared-stop-date-clears-it`,
    title: `${f.name}: the stop date, cleared, reaches the server as null`,
    contexts: TZ_MATRIX,
    async run(env) {
      const { page, stub } = env;
      await f.open(env);
      await typeAndLeave(page.locator(f.box), "");
      await f.save(page).click();
      await stub.quiet();
      const writes = stub.writesTo(f.write);
      assert.equal(writes.length, 1, `${f.name}: expected one write for the cleared stop date, saw ${writes.length}`);
      const body = JSON.parse(writes[0].body);
      assert.ok("end_date" in body && body.end_date === null, `${f.name}: a cleared stop date must reach the server as null, saw ${JSON.stringify(body.end_date)} (key present: ${"end_date" in body})`);
    },
  })),
  // The end box of both templates only HINTS when it is before the start. The bill form refused it in its own words; the journal form let it reach the server.
  ...[
    { id: "recurring-journal", name: "Accounting > Recurring journals > New template", open: openRecurringJournalTemplate, start: "#rj-start", end: "#rj-end",
      sentence: "End date: it is before the start date.", write: /api\/recurring-journals$/, save: (p) => p.getByRole("button", { name: "Save template", exact: true }) },
    { id: "recurring-bill", name: "Purchases > Recurring bills > New Template", open: openRecurringBillTemplate, start: "#rec-bill-start", end: "#rec-bill-end",
      sentence: "The end date cannot be before the start date.", write: /api\/recurring-purchase-bills$/, save: (p) => p.getByRole("button", { name: "Create template", exact: true }) },
  ].map((f) => ({
    id: `${f.id}-a-reversed-window-is-refused-in-a-sentence`,
    title: `${f.name}: a stop date before the first date is refused in a sentence and nothing is sent`,
    contexts: TZ_MATRIX,
    async run(env) {
      const { page, stub } = env;
      await f.open(env);
      await typeAndLeave(page.locator(f.start), "01/11/2026");
      await typeAndLeave(page.locator(f.end), "01/10/2026");
      await f.save(page).click();
      await page.getByText(f.sentence).first().waitFor({ timeout: 4000 }).catch(() => {
        throw new Error(`${f.name}: a reversed window did not say "${f.sentence}"`);
      });
      await stub.quiet();
      assert.equal(stub.writesTo(f.write).length, 0, `${f.name}: a reversed window SENT A WRITE`);
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

  // ── THE REST OF THE "I FILED IT / I PAID IT AT THE PORTAL" PROMPTS (thirteenth slice) ───────────────────────────────────────────────────
  // Each started with TODAY's date in the box (one never asked at all: the GST tracker's Add Filing form sent today's date for a filing recorded as Filed).
  // The day a return was filed is the CA's statement, so the box starts empty; and it can never be later than today, so a day after it is refused in a sentence
  // before anything is sent (a bare `max` only hinted at it, and one reached the server, which words it with a column name).
  //   box     : the date box;  label : the field's name in a sentence;  save : the control that records it
  //   empty   : "held" (the control is disabled over no date) or the sentence a click on it says
  //   after   : "held" (the control is disabled over a date after today), "sentence" (a click says `${label}: ${AFTER_TODAY_SENTENCE}`) or "toast" (the sentence is a toast)
  //   server  : [route regex, the refusal it answers, where it shows] for a date before the period or year: the server's to refuse, said INSIDE the dialog
  ...[
    { id: "deadlines-mark-filed", name: "Deadlines > Mark as Filed", open: openMarkFiled, box: (p) => modalOf(p).locator("#mark-filed-date"), label: "Filed on",
      save: (p) => modalOf(p).getByRole("button", { name: "Confirm Filed", exact: true }), empty: "held", after: "held", write: /compliance\/obligations\/ob-1\/mark-filed$/,
      server: { sentence: GSTR_BEFORE_PERIOD_SENTENCE("2026-09-15", "2026-09-30") } },
    { id: "itr-single", name: "Income Tax > ITR tracker > Mark Filed", open: openItrTracker("single"), box: (p) => p.locator("#itr-filed-modal-date"), label: "Date of filing",
      save: (p) => p.getByRole("button", { name: "Confirm Filing", exact: true }), empty: "Filing date is required", after: "sentence", write: /compliance\/calendar\/itr-1\/filed$/ },
    { id: "itr-batch", name: "Income Tax > ITR tracker > Mark Filed (several)", open: openItrTracker("batch"), box: (p) => p.locator("#itr-batch-filed-date"), label: "Date of filing",
      save: (p) => p.getByRole("button", { name: /^Confirm Filing \(/ }), empty: "held", after: "sentence", write: /compliance\/calendar\/itr-1\/filed$/ },
    { id: "gst-single", name: "GST > filing tracker > Mark as Filed", open: openGstTracker("single"), box: (p) => p.locator("#gst-filed-modal-date"), label: "Date of filing",
      save: (p) => p.getByRole("button", { name: "Confirm Filing", exact: true }), empty: "Filing date is required", after: "sentence", write: /compliance\/calendar\/gst-1\/filed$/,
      server: { sentence: GSTR_BEFORE_PERIOD_SENTENCE("2026-09-15", "2026-09-30") } },
    { id: "gst-batch", name: "GST > filing tracker > Mark Filed (several)", open: openGstTracker("batch"), box: (p) => p.locator("#gst-batch-filed-date"), label: "Date of filing",
      save: (p) => p.getByRole("button", { name: /^Confirm \d+ Filings?$/ }), empty: "held", after: "sentence", write: /compliance\/calendar\/gst-1\/filed$/,
      server: { sentence: GSTR_BEFORE_PERIOD_SENTENCE("2026-09-15", "2026-09-30") } },
    { id: "gst-add-filed", name: "GST > filing tracker > Add GST Filing recorded as Filed", open: openGstTracker("add-filed"), box: (p) => p.locator("#gst-add-filing-filed-on"), label: "Filed on",
      save: (p) => p.getByRole("button", { name: "Save Filing", exact: true }), empty: "Filed on: enter the date this return was filed on the portal.", after: "sentence",
      write: /compliance\/calendar\/gst-new\/filed$/, insert: /rest\/v1\/compliance_calendar/ },
    { id: "mca-single", name: "MCA > Filings > Mark Filed", open: openMcaTracker("single"), box: (p) => p.locator("#mca-filed-modal-date"), label: "Date of filing",
      save: (p) => p.getByRole("button", { name: "Confirm Filing", exact: true }), empty: "Filing date is required", after: "sentence", write: /mca-workspace\/filings\/m-1\/status$/,
      server: { sentence: MCA_BEFORE_YEAR_SENTENCE, typed: "15/01/2026" } },
    { id: "mca-batch", name: "MCA > Filings > Mark Filed (several)", open: openMcaTracker("batch"), box: (p) => p.locator("#mca-batch-filed-date"), label: "Date of filing",
      save: (p) => p.getByRole("button", { name: /^Confirm \d+ Filings?$/ }), empty: "held", after: "held", write: /mca-workspace\/filings\/m-1\/status$/,
      server: { sentence: MCA_BEFORE_YEAR_SENTENCE, typed: "15/01/2026" } },
    { id: "mca-add-filed", name: "MCA > Filings > Add Filing recorded as Filed", open: openMcaTracker("add-filed"), box: (p) => p.locator("#mca-filed-on"), label: "Filed on MCA21 on",
      save: (p) => p.getByRole("button", { name: "Add Filing", exact: true }).last(), empty: "A filing marked Filed needs its SRN and the date it was filed on MCA21.", after: "sentence",
      write: /mca-workspace\/filings\/m-new\/status$/, insert: /rest\/v1\/mca_filings/ },
    { id: "client-mca-confirm", name: "A client's MCA filings > Mark Filed (CA)", open: openClientMcaConfirm, box: (p) => p.locator("#mca-confirm-filing-date"), label: "Filing date",
      save: (p) => p.getByRole("button", { name: "Confirm Filing", exact: true }), empty: "Filing date is required", after: "sentence", write: /mca-workspace\/filings\/mf-1\/status$/,
      server: { sentence: MCA_BEFORE_YEAR_SENTENCE, typed: "15/01/2026" } },
    { id: "payroll-esi", name: "Payroll > File > record an ESI payment", open: openStatutoryHandoff("esic"), box: (p) => p.getByLabel("Date of the payment or filing"), label: "Date",
      save: (p) => p.getByRole("button", { name: "Record it", exact: true }), empty: "Date: enter the date of the payment or filing.", after: "sentence", write: /payroll\/clients\/[^/]+\/remittances$/ },
    { id: "payroll-epf", name: "Payroll > File > record an EPF return", open: openStatutoryHandoff("epf"), box: (p) => p.getByLabel("Date of the payment or filing"), label: "Date",
      save: (p) => p.getByRole("button", { name: "Record it", exact: true }), empty: "Date: enter the date of the payment or filing.", after: "sentence", write: /payroll\/runs\/run1\/ecr\/filed$/ },
    { id: "itr-acknowledgement", name: "Income Tax > Filing > Record as Filed", open: openRecordItrAcknowledgement, box: (p) => p.locator("#itr-ack-filing-date"), label: "Filing date",
      save: (p) => p.getByRole("button", { name: "Record as Filed", exact: true }), empty: "held", after: "toast", write: /api\/itr\/filings\/itr-f1\/acknowledge$/ },
    { id: "itr-earlier-return", name: "Income Tax > Filing > New Filing (revised): the earlier return's filing date", open: openNewRevisedReturn, box: (p) => p.locator("#itr-original-filing-date"),
      label: "Earlier return's filing date", save: (p) => p.getByRole("button", { name: "Create", exact: true }),
      empty: "Earlier return's filing date: enter the date on the earlier return's receipt.", after: "sentence", write: /api\/itr\/filings$/ },
  ].flatMap((f) => [
    {
      id: `${f.id}-starts-with-no-date`,
      title: `${f.name}: the date box starts empty, and the control waits for a date or says it is needed`,
      contexts: TZ_MATRIX,
      async run(env) {
        const { page, stub } = env;
        await f.open(env);
        assert.equal(await f.box(page).inputValue(), "", `${f.name}: the box offered a date the CA had not stated`);
        if (f.empty === "held") {
          assert.equal(await f.save(page).isDisabled(), true, `${f.name}: the control was live over no date`);
        } else {
          await f.save(page).click();
          await shownInTheDialog(page, f.empty, `${f.name}: no date was not answered in a sentence`);
        }
        await stub.quiet();
        assert.equal(stub.writesTo(f.write).length, 0, `${f.name}: no date SENT A WRITE`);
        // An Add form inserts its row BEFORE it records the filing, so "nothing is sent" has to cover the insert too: a row inserted and then refused is an orphan.
        if (f.insert) assert.equal(stub.writesTo(f.insert, "POST").length, 0, `${f.name}: no date INSERTED A ROW`);
      },
    },
    {
      id: `${f.id}-a-date-after-today-is-refused`,
      title: `${f.name}: a date after today is refused in a sentence and nothing is sent`,
      contexts: TZ_MATRIX,
      async run(env) {
        const { page, stub } = env;
        await f.open(env);
        // After today (the clock is pinned at 8 October 2026).
        await typeAndLeave(f.box(page), "15/10/2026");
        await page.getByText(AFTER_TODAY_SENTENCE).first().waitFor({ timeout: 4000 }).catch(() => { throw new Error(`${f.name}: the box did not say "${AFTER_TODAY_SENTENCE}"`); });
        if (f.after === "held") {
          assert.equal(await f.save(page).isDisabled(), true, `${f.name}: the control was live over a date after today`);
        } else {
          await f.save(page).click();
          const said = `${f.label}: ${AFTER_TODAY_SENTENCE}`;
          if (f.after === "toast") {
            await page.getByText(said).first().waitFor({ timeout: 4000 }).catch(() => { throw new Error(`${f.name}: a date after today was not refused in a toast saying "${said}"`); });
          } else {
            await shownInTheDialog(page, said, `${f.name}: a date after today was not refused in a sentence`);
          }
        }
        await stub.quiet();
        assert.equal(stub.writesTo(f.write).length, 0, `${f.name}: a date after today SENT A WRITE`);
        if (f.insert) assert.equal(stub.writesTo(f.insert, "POST").length, 0, `${f.name}: a date after today INSERTED A ROW`);
      },
    },
    ...(f.server ? [{
      id: `${f.id}-the-servers-answer-to-an-early-date-is-shown-inside`,
      title: `${f.name}: the server's refusal of a date before the period or year ended is shown inside the dialog`,
      contexts: TZ_MATRIX,
      async run(env) {
        const { page, stub } = env;
        await f.open(env);
        // The opener's stub is the real door's rule: it refuses a date before the period or year ended, in the door's own words.
        await typeAndLeave(f.box(page), f.server.typed ?? "15/09/2026");
        await f.save(page).click();
        await shownInTheDialog(page, f.server.sentence, `${f.name}: the server's answer to an early date was not shown`);
        await stub.quiet();
        assert.equal(stub.writesTo(f.write).length, 1, `${f.name}: an early date should send ONE request for the server to answer`);
      },
    }] : []),
  ]),
  // A filing recorded as Filed on the GST tracker is added as a row first and recorded second. If the server declines the second step (a date before the
  // period ended is its to refuse), the row exists as pending; the dialog used to stay open over it, and the next Save inserted it again.
  {
    id: "gst-add-filed-a-refusal-keeps-the-row-and-closes-the-dialog",
    title: "GST > filing tracker > Add GST Filing recorded as Filed: when the server declines the date, the row is kept as pending, the sentence is said, and a second Save is not possible",
    contexts: TZ_MATRIX,
    async run(env) {
      const { page, stub } = env;
      await openGstTracker("add-filed")(env);   // the September return: the door refuses a date before 30 September
      await typeAndLeave(page.locator("#gst-add-filing-filed-on"), "15/09/2026");
      await page.getByRole("button", { name: "Save Filing", exact: true }).click();
      await page.getByText("Filing added, but not marked filed").first().waitFor({ timeout: 4000 }).catch(() => { throw new Error("the refusal was not said as 'Filing added, but not marked filed'"); });
      await page.getByText(GSTR_BEFORE_PERIOD_SENTENCE("2026-09-15", "2026-09-30")).first().waitFor({ timeout: 4000 });
      await page.locator("#gst-add-filing-filed-on").waitFor({ state: "detached", timeout: 4000 }).catch(() => { throw new Error("the dialog stayed open over a row that now exists"); });
      await stub.quiet();
      assert.equal(stub.writesTo(/rest\/v1\/compliance_calendar/, "POST").length, 1, "the row should have been inserted once");
    },
  },
  // The MCA Add Filing form inserts a row and then records it as filed. A date the door refuses (HTTP 200 with success false) or a caller the door refuses (HTTP 403,
  // which the API client RAISES) both leave a pending row: it is kept, the reason is said, and the dialog closes instead of staying open over a row that exists.
  ...[
    { id: "a-date-the-door-refuses", name: "a date before the year ended", answer: null, typed: "15/01/2026", sentence: MCA_BEFORE_YEAR_SENTENCE },
    { id: "a-caller-the-door-refuses", name: "a caller who may not approve MCA filings", answer: refuse("Only Manager or above can mark filings as filed", 403), typed: "05/10/2026",
      sentence: "Only Manager or above can mark filings as filed" },
  ].map((c) => ({
    id: `mca-add-filed-${c.id}-keeps-the-row-and-closes-the-dialog`,
    title: `MCA > Filings > Add Filing recorded as Filed, ${c.name}: the row is kept as pending, the reason is said and the dialog closes`,
    contexts: TZ_MATRIX,
    async run(env) {
      const { page, stub } = env;
      await openMcaTracker("add-filed")(env);
      if (c.answer) stub.route({ method: "PATCH", re: /mca-workspace\/filings\/m-new\/status$/, ...c.answer });   // after the opener's own, so it answers first
      await typeAndLeave(page.locator("#mca-filed-on"), c.typed);
      await page.getByRole("button", { name: "Add Filing", exact: true }).last().click();
      await page.getByText("Filing added, but not marked filed").first().waitFor({ timeout: 4000 }).catch(() => { throw new Error("the refusal was not said as 'Filing added, but not marked filed'"); });
      await page.getByText(c.sentence).first().waitFor({ timeout: 4000 }).catch(() => { throw new Error(`the reason was not said: "${c.sentence}"`); });
      await page.locator("#mca-filed-on").waitFor({ state: "detached", timeout: 4000 }).catch(() => { throw new Error("the dialog stayed open over a row that now exists"); });
      await stub.quiet();
      assert.equal(stub.writesTo(/rest\/v1\/mca_filings/, "POST").length, 1, "the row should have been inserted once");
    },
  })),
  // ── STATE THAT OUTLIVED ITS SUBJECT, found by an independent read of the thirteenth slice ─────────────────────────────────────────────────────────────────────
  // The ITR acknowledgement panel is about ONE return. Its number and date were still in it after Cancel, after a record and when another return was picked (and the
  // panel then sat under the other return, so "Record as Filed" sent the first return's number and date for it).
  {
    id: "itr-acknowledgement-opens-empty-every-time-and-belongs-to-its-return",
    title: "Income Tax > Filing > Record Acknowledgement: after Cancel and after another return is picked the panel is empty",
    contexts: TZ_MATRIX,
    async run(env) {
      const { page, stub } = env;
      await openAcknowledgementOfTwoReturns(env);
      const number = page.getByLabel("Acknowledgement Number", { exact: true });
      const date = page.locator("#itr-ack-filing-date");
      const record = page.getByRole("button", { name: "Record Acknowledgement", exact: true });
      await number.fill("123456789012345");
      await typeAndLeave(date, "05/10/2026");
      await page.getByRole("button", { name: "Cancel", exact: true }).click();
      await record.click();
      assert.equal(await number.inputValue(), "", "the number typed before Cancel was still in the panel");
      assert.equal(await date.inputValue(), "", "the date typed before Cancel was still in the panel");
      // Unreadable text too: the box does not reset what it could not read unless it is remounted.
      await typeAndLeave(date, "31/02/2026");
      await page.getByRole("button", { name: "Cancel", exact: true }).click();
      await record.click();
      assert.equal(await date.inputValue(), "", "unreadable text typed before Cancel was still in the box");
      assert.equal(await page.getByText(FEB_SENTENCE).count(), 0, "the sentence about text typed before Cancel was still on the panel");
      // Another return picked while the panel is open: the panel goes, and opens empty on the other return.
      await number.fill("999999999999999");
      await typeAndLeave(date, "06/10/2026");
      await page.getByRole("button", { name: /ITR-4/ }).first().click();
      assert.equal(await page.getByText("Record Filing Acknowledgement").count(), 0, "the panel of the first return stayed open under the second");
      await page.getByRole("button", { name: "Record Acknowledgement", exact: true }).click();
      assert.equal(await number.inputValue(), "", "the first return's number was in the second return's panel");
      assert.equal(await date.inputValue(), "", "the first return's date was in the second return's panel");
      await stub.quiet();
      assert.equal(stub.writesTo(/api\/itr\/filings\/itr-f[12]\/acknowledge$/).length, 0, "nothing should have been recorded");
    },
  },
  // The new-filing form's earlier-receipt boxes show only for a revised or updated return. Their text was still in the state when the kind was changed back to an
  // original return, and was sent (and judged by the server, in a sentence about a box that was not on the screen); Cancel kept it too.
  {
    id: "itr-new-filing-sends-the-earlier-receipt-only-where-the-kind-needs-it-and-opens-empty",
    title: "Income Tax > Filing > New Filing: a receipt typed for a revised return is not sent for an original one, and the form opens empty",
    contexts: TZ_MATRIX,
    async run(env) {
      const { page, stub } = env;
      await openNewRevisedReturn(env);   // kind revised, the earlier return's number typed
      await typeAndLeave(page.locator("#itr-original-filing-date"), "20/07/2026");
      await page.getByLabel("Kind of return", { exact: true }).selectOption("original");
      await page.getByRole("button", { name: "Create", exact: true }).click();
      await stub.quiet();
      const writes = stub.writesTo(/api\/itr\/filings$/);
      assert.equal(writes.length, 1, `expected one create request, saw ${writes.length}`);
      const body = JSON.parse(writes[0].body);
      assert.equal(body.original_filing_date, null, `an original return sent the earlier return's date: ${JSON.stringify(body.original_filing_date)}`);
      assert.equal(body.original_acknowledgement_number, null, `an original return sent the earlier return's number: ${JSON.stringify(body.original_acknowledgement_number)}`);
      // Cancel and open again: nothing typed before is in the boxes.
      stub.forgetWrites();
      await page.getByRole("button", { name: "New Filing" }).first().click();
      await page.getByLabel("Kind of return", { exact: true }).selectOption("revised");
      await typeAndLeave(page.locator("#itr-original-filing-date"), "31/02/2026");
      await page.getByRole("button", { name: "Cancel", exact: true }).click();
      await page.getByRole("button", { name: "New Filing" }).first().click();
      await page.getByLabel("Kind of return", { exact: true }).selectOption("revised");
      assert.equal(await page.locator("#itr-original-filing-date").inputValue(), "", "unreadable text typed before Cancel was still in the box");
      assert.equal(await page.getByLabel("Earlier return's acknowledgement number").inputValue(), "", "the number typed before Cancel was still in the box");
    },
  },
  // The File tab keys a card by the obligation ("epf", "esic", "professional_tax:<state>"), the same in every month, so a card is one instance for every month: what was typed
  // for September (the challan, the date, the amount) was offered for August and "Record it" saved it there.
  {
    id: "payroll-file-a-card-does-not-carry-another-months-answers",
    title: "Payroll > File: choosing another month starts its card empty (the challan, the date and the amount typed for the first)",
    contexts: TZ_MATRIX,
    async run(env) {
      const { page, stub } = env;
      await openStatutoryHandoff("esic", { twoMonths: true })(env);
      await page.getByLabel("Challan number", { exact: true }).fill("CH-SEP-1");
      await typeAndLeave(page.getByLabel("Date of the payment or filing"), "05/10/2026");
      await page.getByLabel("Amount paid (₹)", { exact: true }).fill("1234");
      await page.getByLabel("Month", { exact: true }).selectOption("run0");
      await page.getByText("ESIC · August 2026").first().waitFor({ timeout: 4000 }).catch(() => { throw new Error("August's card never arrived"); });
      assert.equal(await page.getByLabel("Challan number", { exact: true }).inputValue(), "", "September's challan number was in August's card");
      assert.equal(await page.getByLabel("Date of the payment or filing").inputValue(), "", "September's date was in August's card");
      assert.equal(await page.getByLabel("Amount paid (₹)", { exact: true }).inputValue(), "", "September's amount was in August's card");
      await stub.quiet();
      assert.equal(stub.writesTo(/payroll\/clients\/[^/]+\/remittances$/).length, 0, "nothing should have been recorded");
    },
  },
  // A box shown again over a value its parent kept: the Add forms keep the filed-on state while the Status is not Filed. The date typed before (a date after today, with its
  // sentence) came back with no sentence, and Save sent it.
  ...[
    { id: "gst", name: "GST > filing tracker > Add GST Filing", open: openGstTracker("add-filed"), box: "#gst-add-filing-filed-on", select: "select[aria-label='Status']",
      insert: /rest\/v1\/compliance_calendar/, write: /compliance\/calendar\/gst-new\/filed$/, needs: "Acknowledgement number (ARN): enter the number on the portal's receipt." },
    { id: "mca", name: "MCA > Filings > Add Filing", open: openMcaTracker("add-filed"), box: "#mca-filed-on", select: "select[aria-label='Status']",
      insert: /rest\/v1\/mca_filings/, write: /mca-workspace\/filings\/m-new\/status$/, needs: "A filing marked Filed needs its SRN and the date it was filed on MCA21." },
  ].map((f) => ({
    id: `${f.id}-add-filed-a-date-does-not-come-back-after-the-status-is-changed`,
    title: `${f.name}: a date typed for Filed (after today) is gone when Status is changed away and back, and nothing is sent`,
    contexts: TZ_MATRIX,
    async run(env) {
      const { page, stub } = env;
      await f.open(env);
      await typeAndLeave(page.locator(f.box), "15/10/2026");
      await page.getByText(AFTER_TODAY_SENTENCE).first().waitFor({ timeout: 4000 }).catch(() => { throw new Error(`${f.name}: the box did not say "${AFTER_TODAY_SENTENCE}"`); });
      const status = page.locator(f.select).last();
      await status.selectOption("Pending");
      await status.selectOption("Filed");
      await page.locator(f.box).waitFor();
      assert.equal(await page.locator(f.box).inputValue(), "", `${f.name}: the date typed before the box was hidden came back`);
      await page.getByRole("button", { name: /^(Save Filing|Add Filing)$/ }).last().click();
      await stub.quiet();
      assert.equal(stub.writesTo(f.insert, "POST").length, 0, `${f.name}: a filing recorded as Filed with no date INSERTED A ROW`);
      assert.equal(stub.writesTo(f.write).length, 0, `${f.name}: a filing recorded as Filed with no date SENT A WRITE`);
    },
  })),
  // The GST tracker's own prompts refuse a filing recorded without the portal's receipt (the ARN); the Add form skipped it and, with its new Filed-on box, looked like
  // a complete record.
  {
    id: "gst-add-filed-without-the-acknowledgement-number-is-refused-in-a-sentence",
    title: "GST > filing tracker > Add GST Filing recorded as Filed: with no ARN it is refused in a sentence and nothing is inserted",
    contexts: TZ_MATRIX,
    async run(env) {
      const { page, stub } = env;
      await openGstTracker("add-filed")(env);
      await page.getByLabel("Acknowledgement number (ARN)", { exact: true }).fill("");
      await typeAndLeave(page.locator("#gst-add-filing-filed-on"), "05/10/2026");
      await page.getByRole("button", { name: "Save Filing", exact: true }).click();
      await shownInTheDialog(page, "Acknowledgement number (ARN): enter the number on the portal's receipt.", "a filing recorded as Filed without its ARN was not refused in a sentence");
      await stub.quiet();
      assert.equal(stub.writesTo(/rest\/v1\/compliance_calendar/, "POST").length, 0, "a filing recorded as Filed with no ARN INSERTED A ROW");
      assert.equal(stub.writesTo(/compliance\/calendar\/gst-new\/filed$/).length, 0, "a filing recorded as Filed with no ARN SENT A WRITE");
    },
  },
  // A client's MCA confirmation panel is one panel for every row. Text the box could not read, typed for the first filing, was still in it when the second filing's panel
  // was opened without cancelling (the box does not reset unreadable text unless it is remounted).
  {
    id: "client-mca-confirm-unreadable-text-does-not-carry-to-another-filing",
    title: "A client's MCA filings > Mark Filed (CA): opening it on a second filing starts the date box empty, with no sentence about the first one's text",
    contexts: TZ_MATRIX,
    async run(env) {
      const { page } = env;
      await openClientMcaConfirm(env, { two: true });
      const box = page.locator("#mca-confirm-filing-date");
      await typeAndLeave(box, "31/02/2026");
      await page.getByText(FEB_SENTENCE).first().waitFor({ timeout: 4000 }).catch(() => { throw new Error("the box did not say " + FEB_SENTENCE); });
      await page.getByRole("button", { name: "Mark Filed (CA)", exact: true }).nth(1).click();
      await page.waitForTimeout(300);
      assert.equal(await box.inputValue(), "", "text typed for the first filing was still in the box for the second");
      assert.equal(await page.getByText(FEB_SENTENCE).count(), 0, "the sentence about the first filing's text was still on the second filing's panel");
    },
  },
  // ── the four forms on a client's compliance tabs (fourteenth slice) ────────────────────────────────────────────────────────────────────────
  // Three took their date as plain typed text, sent whatever it held ("" for a box left empty, which a DATE column cannot take), ignored the server's answer and closed as
  // though they had saved. A company or a filing typed with no date, and a challan with a mistyped one, was not created and nothing said so; a form left open for a second
  // record still held the first. (The first fix sent null for a blank filing date; the column is NOT NULL, so the date is required and the form asks for it.)
  ...CLIENT_COMPLIANCE_FORMS.flatMap((f) => [
    {
      id: `${f.id}-a-refusal-is-said-inside-the-form-and-keeps-what-was-typed`,
      title: `${f.name}: when the server refuses, its sentence is shown in the form and the form stays open with what was typed`,
      contexts: TZ_MATRIX,
      async run(env) {
        const { page, stub } = env;
        await f.open(env);
        for (const how of ["answers success false", "refuses with a status"]) {
          stub.route({ method: "POST", re: f.write, ...(how === "refuses with a status" ? refuse(f.httpRefusal, 404) : { reply: () => ({ success: false, data: null, error: f.refusal }) }) });
          stub.forgetWrites();
          await typeAndLeave(page.locator(f.dateBox), f.typedDate);
          await page.getByRole("button", { name: "Save", exact: true }).click();
          await shownInTheDialog(page, how === "refuses with a status" ? f.httpRefusal : f.refusal, `${f.name}: the server's refusal (it ${how}) was not shown`);
          await stub.quiet();
          assert.equal(stub.writesTo(f.write).length, 1, `${f.name}: expected the one refused request (it ${how})`);
          assert.equal(await page.locator(f.dateBox).count(), 1, `${f.name}: the form closed over a refusal (it ${how}), as though it had saved`);
          assert.equal(await page.getByLabel(f.typedLabel, { exact: true }).inputValue(), f.typedValue, `${f.name}: the form lost ${f.typedLabel} over a refusal (it ${how})`);
          assert.equal(await page.locator(f.dateBox).inputValue(), f.typedDate, `${f.name}: the form lost the date over a refusal (it ${how})`);
        }
      },
    },
    {
      id: `${f.id}-cancel-after-a-refusal-starts-the-next-record-clean`,
      title: `${f.name}: a refusal, Cancel and the form opened again hold nothing of the last record, and not its sentence`,
      contexts: TZ_MATRIX,
      async run(env) {
        const { page, stub } = env;
        await f.open(env);
        stub.route({ method: "POST", re: f.write, reply: () => ({ success: false, data: null, error: f.refusal }) });
        await typeAndLeave(page.locator(f.dateBox), f.typedDate);
        await page.getByRole("button", { name: "Save", exact: true }).click();
        await shownInTheDialog(page, f.refusal, `${f.name}: the server's refusal was not shown`);
        await page.getByRole("button", { name: "Cancel", exact: true }).click();
        await page.locator(f.dateBox).waitFor({ state: "detached", timeout: 4000 }).catch(() => { throw new Error(`${f.name}: Cancel did not close the form`); });
        await page.getByRole("button", { name: f.add, exact: true }).click();
        assert.equal(await page.getByText(f.refusal).count(), 0, `${f.name}: the form opened again still said the last record's refusal`);
        assert.equal(await page.getByLabel(f.typedLabel, { exact: true }).inputValue(), "", `${f.name}: ${f.typedLabel} of the cancelled record was still in the form`);
        assert.equal(await page.locator(f.dateBox).inputValue(), "", `${f.name}: the date of the cancelled record was still in the form`);
      },
    },
    {
      id: `${f.id}-reopened-after-a-saved-record-starts-empty-and-the-record-is-in-its-list`,
      title: `${f.name}: after a record is saved the form is closed and the record is in its list, and the form opened again holds nothing of it`,
      contexts: TZ_MATRIX,
      async run(env) {
        const { page, stub } = env;
        await f.open(env);
        await typeAndLeave(page.locator(f.dateBox), f.typedDate);
        await page.getByRole("button", { name: "Save", exact: true }).click();
        await page.locator(f.dateBox).waitFor({ state: "detached", timeout: 4000 }).catch(() => { throw new Error(`${f.name}: the form stayed open after the record was saved`); });
        await stub.quiet();
        assert.equal(stub.writesTo(f.write).length, 1, `${f.name}: expected one request`);
        await page.getByText(f.listShows).first().waitFor({ timeout: 4000 }).catch(() => { throw new Error(`${f.name}: the saved record (${f.listShows}) is not in the list`); });
        await page.getByRole("button", { name: f.add, exact: true }).click();
        assert.equal(await page.getByLabel(f.typedLabel, { exact: true }).inputValue(), "", `${f.name}: ${f.typedLabel} of the last record was still in the form`);
        assert.equal(await page.locator(f.dateBox).inputValue(), "", `${f.name}: the date of the last record was still in the form`);
      },
    },
    {
      id: `${f.id}-pressing-the-open-button-again-keeps-what-was-typed`,
      title: `${f.name}: the open button stays on screen above the form, and pressing it again keeps what was typed`,
      contexts: TZ_MATRIX,
      async run(env) {
        const { page } = env;
        await f.open(env);
        await typeAndLeave(page.locator(f.dateBox), f.typedDate);
        await page.getByRole("button", { name: f.add, exact: true }).click();
        await page.waitForTimeout(300);
        assert.equal(await page.getByLabel(f.typedLabel, { exact: true }).inputValue(), f.typedValue, `${f.name}: pressing the open button again emptied ${f.typedLabel}`);
        assert.equal(await page.locator(f.dateBox).inputValue(), f.typedDate, `${f.name}: pressing the open button again emptied the date`);
      },
    },
    {
      id: `${f.id}-two-clicks-in-the-same-moment-send-one-request`,
      title: `${f.name}: a same-tick double click on Save sends ONE request`,
      async run(env) {
        const { page, stub } = env;
        await f.open(env);
        await typeAndLeave(page.locator(f.dateBox), f.typedDate);
        await sameTickDouble(page.getByRole("button", { name: "Save", exact: true }));
        await expectWrites(stub, f.write, 1, `two same-tick clicks on Save in ${f.name}`);
      },
    },
    {
      id: `${f.id}-cancel-is-held-while-the-save-is-out`,
      title: `${f.name}: while a Save is out Cancel is held, so a late answer cannot act on a form opened for another record`,
      async run(env) {
        const { page, stub } = env;
        await f.open(env);
        stub.route({ method: "POST", re: f.write, delay: 1800, reply: () => ({ success: false, data: null, error: f.refusal }) });
        await typeAndLeave(page.locator(f.dateBox), f.typedDate);
        await page.getByRole("button", { name: "Save", exact: true }).click();
        const cancel = page.getByRole("button", { name: "Cancel", exact: true });
        await until(async () => await cancel.isDisabled(), `${f.name}: Cancel stayed live while the Save was out`);
        await shownInTheDialog(page, f.refusal, `${f.name}: the refusal was not shown once the answer came`);
        assert.equal(await cancel.isDisabled(), false, `${f.name}: Cancel stayed held after the answer`);
      },
    },
    ...(f.optionalDate ? [{
      id: `${f.id}-no-date-typed-is-sent-as-no-date`,
      title: `${f.name}: with no date typed the request carries null, never an empty string the database cannot read`,
      contexts: TZ_MATRIX,
      async run(env) {
        const { page, stub } = env;
        await f.open(env);
        await page.getByRole("button", { name: "Save", exact: true }).click();
        await stub.quiet();
        const sent = stub.writesTo(f.write);
        assert.equal(sent.length, 1, `${f.name}: expected one request, saw ${sent.length}`);
        assert.equal(JSON.parse(sent[0].body)[f.dateKey], null, `${f.name}: with no date typed ${f.dateKey} reached the server as ${JSON.stringify(JSON.parse(sent[0].body)[f.dateKey])}, not null`);
      },
    }] : [{
      id: `${f.id}-no-date-typed-is-asked-for-and-nothing-is-sent`,
      title: `${f.name}: the date is required (the column is NOT NULL): with none typed the form asks for it in a sentence and sends nothing`,
      contexts: TZ_MATRIX,
      async run(env) {
        const { page, stub } = env;
        await f.open(env);
        await page.getByRole("button", { name: "Save", exact: true }).click();
        await shownInTheDialog(page, f.askedFor, `${f.name}: a blank date was not asked for`);
        await stub.quiet();
        assert.equal(stub.writesTo(f.write).length, 0, `${f.name}: a blank date SENT A WRITE (the column is NOT NULL, so the database would refuse it)`);
      },
    }]),
  ]),
  // A company that has a CIN has been incorporated: a day after today is refused in a sentence and nothing is sent.
  {
    id: "client-mca-company-an-incorporation-date-after-today-is-refused",
    title: "A client's MCA > Company Master > Add Company: an incorporation date after today is refused in a sentence and nothing is sent",
    contexts: TZ_MATRIX,
    async run(env) {
      const { page, stub } = env;
      await openClientMcaCompany(env);
      await typeAndLeave(page.locator("#mca-company-incorporated"), "15/10/2026");
      await page.getByRole("button", { name: "Save", exact: true }).click();
      await shownInTheDialog(page, `Incorporation date: ${AFTER_TODAY_SENTENCE}`, "a company incorporated after today was not refused in a sentence");
      await stub.quiet();
      assert.equal(stub.writesTo(/mca-workspace\/companies$/).length, 0, "an incorporation date after today SENT A WRITE");
      // …and the sentence is withdrawn the moment the date is right (it was a copy that stayed after the fix).
      await typeAndLeave(page.locator("#mca-company-incorporated"), "08/10/2026");
      await page.waitForTimeout(300);
      assert.equal(await page.getByText(`Incorporation date: ${AFTER_TODAY_SENTENCE}`).count(), 0, "the refusal stayed on the form after the date was put right");
    },
  },
  // The challan is known by its number, its BSR code, its section and its year: a box skipped is asked for, in a sentence, and nothing is sent (a challan with a box skipped was
  // stored as empty text, which the NOT NULL columns accept).
  ...[
    { label: "Challan No.", sentence: "Challan number: enter the serial number printed on the challan." },
    { label: "BSR Code (7 digits)", sentence: "BSR code: enter the code of the bank branch printed on the challan." },
    { label: "TDS Section (e.g. 194C)", sentence: "TDS section: enter the section this challan pays, for example 194C." },
    { label: "FY (e.g. 2025-26)", sentence: "Financial year: enter it as 2026-27." },
  ].map((box) => ({
    id: `client-tds-challan-without-${box.label.split(" ")[0].toLowerCase().replace(/[^a-z]/g, "")}-is-asked-for-and-nothing-is-sent`,
    title: `A client's TDS > Challans > New Challan: with "${box.label}" left empty the form asks for it in a sentence and sends nothing`,
    async run(env) {
      const { page, stub } = env;
      await openClientTdsChallan(env);
      await typeAndLeave(page.locator("#tds-client-challan-date"), "07/10/2026");
      await page.getByLabel(box.label, { exact: true }).fill("");
      await page.getByRole("button", { name: "Save", exact: true }).click();
      await shownInTheDialog(page, box.sentence, `a challan with "${box.label}" empty was not asked for it`);
      await stub.quiet();
      assert.equal(stub.writesTo(/api\/tds-workspace\/challans$/).length, 0, `a challan with "${box.label}" empty SENT A WRITE`);
    },
  })),
  // The firm-level Add Challan 281 modal asks for the same: the server now refuses a challan without its serial number or BSR code for every caller, and a validation list
  // from the server is not a sentence this screen's fetch can show (it came back as "Could not record the challan", with no reason).
  ...[
    { name: "Serial No.", placeholder: "00001", sentence: "Challan number: enter the serial number printed on the challan." },
    { name: "BSR Code", placeholder: "7-digit BSR code", sentence: "BSR code: enter the code of the bank branch printed on the challan." },
  ].map((box) => ({
    id: `tds-add-challan-281-without-${box.name.split(" ")[0].toLowerCase()}-is-asked-for-and-nothing-is-sent`,
    title: `TDS > Challans > Add Challan 281: with "${box.name}" left empty the modal asks for it in a sentence and sends nothing`,
    async run(env) {
      const { page, stub } = env;
      const form = await openTdsChallanForm(env);
      await typeAndLeave(form.locator("#tds-challan-date"), "07/10/2026");
      await form.getByPlaceholder(box.placeholder).fill("");
      await form.getByRole("button", { name: "Add", exact: true }).click();
      await shownInTheDialog(page, box.sentence, `a challan with "${box.name}" empty was not asked for it`);
      await stub.quiet();
      assert.equal(stub.writesTo(/tds-workspace\/challans$/).length, 0, `a challan with "${box.name}" empty SENT A WRITE`);
    },
  })),
  // The answer to a recorded challan says what became of the month's deposit obligation on the compliance calendar (the server's words); the form used to throw it away.
  {
    id: "client-tds-challan-says-what-became-of-the-monthly-deposit",
    title: "A client's TDS > Challans > New Challan: what the server says about the compliance calendar is shown after the challan is recorded",
    contexts: TZ_MATRIX,
    async run(env) {
      const { page, stub } = env;
      await openClientTdsChallan(env);
      env.challanAnswer = [{ state: "not_closed", closed: false, month: "2026-09", needs_action: true, message: "A stub message about September 2026's deposit." }];
      await typeAndLeave(page.locator("#tds-client-challan-date"), "07/10/2026");
      await page.getByRole("button", { name: "Save", exact: true }).click();
      await page.getByText("Challan recorded. What became of the monthly deposits on the compliance calendar:").first().waitFor({ timeout: 4000 }).catch(() => { throw new Error("the server's answer about the compliance calendar was not shown"); });
      await page.getByText("A stub message about September 2026's deposit.").first().waitFor({ timeout: 4000 });
      await stub.quiet();
      assert.equal(stub.writesTo(/api\/tds-workspace\/challans$/).length, 1);
    },
  },
  // ── the fifteenth slice (6-11-2026) ─────────────────────────────────────────────────────────────────────────────────────────────────────────
  // The statutory values screen is a full-screen overlay over a page whose message line sits BEHIND it: every sentence its save had (a state code that is not two letters, the
  // required fields, a band amount with a comma, the server's refusal) went to that line, so a CA who pressed Record over a gap saw nothing happen. Only the date's own sentence was
  // said inside.
  {
    id: "statutory-values-every-refusal-is-said-inside-the-dialog",
    title: "Settings > Statutory values > Record a notification: a state code that is not two letters, a band amount with a comma and the server's refusal are each said inside the dialog",
    contexts: TZ_MATRIX,
    async run(env) {
      const { page, stub } = env;
      await openStatutoryValues(env);
      await typeAndLeave(page.locator("#sv-effective-from"), "01/04/2026");
      await typeAndLeave(page.locator("#sv-notified-on"), "10/03/2026");
      const record = page.getByRole("button", { name: "Record", exact: true });
      await page.getByLabel("State code", { exact: true }).fill("G");
      await record.click();
      await shownInTheDialog(page, PT_STATE_CODE_SENTENCE, "a state code that is not two letters was not refused inside the dialog");
      await page.getByLabel("State code", { exact: true }).fill("GJ");
      await page.getByLabel("Band 1: tax (₹)", { exact: true }).fill("2,000");
      await record.click();
      await shownInTheDialog(page, PT_BAND_COMMA_SENTENCE, "a band amount with a comma was not refused inside the dialog");
      await stub.quiet();
      assert.equal(stub.writesTo(/statutory-values\/pt$/).length, 0, "a refusal the screen could make itself SENT A WRITE");
      // The server's refusal of a set with a hole in it (the first band does not start at zero) comes back as an HTTP 422 whose detail is the sentence.
      stub.route({ method: "PUT", re: /api\/payroll\/statutory-values\/pt$/, ...refuse(PT_UNCOVERED_SENTENCE, 422) });
      await page.getByLabel("Band 1: tax (₹)", { exact: true }).fill("200");
      await page.getByLabel("Band 1: from (₹)", { exact: true }).fill("100");
      await record.click();
      await shownInTheDialog(page, PT_UNCOVERED_SENTENCE, "the server's refusal was not said inside the dialog");
      await stub.quiet();
      assert.equal(stub.writesTo(/statutory-values\/pt$/).length, 1, "expected the one refused request");
      assert.equal(await page.getByLabel("State code", { exact: true }).inputValue(), "GJ", "the dialog lost what was typed over the server's refusal");
      assert.equal(await page.locator("#sv-effective-from").inputValue(), "01/04/2026", "the dialog lost the effective-from date over the server's refusal");
    },
  },
  // A notification names its source and the two days: with a box empty the dialog says so, and the sentence goes the moment the last box is filled (it was a copy in the form's error
  // that stayed after the fix).
  {
    id: "statutory-values-a-notification-that-names-no-source-or-date-is-refused-and-the-sentence-goes-when-it-is-filled",
    title: "Settings > Statutory values > Record a notification: a notification with a date or the reference missing is refused in a sentence inside the dialog, which goes when the boxes are filled",
    contexts: TZ_MATRIX,
    async run(env) {
      const { page, stub } = env;
      await openStatutoryValues(env);
      const record = page.getByRole("button", { name: "Record", exact: true });
      const sentence = page.getByText(STATUTORY_REQUIRED_SENTENCE);
      await record.click();
      await shownInTheDialog(page, STATUTORY_REQUIRED_SENTENCE, "a notification with no dates was not refused inside the dialog");
      await stub.quiet();
      assert.equal(stub.writesTo(/statutory-values\/pt$/).length, 0, "a notification with no dates SENT A WRITE");
      // One date is not enough: the sentence stays while any box is empty…
      await typeAndLeave(page.locator("#sv-effective-from"), "01/04/2026");
      await page.waitForTimeout(300);
      assert.equal(await sentence.count(), 1, "the sentence went before every box was filled");
      // …and goes the moment the last one is filled.
      await typeAndLeave(page.locator("#sv-notified-on"), "10/03/2026");
      await page.waitForTimeout(300);
      assert.equal(await sentence.count(), 0, "the sentence stayed in the dialog after the boxes were filled");
      // The reference is one of the three: emptied, the sentence comes back on the next Record and goes when it is typed again.
      await page.getByLabel("Notification reference", { exact: true }).fill("");
      await record.click();
      await shownInTheDialog(page, STATUTORY_REQUIRED_SENTENCE, "a notification with no reference was not refused inside the dialog");
      await page.getByLabel("Notification reference", { exact: true }).fill("PFT/2026/12");
      await page.waitForTimeout(300);
      assert.equal(await sentence.count(), 0, "the sentence stayed in the dialog after the reference was typed");
      await stub.quiet();
      assert.equal(stub.writesTo(/statutory-values\/pt$/).length, 0, "a refused notification SENT A WRITE");
    },
  },
  // A notification the CA has read has been issued, so its date cannot be after today; the day it takes effect can be ahead (a notice made now for the next April).
  {
    id: "statutory-values-a-notification-date-after-today-is-refused-and-an-effective-date-ahead-is-sent",
    title: "Settings > Statutory values > Record a notification: a notification date after today is refused in a sentence and nothing is sent, and an effective-from date ahead is sent",
    contexts: TZ_MATRIX,
    async run(env) {
      const { page, stub } = env;
      await openStatutoryValues(env);
      await typeAndLeave(page.locator("#sv-effective-from"), "01/04/2027");
      await typeAndLeave(page.locator("#sv-notified-on"), "15/10/2026");
      const record = page.getByRole("button", { name: "Record", exact: true });
      await record.click();
      await shownInTheDialog(page, `Notification date: ${AFTER_TODAY_SENTENCE}`, "a notification dated after today was not refused in a sentence");
      await stub.quiet();
      assert.equal(stub.writesTo(/statutory-values\/pt$/).length, 0, "a notification date after today SENT A WRITE");
      await typeAndLeave(page.locator("#sv-notified-on"), "10/03/2026");
      await record.click();
      await stub.quiet();
      const sent = stub.writesTo(/statutory-values\/pt$/);
      assert.equal(sent.length, 1, `expected one write, saw ${sent.length}`);
      const body = JSON.parse(sent[0].body);
      assert.equal(body.effective_from, "2027-04-01", `an effective-from date ahead should be sent as typed, was ${body.effective_from}`);
      assert.equal(body.notification_date, "2026-03-10");
    },
  },
  // The bound is INDIA's day, which the server judges by: at 20:00 UTC on 8 October it is already 9 October in India and still 8 October in Los Angeles. The day the pinned clock
  // gives every other scenario is the same date in all three zones, so only this one can tell the Indian day from the browser's.
  {
    id: "statutory-values-a-notification-date-is-bounded-by-the-indian-day",
    title: "Settings > Statutory values > Record a notification: at an hour when India is a day ahead of the browser the notification date is bounded by India's day",
    contexts: TZ_MATRIX,
    async run(env) {
      const { page, context, stub } = env;
      await context.clock.setFixedTime(new Date("2026-10-08T20:00:00Z"));
      await openStatutoryValues(env);
      await typeAndLeave(page.locator("#sv-effective-from"), "01/04/2027");
      await typeAndLeave(page.locator("#sv-notified-on"), "10/10/2026");
      const record = page.getByRole("button", { name: "Record", exact: true });
      await record.click();
      await shownInTheDialog(page, "Notification date: 10 Oct 2026 is after 09 Oct 2026.", "a day after India's today was not refused in a sentence");
      await stub.quiet();
      assert.equal(stub.writesTo(/statutory-values\/pt$/).length, 0, "a notification date after India's today SENT A WRITE");
      await typeAndLeave(page.locator("#sv-notified-on"), "09/10/2026");
      await record.click();
      await stub.quiet();
      const sent = stub.writesTo(/statutory-values\/pt$/);
      assert.equal(sent.length, 1, `India's today was refused or not sent: ${sent.length} writes`);
      assert.equal(JSON.parse(sent[0].body).notification_date, "2026-10-09");
    },
  },
  // While a Record is out the dialog cannot be left: Close and Cancel are held, so a late answer cannot act on a dialog the person has already left, and they are live again after a refusal.
  {
    id: "statutory-values-close-and-cancel-are-held-while-a-record-is-out",
    title: "Settings > Statutory values > Record a notification: while a Record is out Close and Cancel are held, and live again once the answer is a refusal",
    async run(env) {
      const { page, stub } = env;
      await openStatutoryValues(env);
      await typeAndLeave(page.locator("#sv-effective-from"), "01/04/2026");
      await typeAndLeave(page.locator("#sv-notified-on"), "10/03/2026");
      stub.route({ method: "PUT", re: /api\/payroll\/statutory-values\/pt$/, delay: 1800, ...refuse(PT_UNCOVERED_SENTENCE, 422) });
      const dialog = statutoryDialog(page);
      await dialog.getByRole("button", { name: "Record", exact: true }).click();
      const close = dialog.getByRole("button", { name: "Close", exact: true });
      const cancel = dialog.getByRole("button", { name: "Cancel", exact: true });
      await until(async () => (await close.isDisabled({ timeout: 500 }).catch(() => false)) && (await cancel.isDisabled({ timeout: 500 }).catch(() => false)),
        "Close and Cancel to be held while the Record was out");
      await shownInTheDialog(page, PT_UNCOVERED_SENTENCE, "the refusal was not shown once the answer came");
      assert.equal(await close.isDisabled(), false, "Close stayed held after the answer");
      assert.equal(await cancel.isDisabled(), false, "Cancel stayed held after the answer");
    },
  },
  // A dialog opened again after a refusal holds nothing of the last one: not its boxes and not its sentence.
  {
    id: "statutory-values-the-form-is-opened-afresh-after-a-refusal",
    title: "Settings > Statutory values > Record a notification: opened again after a refusal and a Cancel it holds none of the last record and none of its sentence",
    async run(env) {
      const { page } = env;
      await openStatutoryValues(env);
      const dialog = statutoryDialog(page);
      await page.getByLabel("State code", { exact: true }).fill("G");
      await dialog.getByRole("button", { name: "Record", exact: true }).click();
      await shownInTheDialog(page, PT_STATE_CODE_SENTENCE, "a state code that is not two letters was not refused inside the dialog");
      await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
      await dialog.waitFor({ state: "detached", timeout: 4000 }).catch(() => { throw new Error("Cancel did not close the dialog"); });
      await page.getByRole("button", { name: "Record a notification" }).click();
      await statutoryDialog(page).waitFor();
      assert.equal(await page.getByLabel("State code", { exact: true }).inputValue(), "", "the dialog was opened with the last record's state code");
      assert.equal(await page.getByLabel("Notification reference", { exact: true }).inputValue(), "", "the dialog was opened with the last record's reference");
      assert.equal(await page.getByText(PT_STATE_CODE_SENTENCE).count(), 0, "the dialog was opened again with the last refusal still on it");
    },
  },
  // The overlay keeps a pointer off the button behind it and not the keyboard: Enter on it ran the opener, which empties the form, in the middle of whatever was typed or sent.
  {
    id: "statutory-values-the-open-button-does-nothing-while-the-form-is-open",
    title: "Settings > Statutory values > Record a notification: Enter on the open button behind the dialog does not empty what was typed",
    async run(env) {
      const { page } = env;
      await openStatutoryValues(env);
      await page.getByRole("button", { name: "Record a notification" }).focus();
      await page.keyboard.press("Enter");
      await page.waitForTimeout(300);
      assert.equal(await page.getByLabel("State code", { exact: true }).inputValue(), "GJ", "Enter on the open button behind the dialog emptied the state code");
      assert.equal(await page.getByLabel("Notification reference", { exact: true }).inputValue(), "PFT/2026/12", "Enter on the open button behind the dialog emptied the reference");
    },
  },
  // A letter that lapses before it starts is nonsense: the box hinted at it (`notBefore`) and the form sent it. The sentence is true only while the two boxes are out of order.
  {
    id: "new-engagement-letter-an-expiry-before-the-start-is-refused",
    title: "Engagements > New Engagement: an expiry date before the start date is refused in a sentence and nothing is sent, and the sentence goes when the dates are in order",
    contexts: TZ_MATRIX,
    async run(env) {
      const { page, stub } = env;
      await openNewEngagementLetter(env);
      const dialog = engagementDialog(page);
      await typeAndLeave(dialog.getByLabel("Start date", { exact: true }), "01/04/2026");
      await typeAndLeave(dialog.getByLabel("Expiry date", { exact: true }), "01/03/2026");
      await dialog.getByRole("button", { name: "Create Engagement", exact: true }).click();
      await shownInTheDialog(page, ENGAGEMENT_ORDER_SENTENCE, "an expiry date before the start date was not refused in a sentence");
      await stub.quiet();
      assert.equal(stub.writesTo(/api\/engagement-letters$/).length, 0, "an expiry date before the start date SENT A WRITE");
      await typeAndLeave(dialog.getByLabel("Expiry date", { exact: true }), "31/03/2027");
      await page.waitForTimeout(300);
      assert.equal(await page.getByText(ENGAGEMENT_ORDER_SENTENCE).count(), 0, "the refusal stayed in the dialog after the dates were put in order");
      await dialog.getByRole("button", { name: "Create Engagement", exact: true }).click();
      await stub.quiet();
      assert.equal(stub.writesTo(/api\/engagement-letters$/).length, 1, "the letter was not sent once the dates were in order");
    },
  },
  // An end is read after its start: `15/6` beside a start of 01/03/2026 is 15/06/2026 and not 15/06/2025.
  {
    id: "new-engagement-letter-a-short-expiry-is-read-after-the-start",
    title: "Engagements > New Engagement: a short expiry date typed beside a start in March is read in the year after it, not before",
    contexts: TZ_MATRIX,
    async run(env) {
      const { page, stub } = env;
      await openNewEngagementLetter(env);
      const dialog = engagementDialog(page);
      await typeAndLeave(dialog.getByLabel("Start date", { exact: true }), "01/03/2026");
      await typeAndLeave(dialog.getByLabel("Expiry date", { exact: true }), "15/6");
      assert.equal(await dialog.getByLabel("Expiry date", { exact: true }).inputValue(), "15/06/2026", "15/6 beside a start of 01/03/2026 should be read as 15/06/2026");
      await dialog.getByRole("button", { name: "Create Engagement", exact: true }).click();
      await stub.quiet();
      const sent = stub.writesTo(/api\/engagement-letters$/);
      assert.equal(sent.length, 1, `expected one write, saw ${sent.length}`);
      assert.equal(JSON.parse(sent[0].body).expiry_date, "2026-06-15");
    },
  },
  // While a Create is out the dialog cannot be left: Close and Cancel are held, and live again after a refusal.
  {
    id: "new-engagement-letter-close-and-cancel-are-held-while-a-create-is-out",
    title: "Engagements > New Engagement: while a Create is out Close and Cancel are held, and live again once the answer is a refusal",
    async run(env) {
      const { page, stub } = env;
      await openNewEngagementLetter(env);
      const dialog = engagementDialog(page);
      stub.route({ method: "POST", re: /api\/engagement-letters$/, delay: 1800, ...refuse("A stub refusal of the letter.", 422) });
      await dialog.getByRole("button", { name: "Create Engagement", exact: true }).click();
      const close = dialog.getByRole("button", { name: "Close", exact: true });
      const cancel = dialog.getByRole("button", { name: "Cancel", exact: true });
      await until(async () => (await close.isDisabled({ timeout: 500 }).catch(() => false)) && (await cancel.isDisabled({ timeout: 500 }).catch(() => false)),
        "Close and Cancel to be held while the Create was out");
      await shownInTheDialog(page, "A stub refusal of the letter.", "the refusal was not shown once the answer came");
      assert.equal(await close.isDisabled(), false, "Close stayed held after the answer");
      assert.equal(await cancel.isDisabled(), false, "Cancel stayed held after the answer");
    },
  },
  // A dialog opened again after a refusal holds nothing of the last one, whether the sentence came from the boxes (the order of the two dates) or from the server.
  {
    id: "new-engagement-letter-is-opened-afresh-after-a-refusal",
    title: "Engagements > New Engagement: opened again after a refusal and a Cancel it holds none of the last letter and none of its sentence",
    async run(env) {
      const { page, stub } = env;
      await openNewEngagementLetter(env);
      let dialog = engagementDialog(page);
      const reopen = async () => {
        await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
        await dialog.waitFor({ state: "detached", timeout: 4000 }).catch(() => { throw new Error("Cancel did not close the dialog"); });
        await page.getByRole("button", { name: "New Engagement" }).first().click();
        dialog = engagementDialog(page);
        await dialog.waitFor();
      };
      // …a sentence from the server,
      stub.route({ method: "POST", re: /api\/engagement-letters$/, ...refuse("A stub refusal of the letter.", 422) });
      await dialog.getByRole("button", { name: "Create Engagement", exact: true }).click();
      await shownInTheDialog(page, "A stub refusal of the letter.", "the server's refusal was not shown");
      await reopen();
      assert.equal(await page.getByText("A stub refusal of the letter.").count(), 0, "the dialog was opened again with the server's last refusal still on it");
      assert.equal(await dialog.getByLabel("Title", { exact: true }).inputValue(), "", "the dialog was opened with the last letter's title");
      // …and one from the boxes.
      await dialog.getByLabel("Title", { exact: true }).fill("Another letter");
      await typeAndLeave(dialog.getByLabel("Start date", { exact: true }), "01/04/2026");
      await typeAndLeave(dialog.getByLabel("Expiry date", { exact: true }), "01/03/2026");
      await dialog.getByRole("button", { name: "Create Engagement", exact: true }).click();
      await shownInTheDialog(page, ENGAGEMENT_ORDER_SENTENCE, "the order of the dates was not refused");
      await reopen();
      assert.equal(await page.getByText(ENGAGEMENT_ORDER_SENTENCE).count(), 0, "the dialog was opened again with the last order refusal still on it");
      assert.equal(await dialog.getByLabel("Start date", { exact: true }).inputValue(), "", "the dialog was opened with the last letter's start date");
      assert.equal(await dialog.getByLabel("Expiry date", { exact: true }).inputValue(), "", "the dialog was opened with the last letter's expiry date");
    },
  },
  // The card scrolls when the window is short, and the sentence is at its top while the button that raised it is at the bottom: it must be brought into view, or pressing Create
  // looks like a button that does nothing. 440 px is a laptop screen at about 150% zoom; at 520 the same card scrolls less than the sentence's height and the sentence stays in view
  // by luck, so the window is shorter than that on purpose.
  {
    id: "new-engagement-letter-a-refusal-is-in-view-at-a-short-window",
    title: "Engagements > New Engagement: at a short window the refusal raised by Create is in view, not above the fold of the scrolled card",
    async run(env) {
      const { page } = env;
      await page.setViewportSize({ width: 1440, height: 440 });
      await openNewEngagementLetter(env);
      const dialog = engagementDialog(page);
      await typeAndLeave(dialog.getByLabel("Start date", { exact: true }), "01/04/2026");
      await typeAndLeave(dialog.getByLabel("Expiry date", { exact: true }), "01/03/2026");
      await dialog.getByRole("button", { name: "Create Engagement", exact: true }).click();
      const sentence = page.getByText(ENGAGEMENT_ORDER_SENTENCE).first();
      await sentence.waitFor({ timeout: 4000 });
      await page.waitForTimeout(400);
      const seen = await sentence.evaluate((el) => {
        const r = el.getBoundingClientRect();
        let top = 0, bottom = window.innerHeight;
        for (let p = el.parentElement; p; p = p.parentElement) {
          const s = getComputedStyle(p);
          if (/(auto|scroll)/.test(s.overflowY) && p.scrollHeight > p.clientHeight) { const pr = p.getBoundingClientRect(); top = Math.max(top, pr.top); bottom = Math.min(bottom, pr.bottom); }
          if (s.position === "fixed") break; // a fixed overlay is not clipped by the scrolling ancestors of the place it was rendered
        }
        return { ok: r.top >= top - 1 && r.bottom <= bottom + 1, top: Math.round(r.top), bottom: Math.round(r.bottom), from: Math.round(top), to: Math.round(bottom) };
      });
      assert.ok(seen.ok, `the refusal is drawn outside what the person can see (sentence ${seen.top}-${seen.bottom}, visible ${seen.from}-${seen.to})`);
    },
  },
  // The page words a refusal through the one helper every screen that calls fetch itself is meant to use: a validation error's detail is a LIST of {loc, msg}, which this page's own
  // reading put on screen as "[object Object]".
  {
    id: "new-engagement-letter-a-validation-list-from-the-server-is-said-as-a-sentence",
    title: "Engagements > New Engagement: a 422 whose detail is a list of validation messages is said as their sentence, not as [object Object]",
    async run(env) {
      const { page, stub } = env;
      await openNewEngagementLetter(env);
      const dialog = engagementDialog(page);
      stub.route({ method: "POST", re: /api\/engagement-letters$/, ...refuse([{ type: "value_error", loc: ["body"], msg: "Value error, The expiry date cannot be before the start date.", input: {} }], 422) });
      await dialog.getByRole("button", { name: "Create Engagement", exact: true }).click();
      await shownInTheDialog(page, "Value error, The expiry date cannot be before the start date.", "a validation list from the server was not said as its sentence");
      assert.equal(await page.getByText("[object Object]").count(), 0, "a validation list was put on screen as [object Object]");
    },
  },
  // A lot is made before it is recorded, and it cannot lapse before it was made.
  {
    id: "stock-lot-a-manufacture-date-after-today-and-an-expiry-before-it-are-refused",
    title: "Inventory > Locations > New lot: a manufacture date after today and an expiry before the manufacture date are refused in a sentence and nothing is sent, and each sentence goes when the date is right",
    contexts: TZ_MATRIX,
    async run(env) {
      const { page, stub } = env;
      await openStockLocations("lot")(env);
      const made = page.getByLabel("Manufactured (optional)");
      const expires = page.getByLabel("Expires (optional)");
      const create = lotDialog(page).getByRole("button", { name: "Create", exact: true });
      await typeAndLeave(made, "15/10/2026");
      await create.click();
      await shownInTheDialog(page, `Manufactured: ${AFTER_TODAY_SENTENCE}`, "a lot made after today was not refused in a sentence");
      // …and the sentence is withdrawn the moment the date is right (it was a copy in the form's error that stayed after the fix).
      await typeAndLeave(made, "01/09/2026");
      await page.waitForTimeout(300);
      assert.equal(await page.getByText(`Manufactured: ${AFTER_TODAY_SENTENCE}`).count(), 0, "the refusal stayed in the dialog after the date was put right");
      await typeAndLeave(expires, "01/08/2026");
      await create.click();
      await shownInTheDialog(page, LOT_ORDER_SENTENCE, "a lot that expires before it was made was not refused in a sentence");
      await stub.quiet();
      assert.equal(stub.writesTo(/api\/inventory\/batches$/).length, 0, "a lot with dates out of order SENT A WRITE");
      await typeAndLeave(expires, "31/08/2028");
      await page.waitForTimeout(300);
      assert.equal(await page.getByText(LOT_ORDER_SENTENCE).count(), 0, "the order refusal stayed in the dialog after the dates were put in order");
    },
  },
  // An end is read after its start.
  {
    id: "stock-lot-a-short-expiry-is-read-after-the-manufacture-date",
    title: "Inventory > Locations > New lot: a short expiry date typed beside a manufacture date in March is read in the year after it, not before",
    contexts: TZ_MATRIX,
    async run(env) {
      const { page, stub } = env;
      await openStockLocations("lot")(env);
      const made = page.getByLabel("Manufactured (optional)");
      const expires = page.getByLabel("Expires (optional)");
      await typeAndLeave(made, "01/03/2026");
      await typeAndLeave(expires, "15/6");
      assert.equal(await expires.inputValue(), "15/06/2026", "15/6 beside a manufacture date of 01/03/2026 should be read as 15/06/2026");
      await lotDialog(page).getByRole("button", { name: "Create", exact: true }).click();
      await stub.quiet();
      const sent = stub.writesTo(/api\/inventory\/batches$/);
      assert.equal(sent.length, 1, `expected one write, saw ${sent.length}`);
      assert.equal(JSON.parse(sent[0].body).expiry_date, "2026-06-15");
    },
  },
  // A lot is made on a day that has come in INDIA: at 20:00 UTC on 8 October it is already 9 October there.
  {
    id: "stock-lot-a-manufacture-date-is-bounded-by-the-indian-day",
    title: "Inventory > Locations > New lot: at an hour when India is a day ahead of the browser the manufacture date is bounded by India's day",
    contexts: TZ_MATRIX,
    async run(env) {
      const { page, context, stub } = env;
      await context.clock.setFixedTime(new Date("2026-10-08T20:00:00Z"));
      await openStockLocations("lot")(env);
      const made = page.getByLabel("Manufactured (optional)");
      const create = lotDialog(page).getByRole("button", { name: "Create", exact: true });
      await typeAndLeave(made, "10/10/2026");
      await create.click();
      await shownInTheDialog(page, "Manufactured: 10 Oct 2026 is after 09 Oct 2026.", "a day after India's today was not refused in a sentence");
      await stub.quiet();
      assert.equal(stub.writesTo(/api\/inventory\/batches$/).length, 0, "a manufacture date after India's today SENT A WRITE");
      await typeAndLeave(made, "09/10/2026");
      await create.click();
      await stub.quiet();
      const sent = stub.writesTo(/api\/inventory\/batches$/);
      assert.equal(sent.length, 1, `India's today was refused or not sent: ${sent.length} writes`);
      assert.equal(JSON.parse(sent[0].body).manufactured_on, "2026-10-09");
    },
  },
  // While a lot is being created Cancel is held: a late answer must not act on a dialog the person has already left (a lot created behind a Cancel).
  {
    id: "stock-lot-cancel-is-held-while-the-lot-is-being-created",
    title: "Inventory > Locations > New lot: while a Create is out Cancel is held, and the dialog closes when the answer comes",
    async run(env) {
      const { page, stub } = env;
      await openStockLocations("lot")(env);
      stub.route({ method: "POST", re: /api\/inventory\/batches$/, delay: 1800, reply: () => ok({ id: "b-1" }) });
      const dialog = lotDialog(page);
      await dialog.getByRole("button", { name: "Create", exact: true }).click();
      const cancel = dialog.getByRole("button", { name: "Cancel", exact: true });
      await until(async () => await cancel.isDisabled({ timeout: 500 }).catch(() => false), "Cancel to be held while the Create was out");
      await dialog.waitFor({ state: "detached", timeout: 6000 }).catch(() => { throw new Error("the dialog stayed open after the lot was created"); });
      await stub.quiet();
      assert.equal(stub.writesTo(/api\/inventory\/batches$/).length, 1, "expected exactly one lot to be sent");
    },
  },
  // The same for a godown, which sits on the same screen.
  {
    id: "stock-godown-cancel-is-held-while-the-godown-is-being-created",
    title: "Inventory > Locations > New godown: while a Create is out Cancel is held, and the dialog closes when the answer comes",
    async run(env) {
      const { page, stub } = env;
      await openStockLocations("transfer")(env);
      stub.route({ method: "POST", re: /api\/inventory\/godowns$/, delay: 1800, reply: () => ok({ id: "g3" }) });
      await page.getByRole("button", { name: /Add godown/ }).first().click();
      const dialog = page.locator("div.fixed").filter({ has: page.getByRole("heading", { name: "New godown" }) });
      await dialog.waitFor();
      await dialog.locator("input").first().fill("Annexe");
      await dialog.getByRole("button", { name: "Create", exact: true }).click();
      const cancel = dialog.getByRole("button", { name: "Cancel", exact: true });
      await until(async () => await cancel.isDisabled({ timeout: 500 }).catch(() => false), "Cancel to be held while the Create was out");
      await dialog.waitFor({ state: "detached", timeout: 6000 }).catch(() => { throw new Error("the dialog stayed open after the godown was created"); });
      await stub.quiet();
      assert.equal(stub.writesTo(/api\/inventory\/godowns$/).length, 1, "expected exactly one godown to be sent");
    },
  },
  // The Move stock panel defaulted its date to today and let the person clear it: a blank date went to the server as "", which answered in pydantic's words. The date box is found by
  // the word above it here, so the previous product (which left it unnamed) fails on the behaviour and not on a name.
  {
    id: "stock-transfer-a-cleared-date-is-asked-for-and-nothing-is-sent",
    title: "Inventory > Locations > Move stock: with the date cleared the panel asks for it in a sentence and sends nothing, and the sentence goes when a date is typed",
    contexts: TZ_MATRIX,
    async run(env) {
      const { page, stub } = env;
      await openStockLocations("transfer")(env);
      await typeAndLeave(transferDateBox(page), "");
      await page.getByRole("button", { name: "Move stock", exact: true }).click();
      await shownInTheDialog(page, "Date: enter the date the stock moved.", "a cleared date was not asked for in a sentence");
      await stub.quiet();
      assert.equal(stub.writesTo(/api\/inventory\/transfer$/).length, 0, "a cleared date SENT A WRITE");
      await typeAndLeave(transferDateBox(page), "05/10/2026");
      await page.waitForTimeout(300);
      assert.equal(await page.getByText("Date: enter the date the stock moved.").count(), 0, "the sentence stayed on the panel after a date was typed");
    },
  },
  // A date that is not a day is refused in its own sentence once a Move was tried, and the sentence goes the moment the date is put right.
  {
    id: "stock-transfer-an-unreadable-date-is-refused-and-the-sentence-goes-when-it-is-put-right",
    title: "Inventory > Locations > Move stock: an unreadable date is refused in a sentence and nothing is sent, and the sentence is withdrawn when the date is right",
    contexts: TZ_MATRIX,
    async run(env) {
      const { page, stub } = env;
      await openStockLocations("transfer")(env);
      await typeAndLeave(transferDateBox(page), "31/02/2026");
      await page.getByRole("button", { name: "Move stock", exact: true }).click();
      await shownInTheDialog(page, `Date: ${FEB_SENTENCE}`, "a date that is not a day was not refused in a sentence");
      await stub.quiet();
      assert.equal(stub.writesTo(/api\/inventory\/transfer$/).length, 0, "a date that is not a day SENT A WRITE");
      await typeAndLeave(transferDateBox(page), "05/10/2026");
      await page.waitForTimeout(300);
      assert.equal(await page.getByText(`Date: ${FEB_SENTENCE}`).count(), 0, "the refusal stayed on the panel after the date was put right");
    },
  },
  // A quantity the server cannot read ("1,500", "5 kg") raised inside the service and came back as a generic failure naming nothing.
  {
    id: "stock-transfer-a-quantity-that-is-not-a-number-is-refused-and-nothing-is-sent",
    title: "Inventory > Locations > Move stock: a quantity that is not a number is refused in a sentence and nothing is sent, and a number is sent as typed",
    async run(env) {
      const { page, stub } = env;
      await openStockLocations("transfer")(env);
      const quantity = transferPanel(page).locator("input[inputmode=decimal]");
      await quantity.fill("1,500");
      await page.getByRole("button", { name: "Move stock", exact: true }).click();
      await shownInTheDialog(page, TRANSFER_QUANTITY_SENTENCE, "a quantity with a comma was not refused in a sentence");
      await stub.quiet();
      assert.equal(stub.writesTo(/api\/inventory\/transfer$/).length, 0, "a quantity that is not a number SENT A WRITE");
      await quantity.fill("1500");
      await page.getByRole("button", { name: "Move stock", exact: true }).click();
      await stub.quiet();
      const sent = stub.writesTo(/api\/inventory\/transfer$/);
      assert.equal(sent.length, 1, `expected one write, saw ${sent.length}`);
      assert.equal(JSON.parse(sent[0].body).quantity, "1500");
    },
  },
];
