/**
 * Group: the files the upload-screen drive of PRE-A-001 did not reach, driven in Chromium (POST-A-218).
 *
 * PRE-A-001 drove the Excel import preview, the opening register, vouchers, the GSTR-2B tab and the bulk drop against the real API. What it did
 * not open, and what this group opens:
 *
 *   1. a LEGACY `.xls` workbook (BIFF8, what Excel 97-2003 saves). The import dialog accepts `.xls`, and the date rule of
 *      `lib/spreadsheet/xlsxCsv.ts` had only ever been run on `.xlsx`: a BIFF file carries its number formats in a different record, so
 *      whether a date cell still comes through as the date it holds was not known;
 *   2. a workbook in the 1904 DATE SYSTEM (Excel for Mac's old default). The reading is unit-tested with `.xlsx` round trips in node; this
 *      chooses one in the browser, where the same serial read in the 1900 system is a date four years and a day early;
 *   3. a LARGE workbook (5,000 rows), which the dialog reads in the page, previews in full and counts;
 *   4. the LOCKED-PDF password dialog of the bank statement import, after the date-sentence change (POST-A-381) moved the shared form
 *      code: the box appears only on the server's code, is a password box the browser will not offer to save, the retry carries the
 *      password in the BODY and never in the URL, the second refusal says the password did not open it, and the box goes once the file
 *      is in.
 *
 * WHAT IT DOES NOT PROVE. Firefox and Safari (only Chromium is installed here), a workbook written by Excel itself (these are written by the
 * SheetJS the page ships, which is what the import reads them with), and the server's reading of a locked PDF (the backend suite's).
 */
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { until } from "../kit.mjs";
import { ok } from "../stub.mjs";

export const group = "workbooks";

const require = createRequire(import.meta.url);
const X = require("xlsx");

const HEAD = ["client_name", "employee_code", "name", "date_of_birth", "joining_date", "basic"];

/** A workbook of the employee import's columns. `rows` are cell objects or strings; `date1904` writes the workbook flag. */
function workbook(rows, { bookType = "xlsx", date1904 = false } = {}) {
  const ws = {};
  HEAD.forEach((h, c) => { ws[X.utils.encode_cell({ r: 0, c })] = { t: "s", v: h }; });
  rows.forEach((row, r) => row.forEach((cell, c) => {
    ws[X.utils.encode_cell({ r: r + 1, c })] = typeof cell === "string" ? { t: "s", v: cell } : cell;
  }));
  ws["!ref"] = `A1:F${rows.length + 1}`;
  const wb = { SheetNames: ["Employees"], Sheets: { Employees: ws } };
  if (date1904) wb.Workbook = { WBProps: { date1904: true } };
  return Buffer.from(X.write(wb, { type: "buffer", bookType }));
}

/** Payroll > People with the import dialog open and `file` chosen; resolves once the preview has counted the rows. */
async function preview(env, file) {
  const { page } = env;
  await page.goto(`${env.base}/payroll/people/`, { waitUntil: "networkidle" });
  const open = page.getByRole("button", { name: /Import CSV/i }).first();
  await open.waitFor({ timeout: 20000 });
  await open.click();
  await page.getByText("Import Employees").first().waitFor({ timeout: 10000 });
  await page.locator('input[aria-label="CSV or Excel file to import"]').setInputFiles(file);
  await page.getByText(/valid rows/).first().waitFor({ timeout: 30000 });
  return page.locator("table").last().locator("tbody tr").evaluateAll((trs) =>
    trs.map((tr) => Array.from(tr.querySelectorAll("td")).map((td) => (td.textContent || "").trim())));
}

const errorRows = async (page) => page.getByText(/rows with errors/).count();

// 15 March 2025 is serial 45731 in the 1900 system and 44269 in the 1904 system (1,462 days apart); 25 March 2025 is 45741 / 44279.
const DATE_ROWS_1900 = [
  ["Acme Traders", "E001", "Asha Rao", { t: "n", v: 45731, z: "m/d/yy" }, { t: "n", v: 45741, z: "d-mmm-yy" }, { t: "n", v: 25000 }],
  ["Acme Traders", "E002", "Bimal Das", { t: "n", v: 45731, z: "dd-mm-yyyy" }, "25/03/2025", { t: "n", v: 30000 }],
];

