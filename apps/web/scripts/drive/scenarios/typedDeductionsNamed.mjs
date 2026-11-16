/**
 * A DEDUCTION TYPED ON THE TDS SCREEN IS NAMED ON THE STATEMENT BUILT FROM THE BOOKS, AND THE YEAR IS NOT CALLED BELOW A THRESHOLD FOR A PAYEE THE SERVER COULD NOT LOOK UP (POST-A-078).
 *
 * The 26Q built from the books reads posted purchase bills and withholding advances only, so a deduction a CA typed on the TDS screen is not on it, and the two return
 * screens said nothing: a statement that is silent about the register's tax reads as a complete one. The server names them now (`excluded_typed`) and the screens draw what
 * it said: how many, the tax they withheld, its own sentence, and (folded away) which they are. Nothing is added to the statement. Here, on the client's TDS tab and on the
 * firm-level page, at 1280 px and at 440: the note is drawn from a whole answer, it is not drawn when nothing is left out or when the key is absent, an answer that is there
 * and cannot be read is SAID to be unreadable (silence would read as "none"), the list is drawn only when it is whole, and the box that holds it can be reached from the
 * keyboard with the tax column in view.
 *
 * And the typed form's sentence "…and with the payments already typed for this payee in the year it is below the section's yearly threshold too" is a statement about what the
 * server ADDED UP, so it is said only when the server says it did (`aggregate_tested`): a payee with no usable PAN has no key to be looked up by, a section with no yearly
 * threshold (s.194I) has nothing to add the year up against, and a server that sends no key is not a server that did. And the form shows nothing of a quote that has just been
 * typed over.
 *
 * The sentences the server speaks are its words, word for word, and a test compares them (tests/test_a_typed_tds_deduction_is_named_on_the_statement_built_from_the_books_and_a_payee_without_a_pan_is_never_pooled.py).
 * No scenario has a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { until, pick } from "../kit.mjs";
import { ok } from "../stub.mjs";
import { openTdsDeductionForm } from "../flows.mjs";

export const group = "typed-deductions-named";

/** services/tds_return_service.EXCLUDED_TYPED_REASON. */
const TYPED_REASON = "A statement built from the books carries posted purchase bills and advances only, so deductions typed on the TDS screen are not in its totals. Key them from the register when you key the statement: tax withheld on a typed deduction is still owed on the statement, and a typed deduction counted in a supplier's year was taken into the tax worked out on that supplier's later bills.";

const ROW_ONE = { id: "t1", deductee_name: "Acme Services", deductee_pan: "AAACA1234A", section: "194J", section_1961: "194J", transaction_date: "2025-10-12", payment_amount_paise: 10000000, tds_paise: 1000000 };
const ROW_TWO = { id: "t2", deductee_name: "Late Co", deductee_pan: null, section: "393(1)", section_1961: "194H", transaction_date: "2025-12-05", payment_amount_paise: 4000000, tds_paise: 80000 };
const TYPED = { count: 2, payment_paise: 14000000, tds_paise: 1080000, reason: TYPED_REASON, deductions: [ROW_ONE, ROW_TWO] };

/** The statement's own figures: the books' tax, deliberately NOT the typed deductions' (₹10,000.00 against ₹10,800.00), so a sum of the two would be visible. */
const STATEMENT = {
  form: "26Q", tan: "MUMA12345B", deductor_name: "Acme Traders Pvt Ltd", quarter_end_date: "2025-12-31",
  total_tds_deducted_paise: 1000000, total_tds_deposited_paise: 1000000, deductee_count: 1, deductees: [], challans: [], validation_errors: [], warnings: [], challan_gaps: [],
  reconciliation: { matched: true, account_found: true, books_paise: 1000000, ledger_paise: 1000000, difference_paise: 0 },
};

const LEAD = (count, tax) => `${count} deduction${count === 1 ? "" : "s"} typed on the TDS screen for this quarter, with ${tax} of tax withheld, ${count === 1 ? "is" : "are"} not on this statement.`;
const squash = (s) => s.replace(/\s+/g, " ").trim();
const UNREADABLE = "The note of the deductions typed on the TDS screen for this quarter could not be read from the server's answer, so this statement does not say whether it leaves any out.";

