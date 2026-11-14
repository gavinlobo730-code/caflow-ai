/**
 * Group: a ledger row that names a settlement or a year-end adjustment opens it, and an AR ageing bucket opens to its invoices
 * (POST-A-096 and POST-A-099, driven in a browser).
 *
 * The source guards read that the route map sends both sources somewhere and that the receivables page links through
 * practiceSalesHref; this drives what a person sees. A settlement arrives on the payroll Inputs tab and is shown AS RECORDED,
 * and closing it takes `doc` off the address; a run's id on the Register tab is never read as a settlement's; the year-end list
 * asks whose engagement an adjustment is in and goes there with the adjustment ringed, or says the server's sentence; a bucket
 * opens to its invoices, most overdue first, linked into the practice's books, and says when its list was cut.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";
import { ok, refuse } from "../stub.mjs";

export const group = "open-the-document";

const SETTLEMENT = {
  settlement_id: "S1", employee_id: "E1",
  employee: { id: "E1", name: "Ravi Kumar", employee_code: "EMP-7", status: "resigned" },
  financial_year: "2026-27", leaving_date: "2026-10-31",
  gross_paise: 50_000_00, exempt_paise: 20_000_00, taxable_paise: 30_000_00, deductions_paise: 5_000_00,
  tds_paise: 1_500_00, net_paid_paise: 43_500_00, journal_entry_id: "J1", posted: true,
  recorded_at: "2026-11-01T20:00:00+00:00", recorded_by: "Asha Rao",
  components: [
    { kind: "earning", label: "Salary to the last day", gross_paise: 30_000_00, exempt_paise: 0, tax_head: "17(1)", exempt_section: "", statute: "" },
    { kind: "earning", label: "Gratuity", gross_paise: 20_000_00, exempt_paise: 20_000_00, tax_head: "17(3)", exempt_section: "10(10)", statute: "" },
    { kind: "deduction", label: "Notice pay recovered", gross_paise: 5_000_00, exempt_paise: 0, tax_head: "17(1)", exempt_section: "", statute: "" },
  ],
};

function payrollPermissions(stub) {
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { payroll: ["read", "write", "approve", "finalize"] } }) });
}

const text = (page) => page.locator("body").innerText();

const AGING = {
  buckets: {
    not_due: { paise: 0, count: 0 }, "0-30": { paise: 168_000, count: 3 }, "31-60": { paise: 0, count: 0 },
    "61-90": { paise: 0, count: 0 }, "90+": { paise: 60_000, count: 1 },
  },
  total_outstanding_paise: 228_000, overdue_paise: 228_000, overdue_count: 4,
  invoices_by_bucket: {
    not_due: { invoices: [], truncated: false },
    "0-30": { truncated: true, invoices: [
      { id: "inv-g", invoice_no: "FEE/26-27/0007", customer_id: "K1", customer_name: "Mehta Traders", invoice_date: "2026-06-01",
        ageing_from: "2026-06-11", days_overdue: 19, outstanding_paise: 30_000 },
      { id: "inv-a", invoice_no: "FEE/26-27/0003", customer_id: "K2", customer_name: null, invoice_date: "2026-03-01",
        ageing_from: "2026-06-20", days_overdue: 10, outstanding_paise: 118_000 },
    ] },
    "31-60": { invoices: [], truncated: false },
    "61-90": { invoices: [], truncated: false },
    "90+": { truncated: false, invoices: [
      { id: "inv-d", invoice_no: "FEE/25-26/0091", customer_id: "K1", customer_name: "Mehta Traders", invoice_date: "2025-12-01",
        ageing_from: "2026-01-01", days_overdue: 180, outstanding_paise: 60_000 },
    ] },
  },
  customer_names_read: false,
  list_cap: 2,
};

async function atTheReceivables(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { billing: ["read", "write"] } }) });
  stub.route({ method: "GET", re: /api\/billing\/ar-aging$/, reply: () => ok(AGING) });
  stub.route({ method: "GET", re: /api\/practice$/, reply: () => ok({ internal_client_id: "int-1", provisioned: true }) });
  await page.goto(`${env.base}/practice/ar/`, { waitUntil: "networkidle" });
  await page.getByRole("heading", { name: "AR Aging" }).waitFor();
}

export const scenarios = [
  {
    id: "a-ledger-rows-settlement-opens-on-the-payroll-inputs-tab-as-it-was-recorded",
    title: "?tab=inputs&doc=S1 shows the settlement as recorded: whose, its components in order, the recovery, the tax, what was paid and its ledger entry",
    async run(env) {
      const { page, stub } = env;
      payrollPermissions(stub);
      stub.route({ method: "GET", re: /api\/payroll\/settlements\/S1\?client_id=/, reply: () => ok(SETTLEMENT) });
      await page.goto(env.at("/payroll/?tab=inputs&doc=S1"), { waitUntil: "networkidle" });
      const dialog = page.getByRole("dialog", { name: "Recorded settlement" });
      await dialog.waitFor();
      await until(async () => /Ravi Kumar \(EMP-7\)/.test(await dialog.innerText()), "the employee named on the settlement");
      const body = await dialog.innerText();
      assert.match(body, /As it was recorded\. Nothing on this page is recomputed\./);
      assert.match(body, /02 Nov 2026 by Asha Rao/, "20:00 UTC on 1 November is 2 November in India");
      assert.ok(body.indexOf("Salary to the last day") < body.indexOf("Gratuity"), "the components are not in the order recorded");
      assert.match(body, /Notice pay recovered/);
      assert.match(body, /A recovery reduces what was paid\. It does not reduce the salary earned\./);
      assert.match(await dialog.getByTestId("settlement-net-paid").innerText(), /₹43,500\.00/);
      const ledger = dialog.getByRole("link", { name: "Open its ledger entry" });
      assert.match(await ledger.getAttribute("href"), /\/accounting\/journal\/J1\/edit\/?$/);
      await page.keyboard.press("Escape");
      await until(async () => (await page.getByRole("dialog", { name: "Recorded settlement" }).count()) === 0, "the dialog closed");
      await until(async () => !new URL(page.url()).searchParams.has("doc"), "doc taken off the address on close");
    },
  },
  {
    id: "a-settlement-the-server-refuses-is-said-in-its-words",
    title: "a settlement id the server does not find shows its sentence in the dialog, and nothing else",
    async run(env) {
      const { page, stub } = env;
      payrollPermissions(stub);
      stub.route({ method: "GET", re: /api\/payroll\/settlements\/S404\?client_id=/, ...refuse("Settlement not found", 404) });
      await page.goto(env.at("/payroll/?tab=inputs&doc=S404"), { waitUntil: "networkidle" });
      const dialog = page.getByRole("dialog", { name: "Recorded settlement" });
      await dialog.getByRole("alert").filter({ hasText: "Settlement not found" }).waitFor();
      assert.doesNotMatch(await dialog.innerText(), /₹/, "a refused settlement drew a figure");
    },
  },
  {
    id: "a-runs-id-on-the-register-tab-is-never-read-as-a-settlement",
    title: "?tab=register&doc=run-1, then the Inputs tab: no settlement dialog opens and no settlement is asked for",
    async run(env) {
      const { page, stub } = env;
      payrollPermissions(stub);
      stub.route({ method: "GET", re: /payroll\/runs\?/, reply: () => ok([]) });
      let asked = 0;
      stub.route({ method: "GET", re: /api\/payroll\/settlements\//, reply: () => { asked += 1; return ok(SETTLEMENT); } });
      await page.goto(env.at("/payroll/?tab=register&doc=run-1"), { waitUntil: "networkidle" });
      await page.getByRole("button", { name: "Inputs", exact: true }).click();
      // The Inputs tab is on screen: a dialog keyed on the wrong tab would have opened in the same render, and its read with it.
      await page.getByRole("button", { name: /Add Employee/ }).first().waitFor();
      assert.equal(await page.getByRole("dialog", { name: "Recorded settlement" }).count(), 0, "a run's id opened a settlement dialog");
      assert.equal(asked, 0, "a run's id was asked for as a settlement");
    },
  },
  {
    id: "a-ledger-rows-adjustment-goes-to-its-engagement-and-is-ringed",
    title: "?tab=adjustments&doc=adj-2 on the year-end list asks whose engagement it is, opens that engagement's Adjustments stage and rings the row",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { year_end: ["read", "write"] } }) });
      stub.route({ method: "GET", re: /api\/year-end\/adjustments\/adj-2\/engagement\?client_id=/, reply: () => ok({ adjustment_id: "adj-2", engagement_id: "eng-1", status: "posted" }) });
      stub.route({ method: "GET", re: /api\/year-end\/engagements\/eng-1$/, reply: () => ok({ id: "eng-1", client_id: env.clientId, financial_year: "2025-26", status: "locked", version: 1, created_at: "2026-04-05T00:00:00Z", updated_at: "2026-04-05T00:00:00Z" }) });
      stub.setTable("year_end_engagements", []);
      stub.setTable("year_end_adjustments", [
        { id: "adj-1", engagement_id: "eng-1", adjustment_type: "accrual", description: "Audit fee payable", amount_paise: 50_000_00, status: "posted", adjustment_date: "2026-03-31", created_at: "2026-04-10T05:00:00Z" },
        { id: "adj-2", engagement_id: "eng-1", adjustment_type: "provision", description: "Provision for gratuity", amount_paise: 1_20_000_00, status: "posted", adjustment_date: "2026-03-31", created_at: "2026-04-11T05:00:00Z" },
      ]);
      stub.setTable("chart_of_accounts", []);
      // Where the CA came from: Back from the adjustment must return here, not to the list (which would send them forward again).
      await page.goto(env.at("/accounting/?tab=ledger"), { waitUntil: "networkidle" });
      const cameFrom = new URL(page.url()).pathname;
      await page.goto(env.at("/year-end/?tab=adjustments&doc=adj-2"), { waitUntil: "networkidle" });
      await until(async () => /\/year-end\/eng-1\/?\?/.test(page.url()), "the list went on to the adjustment's engagement");
      const url = new URL(page.url());
      assert.equal(url.searchParams.get("tab"), "adjustments");
      assert.equal(url.searchParams.get("doc"), "adj-2");
      const ringed = page.locator('tr[data-ringed="true"]');
      await ringed.waitFor();
      assert.match(await ringed.innerText(), /Provision for gratuity/, "the wrong row is ringed");
      assert.equal(await page.locator('tr[data-ringed="true"]').count(), 1);
      await page.goBack({ waitUntil: "networkidle" });
      await until(async () => new URL(page.url()).pathname === cameFrom, `Back did not return to ${cameFrom} (it is at ${page.url()})`);
    },
  },
  {
    id: "an-adjustment-the-server-refuses-is-said-in-its-words-and-the-list-stays",
    title: "an adjustment id the server will not answer for shows its sentence on the year-end list, which does not move",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { year_end: ["read", "write"] } }) });
      stub.route({ method: "GET", re: /api\/year-end\/adjustments\/adj-x\/engagement\?client_id=/, ...refuse("Adjustment not found", 404) });
      stub.setTable("year_end_engagements", []);
      await page.goto(env.at("/year-end/?tab=adjustments&doc=adj-x"), { waitUntil: "networkidle" });
      await page.getByRole("alert").filter({ hasText: "Adjustment not found" }).waitFor();
      assert.match(new URL(page.url()).pathname, /\/year-end\/$/, "the list moved on a refusal");
    },
  },
  {
    id: "an-ageing-bucket-opens-to-its-invoices-most-overdue-first-and-says-when-the-list-stopped",
    title: "0-30 days opens to its invoices in the server's order, each linked into the practice's books; the cut list and the unread names are said",
    async run(env) {
      const { page } = env;
      await atTheReceivables(env);
      const opener = page.getByRole("button", { name: "0–30 days" });
      assert.equal(await opener.getAttribute("aria-expanded"), "false");
      await opener.click();
      assert.equal(await opener.getAttribute("aria-expanded"), "true");
      const list = page.locator("#ar-bucket-0-30");
      await list.waitFor();
      const body = await list.innerText();
      assert.ok(body.indexOf("FEE/26-27/0007") < body.indexOf("FEE/26-27/0003"), "the most overdue invoice is not first");
      assert.match(body, /Name not read/, "a name that could not be read was not said");
      assert.match(body, /Showing the 2 most overdue of the 3 invoices in this bucket\./);
      assert.match(body, /11 Jun 2026/);
      const href = await list.getByRole("link", { name: "FEE/26-27/0007" }).getAttribute("href");
      assert.match(href, /\/clients\/int-1\/sales\/?\?.*invoice=inv-g/, `the invoice did not link into the practice's books: ${href}`);
      // A bucket with nothing in it is not a control.
      assert.equal(await page.getByRole("button", { name: "31–60 days" }).count(), 0);
      await opener.click();
      assert.equal(await page.locator("#ar-bucket-0-30").count(), 0, "the bucket did not close");
      assert.doesNotMatch(await text(page), /undefined|NaN/);
    },
  },
];
