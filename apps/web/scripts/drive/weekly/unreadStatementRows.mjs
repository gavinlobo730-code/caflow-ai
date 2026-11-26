/**
 * A BANK STATEMENT ROW THAT COULD NOT BE READ IS NAMED ON THE SCREEN (POST-A-551), driven in a browser.
 *
 * The server now names each row of a statement that looks like a transaction and could not be read (an amount printed as
 * "12x4.00", a date that is not one), with the cell as the bank printed it. This drives the import dialog against a stubbed
 * server, in Chromium, and holds what the CA is shown:
 *
 *   1. an import that went in short says which row is missing, beside the result, with the row's date, its narration and
 *      the cell as printed, and how many;
 *   2. an answer that carries no such rows (a clean file, or a server not yet deployed, which sends neither key) draws no
 *      notice at all;
 *   3. the check of a column mapping names the row BEFORE anything is imported, and checking sends no import;
 *   4. an import the server refuses for not adding up shows the server's sentence, which names the row.
 *
 * No scenario has a date of its own to type, so none has a zone.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";
import { ok } from "../stub.mjs";

export const group = "unread-statement-rows";

const ACCOUNT = { id: "ba-1", bank_name: "HDFC Bank", account_no: "50100012345678", is_active: true, ledger_account_id: "acc-bank" };
const COUNTS = { needs_you: 0, proposed: 0, ready: 0, covered: 0, passed: 0, set_aside: 0, to_do: 0, undrafted: 0, trusted_pending: 0, tds_decision_pending: 0 };
const UPLOAD = /api\/banking\/statements\/upload$/;
const INSPECT = /api\/banking\/statements\/inspect$/;
const PREVIEW = /api\/banking\/statements\/preview$/;

const CSV = "Date,Description,Debit,Credit,Balance\n02/04/2026,Rent,5000.00,,5000.00\n03/04/2026,UPI to vendor,12x4.00,,3766.00\n04/04/2026,Receipt,,2000.00,5766.00\n";
const UNREAD = [{ column: "debit", cell: "12x4.00", date: "2026-04-03", description: "UPI to vendor" }];
const NOTE = '1 row of the file could not be read and is not in these figures: 2026-04-03, "UPI to vendor" (debit printed as "12x4.00"). '
  + "Correct it in the file, or check the column mapping, and upload it again.";

/** The bank screen with the import dialog open and the statement chosen. */
async function withTheFileChosen(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /api\/banking\/accounts/, reply: () => ok([ACCOUNT]) });
  stub.route({ method: "GET", re: /api\/banking\/entries\/counts/, reply: () => ok(COUNTS) });
  stub.route({ method: "GET", re: /api\/banking\/entries\?/, reply: () => ok({ rows: [], total: 0, ledger_order: [] }) });
  await page.goto(env.at("/bank/"), { waitUntil: "networkidle" });
  const openImport = page.getByRole("button", { name: /Import statement/ }).first();
  await until(async () => (await openImport.count()) > 0 && await openImport.isEnabled(), "Import statement to be offered", 20000);
  await openImport.click();
  await page.getByText("Import Bank Statement").waitFor();
  await page.locator('input[aria-label="Statement File * (.csv, .xlsx or .pdf)"]').setInputFiles({ name: "statement-apr.csv", mimeType: "text/csv", buffer: Buffer.from(CSV) });
}

const notice = (page) => page.locator("[data-unread-rows]");