/** The note's paragraph, found by what it says it is and not by where it sits. */
const noteParagraph = (page) => page.locator("p").filter({ hasText: /typed on the TDS screen for this quarter, with/ });
const unreadableLine = (page) => page.locator("p").filter({ hasText: /could not be read from the server's answer/ });
const listBox = (page) => page.getByRole("region", { name: /Deductions typed on the TDS screen that are not on this statement/ });
const sidewaysOverflow = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

// ── the client's TDS tab ─────────────────────────────────────────────────────

async function computeOnTheClientsTab(env, answer) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { tds: ["read", "write", "compute", "approve"] } }) });
  stub.route({ method: "GET", re: /api\/tds-workspace\/returns\?/, reply: () => ok({ returns: [], has_more: false, limit: 200, max_limit: 200 }) });
  stub.route({ method: "POST", re: /api\/tds\/26q\/from-books$/, reply: (_req, raw) => ok({ ...STATEMENT, financial_year: JSON.parse(raw).financial_year, quarter: JSON.parse(raw).quarter, ...answer }) });
  await page.goto(env.at("/compliance/tds/"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Returns", exact: true }).click();
  await page.getByRole("heading", { name: "TDS Returns", exact: true }).waitFor();
  await page.getByRole("button", { name: "Compute from Books", exact: true }).first().click();
  await page.getByLabel("Financial year (for example 2025-26)", { exact: true }).fill("2025-26");
  await page.getByLabel("TAN (10 characters)", { exact: true }).fill("MUMA12345B");
  await page.getByLabel("Deductor name", { exact: true }).fill("Acme Traders Pvt Ltd");
  await page.getByLabel("Deductor PAN", { exact: true }).fill("AAACA1234A");
  await page.getByRole("button", { name: "Compute", exact: true }).click();
  await page.getByRole("button", { name: "Save as Draft", exact: true }).waitFor({ timeout: 4000 });
}

/** The statement again, with another answer for `excluded_typed` (or none). */
async function computeAgain(env, extra) {
  const { page, stub } = env;
  stub.route({ method: "POST", re: /api\/tds\/26q\/from-books$/, reply: (_req, raw) => ok({ ...STATEMENT, financial_year: JSON.parse(raw).financial_year, quarter: JSON.parse(raw).quarter, ...extra }) });
  await page.getByRole("button", { name: "Compute", exact: true }).click();
  await page.getByRole("button", { name: "Save as Draft", exact: true }).waitFor({ timeout: 4000 });
  await stub.quiet();
}

async function assertTheNoteIsWhole(page, where) {
  const note = noteParagraph(page);
  await note.first().waitFor({ timeout: 4000 });
  assert.equal(await note.count(), 1, `${where}: the note was drawn ${await note.count()} times`);
  assert.equal(squash(await note.innerText()), `${LEAD(2, "₹10,800.00")} ${TYPED_REASON}`, `${where}: the note is not the count, the tax and the server's sentence`);
  // the list is folded away until asked for
  const details = page.locator("details").filter({ hasText: "Show the 2 deductions" });
  assert.equal(await details.count(), 1, `${where}: no folded list`);
  assert.equal(await details.evaluate((d) => d.open), false, `${where}: the list was open before it was asked for`);
  assert.equal(await listBox(page).isVisible(), false, `${where}: the rows were showing before they were asked for`);
  const overflowBefore = await sidewaysOverflow(page);
  await details.locator("summary").click();
  const box = listBox(page);
  await box.waitFor({ timeout: 4000 });
  const table = box.getByRole("table", { name: /not on this statement/ });
  const rows = table.locator("tbody tr");
  assert.equal(await rows.count(), 2, `${where}: expected the two rows`);
  const cells = async (row) => (await row.locator("td").allInnerTexts()).map(squash);
  // columns: date, payee, tax withheld, payment, section (with the stored key beside a label that differs), PAN (— for none recorded)
  assert.deepEqual(await cells(rows.nth(0)), ["12 Oct 2025", "Acme Services", "₹10,000.00", "₹1,00,000.00", "194J", "AAACA1234A"], `${where}: row one`);
  assert.deepEqual(await cells(rows.nth(1)), ["05 Dec 2025", "Late Co", "₹800.00", "₹40,000.00", "393(1) (194H)", "—"], `${where}: row two`);
  // nothing was added to the statement: the books' tax is the statement's, and no sum of the two is drawn anywhere
  assert.equal(await page.getByText("₹20,800.00").count(), 0, `${where}: the typed tax was added to the statement's total`);
  assert.equal(await page.getByText("₹10,800.00", { exact: true }).count(), 1, `${where}: the typed tax appears outside the note, or not once`);
  // the box that holds the list is reachable from the keyboard, and opening the list does not push the page out sideways
  assert.equal(await box.getAttribute("tabindex"), "0", `${where}: the list's scroll box cannot take focus`);
  await box.focus();
  assert.equal(await box.evaluate((el) => el === document.activeElement), true, `${where}: the list's scroll box did not take focus`);
  assert.ok((await sidewaysOverflow(page)) <= overflowBefore, `${where}: opening the list pushed the page out sideways (${overflowBefore} -> ${await sidewaysOverflow(page)}px)`);
  return { box, table };
}

/** On a narrow screen the tax withheld, which is what the note is about, is in view without scrolling the box. */
async function assertTheTaxIsInView(box, table, where) {
  const taxHeader = await table.getByRole("columnheader", { name: "Tax withheld" }).boundingBox();
  const boxEdge = await box.evaluate((el) => el.getBoundingClientRect().right);
  assert.ok(taxHeader.x + taxHeader.width <= boxEdge + 1, `${where}: the Tax withheld column is off the right of its box (${Math.round(taxHeader.x + taxHeader.width)} > ${Math.round(boxEdge)}px)`);
  const overflowX = await box.evaluate((el) => getComputedStyle(el).overflowX);
  assert.equal(overflowX, "auto", `${where}: the list's box does not scroll sideways, so a wide table would push the page out`);
}

const clientTabNames = {
  id: "a-26q-built-from-the-books-names-the-deductions-typed-on-the-tds-screen",
  title: "A client's TDS > Returns > Compute from Books: the typed deductions are named with their count, tax and the server's sentence, the rows are folded away until asked for, nothing is added to the statement, an answer that cannot be read is said so, and nothing is drawn for none or no key",
  async run(env) {
    const { page } = env;
    await computeOnTheClientsTab(env, { excluded_typed: TYPED });
    await assertTheNoteIsWhole(page, "a client's TDS tab");

    // one deduction: the singular, and the heading of the list
    await computeAgain(env, { excluded_typed: { ...TYPED, count: 1, payment_paise: 10000000, tds_paise: 1000000, deductions: [ROW_ONE] } });
    assert.equal(squash(await noteParagraph(page).innerText()), `${LEAD(1, "₹10,000.00")} ${TYPED_REASON}`, "one deduction is not written in the singular");
    assert.equal(await page.locator("details").filter({ hasText: "Show the deduction" }).count(), 1, "the singular list has no heading");

    // a list that is not whole is not drawn, and the count and the tax still are
    for (const [why, deductions] of [["fewer rows than the count", [ROW_ONE]], ["a row that cannot be read", [ROW_ONE, { ...ROW_TWO, tds_paise: "80000" }]], ["no rows at all", undefined]]) {
      await computeAgain(env, { excluded_typed: { ...TYPED, deductions } });
      assert.equal(squash(await noteParagraph(page).innerText()), `${LEAD(2, "₹10,800.00")} ${TYPED_REASON}`, `${why}: the count and the tax were not drawn`);
      assert.equal(await page.locator("details").count(), 0, `${why}: a list that is not whole was drawn`);
    }

    // only what the note draws is required: a missing payment total, a blank sentence and a payment total that is text still draw the count and the tax
    for (const [why, extra, sentence] of [
      ["no payment total", { excluded_typed: { count: 2, tds_paise: 1080000, reason: TYPED_REASON, deductions: [ROW_ONE, ROW_TWO] } }, TYPED_REASON],
      ["a payment total that is text", { excluded_typed: { ...TYPED, payment_paise: "14000000" } }, TYPED_REASON],
      ["a blank sentence", { excluded_typed: { ...TYPED, reason: "" } }, ""],
      ["no sentence", { excluded_typed: { count: 2, tds_paise: 1080000, deductions: [ROW_ONE, ROW_TWO] } }, ""],
    ]) {
      await computeAgain(env, extra);
      assert.equal(squash(await noteParagraph(page).innerText()), squash(`${LEAD(2, "₹10,800.00")} ${sentence}`), `${why}: the note was not drawn from the figures the server sent`);
      assert.equal(await unreadableLine(page).count(), 0, `${why}: said unreadable though the count and the tax are whole`);
    }

    // nothing left out, and no key (a server that predates it, or a statement that is not a 26Q): silence
    for (const [why, extra] of [
      ["none left out", { excluded_typed: { count: 0, payment_paise: 0, tds_paise: 0, reason: TYPED_REASON, deductions: [] } }],
      ["no key", {}],
      ["a null key", { excluded_typed: null }],
    ]) {
      await computeAgain(env, extra);
      assert.equal(await noteParagraph(page).count(), 0, `${why}: a note was drawn`);
      assert.equal(await unreadableLine(page).count(), 0, `${why}: said unreadable though there is nothing to read`);
      assert.equal(await page.locator("details").count(), 0, `${why}: a list was drawn`);
    }

    // a key that is THERE and cannot be read is said to be unreadable (silence would read as none), and no note is drawn from it
    for (const [why, extra] of [
      ["a count that is not a number", { excluded_typed: { ...TYPED, count: "2" } }],
      ["a tax that is not a number", { excluded_typed: { ...TYPED, tds_paise: "1080000" } }],
      ["no tax", { excluded_typed: { count: 2, reason: TYPED_REASON, deductions: [ROW_ONE, ROW_TWO] } }],
      ["an answer that is not an object", { excluded_typed: "2 deductions" }],
    ]) {
      await computeAgain(env, extra);
      assert.equal(await unreadableLine(page).count(), 1, `${why}: not said to be unreadable`);
      assert.equal(squash(await unreadableLine(page).innerText()), UNREADABLE, `${why}: the unreadable sentence is not the screen's own`);
      assert.equal(await noteParagraph(page).count(), 0, `${why}: a note was drawn from an answer that cannot be read`);
      assert.equal(await page.locator("details").count(), 0, `${why}: a list was drawn`);
    }
  },
};

const clientTabNarrow = {
  id: "a-26q-on-a-clients-tab-keeps-the-typed-deductions-reachable-on-a-narrow-screen",
  title: "A client's TDS > Returns at 440 px: the folded list opens without pushing the page out sideways, its scroll box takes the keyboard, and the Tax withheld column is in view",
  async run(env) {
    const { page } = env;
    await page.setViewportSize({ width: 440, height: 900 });
    await computeOnTheClientsTab(env, { excluded_typed: TYPED });
    const { box, table } = await assertTheNoteIsWhole(page, "a client's TDS tab at 440 px");
    await assertTheTaxIsInView(box, table, "a client's TDS tab at 440 px");
  },
};

// ── the firm-level page, on a phone's width ──────────────────────────────────

const firmPageNames = {
  id: "a-26q-on-the-firm-page-names-the-typed-deductions-and-keeps-them-reachable-on-a-narrow-screen",
  title: "TDS > Returns (firm) at 440 px: the same note, the folded list opens without pushing the page out sideways, its scroll box takes the keyboard, and the Tax withheld column is in view",
  async run(env) {
    const { page, stub } = env;
    await page.setViewportSize({ width: 440, height: 900 });
    stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { tds: ["read", "write", "approve", "compute"] } }) });
    stub.route({ method: "POST", re: /api\/tds\/26q\/from-books$/, reply: (_req, raw) => ok({ ...STATEMENT, financial_year: JSON.parse(raw).financial_year, quarter: JSON.parse(raw).quarter, excluded_typed: TYPED }) });
    stub.route({ method: "POST", re: /api\/tds-workspace\/returns$/, reply: () => ok({ id: "tr-1" }) });
    await page.goto(`${env.base}/tds/returns/`, { waitUntil: "networkidle" });
    await pick(page, page.locator('button[aria-label="Client"]'), "Acme Traders Pvt Ltd");
    await page.getByLabel("Quarter", { exact: true }).selectOption("Q2");
    await page.getByRole("button", { name: "Compute 26Q", exact: true }).click();
    await page.getByRole("button", { name: "CA Approve", exact: true }).waitFor({ timeout: 4000 });
    const { box, table } = await assertTheNoteIsWhole(page, "the firm-level page");
    await assertTheTaxIsInView(box, table, "the firm-level page");
    // and an answer that cannot be read is said on this screen too
    stub.route({ method: "POST", re: /api\/tds\/26q\/from-books$/, reply: (_req, raw) => ok({ ...STATEMENT, financial_year: JSON.parse(raw).financial_year, quarter: JSON.parse(raw).quarter, excluded_typed: { ...TYPED, tds_paise: null } }) });
    await page.getByRole("button", { name: "Compute 26Q", exact: true }).click();
    await unreadableLine(page).first().waitFor({ timeout: 4000 });
    assert.equal(squash(await unreadableLine(page).innerText()), UNREADABLE);
    assert.equal(await noteParagraph(page).count(), 0, "the firm-level page drew a note from an answer that cannot be read");
  },
};

