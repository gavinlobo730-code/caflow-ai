/**
 * Group: first-read. A reload a child asks for does not replace the screen with "Loading…" and unmount the child (POST-A-400).
 *
 * A screen that showed "Loading…" in place of itself on EVERY read unmounted whatever it had drawn when it read again, and the
 * children that save something ask for that read themselves. These drive the two kinds in Chromium:
 *
 *   1. the payroll roster's portal access dialog: sending an invitation asks the roster to read again, and the dialog then shows
 *      the one-time activation link to copy (it is returned once and cannot be fetched again). The reload used to unmount the
 *      dialog, so the link was lost the moment it was made;
 *   2. the deadlines list's Refresh: the table asks the page to read again, and the reload used to replace the page with a
 *      spinner, so the search typed into the table was thrown away with the table.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";
import { CLIENT_ROW } from "../fixtures.mjs";
import { ok } from "../stub.mjs";

export const group = "first-read";

const EMPLOYEE = {
  id: "emp-1", client_id: CLIENT_ROW.id, name: "Asha Rao", employee_code: "E001", designation: "Accountant",
  is_active: true, status: "active", portal_enabled: false, pan: null, uan: null, email: null,
};
const LINK = "http://127.0.0.1:4319/portal/employee/activate/?token=one-time-token";

export const scenarios = [
  {
    id: "an-invitation-sent-from-the-roster-keeps-its-dialog-and-its-one-time-link",
    title: "sending a portal invitation reads the roster again and the dialog stays, showing the one-time link to copy",
    async run({ page, stub, base }) {
      let reads = 0;
      stub.route({ method: "GET", re: /\/api\/clients$/, reply: () => ok({ clients: [CLIENT_ROW], total: 1 }) });
      stub.route({
        method: "GET", re: /\/api\/payroll\/employees(\?|$)/,
        reply: () => { reads += 1; return ok([EMPLOYEE]); },
      });
      stub.route({
        method: "GET", re: /\/api\/payroll\/employees\/emp-1\/portal-status$/,
        reply: () => ok({ employee_id: "emp-1", email: null, portal_enabled: false, activated: false, invite_pending: false,
                          invited_at: null, invite_expires_at: null, activated_at: null }),
      });
      stub.route({
        method: "POST", re: /\/api\/payroll\/employees\/emp-1\/portal-invite$/,
        reply: () => ok({ employee_id: "emp-1", email: "asha@example.com", token: "one-time-token", activation_url: LINK }),
      });

      await page.goto(`${base}/payroll/people/`, { waitUntil: "networkidle" });
      await page.getByRole("button", { name: "Give access" }).first().click();
      await page.getByLabel("Their email address").fill("asha@example.com");
      await page.getByRole("button", { name: "Send invitation" }).click();

      await until(async () => reads >= 2, "the roster to be read again after the invitation");
      const link = page.getByLabel("Invitation link");
      await link.waitFor({ timeout: 5000 });
      assert.equal(await link.inputValue(), LINK, "the dialog lost the one-time link to the reload it asked for");
      assert.equal(await page.getByText("Loading the roster…").count(), 0, "the roster blanked for a read after the first");
    },
  },
  {
    id: "refreshing-the-deadlines-list-keeps-the-search-typed-into-it",
    title: "the deadlines table's Refresh reads the list again and the table, with the search typed into it, stays drawn",
    async run({ page, stub, base }) {
      let reads = 0;
      stub.route({
        method: "GET", re: /compliance\/obligations(\?|$)/,
        reply: () => {
          reads += 1;
          return ok({ obligations: [{ id: "ob-1", client_id: CLIENT_ROW.id, compliance_type: "GST", obligation_type: "GSTR3B",
                                      status: "Pending", period_start: "2026-10-01", period_end: "2026-10-31",
                                      due_date: "2026-11-20", filed_date: null, acknowledgement_no: null, notes: null,
                                      period_label: "GSTR-3B October 2026" }], total: 1 });
        },
      });
      await page.goto(`${base}/deadlines/`, { waitUntil: "networkidle" });
      const search = page.getByPlaceholder("Search by client name or GSTIN…");
      await search.waitFor();
      await search.fill("GSTR");
      const before = reads;
      const handle = await search.elementHandle();

      await page.getByRole("button", { name: "Refresh" }).click();
      await until(async () => reads > before, "the list to be read again");
      await page.waitForLoadState("networkidle");

      assert.equal(await handle.evaluate((el) => el.isConnected), true, "the table was unmounted by the reload its Refresh asked for");
      assert.equal(await search.inputValue(), "GSTR", "the search typed into the table was lost");
    },
  },
];