export const scenarios = [
  {
    id: "an-import-that-went-in-short-says-which-row-is-missing",
    title: "Bank > Import statement: an import that left a row out names the row beside the result, with its date, its narration and the cell as the bank printed it",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "POST", re: UPLOAD, reply: () => ok({
        imported: 2, duplicates_skipped: 0, verified: false, verification_gap: "This statement prints no totals of its own.", unread_rows: UNREAD, unread_note: NOTE }) });
      await withTheFileChosen(env);
      await page.getByRole("button", { name: /^Import$/ }).click();
      await page.getByText("2 transactions imported").waitFor({ timeout: 10000 });
      const box = notice(page);
      await box.waitFor({ timeout: 5000 });
      assert.equal(await box.count(), 1);
      assert.equal(await box.getAttribute("data-unread-rows"), "1");
      assert.equal(await box.getAttribute("role"), "status");
      const said = (await box.innerText()).replace(/\s+/g, " ");
      assert.match(said, /^1 row of the file could not be read and is not in these figures\./, said);
      assert.ok(said.includes('UPI to vendor: the debit is printed as "12x4.00"'), `the row is not named as printed: ${said}`);
      assert.ok(/0?3[ /-](Apr|04)[ /-]2026/.test(said), `the row's date is not shown as a date a person reads: ${said}`);
      assert.ok(!said.includes("2026-04-03"), `the row's date is shown as the server's ISO string: ${said}`);
      assert.ok(said.endsWith("Correct it in the file, or check the column mapping, and upload it again."), said);
      assert.equal(stub.writesTo(UPLOAD, "POST").length, 1, "the statement was sent more than once");
    },
  },
  {
    id: "an-answer-with-no-unread-rows-draws-no-notice",
    title: "Bank > Import statement: a clean import, and an answer from a server that sends neither key, draw no notice",
    async run(env) {
      const { page, stub } = env;
      let n = 0;
      stub.route({ method: "POST", re: UPLOAD, reply: () => {
        n += 1;
        const base = { imported: 3, duplicates_skipped: 0, verified: true, totals_check: { agrees: true, label: "Closing Balance" } };
        return ok(n === 1 ? base : { ...base, unread_rows: [], unread_note: null });
      } });
      await withTheFileChosen(env);
      await page.getByRole("button", { name: /^Import$/ }).click();
      await page.getByText("3 transactions imported").waitFor({ timeout: 10000 });
      assert.equal(await notice(page).count(), 0, "a notice was drawn for an answer that carries no unread rows (an older server)");
      await page.getByRole("button", { name: /^Done$/ }).click();
      // The same again with the keys present and empty.
      const openImport = page.getByRole("button", { name: /Import statement/ }).first();
      await until(async () => (await openImport.count()) > 0 && await openImport.isEnabled(), "Import statement to be offered again", 20000);
      await openImport.click();
      await page.getByText("Import Bank Statement").waitFor();
      await page.locator('input[aria-label="Statement File * (.csv, .xlsx or .pdf)"]').setInputFiles({ name: "statement-may.csv", mimeType: "text/csv", buffer: Buffer.from(CSV.replace("12x4.00", "1234.00")) });
      await page.getByRole("button", { name: /^Import$/ }).click();
      await page.getByText("3 transactions imported").waitFor({ timeout: 10000 });
      assert.equal(n, 2, `expected two uploads, there were ${n}`);
      assert.equal(await notice(page).count(), 0, "a notice was drawn for an empty list");
    },
  },
  {
    id: "checking-a-column-mapping-names-the-row-before-anything-is-imported",
    title: "Bank > Import statement > Map columns > Check this mapping: the unread row is named in the check, and checking imports nothing",
    async run(env) {
      const { page, stub } = env;
      const MAPPING = { date: 0, desc: 1, debit: 2, credit: 3, balance: 4 };
      stub.route({ method: "POST", re: INSPECT, reply: () => ok({
        headers: ["Date", "Description", "Debit", "Credit", "Balance"], sample_rows: [["02/04/2026", "Rent", "5000.00", "", "5000.00"]], total_rows: 3,
        detected_format: "generic", detected_fits: true, proposed_mapping: MAPPING, saved_mapping: null, saved_mapping_scope: null, header_fingerprint: "fp-1" }) });
      stub.route({ method: "POST", re: PREVIEW, reply: () => ok({
        headers: ["Date", "Description", "Debit", "Credit", "Balance"], total_rows: 3, parsed_count: 2, skipped_count: 0,
        rows: [
          { transaction_date: "2026-04-02", description: "Rent", reference_no: null, debit_paise: 500000, credit_paise: 0, balance_paise: 500000 },
          { transaction_date: "2026-04-04", description: "Receipt", reference_no: null, debit_paise: 0, credit_paise: 200000, balance_paise: 576600 },
        ],
        balance_check: { checked: true, agrees: false, reason: "Row 2 does not follow from row 1 by its own movement." },
        unread_rows: UNREAD, unread_note: NOTE }) });
      await withTheFileChosen(env);
      await page.getByRole("button", { name: /^Map columns$/ }).click();
      await page.getByText("Map the statement columns").waitFor({ timeout: 10000 });
      assert.equal(await notice(page).count(), 0, "a notice is drawn before the mapping was checked");
      await page.getByRole("button", { name: /^Check this mapping$/ }).click();
      const box = notice(page);
      await box.waitFor({ timeout: 10000 });
      const said = (await box.innerText()).replace(/\s+/g, " ");
      assert.ok(said.includes('UPI to vendor: the debit is printed as "12x4.00"'), `the check does not name the row: ${said}`);
      assert.match(await page.locator("body").innerText(), /2 of 3 rows read/);
      assert.equal(stub.writesTo(UPLOAD, "POST").length, 0, "checking a mapping imported the statement");
      assert.equal(stub.writesTo(PREVIEW, "POST").length, 1);
    },
  },
  {
    id: "an-import-refused-for-not-adding-up-shows-the-sentence-that-names-the-row",
    title: "Bank > Import statement: a refusal for not adding up is shown in the server's words, which name the row that was not read",
    async run(env) {
      const { page, stub } = env;
      const REFUSAL = `The transactions read from this statement do not take the opening balance to the closing balance. ${NOTE}`;
      stub.route({ method: "POST", re: UPLOAD, status: () => 422, reply: () => ({ detail: { message: REFUSAL, code: "balance_mismatch", unread_rows: UNREAD } }) });
      await withTheFileChosen(env);
      await page.getByRole("button", { name: /^Import$/ }).click();
      await until(async () => (await page.locator("body").innerText()).includes('"UPI to vendor" (debit printed as "12x4.00")'), "the refusal that names the row", 10000);
      assert.equal(await page.getByText(/transactions? imported/).count(), 0, "a refused import is shown as imported");
    },
  },
];
