/**
 * Group: the buttons converted to single-flight on 31-10-2026, double-clicked in one tick (POST-A-396, part 1).
 *
 * Thirty-three buttons were moved onto the shared `<Button>` (components/ui/button.tsx), which ignores a second click while the promise its
 * handler returned is out, when the repeat-click scan learned to follow a write into `lib/`. The scan holds that each IS a `<Button>` whose
 * handler returns its promise; nothing pressed one twice. A double click on GSTR-1 Mark filed records the filing twice and locks the period
 * twice; a double click on a client's permanent delete sends two deletes. One scenario per family, each pressing the control twice inside one
 * evaluate (`sameTickDouble`, kit.mjs, the defect reproduced) against the stub's 700 ms hold, and counting the writes the STUB saw:
 *
 *   * the GST returns: GSTR-1 Build, CA Approve and Confirm Filed; GSTR-3B Confirm Filed;
 *   * the TDS returns: Compute 26Q, CA Approve and Confirm Filed;
 *   * a client's lifecycle: Archive and Delete Permanently;
 *   * the deletes: a task's delete (it takes the row off the list at once, so the second press lands on a row already gone from the state);
 *   * the removals: a capital-gains record's delete, whose second press must not open a second confirmation;
 *   * the AIS decisions: Accept on a statement line;
 *   * the worksheet saves: the house property worksheet's Save and work out.
 *
 * The time, template and notice deletes and the challan removal are the same `<Button>` with the same shape of handler and are not driven one
 * by one: the family is.
 */
import assert from "node:assert/strict";
import { expectWrites, sameTickDouble, until } from "../kit.mjs";
import { ok } from "../stub.mjs";
import { CLIENT_ID, CLIENT_ROW } from "../fixtures.mjs";
import {
  atGstr1, atTdsReturns, openCapitalGainsRegisterTab, openGstr3bMarkFiled, openHousePropertyWorksheet, typeAndLeave,
} from "./dates.mjs";

export const group = "held-clicks";

const FIRM = "00000000-0000-4000-8000-0000000000f1";

