/**
 * A NEW MCA FILING NAMES THE CLIENT'S COMPANY AND A YEAR THE CALENDAR HOLDS OPEN (POST-A-291), driven in a browser.
 *
 * Against a stubbed server, in Chromium:
 *
 *   1. the firm's Add Filing, for a client with two companies and two open years: a company must be chosen (the form says so and writes
 *      nothing), the chosen company's own CIN is shown and written with its id, and the year chosen from the list is written as the period
 *      and the financial year;
 *   2. the same form for a client with one company and one open year: no choice is asked, the company and the year are filled in;
 *   3. "Another year" on that list gives an empty box to type the period in, and the financial year is then not written;
 *   4. a client with no company on record and no open year: the CIN and the period are typed, the period box starts EMPTY (it used to hold
 *      the current financial year from the browser's clock), and both say why;
 *   5. a client's own MCA tab, two companies: Save without a company is refused in words and sends nothing; with one, the company's id goes
 *      to the server and the only open year is preselected;
 *   6. the same tab, one company: it is named on the form and its id is sent without a choice;
 *   7. the firm's form for an AOC-4 with no open year: a period must be typed (a filing with none could never close its obligation);
 *   8. an answer that cannot be read is said with Try again, and Try again reads it, after which the company is chosen from the list;
 *   9. the client tab with two open years and none preselected: Save without a year is refused in words and sends nothing;
 *  10. an earlier, slower answer (for AOC-4) that lands after a later one (for MGT-7) does not replace it;
 *  11. the firm's form creates the filing through the API (POST-A-442): it offers only the forms the server takes, says which it does not,
 *      and sends the status and the notes the CA chose.
 *
 * No scenario has a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { pick, until } from "../kit.mjs";
import { ok } from "../stub.mjs";
import { CLIENT_ID } from "../fixtures.mjs";

export const group = "mca-filing-choices";

const ALPHA = { id: "co-a", company_name: "Alpha Pvt Ltd", cin: "U17200MH2010PTC205678" };
const BETA = { id: "co-b", company_name: "Beta Pvt Ltd", cin: "U17200MH2011PTC205679" };
const YEARS = [
  { financial_year: "2025-26", due_date: "2026-10-30", status: "Not Started" },
  { financial_year: "2024-25", due_date: "2025-10-30", status: "Overdue" },
];
const CHOICES = /\/api\/mca-workspace\/filing-choices\?client_id=/;

function answersChoices(stub, data) {
  const asked = [];
  stub.route({ method: "GET", re: CHOICES, reply: (_req, _body, url) => {
    asked.push({ client: url.searchParams.get("client_id"), form: url.searchParams.get("form_type") });
    return ok(data);
  } });
  return asked;
}

async function atAddFiling(env, data) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { mca: ["read", "write", "approve"] } }) });
  // The firm-level form creates the filing through the API (POST-A-442), as the client tab does: what it SENDS is recorded here.
  const inserted = [];
  stub.route({ method: "POST", re: /\/api\/mca-workspace\/filings$/, reply: (_req, body) => {
    const sent = JSON.parse(body);
    inserted.push(sent);
    return ok({ ...sent, id: `m-new-${inserted.length}`, filed_date: null, srn: null });
  } });
  stub.setTable("mca_filings", []);
  const asked = answersChoices(stub, data);
  await page.goto(`${env.base}/mca/`, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Filings", exact: true }).click();
  await page.getByRole("button", { name: /Add Filing/ }).first().click();
  await pick(page, page.locator('button[aria-label="Client"]'), "Acme Traders");
  await until(async () => asked.length > 0, "the form to ask the server for the client's companies and years");
  return { inserted, asked };
}

async function dueAndAdd(page) {
  await page.locator("#mca-due-date").fill("30/10/2026");
  await page.locator("#mca-due-date").press("Tab");
  await page.getByRole("button", { name: "Add Filing", exact: true }).last().click();
}

export const scenarios = [
  {
    id: "firm-form-two-companies-asks-which-and-writes-its-own-cin-and-the-chosen-year",
    title: "firm Add Filing, two companies and two open years: a company is required, its CIN and the chosen year are written",
    async run(env) {
      const { page } = env;
      const { inserted, asked } = await atAddFiling(env, { companies: [ALPHA, BETA], company_required: true, has_obligation: true, periods: YEARS, periods_note: null });
      assert.deepEqual(asked[0], { client: CLIENT_ID, form: "AOC-4" });
      const period = page.locator("select[aria-label='Period']");
      await period.waitFor();
      assert.equal(await page.getByLabel("CIN / LLPIN", { exact: true }).count(), 0, "the CIN is not typed when the client's companies are offered");
      assert.deepEqual(await period.locator("option").allInnerTexts(),
        ["Choose the year", "FY 2025-26 · due 30 Oct 2026", "FY 2024-25 · due 30 Oct 2025", "Another year…"]);
      await period.selectOption("2024-25");
      await dueAndAdd(page);
      await page.getByText("Choose the company this filing is for.", { exact: false }).waitFor();
      assert.equal(inserted.length, 0, "nothing is written without a company");
      await page.locator("select#mca-add-company").selectOption("co-b");
      await page.getByTestId("mca-add-company-cin").waitFor();
      assert.match(await page.getByTestId("mca-add-company-cin").innerText(), /U17200MH2011PTC205679 · Beta Pvt Ltd/);
      await page.getByRole("button", { name: "Add Filing", exact: true }).last().click();
      await until(async () => inserted.length === 1, "the filing to be written");
      const row = inserted[0];
      assert.equal(row.company_id, "co-b");
      // The company's own CIN is the server's to write from its row: none is sent where the chosen company holds one.
      assert.equal(row.cin, null);
      assert.equal(row.period, "FY 2024-25");
      assert.equal(row.financial_year, "2024-25");
    },
  },
  {
    id: "firm-form-one-company-and-one-year-fills-both-in",
    title: "firm Add Filing, one company and one open year: no choice is asked, both are filled in",
    async run(env) {
      const { page } = env;
      const { inserted } = await atAddFiling(env, { companies: [ALPHA], company_required: false, has_obligation: true, periods: [YEARS[0]], periods_note: null });
      assert.equal(await page.locator("select#mca-add-company").count(), 0);
      await page.getByTestId("mca-add-company-cin").waitFor();
      assert.equal(await page.locator("select[aria-label='Period']").inputValue(), "2025-26");
      await dueAndAdd(page);
      await until(async () => inserted.length === 1, "the filing to be written");
      assert.equal(inserted[0].company_id, "co-a");
      assert.equal(inserted[0].cin, null);
      assert.equal(inserted[0].period, "FY 2025-26");
      assert.equal(inserted[0].financial_year, "2025-26");
    },
  },
  {
    id: "firm-form-another-year-is-typed-and-names-no-financial-year",
    title: "firm Add Filing, Another year: an empty box to type in, and no financial year written",
    async run(env) {
      const { page } = env;
      const { inserted } = await atAddFiling(env, { companies: [ALPHA], company_required: false, has_obligation: true, periods: YEARS, periods_note: null });
      await page.locator("select[aria-label='Period']").selectOption("__another__");
      const typed = page.locator("input[aria-label='Period']");
      await typed.waitFor();
      assert.equal(await typed.inputValue(), "");
      await typed.fill("FY 2022-23");
      await dueAndAdd(page);
      await until(async () => inserted.length === 1, "the filing to be written");
      assert.equal(inserted[0].period, "FY 2022-23");
      assert.equal(inserted[0].financial_year, null);
    },
  },
  {
    id: "firm-form-no-company-and-no-year-is-typed-and-the-period-starts-empty",
    title: "firm Add Filing, no company on record and no open year: CIN and period typed, the period starting empty, each saying why",
    async run(env) {
      const { page } = env;
      const note = "The compliance calendar holds no open AOC-4 for this client, so no year is offered. Type the year this filing is for.";
      const { inserted } = await atAddFiling(env, { companies: [], company_required: false, has_obligation: true, periods: [], periods_note: note });
      await page.getByText("No active company of this client is in the Company Master, so type its CIN.").waitFor();
      await page.getByText(note).waitFor();
      const period = page.locator("input[aria-label='Period']");
      assert.equal(await period.inputValue(), "", "the period is not filled in from the browser's clock");
      await page.getByLabel("CIN / LLPIN", { exact: true }).fill("u17200mh2010ptc205678");
      await period.fill("FY 2025-26");
      await dueAndAdd(page);
      await until(async () => inserted.length === 1, "the filing to be written");
      assert.equal(inserted[0].company_id, null);
      assert.equal(inserted[0].cin, "U17200MH2010PTC205678");
      assert.equal(inserted[0].period, "FY 2025-26");
    },
  },
  {
    id: "firm-form-offers-only-the-forms-the-server-takes-and-sends-what-the-ca-chose",
    title: "firm Add Filing (POST-A-442): INC-20A, DIR-3 KYC and MSME-1 are not offered and the form says so; Overdue and the notes reach the server",
    async run(env) {
      const { page } = env;
      const { inserted } = await atAddFiling(env, { companies: [ALPHA], company_required: false, has_obligation: true, periods: [YEARS[0]], periods_note: null });
      const offered = await page.locator("select[aria-label='Form Type']").last().locator("option").evaluateAll((os) => os.map((o) => o.value));
      assert.deepEqual(offered, ["AOC-4", "MGT-7", "MGT-7A", "ADT-1", "CHG-1"]);
      await page.getByText("INC-20A, DIR-3 KYC and MSME-1 are not recorded here.").waitFor();
      await page.locator("select[aria-label='Status']").selectOption("Overdue");
      await page.getByLabel("Notes", { exact: true }).fill("Board approval awaited");
      await dueAndAdd(page);
      await until(async () => inserted.length === 1, "the filing to be sent");
      assert.equal(inserted[0].status, "overdue");
      assert.equal(inserted[0].description, "Board approval awaited");
      assert.equal(inserted[0].client_id, CLIENT_ID);
      assert.equal(inserted[0].due_date, "2026-10-30");
    },
  },
  {
    id: "client-tab-two-companies-refuses-without-one-and-sends-the-one-chosen",
    title: "client MCA tab, two companies: Save without one is refused in words and sends nothing; with one, its id is sent and the only year is preselected",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { mca: ["read", "write", "approve"] } }) });
      stub.route({ method: "GET", re: /mca-workspace\/filings\?client_id=/, reply: () => ok([]) });
      const sent = [];
      stub.route({ method: "POST", re: /mca-workspace\/filings$/, reply: (_req, raw) => { sent.push(JSON.parse(raw)); return ok({ id: "mf-1" }); } });
      answersChoices(stub, { companies: [ALPHA, BETA], company_required: true, has_obligation: true, periods: [YEARS[1]], periods_note: null });
      stub.setTable("mca_companies", []);
      await page.goto(`${env.base}/clients/${CLIENT_ID}/compliance/mca/`, { waitUntil: "networkidle" });
      await page.getByRole("button", { name: "Annual Filings", exact: true }).click();
      await page.getByRole("button", { name: "+ New Filing" }).click();
      await page.getByLabel("Form", { exact: true }).selectOption("AOC-4");
      const year = page.locator("select[aria-label='Financial year']");
      await year.waitFor();
      assert.equal(await year.inputValue(), "2024-25");
      await page.locator("#mca-new-filing-due-date").fill("30/10/2025");
      await page.locator("#mca-new-filing-due-date").press("Tab");
      await page.getByRole("button", { name: "Save", exact: true }).click();
      await page.getByText("Company: choose the company this filing is for.", { exact: false }).waitFor();
      assert.equal(sent.length, 0, "nothing is sent without a company");
      await page.locator("select[aria-label='Company']").selectOption("co-a");
      await page.getByRole("button", { name: "Save", exact: true }).click();
      await until(async () => sent.length === 1, "the filing to be sent");
      assert.equal(sent[0].company_id, "co-a");
      assert.equal(sent[0].financial_year, "2024-25");
      assert.equal(sent[0].client_id, CLIENT_ID);
    },
  },
  {
    id: "client-tab-one-company-is-named-and-sent-without-a-choice",
    title: "client MCA tab, one company: it is named on the form and its id sent without a choice",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { mca: ["read", "write", "approve"] } }) });
      stub.route({ method: "GET", re: /mca-workspace\/filings\?client_id=/, reply: () => ok([]) });
      const sent = [];
      stub.route({ method: "POST", re: /mca-workspace\/filings$/, reply: (_req, raw) => { sent.push(JSON.parse(raw)); return ok({ id: "mf-1" }); } });
      answersChoices(stub, { companies: [ALPHA], company_required: false, has_obligation: true, periods: null, periods_note: "The compliance calendar holds no obligation for DIR-12, so no year is offered. Type the year this filing is for." });
      stub.setTable("mca_companies", []);
      await page.goto(`${env.base}/clients/${CLIENT_ID}/compliance/mca/`, { waitUntil: "networkidle" });
      await page.getByRole("button", { name: "Event Filings", exact: true }).click();
      await page.getByRole("button", { name: "+ New Filing" }).click();
      await page.getByLabel("Form", { exact: true }).selectOption("DIR-12");
      await page.getByTestId("mca-new-filing-company").waitFor();
      assert.match(await page.getByTestId("mca-new-filing-company").innerText(), /For Alpha Pvt Ltd · U17200MH2010PTC205678/);
      await page.getByText("holds no obligation for DIR-12").waitFor();
      await page.getByLabel("Financial year (for example 2025-26)", { exact: true }).fill("2025-26");
      await page.locator("#mca-new-filing-due-date").fill("30/10/2026");
      await page.locator("#mca-new-filing-due-date").press("Tab");
      await page.getByRole("button", { name: "Save", exact: true }).click();
      await until(async () => sent.length === 1, "the filing to be sent");
      assert.equal(sent[0].company_id, "co-a");
    },
  },
  {
    id: "firm-form-an-aoc4-with-no-open-year-needs-a-period-typed",
    title: "firm Add Filing, an AOC-4 with no open year: a period must be typed, and nothing is written without one",
    async run(env) {
      const { page } = env;
      const { inserted } = await atAddFiling(env, { companies: [ALPHA], company_required: false, has_obligation: true, periods: [],
        periods_note: "The compliance calendar holds no open AOC-4 for this client, so no year is offered. Type the year this filing is for." });
      await page.getByTestId("mca-add-company-cin").waitFor();
      await dueAndAdd(page);
      await page.getByText("Period: type the financial year this AOC-4 is for", { exact: false }).waitFor();
      assert.equal(inserted.length, 0, "nothing is written without a year");
      await page.locator("input[aria-label='Period']").fill("FY 2023-24");
      await page.getByRole("button", { name: "Add Filing", exact: true }).last().click();
      await until(async () => inserted.length === 1, "the filing to be written");
      assert.equal(inserted[0].period, "FY 2023-24");
    },
  },
  {
    id: "firm-form-an-unreadable-answer-says-so-and-try-again-reads-it",
    title: "firm Add Filing: an answer that cannot be read is said with Try again, and Try again reads it",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { mca: ["read", "write", "approve"] } }) });
      stub.setTable("mca_filings", []);
      let calls = 0;
      stub.route({ method: "GET", re: CHOICES, reply: () => {
        calls += 1;
        return calls === 1 ? { success: false, data: null, error: "The client's companies and open years could not be read. Please try again." }
          : ok({ companies: [ALPHA, BETA], company_required: true, has_obligation: true, periods: YEARS, periods_note: null });
      } });
      await page.goto(`${env.base}/mca/`, { waitUntil: "networkidle" });
      await page.getByRole("button", { name: "Filings", exact: true }).click();
      await page.getByRole("button", { name: /Add Filing/ }).first().click();
      await pick(page, page.locator('button[aria-label="Client"]'), "Acme Traders");
      await page.getByText("the CIN typed is matched to the client's companies when the filing is marked filed", { exact: false }).waitFor();
      await page.getByLabel("CIN / LLPIN", { exact: true }).waitFor();
      await page.getByRole("button", { name: "Try again", exact: true }).click();
      await page.locator("select#mca-add-company").waitFor();
      assert.equal(calls, 2);
      assert.equal(await page.getByLabel("CIN / LLPIN", { exact: true }).count(), 0);
    },
  },
  {
    id: "client-tab-two-open-years-and-none-chosen-is-refused",
    title: "client MCA tab, two open years and none preselected: Save without a year is refused in words and sends nothing",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { mca: ["read", "write", "approve"] } }) });
      stub.route({ method: "GET", re: /mca-workspace\/filings\?client_id=/, reply: () => ok([]) });
      const sent = [];
      stub.route({ method: "POST", re: /mca-workspace\/filings$/, reply: (_req, raw) => { sent.push(JSON.parse(raw)); return ok({ id: "mf-1" }); } });
      answersChoices(stub, { companies: [ALPHA], company_required: false, has_obligation: true, periods: YEARS, periods_note: null });
      stub.setTable("mca_companies", []);
      await page.goto(`${env.base}/clients/${CLIENT_ID}/compliance/mca/`, { waitUntil: "networkidle" });
      await page.getByRole("button", { name: "Annual Filings", exact: true }).click();
      await page.getByRole("button", { name: "+ New Filing" }).click();
      await page.getByLabel("Form", { exact: true }).selectOption("AOC-4");
      const year = page.locator("select[aria-label='Financial year']");
      await year.waitFor();
      assert.equal(await year.inputValue(), "");
      await page.locator("#mca-new-filing-due-date").fill("30/10/2026");
      await page.locator("#mca-new-filing-due-date").press("Tab");
      await page.getByRole("button", { name: "Save", exact: true }).click();
      await page.getByText("Financial year: choose the year this filing is for, or Another year to type it.").waitFor();
      assert.equal(sent.length, 0);
      await year.selectOption("2025-26");
      await page.getByRole("button", { name: "Save", exact: true }).click();
      await until(async () => sent.length === 1, "the filing to be sent");
      assert.equal(sent[0].financial_year, "2025-26");
    },
  },
  {
    id: "firm-form-an-earlier-slower-answer-does-not-replace-a-later-one",
    title: "firm Add Filing: the slow answer for AOC-4 lands after the answer for MGT-7, and the MGT-7 years stay on the form",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { mca: ["read", "write", "approve"] } }) });
      stub.setTable("mca_filings", []);
      stub.route({ method: "GET", re: /filing-choices\?client_id=[^&]+&form_type=AOC-4$/, delay: 1500, reply: () => ok({
        companies: [ALPHA], company_required: false, has_obligation: true, periods: [YEARS[0]], periods_note: null }) });
      stub.route({ method: "GET", re: /filing-choices\?client_id=[^&]+&form_type=MGT-7$/, reply: () => ok({
        companies: [ALPHA], company_required: false, has_obligation: true, periods: [{ financial_year: "2021-22", due_date: "2022-11-29", status: "Overdue" }], periods_note: null }) });
      await page.goto(`${env.base}/mca/`, { waitUntil: "networkidle" });
      await page.getByRole("button", { name: "Filings", exact: true }).click();
      await page.getByRole("button", { name: /Add Filing/ }).first().click();
      await pick(page, page.locator('button[aria-label="Client"]'), "Acme Traders");
      const started = Date.now();
      await page.locator("select[aria-label='Form Type']").last().selectOption("MGT-7");
      const period = page.locator("select[aria-label='Period']");
      await period.waitFor();
      assert.equal(await period.inputValue(), "2021-22");
      await page.waitForTimeout(Math.max(0, started + 1500 + 400 - Date.now()));     // the AOC-4 answer has landed
      assert.equal(await period.inputValue(), "2021-22", "the earlier AOC-4 answer replaced the MGT-7 one");
      assert.deepEqual(await period.locator("option").allInnerTexts(), ["Choose the year", "FY 2021-22 · due 29 Nov 2022", "Another year…"]);
    },
  },
];