// ── the typed form's sentence ────────────────────────────────────────────────

/** domain/tds/manual_register.GAP_MESSAGES, the two a deduction with no supplier can carry (one or the other: with a usable PAN, or with none), in the server's words. */
const GAP_NO_SUPPLIER = "This deduction names no supplier, so its year is added up with the other deductions typed for this PAN that name none, and not with any supplier's purchase bills or advances. Pick the supplier to count it in that supplier's year.";
const GAP_NO_PAN = "No usable PAN is recorded for this payee, so the year's earlier payments to the same payee were not looked for. This payment is charged as if it were the payee's first of the year, and that says nothing about what the year's total is.";

const BELOW = (aggregateTested, { section = "194J", noPan = false } = {}) => ({
  section, payment_amount_paise: 10000000, tds_rate_pct: 0, tds_paise: 0, quarter: "Q1", financial_year: "2026-27",
  explain: {
    applies: false, reason: "below_threshold", rate_pct: 0, tds_paise: 0, rate_basis: noPan
      ? "Charged at the non-individual rate: no PAN is on file to read the payee's type from, so the higher rate applies by default."
      : "Charged at the non-individual rate: PAN 4th character C.",
    fy_prior_taxable_paise: 0, fy_prior_tds_paise: 0, ...(aggregateTested === undefined ? {} : { aggregate_tested: aggregateTested }),
    gaps: noPan ? ["tds_aggregate_not_read_without_a_pan"] : ["tds_deduction_names_no_supplier"],
    gap_messages: noPan ? [GAP_NO_PAN] : [GAP_NO_SUPPLIER],
  },
});