export const scenarios = [
  {
    id: "gstr1-build-approve-and-mark-filed-each-write-once",
    title: "GST > GSTR-1: Build, CA Approve and Confirm Filed, each pressed twice in one tick, each write once",
    async run(env) {
      const { page, stub } = env;
      await atGstr1(env);
      await sameTickDouble(page.getByRole("button", { name: "Build GSTR-1", exact: true }));
      await expectWrites(stub, /api\/gst\/gstr1\/from-books$/, 1, "Build GSTR-1 pressed twice", "POST");
      stub.forgetWrites();
      await sameTickDouble(page.getByRole("button", { name: "CA Approve", exact: true }));
      await expectWrites(stub, /gst-workspace\/gstr1\/g1-1\/status$/, 1, "CA Approve pressed twice", "PATCH");
      stub.forgetWrites();
      await page.getByRole("button", { name: "Mark as Filed", exact: true }).click();
      await page.getByLabel("ARN (Acknowledgment Reference Number)", { exact: true }).fill("AA2710260000001");
      await typeAndLeave(page.locator("#gstr1-filed-date"), "07/10/2026");
      await sameTickDouble(page.getByRole("button", { name: "Confirm Filed", exact: true }));
      await expectWrites(stub, /gst-workspace\/gstr1\/g1-1\/status$/, 1, "Confirm Filed pressed twice on GSTR-1", "PATCH");
      assert.equal(JSON.parse(stub.writesTo(/gstr1\/g1-1\/status$/, "PATCH")[0].body).status, "submitted", "the one write was not the filing");
    },
  },
  {
    id: "gstr3b-mark-filed-writes-once",
    title: "GST > GSTR-3B > Mark as Filed: Confirm Filed pressed twice in one tick records the filing once",
    async run(env) {
      const { page, stub } = env;
      await openGstr3bMarkFiled(env);
      await typeAndLeave(page.locator("#gstr3b-filed-date"), "07/10/2026");
      await sameTickDouble(page.getByRole("button", { name: "Confirm Filed", exact: true }));
      await expectWrites(stub, /gst-workspace\/gstr3b\/g3-1\/status$/, 1, "Confirm Filed pressed twice on GSTR-3B", "PATCH");
    },
  },
  {
    id: "tds-return-compute-approve-and-mark-filed-each-write-once",
    title: "TDS > Returns: Compute 26Q, CA Approve and Confirm Filed, each pressed twice in one tick, each write once",
    async run(env) {
      const { page, stub } = env;
      await atTdsReturns(env);
      await sameTickDouble(page.getByRole("button", { name: "Compute 26Q", exact: true }));
      await expectWrites(stub, /api\/tds\/26q\/from-books$/, 1, "Compute 26Q pressed twice", "POST");
      await page.getByRole("button", { name: "CA Approve", exact: true }).waitFor();
      stub.forgetWrites();
      await sameTickDouble(page.getByRole("button", { name: "CA Approve", exact: true }));
      // Approve may save the statement and moves its status: whatever it writes, it writes once.
      await stub.quiet();
      const saves = stub.writesTo(/api\/tds-workspace\/returns$/, "POST").length;
      const moves = stub.writesTo(/api\/tds-workspace\/returns\/tr-1\/status$/, "PATCH").length;
      assert.ok(saves + moves > 0, "CA Approve wrote nothing");
      assert.ok(saves <= 1 && moves <= 1, `CA Approve pressed twice wrote ${saves} save(s) and ${moves} status move(s)`);
      stub.forgetWrites();
      await page.getByRole("button", { name: "Mark as Filed", exact: true }).click();
      await page.getByLabel("PRN (Provisional Receipt Number)", { exact: true }).fill("PRN0000000001");
      await typeAndLeave(page.locator("#tds-filing-date"), "07/10/2026");
      await sameTickDouble(page.getByRole("button", { name: "Confirm Filed", exact: true }));
      await expectWrites(stub, /api\/tds-workspace\/returns\/tr-1\/status$/, 1, "Confirm Filed pressed twice on a TDS return", "PATCH");
    },
  },
  {
    id: "a-clients-archive-and-permanent-delete-each-write-once",
    title: "Clients > a client's menu: Archive and Delete Permanently, each pressed twice in one tick, each write once",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "POST", re: new RegExp(`/api/clients/${CLIENT_ID}/archive$`), reply: () => ok({ id: CLIENT_ID, status: "archived" }) });
      stub.route({ method: "DELETE", re: new RegExp(`/api/clients/${CLIENT_ID}$`), reply: () => ok(null) });
      await page.goto(`${env.base}/clients/`, { waitUntil: "networkidle" });
      const row = page.locator("tr, [role=row], a, div").filter({ hasText: CLIENT_ROW.client_name }).filter({ has: page.getByTitle("More actions") }).last();
      const openMenu = async () => { await row.hover(); await row.getByTitle("More actions").click(); };
      await openMenu();
      // "Archive" exactly: the page's "Archived" tab is a button too.
      await page.getByRole("button", { name: "Archive", exact: true }).first().click();
      await sameTickDouble(page.getByRole("button", { name: "Archive", exact: true }).last());
      await expectWrites(stub, new RegExp(`/api/clients/${CLIENT_ID}/archive$`), 1, "Archive pressed twice", "POST");
      stub.forgetWrites();
      await until(async () => (await page.getByRole("heading", { name: "Archive Client" }).count()) === 0, "the archive dialog to close");
      await openMenu();
      await page.getByRole("button", { name: /Permanent Delete/ }).click();
      await page.getByLabel(`Type ${CLIENT_ROW.client_name} to confirm`).fill(CLIENT_ROW.client_name);
      await sameTickDouble(page.getByRole("button", { name: "Delete Permanently", exact: true }));
      await expectWrites(stub, new RegExp(`/api/clients/${CLIENT_ID}$`), 1, "Delete Permanently pressed twice", "DELETE");
    },
  },
  {
    id: "a-tasks-delete-writes-once",
    title: "Tasks: a row's Delete pressed twice in one tick deletes the task once",
    async run(env) {
      const { page, stub } = env;
      stub.setTable("tasks", [{ id: "t-1", firm_id: FIRM, client_id: CLIENT_ID, title: "Reconcile the September bank", description: null, status: "todo", priority: "medium",
        due_date: "2026-10-20", assigned_to: null, created_by: null, created_at: "2026-10-01T05:00:00Z", updated_at: "2026-10-01T05:00:00Z", deleted_at: null, clients: { client_name: CLIENT_ROW.client_name } }]);
      stub.route({ method: "DELETE", re: /\/api\/tasks\/t-1$/, reply: () => ok(null) });
      await page.goto(`${env.base}/tasks/`, { waitUntil: "networkidle" });
      const row = page.locator("tr", { hasText: "Reconcile the September bank" }).first();
      await row.waitFor();
      await sameTickDouble(row.getByTitle("Delete"));
      await expectWrites(stub, /\/api\/tasks\/t-1$/, 1, "a task's Delete pressed twice", "DELETE");
    },
  },
  {
    id: "a-capital-gains-records-delete-asks-once-and-deletes-once",
    title: "Capital gains > Register: a record's delete pressed twice in one tick opens ONE confirmation, and Delete removes it once",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "GET", re: /api\/income-tax\/capital-gains\?/, reply: () => ok([{
        id: "cg-1", client_id: CLIENT_ID, asset_description: "Equity shares of Alpha Ltd", asset_type: "listed_equity", purchase_date: "2024-04-10", sale_date: "2026-08-14",
        purchase_cost_paise: 10000000, improvement_cost_paise: 0, sale_value_paise: 15000000, indexed_cost_paise: null, gain_type: "LTCG", tax_rate_percent: 12.5,
        transferred_asset_nature: null, is_listed_security: true, fmv_31_01_2018_paise: null, created_at: "2026-09-01T05:00:00Z" }]) });
      stub.route({ method: "DELETE", re: /api\/income-tax\/capital-gains\/cg-1$/, reply: () => ok(null) });
      await openCapitalGainsRegisterTab(env);
      const remove = page.getByRole("button", { name: "Delete Equity shares of Alpha Ltd", exact: true });
      await remove.waitFor();
      await sameTickDouble(remove);
      // The in-app confirmation is an alertdialog.
      const asks = page.getByRole("alertdialog");
      await asks.last().waitFor();
      await page.waitForTimeout(300);
      assert.equal(await asks.count(), 1, "the delete pressed twice opened two confirmations");
      await asks.last().getByRole("button", { name: "Delete", exact: true }).click();
      await expectWrites(stub, /api\/income-tax\/capital-gains\/cg-1$/, 1, "a capital-gains record's delete pressed twice", "DELETE");
      await until(async () => (await asks.count()) === 0, "no second confirmation to follow the first");
    },
  },
  {
    id: "an-ais-lines-accept-writes-once",
    title: "Tax > Computation > Working papers: Accept on an AIS line pressed twice in one tick records the decision once",
    async run(env) {
      const { page, stub } = env;
      const line = { line_key: "sft-005:int", bucket: "Interest from deposits", target: "other_income", target_label: "Income from other sources", amount_paise: 4500000, tds_paise: 450000,
        sources: [{ payer: "State Bank of India", label: "Interest from deposit", amount_paise: 4500000, source: "SFT-005" }], state: "suggested", decided_at: null, decided_amount_paise: null };
      stub.route({ method: "GET", re: /api\/ais\/computation-lines\?/, reply: () => ok({ financial_year: "2026-27", assessment_year: "2027-28", has_statement: true,
        upload: { id: "ais-1", file_name: "ais.json", created_at: "2026-09-30T05:00:00Z" }, lines: [line],
        targets: [{ target: "other_income", label: "Income from other sources", ais_paise: 4500000, accept_paise: 0, typed_paise: null, differs: false, difference_paise: null }], refused: [], gaps: [] }) });
      stub.route({ method: "PUT", re: /api\/ais\/computation-lines\/[^/]+\/decision$/, reply: () => ok({ ...line, state: "accepted", decided_at: "2026-10-08T08:00:00Z", decided_amount_paise: 4500000 }) });
      await openHousePropertyWorksheet(env);
      const accept = page.getByRole("button", { name: "Accept", exact: true }).first();
      await accept.waitFor();
      await sameTickDouble(accept);
      await expectWrites(stub, /api\/ais\/computation-lines\/[^/]+\/decision$/, 1, "Accept pressed twice on an AIS line", "PUT");
    },
  },
  {
    id: "the-house-property-worksheets-save-writes-once",
    title: "Tax > Computation > Working papers > House property: Save and work out pressed twice in one tick saves once",
    async run(env) {
      const { page, stub } = env;
      await openHousePropertyWorksheet(env);
      await sameTickDouble(page.getByRole("button", { name: /Save and work out/ }).first());
      await expectWrites(stub, /income-tax\/worksheets\/house_property$/, 1, "Save and work out pressed twice", "PUT");
    },
  },
];
