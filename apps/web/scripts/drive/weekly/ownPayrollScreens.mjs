/**
 * THE FIRM-LEVEL PAYROLL SCREENS OPEN FOR THE FIRM'S OWN PRACTICE, AND FOR NOBODY WHO DID NOT ASK (POST-A-534), driven in a
 * browser.
 *
 * The practice is in no list of the firm's clients, so the Statutory, Declarations and Reports payroll screens, whose pickers
 * are those lists, could not be opened for it. Each takes `?client=` now. Against a stubbed server, in Chromium:
 *
 *   1. Statutory opened for the practice by a Partner chooses "My practice" and asks the server for the practice's position;
 *   2. Statutory opened from the menu offers the firm's clients only, asks nothing about the practice and reads no position;
 *   3. an address naming the practice, opened by a Manager, chooses nothing and never asks which client the practice is; an
 *      address naming an id that is nobody's does the same for a Partner;
 *   4. Declarations opened for the practice reads the practice's declarations and employees;
 *   5. Reports opened for the practice reads the practice's employees, runs and year, says it shows My practice only, and
 *      from the menu reads the firm's with no client named and says nothing;
 *   6. the practice's own Payroll page links the four screens with the practice in the address, and a client's page does not.
 *
 * No scenario has a date of its own to type, so none has a zone.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";
import { ok } from "../stub.mjs";
import { CLIENT_ROW } from "../fixtures.mjs";

export const group = "own-payroll-screens";

const PRACTICE_ID = "11111111-1111-4111-8111-111111111111";
const PRACTICE = /\/api\/practice$/;
const POSITION = /\/api\/payroll\/statutory-position\?/;
const DECLARATIONS = /\/api\/payroll\/declarations\?/;
const EMPLOYEES = /\/api\/payroll\/employees(\?|$)/;
const RUNS = /\/api\/payroll\/runs(\?|$)/;
const YEAR_END = /\/api\/payroll\/reports\/year-end\?/;

const EMPLOYEE = { id: "e-1", client_id: PRACTICE_ID, name: "Asha Rao", employee_code: "S001", status: "active", is_active: true,
  basic_paise: 40_000_00, hra_percent: 40, pf_applicable: true, esi_applicable: false, pt_applicable: false };
const RUN = { id: "r-1", client_id: PRACTICE_ID, month: "2026-10", status: "finalized", total_gross_paise: 56_000_00,
  total_net_paise: 50_000_00, total_deductions_paise: 6_000_00, employee_count: 1 };

/** A firm with one client and a practice of its own. Every read this file cares about is recorded with its address. */
function aFirm(env) {
  const seen = { practice: 0, position: [], declarations: [], employees: [], runs: [], yearEnd: [] };
  const note = (list) => (_req, _body, url) => { list.push(String(url)); };
  env.stub.setTable("clients", [{ ...CLIENT_ROW }]);
  env.stub.route({ method: "GET", re: PRACTICE, reply: () => { seen.practice += 1;
    return ok({ internal_client_id: PRACTICE_ID, provisioned: true, firm_has_pan: true, can_provision: false, identity: null, entity_types: [] }); } });
  env.stub.route({ method: "GET", re: POSITION, reply: (...a) => { note(seen.position)(...a);
    return ok({ month: "2026-11", financial_year: "2026-27", rows: [], totals: {}, gaps: [] }); } });
  env.stub.route({ method: "GET", re: DECLARATIONS, reply: (...a) => { note(seen.declarations)(...a); return ok({ declarations: [] }); } });
  env.stub.route({ method: "GET", re: EMPLOYEES, reply: (...a) => { note(seen.employees)(...a); return ok([EMPLOYEE]); } });
  env.stub.route({ method: "GET", re: RUNS, reply: (...a) => { note(seen.runs)(...a); return ok([RUN]); } });
  env.stub.route({ method: "GET", re: YEAR_END, reply: (...a) => { note(seen.yearEnd)(...a); return ok({ rows: [], financial_years: ["2026-27"] }); } });
  return seen;
}