const PREVIEW = /api\/tds-workspace\/deductions\/preview$/;
const CLAIM = /below the section's yearly threshold too/;
const TESTED_SENTENCE = /^Nothing is deducted — this payment is below §\S+'s threshold, and with the payments already typed on this screen for this payee in the year it is below the section's yearly threshold too\.$/;
const TERSE_SENTENCE = /^Nothing is deducted — this payment is below §\S+'s threshold\.$/;

const typedFormSaysWhatWasAddedUp = {
  id: "a-typed-deduction-form-says-the-year-is-below-the-threshold-only-when-the-server-added-it-up",
  title: "TDS > Add Deduction: below the threshold, the form says the year is below the section's yearly threshold too only when the server says it added the year up; for a payee it could not look up, for a section with no yearly threshold and for a server that sends no key it says the payment is below the threshold and nothing more; and a quote that is being replaced explains nothing",
  async run(env) {
    const { page, stub } = env;
    stub.route({ method: "POST", re: PREVIEW, reply: () => ok(BELOW(true)) });
    const form = await openTdsDeductionForm(env);
    await form.locator("#tds-payment-date").fill("15/07/2026");
    await form.locator("#tds-payment-date").press("Tab");
    const nothing = form.locator("p").filter({ hasText: /^\s*Nothing is deducted/ });
    const pan = form.getByLabel("PAN of Party", { exact: true });
    const newQuote = async (reply, panText) => { stub.route({ method: "POST", re: PREVIEW, reply }); await pan.fill(panText); };

    // 1. the server added the year up: said, in what it covers
    await nothing.first().waitFor({ timeout: 4000 });
    assert.match(squash(await nothing.innerText()), TESTED_SENTENCE);

    // 2. the server could not look (no usable PAN): the payment is below the threshold, and the year is NOT called below it; the server's own sentence says why
    await newQuote(() => ok(BELOW(false, { noPan: true })), "PANNOTAVBL");
    await form.getByText(GAP_NO_PAN, { exact: true }).waitFor({ timeout: 4000 });
    assert.match(squash(await nothing.innerText()), TERSE_SENTENCE);
    assert.equal(await form.getByText(/the year's total for this payee has not reached/).count(), 0, "the old claim is still on the form");

    // 3. a server that predates the field says nothing, and nothing is claimed
    await newQuote(() => ok(BELOW(undefined)), "AAACA1234A");
    await until(async () => (await form.getByText(GAP_NO_PAN, { exact: true }).count()) === 0, "the no-PAN sentence to go once the server stopped saying it");
    assert.match(squash(await nothing.innerText()), TERSE_SENTENCE, "a server that sent no key was taken as having added the year up");
    assert.equal(await form.getByText(CLAIM).count(), 0, "the claim was made for a server that sent no key");

    // 4. and back: added up again
    await newQuote(() => ok(BELOW(true)), "AAACB9999B");
    await until(async () => CLAIM.test(await nothing.innerText()), "the claim to come back once the server said it had added the year up");

    // 5. a payee WITH a PAN under a section that has no yearly threshold (s.194I tests a month): the server read the register and compared nothing, so nothing is claimed,
    //    and the payee is not told it has no PAN
    await newQuote(() => ok(BELOW(false, { section: "194I" })), "AAACB9999C");
    await until(async () => !CLAIM.test(await nothing.innerText()), "the claim to go for a section with no yearly threshold");
    assert.match(squash(await nothing.innerText()), TERSE_SENTENCE);
    assert.equal(await form.getByText(GAP_NO_PAN, { exact: true }).count(), 0, "a payee with a PAN was told it has none because its section has no yearly threshold");

    // 6. a quote that is out explains nothing: the answer for the PAN that was just typed over is not shown beside the new one, and the figure is an ellipsis meanwhile
    stub.route({ method: "POST", re: PREVIEW, delay: 1500, reply: () => ok(BELOW(true)) });
    await pan.fill("AAACB9999D");
    await until(async () => (await nothing.count()) === 0, "the explanation of the old quote to go while the new one is out");
    assert.equal(await form.getByText("Charged at the non-individual rate", { exact: false }).count(), 0, "the rate basis of the old quote stayed on the form while the new one was out");
    assert.equal(await form.getByText("…", { exact: true }).count(), 1, "the figure is not an ellipsis while the quote is out");
    await until(async () => CLAIM.test(await nothing.innerText()), "the claim to appear once the new quote has settled");
  },
};

// ── the supplier the payment was made to ─────────────────────────────────────
//
// A deduction that names its supplier is counted in that supplier's year with its purchase bills and advances (POST-A-078). Picking one sends its id, shows its own
// name and PAN in boxes that cannot be typed over, and offers its section; the server's own sentence about the charge replaces this form's two (which describe a
// payee who is not a supplier); a supplier found by the PAN alone is NAMED, so a CA who only typed a PAN knows it was added to a supplier's bills; the reason none was
// found where suppliers hold the PAN is shown; clearing the picker gives the boxes back; and a supplier list that cannot be read is said in words.

const KAPOOR = { id: "v-kapoor", client_id: "c1", name: "Kapoor Associates", gstin: null, pan: "AAKPK1234F", tds_applicable: true, tds_section: "194J", tds_rate_bps: null, credit_days: null, credit_limit_paise: null, is_active: true };
const TARA = { id: "v-tara", client_id: "c1", name: "Tara Traders", gstin: null, pan: null, tds_applicable: true, tds_section: "194C", tds_rate_bps: null, credit_days: null, credit_limit_paise: null, is_active: true };
/** services/vendor_tds.resolve_resident_tds's sentence for a charge on a supplier's year (its shape; the figures are this scenario's). */
const WHY = "§194J at 10% on the year's aggregate of ₹1,20,000, less ₹0 already withheld on earlier bills, advances and deductions typed on the TDS screen (§200).";
/** routers/tds_workspace._supplier_of_the_deduction, for a PAN two active suppliers of the client hold. */
const TWO_HOLD = "2 suppliers of this client hold PAN AAKCT5678G (a supplier registered in more than one state has a record for each), so this payment is not counted in either's year. Pick the supplier to count it in that supplier's year.";

/** What the server answers: for a picked supplier, the bill path's charge; for a PAN one active supplier holds, that supplier named; for a PAN two hold, none and why. */
function supplierAnswer(sent) {
  const base = { payment_amount_paise: sent.payment_amount_paise, quarter: "Q2", financial_year: "2026-27" };
  const explain = { reason: null, rate_basis: "Charged at the individual/HUF rate: PAN 4th character P.", aggregate_tested: true, shortfall_paise: 0, supplier_note: null, gaps: [], gap_messages: [] };
  if (sent.vendor_id === KAPOOR.id) {
    return { ...base, tds_rate_pct: 10, tds_paise: 1200000, explain: { ...explain, applies: true, rate_pct: 10, tds_paise: 1200000, fy_prior_taxable_paise: 2000000, fy_prior_tds_paise: 0, why: WHY, supplier: { id: KAPOOR.id, name: KAPOOR.name } } };
  }
  if (sent.vendor_id === TARA.id) {
    return { ...base, tds_rate_pct: 2, tds_paise: 2000000, explain: { ...explain, applies: true, rate_pct: 2, tds_paise: 2000000, rate_basis: "Charged at the non-individual rate: no PAN is on file to read the payee's type from, so the higher rate applies by default.", fy_prior_taxable_paise: 0, fy_prior_tds_paise: 0, why: "§194C at 2% on ₹10,00,000.", supplier: { id: TARA.id, name: TARA.name }, shortfall_paise: 50000 } };
  }
  if (sent.deductee_pan === KAPOOR.pan) {
    return { ...base, tds_rate_pct: 10, tds_paise: 1200000, explain: { ...explain, applies: true, rate_pct: 10, tds_paise: 1200000, fy_prior_taxable_paise: 2000000, fy_prior_tds_paise: 0, why: WHY, supplier: { id: KAPOOR.id, name: KAPOOR.name } } };
  }
  const note = sent.deductee_pan === "AAKCT5678G" ? TWO_HOLD : null;
  return { ...base, tds_rate_pct: 0, tds_paise: 0, explain: { ...explain, applies: false, reason: "below_threshold", rate_pct: 0, tds_paise: 0, fy_prior_taxable_paise: 0, fy_prior_tds_paise: 0, why: null, supplier: null, supplier_note: note, gaps: ["tds_deduction_names_no_supplier"], gap_messages: [GAP_NO_SUPPLIER] } };
}

const COUNTED = (name, byPan) => `Counted in the year of supplier ${name}${byPan ? ", found by the PAN" : ""}, with its purchase bills and advances.`;

/** The sections the form may record a deduction under, as `GET /api/tds/sections` answers them (only the two these suppliers carry and a third; the form offers a
 *  supplier's own section only when the server lists it as one a deduction may be recorded under). */
const SECTIONS = { fy: "2026-27", sections: [
  { section: "194C", label: "Payments to contractors", vendor_eligible: true },
  { section: "194J", label: "Fees for professional or technical services", vendor_eligible: true },
  { section: "194H", label: "Commission or brokerage", vendor_eligible: true },
] };

async function openWithSuppliers(env, vendorsReply = () => ok([KAPOOR, TARA])) {
  const { stub } = env;
  stub.route({ method: "GET", re: /api\/vendors\/\?/, reply: vendorsReply });
  stub.route({ method: "GET", re: /api\/tds\/sections/, reply: () => ok(SECTIONS) });
  const previews = [];
  stub.route({ method: "POST", re: PREVIEW, reply: (_req, raw) => { const sent = JSON.parse(raw); previews.push(sent); return ok(supplierAnswer(sent)); } });
  const form = await openTdsDeductionForm(env);
  await form.locator("#tds-payment-date").fill("15/08/2026");
  await form.locator("#tds-payment-date").press("Tab");
  return { form, previews };
}

const typedFormNamesItsSupplier = {
  id: "a-typed-deduction-names-the-supplier-it-was-paid-to-and-is-counted-in-its-year",
  title: "TDS > Add Deduction: picking a supplier sends its id, puts its own name and PAN in boxes that cannot be typed over and offers its section, the server's sentence about the supplier's year replaces the form's own, and the deduction is saved with the supplier",
  async run(env) {
    const { page, stub } = env;
    const { form, previews } = await openWithSuppliers(env);
    await pick(page, form.getByRole("button", { name: "Supplier (optional)" }), KAPOOR.name);
    const name = form.getByLabel("Party / Vendor Name", { exact: true });
    const pan = form.getByLabel("PAN of Party", { exact: true });
    await until(async () => (await name.inputValue()) === KAPOOR.name, "the supplier's own name in the name box");
    assert.equal(await pan.inputValue(), KAPOOR.pan, "the supplier's own PAN is not in the PAN box");
    assert.equal(await name.getAttribute("readonly"), "", "the name box can be typed over while a supplier is picked");
    assert.equal(await pan.getAttribute("readonly"), "", "the PAN box can be typed over while a supplier is picked");
    assert.match(await form.getByRole("button", { name: "TDS Section", exact: true }).innerText(), /^\s*194J\b/, "the supplier's section was not offered");

    await form.getByText(COUNTED(KAPOOR.name, false), { exact: true }).waitFor({ timeout: 4000 });
    await form.getByText(WHY, { exact: true }).waitFor();
    assert.ok(previews.some((p) => p.vendor_id === KAPOOR.id), "the preview did not carry the supplier");
    // The form's own two sentences describe a payee who is not a supplier and are not said beside the server's.
    assert.equal(await form.getByText(/already typed on this screen for this payee/).count(), 0);
    assert.equal(await form.getByText(/Charged on the year's aggregate for this payee/).count(), 0);
    assert.equal(await form.getByText(GAP_NO_SUPPLIER, { exact: true }).count(), 0, "the no-supplier sentence was shown for a deduction that names one");

    stub.forgetWrites();
    await form.getByRole("button", { name: "Add Deduction", exact: true }).click();
    await stub.quiet();
    const saved = stub.writesTo(/api\/tds-workspace\/deductions$/, "POST");
    assert.equal(saved.length, 1, `expected one save, saw ${saved.length}`);
    const body = JSON.parse(saved[0].body);
    assert.equal(body.vendor_id, KAPOOR.id, "the deduction was saved without its supplier");
    assert.equal(body.deductee_pan, KAPOOR.pan);
  },
};

const typedFormSaysWhichSupplierItFound = {
  id: "a-typed-deduction-says-which-supplier-its-pan-found-and-why-it-found-none",
  title: "TDS > Add Deduction: with no supplier picked, a PAN one supplier holds is counted in that supplier's year and the form says so; a PAN two suppliers hold says why it was counted in neither; a supplier with no PAN shows an empty, read-only PAN box and a tax the payment cannot cover says how much is left; and clearing the picker gives the boxes back",
  async run(env) {
    const { page } = env;
    const { form, previews } = await openWithSuppliers(env);
    const pan = form.getByLabel("PAN of Party", { exact: true });

    await pan.fill(KAPOOR.pan);
    await form.getByText(COUNTED(KAPOOR.name, true), { exact: true }).waitFor({ timeout: 4000 });
    assert.ok(previews.every((p) => !p.vendor_id), "a supplier id was sent although none was picked");

    await pan.fill("AAKCT5678G");
    await form.getByText(TWO_HOLD, { exact: true }).waitFor({ timeout: 4000 });
    assert.equal(await form.getByText(/^Counted in the year of supplier/).count(), 0, "a supplier was named for a PAN two suppliers hold");
    await form.getByText(GAP_NO_SUPPLIER, { exact: true }).waitFor();

    await pick(page, form.getByRole("button", { name: "Supplier (optional)" }), TARA.name);
    await form.getByText(COUNTED(TARA.name, false), { exact: true }).waitFor({ timeout: 4000 });
    assert.equal(await pan.inputValue(), "", "a supplier with no PAN kept the PAN typed before it was picked");
    assert.equal(await pan.getAttribute("placeholder"), "No PAN on the supplier's record");
    assert.match(await form.getByRole("button", { name: "TDS Section", exact: true }).innerText(), /^\s*194C\b/);
    await form.getByText("₹500.00 of the year's tax is not withheld on this payment, because it is more than the payment.", { exact: true }).waitFor();

    await form.getByRole("button", { name: "Supplier (optional)" }).getByLabel("Clear").click();
    await until(async () => (await pan.getAttribute("readonly")) === null, "the PAN box to be editable again once the supplier is cleared");
    await pan.fill(KAPOOR.pan);
    await form.getByText(COUNTED(KAPOOR.name, true), { exact: true }).waitFor({ timeout: 4000 });
    assert.equal(previews[previews.length - 1].vendor_id, null, "the cleared supplier was still sent");
  },
};

const typedFormSaysTheSuppliersCouldNotBeRead = {
  id: "a-typed-deduction-form-says-when-the-clients-suppliers-could-not-be-read",
  title: "TDS > Add Deduction: a supplier list the server refused is said in words, with the server's reason, and the form still quotes the payment",
  async run(env) {
    const { form } = await openWithSuppliers(env, () => ({ success: false, data: null, error: "Unable to complete vendor operation. Please try again." }));
    await form.getByText(/The client's suppliers could not be read, so none can be picked here: Unable to complete vendor operation\. Please try again\./).waitFor({ timeout: 4000 });
    await form.getByLabel("PAN of Party", { exact: true }).fill(KAPOOR.pan);
    await form.getByText(COUNTED(KAPOOR.name, true), { exact: true }).waitFor({ timeout: 4000 });
  },
};

export const scenarios = [clientTabNames, clientTabNarrow, firmPageNames, typedFormSaysWhatWasAddedUp, typedFormNamesItsSupplier, typedFormSaysWhichSupplierItFound, typedFormSaysTheSuppliersCouldNotBeRead];
