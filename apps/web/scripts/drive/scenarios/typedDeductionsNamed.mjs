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
const TYPED_REASON = "A statement built from the books carries posted purchase bills and advances only, so deductions typed on the TDS screen are not in its totals. Key them from the register when you key the statement, or leave them out knowingly.";

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

/** domain/tds/manual_register.GAP_MESSAGES, both, in the server's words. */
const GAP_NOT_UNIFIED = "This year's aggregate for this payee counts hand-entered deductions only. Purchase bills for the same payee are held in a separate register and are not added in, so a section with an annual threshold may not have been triggered yet.";
const GAP_NO_PAN = "No usable PAN is recorded for this payee, so the year's earlier payments to the same payee were not looked for. This payment is charged as if it were the payee's first of the year, and that says nothing about what the year's total is.";

const BELOW = (aggregateTested, { section = "194J", noPan = false } = {}) => ({
  section, payment_amount_paise: 10000000, tds_rate_pct: 0, tds_paise: 0, quarter: "Q1", financial_year: "2026-27",
  explain: {
    applies: false, reason: "below_threshold", rate_pct: 0, tds_paise: 0, rate_basis: noPan
      ? "Charged at the non-individual rate: no PAN is on file to read the payee's type from, so the higher rate applies by default."
      : "Charged at the non-individual rate: PAN 4th character C.",
    fy_prior_taxable_paise: 0, fy_prior_tds_paise: 0, ...(aggregateTested === undefined ? {} : { aggregate_tested: aggregateTested }),
    gaps: noPan ? ["tds_aggregate_excludes_purchase_bills", "tds_aggregate_not_read_without_a_pan"] : ["tds_aggregate_excludes_purchase_bills"],
    gap_messages: noPan ? [GAP_NOT_UNIFIED, GAP_NO_PAN] : [GAP_NOT_UNIFIED],
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

export const scenarios = [clientTabNames, clientTabNarrow, firmPageNames, typedFormSaysWhatWasAddedUp];