// ── the bank statement import, for the locked PDF ───────────────────────────────────────────────────────────
const ACCOUNT = { id: "ba-1", bank_name: "HDFC Bank", account_no: "50100012345678", is_active: true, ledger_account_id: "acc-bank" };
const UPLOAD = /api\/banking\/statements\/upload$/;
const COUNTS = { needs_you: 0, proposed: 0, ready: 0, covered: 0, passed: 0, set_aside: 0, to_do: 0, undrafted: 0, trusted_pending: 0, tds_decision_pending: 0 };
/** The fields of a multipart body, by name (a file part is reported by its filename). */
function formFields(body) {
  const out = {};
  for (const part of String(body).split(/--[-\w]+\r?\n/)) {
    const name = /name="([^"]+)"/.exec(part)?.[1];
    if (!name) continue;
    const file = /filename="([^"]*)"/.exec(part)?.[1];
    out[name] = file !== undefined ? `<file ${file}>` : part.split(/\r?\n\r?\n/).slice(1).join("\n\n").replace(/\r?\n$/, "");
  }
  return out;
}

export const scenarios = [
  {
    id: "a-legacy-xls-workbook-previews-each-date-as-the-date-it-holds",
    title: "Payroll > People > Import: a BIFF8 .xls with dates in Excel's own formats previews them as yyyy-mm-dd, leaves a typed date as typed, and every row is valid",
    async run(env) {
      const cells = await preview(env, { name: "employees.xls", mimeType: "application/vnd.ms-excel", buffer: workbook(DATE_ROWS_1900, { bookType: "biff8" }) });
      const flat = cells.map((r) => r.join(" | "));
      assert.ok(cells[0]?.includes("2025-03-15") && cells[0]?.includes("2025-03-25") && cells[1]?.includes("2025-03-15"), `the .xls dates were not read as dates:\n${flat.join("\n")}`);
      assert.ok(cells[1]?.includes("25/03/2025"), `a date typed as text was changed:\n${flat.join("\n")}`);
      assert.ok(!flat.some((r) => /\b\d{1,2}\/\d{1,2}\/\d{2}\b|\d{1,2}-[A-Za-z]{3}-\d{2}\b/.test(r)), `a cell shows a two-digit year:\n${flat.join("\n")}`);
      assert.equal(await errorRows(env.page), 0, "the preview reports rows with errors");
      assert.equal(env.stub.allWrites().length, 0, "something was written while a file was only being previewed");
    },
  },
  {
    id: "a-1904-system-workbook-is-not-dated-four-years-early",
    title: "Payroll > People > Import: a workbook in the 1904 date system previews 15 March 2025 as 2025-03-15, not 2021-03-14",
    async run(env) {
      const rows = DATE_ROWS_1900.map((r) => r.map((c) => (typeof c === "object" && c.z && c.z !== "General" ? { ...c, v: c.v - 1462 } : c)));
      const cells = await preview(env, { name: "employees-mac.xlsx", mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", buffer: workbook(rows, { date1904: true }) });
      const flat = cells.map((r) => r.join(" | "));
      assert.ok(cells[0]?.includes("2025-03-15") && cells[0]?.includes("2025-03-25") && cells[1]?.includes("2025-03-15"), `the 1904 dates were misread:\n${flat.join("\n")}`);
      assert.ok(!flat.some((r) => /2021-03-1[34]/.test(r)), `a date was read in the 1900 system:\n${flat.join("\n")}`);
      assert.equal(await errorRows(env.page), 0, "the preview reports rows with errors");
    },
  },
  {
    id: "a-workbook-of-five-thousand-rows-is-read-counted-and-previewed-in-full",
    title: "Payroll > People > Import: a 5,000-row workbook is read in the page, counted as 5,000 valid rows, every row is in the preview, and the first and last dates are right",
    async run(env) {
      const N = 5000;
      const rows = Array.from({ length: N }, (_, i) => ["Acme Traders", `E${String(i + 1).padStart(5, "0")}`, `Employee ${i + 1}`,
        { t: "n", v: 30000 + (i % 3000), z: "dd-mm-yyyy" }, { t: "n", v: 45731, z: "m/d/yy" }, { t: "n", v: 20000 + i }]);
      const started = Date.now();
      const cells = await preview(env, { name: "employees-large.xlsx", mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", buffer: workbook(rows) });
      const took = Date.now() - started;
      assert.equal(cells.length, N, `the preview shows ${cells.length} rows of ${N}`);
      const summary = await env.page.getByText(/valid rows/).first().textContent();
      assert.match(summary ?? "", new RegExp(`^${N} valid rows`), `the count reads ${JSON.stringify(summary)}`);
      assert.ok(cells[0].includes("2025-03-15") && cells[N - 1].includes("2025-03-15"), `a date was misread at either end: ${cells[0].join(" | ")} … ${cells[N - 1].join(" | ")}`);
      assert.ok(cells[N - 1].includes(`E0${N}`), `the last row is not the file's last: ${cells[N - 1].join(" | ")}`);
      assert.equal(await errorRows(env.page), 0, "the preview reports rows with errors");
      // Not a budget anything waits on: a bound well past what a person would sit through, so a pathological slowdown fails here.
      assert.ok(took < 45_000, `the 5,000-row preview took ${took} ms`);
      console.log(`        (the 5,000-row workbook was read and previewed in ${took} ms, page load included)`);
    },
  },
  {
    id: "a-locked-pdf-statement-asks-for-its-password-sends-it-in-the-body-and-forgets-it",
    title: "Bank > Import statement: a locked PDF is asked for its password on the server's code; the retry carries it in the body, a wrong one is said, and the box goes once the file is in",
    async run(env) {
      const { page, stub } = env;
      let attempt = 0;
      stub.route({ method: "GET", re: /api\/banking\/accounts/, reply: () => ok([ACCOUNT]) });
      stub.route({ method: "GET", re: /api\/banking\/entries\/counts/, reply: () => ok(COUNTS) });
      stub.route({ method: "GET", re: /api\/banking\/entries\?/, reply: () => ok({ rows: [], total: 0, ledger_order: [] }) });
      stub.route({
        method: "POST", re: UPLOAD, delay: 50,
        // The stub calls `reply` before `status`, so `attempt` has already counted this upload here.
        status: () => (attempt <= 2 ? 422 : 200),
        reply: () => {
          attempt += 1;
          if (attempt === 1) return { detail: { message: "This PDF is locked with a password.", code: "pdf_password_required" } };
          if (attempt === 2) return { detail: { message: "That password did not open the PDF.", code: "pdf_password_incorrect" } };
          return ok({ imported: 12, duplicates_skipped: 0, verified: true, totals_check: { agrees: true, label: "Closing Balance" } });
        },
      });
      await page.goto(env.at("/bank/"), { waitUntil: "networkidle" });
      const openImport = page.getByRole("button", { name: /Import statement/ }).first();
      await until(async () => (await openImport.count()) > 0 && await openImport.isEnabled(), "Import statement to be offered", 20000);
      await openImport.click();
      await page.getByText("Import Bank Statement").waitFor();
      assert.equal(await page.locator("#stmt-pdf-password").count(), 0, "the password box is offered before the server asked for one");
      await page.locator('input[aria-label="Statement File * (.csv, .xlsx or .pdf)"]').setInputFiles({
        name: "statement-apr.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.7\n% locked\n") });
      await page.getByRole("button", { name: /^Import$/ }).click();

      const box = page.locator("#stmt-pdf-password");
      await box.waitFor({ timeout: 10000 });
      assert.equal(await box.getAttribute("type"), "password");
      assert.equal(await box.getAttribute("autocomplete"), "new-password", "the browser may offer to save the PDF's password as a login");
      assert.ok(await box.evaluate((el) => el === document.activeElement), "focus is not in the password box");
      assert.match(await page.locator("body").innerText(), /The bank locked this statement/);
      const first = formFields(stub.writesTo(UPLOAD, "POST")[0].body);
      assert.equal(first.pdf_password, undefined, "a password was sent before anybody typed one");

      // A wrong one, by Enter.
      await box.fill("WRONG123");
      await box.press("Enter");
      await until(async () => /did not open it/.test(await page.locator("body").innerText()), "the wrong password to be said");
      assert.equal(await box.getAttribute("aria-invalid"), "true");
      const second = stub.writesTo(UPLOAD, "POST")[1];
      assert.equal(formFields(second.body).pdf_password, "WRONG123", "the retry did not carry the password typed");
      assert.ok(!/WRONG123/.test(second.path + (second.search ?? "")), "the password was put in the URL");
      // The right one, by the button.
      await box.fill("CUST0042");
      await page.getByRole("button", { name: /^Import$/ }).click();
      await page.getByText("12 transactions imported").waitFor({ timeout: 10000 });
      const writes = stub.writesTo(UPLOAD, "POST");
      assert.equal(writes.length, 3, `expected three uploads, there were ${writes.length}`);
      assert.equal(formFields(writes[2].body).pdf_password, "CUST0042");
      assert.equal(await page.locator("#stmt-pdf-password").count(), 0, "the password box is still on screen after the import");
      // Nothing about the password was kept in the browser.
      const kept = await page.evaluate(() => JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage }));
      assert.ok(!/CUST0042|WRONG123/.test(kept), "the PDF's password was stored in the browser");
    },
  },
];