const clientOf = (address) => new URL(address, "http://stub").searchParams.get("client_id");
const picker = (page) => page.locator('button[aria-label="Client"]');
const shown = async (page) => (await picker(page).innerText()).replace(/\s+/g, " ").trim();
/** Long enough for a read this screen makes on arrival to have been sent, for the checks that nothing was. */
const settle = (page) => page.waitForTimeout(700);

export const scenarios = [
  {
    id: "statutory-opened-for-the-practice-chooses-my-practice-and-reads-its-position",
    title: "Payroll statutory > ?client=<the practice>, a Partner: the picker reads My practice and the position asked for is the practice's",
    async run(env) {
      const { page } = env;
      const seen = aFirm(env);
      await page.goto(`${env.base}/payroll/statutory/?client=${PRACTICE_ID}`, { waitUntil: "networkidle" });
      await until(() => seen.position.length >= 1, "the practice's statutory position to be asked for");
      assert.equal(clientOf(seen.position.at(-1)), PRACTICE_ID);
      assert.equal(await shown(page), "My practice");
      assert.equal(seen.practice, 1, `which client the practice is was asked ${seen.practice} times`);
    },
  },
  {
    id: "statutory-from-the-menu-offers-the-firms-clients-only",
    title: "Payroll statutory from the menu: the practice is not offered, nothing is asked about it and no position is read",
    async run(env) {
      const { page } = env;
      const seen = aFirm(env);
      await page.goto(`${env.base}/payroll/statutory/`, { waitUntil: "networkidle" });
      await picker(page).waitFor();
      await settle(page);
      assert.equal(seen.practice, 0, "the practice was asked for by a screen nobody opened for it");
      assert.equal(seen.position.length, 0, "a position was read with no client chosen");
      await picker(page).click();
      const options = page.getByRole("option");
      await until(async () => (await options.count()) >= 1, "the client list to open");
      const names = await options.allInnerTexts();
      assert.ok(names.some((n) => n.includes(CLIENT_ROW.client_name)), `the firm's client is not offered: ${names}`);
      assert.ok(!names.some((n) => n.includes("My practice")), `the practice is offered from the menu: ${names}`);
    },
  },
  {
    id: "an-address-that-names-the-practice-opens-nothing-for-a-manager-and-a-stray-id-opens-nothing-for-anybody",
    title: "Payroll statutory > ?client=: a Manager who names the practice is shown nothing of it and the practice is never asked for; an id that is nobody's chooses nothing",
    async run(env) {
      const { page } = env;
      const seen = aFirm(env);
      env.stub.signInAs("Manager");
      await page.goto(`${env.base}/payroll/statutory/?client=${PRACTICE_ID}`, { waitUntil: "networkidle" });
      await picker(page).waitFor();
      await settle(page);
      assert.equal(seen.practice, 0, "a Manager's screen asked which client the practice is");
      assert.equal(seen.position.length, 0, "a Manager's screen asked for the practice's position");
      assert.ok(!(await shown(page)).includes("My practice"), "a Manager is shown the practice as chosen");

      env.stub.signInAs("Partner");
      await page.goto(`${env.base}/payroll/statutory/?client=00000000-0000-4000-8000-000000000000`, { waitUntil: "networkidle" });
      await picker(page).waitFor();
      await until(() => seen.practice >= 1, "a Partner's screen to ask which client the practice is");
      await settle(page);
      assert.equal(seen.position.length, 0, "a position was read for an id that is nobody's");
      assert.ok(!(await shown(page)).includes("My practice"), "an id that is nobody's is named My practice");
    },
  },
  {
    id: "declarations-opened-for-the-practice-reads-the-practices-own",
    title: "Investment declarations > ?client=<the practice>: the picker reads My practice, and the declarations and employees read are the practice's",
    async run(env) {
      const { page } = env;
      const seen = aFirm(env);
      await page.goto(`${env.base}/payroll/declarations/?client=${PRACTICE_ID}`, { waitUntil: "networkidle" });
      await until(() => seen.declarations.length >= 1 && seen.employees.length >= 1, "the practice's declarations and employees to be asked for");
      assert.equal(clientOf(seen.declarations.at(-1)), PRACTICE_ID);
      assert.equal(clientOf(seen.employees.at(-1)), PRACTICE_ID);
      assert.equal(await shown(page), "My practice");
    },
  },
  {
    id: "reports-opened-for-the-practice-reads-one-clients-rows-and-says-so",
    title: "Payroll reports > ?client=<the practice>: employees, runs and the year are the practice's and the screen says it shows My practice only; from the menu no client is named",
    async run(env) {
      const { page } = env;
      const seen = aFirm(env);
      await page.goto(`${env.base}/payroll/reports/?client=${PRACTICE_ID}`, { waitUntil: "networkidle" });
      const line = page.locator("[data-reports-for]");
      await line.waitFor({ timeout: 15000 });
      assert.equal(await line.getAttribute("data-reports-for"), PRACTICE_ID);
      assert.match((await line.innerText()).replace(/\s+/g, " "), /^Showing My practice only\. Show every client$/);
      assert.equal(await line.getByRole("link", { name: "Show every client" }).getAttribute("href"), "/payroll/reports/");
      assert.deepEqual(seen.employees.map(clientOf), [PRACTICE_ID], "the employees were read more than once, or not for the practice");
      assert.deepEqual(seen.runs.map(clientOf), [PRACTICE_ID], "the runs were read more than once, or not for the practice");
      await page.getByRole("tab", { name: /Year End Summary/ }).click();
      await until(() => seen.yearEnd.length >= 1, "the year to be asked for");
      assert.equal(clientOf(seen.yearEnd.at(-1)), PRACTICE_ID, "the year-end summary is the firm's and not the practice's");

      // From the menu: the firm's rows, with no client named, and no line.
      seen.employees.length = 0; seen.runs.length = 0; seen.yearEnd.length = 0; seen.practice = 0;
      await page.goto(`${env.base}/payroll/reports/`, { waitUntil: "networkidle" });
      await page.getByRole("tab", { name: /Year End Summary/ }).waitFor({ timeout: 15000 });
      assert.equal(await page.locator("[data-reports-for]").count(), 0);
      assert.deepEqual(seen.employees.map(clientOf), [null]);
      assert.deepEqual(seen.runs.map(clientOf), [null]);
      assert.equal(seen.practice, 0, "the practice was asked for by a screen nobody opened for it");
      await page.getByRole("tab", { name: /Year End Summary/ }).click();
      await until(() => seen.yearEnd.length >= 1, "the firm's year to be asked for");
      assert.equal(clientOf(seen.yearEnd.at(-1)), null);
    },
  },
  {
    id: "the-practices-own-payroll-page-links-the-four-screens-and-a-clients-does-not",
    title: "the practice's Payroll page: four links, each with the practice in the address; an ordinary client's Payroll page has none",
    async run(env) {
      const { page, stub } = env;
      aFirm(env);
      stub.setTable("clients", [{ ...CLIENT_ROW, client_name: "Sharma & Co", is_internal: true }]);
      stub.route({ method: "GET", re: /api\/payroll\/practice-staff$/, reply: () => ok({ practice_client_id: env.clientId, payroll_enabled: true, employees: [] }) });
      await page.goto(env.at("/payroll/?tab=inputs"), { waitUntil: "networkidle" });
      const links = page.locator("[data-own-payroll-screens]");
      await links.waitFor({ timeout: 15000 });
      const want = { "Attendance": "/payroll/attendance/", "Statutory position": "/payroll/statutory/", "Investment declarations": "/payroll/declarations/", "Reports": "/payroll/reports/" };
      for (const [name, path] of Object.entries(want)) {
        assert.equal(await links.getByRole("link", { name, exact: true }).getAttribute("href"), `${path}?client=${env.clientId}`);
      }
      assert.equal(await links.getByRole("link").count(), 4);

      stub.setTable("clients", [{ ...CLIENT_ROW }]);
      await page.goto(env.at("/payroll/?tab=inputs"), { waitUntil: "networkidle" });
      await page.getByRole("button", { name: /Setup/ }).first().waitFor({ timeout: 15000 });
      assert.equal(await page.locator("[data-own-payroll-screens]").count(), 0, "an ordinary client's Payroll page offers the practice's links");
    },
  },
];
