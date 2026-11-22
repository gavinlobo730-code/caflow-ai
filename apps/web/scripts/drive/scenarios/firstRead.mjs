/**
 * Group: first-read. A reload a child asks for does not replace the screen with "Loading…" and unmount the child (POST-A-400).
 *
 * A screen that showed "Loading…" in place of itself on EVERY read unmounted whatever it had drawn when it read again, and the
 * children that save something ask for that read themselves. These drive the two kinds in Chromium:
 *
 *   1. the payroll roster's portal access dialog: sending an invitation asks the roster to read again, and the dialog then says
 *      where the invitation went. The reload used to unmount the dialog, so what it had to say was lost the moment it was made.
 *      Since POST-A-552 (22-11-2026) what it says is the address and nothing to copy: the link signs its holder in as the
 *      invitation's address, so the server mails it and returns it to nobody. This also holds that the dialog draws no link even
 *      when an answer carries one, sends no sign-in mail of its own from the browser, and says so when the server's mail did not go;
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
/** What an OLDER server's answer carried. The dialog must not draw it wherever it comes from. */
const LINK = "http://127.0.0.1:4319/portal/employee/activate/?token=one-time-token";
const NOT_SENT = "The invitation was created, but the email could not be sent: the mail service did not accept it. Send the invitation again; if it fails again, this deployment's mail is not reaching the mail service.";
/** Every request the browser made to Supabase's own sign-in service for a one-time code (the mail this dialog used to ask for). */
function otpRequests(page) {
  const seen = [];
  page.on("request", (r) => { if (/\/auth\/v1\/otp/.test(r.url())) seen.push(r.url()); });
  return seen;
}

export const scenarios = [
  {
    id: "an-invitation-sent-from-the-roster-keeps-its-dialog-and-shows-no-link",
    title: "sending a portal invitation reads the roster again and the dialog stays, saying where it went, with no link to copy and no sign-in mail asked for from the browser",
    async run({ page, stub, base }) {
      let reads = 0;
      const otp = otpRequests(page);
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
        // The answer of today's server, AND the two fields an older one sent: the dialog must draw neither.
        reply: () => ok({ employee_id: "emp-1", email: "asha@example.com", mail: { sent: true, problem: null }, token: "one-time-token", activation_url: LINK }),
      });

      await page.goto(`${base}/payroll/people/`, { waitUntil: "networkidle" });
      await page.getByRole("button", { name: "Give access" }).first().click();
      await page.getByLabel("Their email address").fill("asha@example.com");
      await page.getByRole("button", { name: "Send invitation" }).click();

      await until(async () => reads >= 2, "the roster to be read again after the invitation");
      const said = page.locator("[data-invitation-sent]");
      await said.waitFor({ timeout: 5000 });
      assert.match((await said.innerText()).replace(/\s+/g, " "), /^Invitation sent to asha@example\.com\. The link in the email signs them in, works once and lasts 14 days\./,
        "the dialog lost what it had to say to the reload it asked for");
      assert.equal(await page.getByText("Loading the roster…").count(), 0, "the roster blanked for a read after the first");
      // Nothing to copy, anywhere on the page: no field, no text, no attribute holds the link or its token.
      assert.equal(await page.getByLabel("Invitation link").count(), 0, "the dialog still offers the link to copy");
      const html = await page.content();
      assert.ok(!html.includes("one-time-token") && !html.includes("activate/?token"), "the invitation's link or token is on the page");
      assert.equal(await page.getByRole("button", { name: "Copy" }).count(), 0, "a Copy button is still drawn");
      assert.deepEqual(otp, [], "the browser asked Supabase to mail a sign-in link of its own");
    },
  },
  {
    id: "an-invitation-whose-mail-did-not-go-says-so-and-can-be-sent-again",
    title: "when the server's mail did not go, the dialog says so as an alert, says nothing was sent, and the form is still there to send again",
    async run({ page, stub, base }) {
      const otp = otpRequests(page);
      let sends = 0;
      stub.route({ method: "GET", re: /\/api\/clients$/, reply: () => ok({ clients: [CLIENT_ROW], total: 1 }) });
      stub.route({ method: "GET", re: /\/api\/payroll\/employees(\?|$)/, reply: () => ok([EMPLOYEE]) });
      stub.route({
        method: "GET", re: /\/api\/payroll\/employees\/emp-1\/portal-status$/,
        reply: () => ok({ employee_id: "emp-1", email: null, portal_enabled: false, activated: false, invite_pending: false,
                          invited_at: null, invite_expires_at: null, activated_at: null }),
      });
      stub.route({
        method: "POST", re: /\/api\/payroll\/employees\/emp-1\/portal-invite$/,
        reply: () => { sends += 1; return ok({ employee_id: "emp-1", email: "asha@example.com", mail: sends === 1 ? { sent: false, problem: NOT_SENT } : { sent: true, problem: null } }); },
      });

      await page.goto(`${base}/payroll/people/`, { waitUntil: "networkidle" });
      await page.getByRole("button", { name: "Give access" }).first().click();
      await page.getByLabel("Their email address").fill("asha@example.com");
      await page.getByRole("button", { name: "Send invitation" }).click();

      const alert = page.getByRole("alert").filter({ hasText: "could not be sent" });
      await alert.waitFor({ timeout: 5000 });
      assert.equal((await alert.innerText()).trim(), NOT_SENT);
      assert.equal(await page.locator("[data-invitation-sent]").count(), 0, "the dialog says the invitation was sent when its mail did not go");
      assert.equal(await page.getByText("Invitation sent to").count(), 0, "a line on the page says the invitation was sent");
      // The invitation exists, so the button now says what pressing it does, and pressing it sends again.
      const again = page.getByRole("button", { name: "Send a new invitation" });
      await again.waitFor({ timeout: 5000 });
      await again.click();
      await page.locator("[data-invitation-sent]").waitFor({ timeout: 5000 });
      assert.equal(sends, 2, `expected two invitations, there were ${sends}`);
      assert.equal(await alert.count(), 0, "the earlier refusal is still on the screen after the mail went");
      assert.deepEqual(otp, [], "the browser asked Supabase to mail a sign-in link of its own");
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
