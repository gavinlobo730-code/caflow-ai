/**
 * Group J: five lists that stop at a number say so, from the server's answer and never from a row count (POST-A-262).
 *
 * The login history, the workflow approvals, the firm's HSN/SAC library and the memory screen's profiles and anomalies each
 * decided "this list was cut short" by comparing the rows they got to the number they had asked for. A source guard can read
 * that the comparison is gone; this drives what a CA sees: the sentence appears only when the server says more exist, "Show
 * more" asks for a bigger window where the server allows one, a list at its ceiling says where to go instead, and the HSN
 * library's Archived tab asks the server for retired codes rather than filtering a window of everything.
 */
import assert from "node:assert/strict";
import { ok } from "../stub.mjs";

export const group = "windows";

const win = (rowsField, rows, { hasMore, limit, max }) =>
  ok({ [rowsField]: rows, returned: rows.length, has_more: hasMore, limit, max_limit: max });

const EVENTS = [
  { id: "e1", email: "asha@firm.in", event: "login", ip: "10.0.0.1", created_at: "2026-10-18T04:00:00Z" },
  { id: "e2", email: "ravi@firm.in", event: "logout", ip: "10.0.0.2", created_at: "2026-10-18T03:00:00Z" },
  { id: "e3", email: "meera@firm.in", event: "failed_login", ip: "10.0.0.3", created_at: "2026-10-18T02:00:00Z" },
];

const APPROVALS = [
  { id: "a1", instance_id: "i1", firm_id: "f", approver_role: "Partner", status: "pending", title: "Approve GSTR-3B for Acme",
    context_data: {}, due_at: "2099-01-01T00:00:00Z", template_name: "GST filing" },
  { id: "a2", instance_id: "i2", firm_id: "f", approver_role: "Partner", status: "pending", title: "Approve TDS return for Beta",
    context_data: {}, due_at: "2099-01-02T00:00:00Z", template_name: "TDS filing" },
];

const CODES = [
  { id: "h1", hsn_code: "1001", description: "Wheat", hsn_type: "goods", gst_rate_pct: 0, uqc: "KGS", is_active: false },
  { id: "h2", hsn_code: "9983", description: "Advice", hsn_type: "services", gst_rate_pct: 18, uqc: "OTH", is_active: false },
];

function track(env, re, reply) {
  const asked = [];
  env.stub.route({
    method: "GET", re,
    reply: (req, body, url) => { asked.push(Object.fromEntries(url.searchParams)); return reply(asked.length, url); },
  });
  return asked;
}

export const scenarios = [
  {
    id: "login-history-says-it-stopped-and-show-more-asks-for-a-bigger-window",
    title: "the login history says older events exist only when the server says so, and Show more reads again with a larger limit",
    async run(env) {
      const { page } = env;
      const asked = track(env, /identity\/login-history/, (n) =>
        win("events", EVENTS, { hasMore: n < 2, limit: n < 2 ? 200 : 300, max: 1000 }));
      await page.goto(`${env.base}/team/login-history/`, { waitUntil: "networkidle" });
      await page.getByText("asha@firm.in").waitFor();
      assert.equal(asked[0].limit, "200");
      let body = await page.locator("body").innerText();
      assert.match(body, /Showing the latest 3 login events\. More exist that are not shown here\./);
      assert.match(body, /3\+ events/, "the count does not say it is a lower bound");
      await page.getByRole("button", { name: "Show more" }).click();
      await page.waitForLoadState("networkidle");
      assert.equal(asked.length, 2, `Show more should read once more, saw ${asked.length} reads`);
      assert.equal(asked[1].limit, "300", "the next window is one step larger");
      body = await page.locator("body").innerText();
      assert.doesNotMatch(body, /More exist that are not shown here/, "the server said nothing more exists");
      assert.match(body, /3 events/);
    },
  },
  {
    id: "a-whole-login-history-is-not-reported-as-cut-short",
    title: "a list the server says is whole says nothing, even when it is exactly as long as the first window",
    async run(env) {
      const { page } = env;
      const full = Array.from({ length: 200 }, (_, i) => ({ id: `x${i}`, email: `u${i}@firm.in`, event: "login", created_at: "2026-10-18T04:00:00Z" }));
      track(env, /identity\/login-history/, () => win("events", full, { hasMore: false, limit: 200, max: 1000 }));
      await page.goto(`${env.base}/team/login-history/`, { waitUntil: "networkidle" });
      await page.getByText("u0@firm.in").waitFor();
      const body = await page.locator("body").innerText();
      assert.doesNotMatch(body, /More exist that are not shown here/, "a list of exactly 200 rows was reported as cut short");
      assert.match(body, /200 events/);
    },
  },
  {
    id: "approvals-at-the-servers-ceiling-say-where-to-go-and-offer-no-show-more",
    title: "a pending queue longer than the server's 200 says so, offers no button that does nothing, and says what makes the next ones appear",
    async run(env) {
      const { page } = env;
      const asked = track(env, /workflows\/approvals/, () => win("approvals", APPROVALS, { hasMore: true, limit: 200, max: 200 }));
      await page.goto(`${env.base}/workflows/approvals/`, { waitUntil: "networkidle" });
      await page.getByText("Approve GSTR-3B for Acme").waitFor();
      assert.equal(asked[0].limit, "200");
      assert.equal(asked[0].status, "pending");
      const body = await page.locator("body").innerText();
      assert.match(body, /Showing the latest 2 approvals\. More exist that are not shown here\./);
      assert.match(body, /Respond to these and the next ones will appear\./);
      assert.equal(await page.getByRole("button", { name: "Show more" }).count(), 0, "a Show more that cannot grow the window is offered");
    },
  },
  {
    id: "a-failed-approvals-read-is-said-and-is-never-an-empty-queue",
    title: "an approvals read that failed says so and does not draw 'No pending approvals'",
    async run(env) {
      const { page } = env;
      track(env, /workflows\/approvals/, () => ({ success: false, data: null, error: "The approvals could not be read." }));
      await page.goto(`${env.base}/workflows/approvals/`, { waitUntil: "networkidle" });
      await page.getByText("The approvals could not be read.").waitFor();
      assert.equal(await page.getByText(/No pending approvals/).count(), 0);
    },
  },
  {
    id: "the-archived-tab-asks-the-server-for-retired-codes",
    title: "the HSN library's Archived tab asks for retired codes and lists what comes back, with the window sentence from the server",
    async run(env) {
      const { page } = env;
      const asked = track(env, /firm-hsn-library\/?(\?|$)/, (n, url) =>
        url.searchParams.get("archived_only") === "true"
          ? win("codes", CODES, { hasMore: true, limit: 200, max: 200 })
          : win("codes", [], { hasMore: false, limit: 200, max: 200 }));
      await page.goto(`${env.base}/settings/firm-hsn-library/`, { waitUntil: "networkidle" });
      await page.getByRole("button", { name: /^archived$/i }).click();
      await page.getByText("Wheat").waitFor();
      const last = asked[asked.length - 1];
      assert.equal(last.archived_only, "true", "the Archived tab did not ask the server for retired codes only");
      assert.equal(last.limit, "200");
      assert.equal(last.include_archived, undefined, "the tab asked for everything and filtered in the browser");
      const body = await page.locator("body").innerText();
      assert.match(body, /Showing the first 2 codes, in code order\. More exist that are not shown here\./);
      assert.match(body, /2\+ codes/);
    },
  },
  {
    id: "memory-profiles-and-anomalies-say-when-more-exist",
    title: "the memory screen's two cut-short lists carry the server's sentence, not a hard-coded 'first 100'",
    async run(env) {
      const { page } = env;
      track(env, /memory\/triggers/, () => ok({ triggers: [], returned: 0, has_more: false, limit: 50, max_limit: 100 }));
      track(env, /memory\/profiles/, () => win("profiles", [{
        id: "p1", client_id: "c1", compliance_score: 41, portal_engagement: 50, doc_upload_reliability: 60,
        recurring_issues: [], missed_deadline_count: 2, last_computed_at: "2026-10-17T05:00:00Z" }],
      { hasMore: true, limit: 100, max: 100 }));
      track(env, /memory\/anomalies/, () => win("anomalies", [{
        id: "n1", client_id: "c1", anomaly_type: "revenue_spike", metric_name: "gst_liability", baseline_value: 100,
        actual_value: 400, deviation_pct: 300, deviation_score: 3, period: "2026-09", explanation: "GST liability spiked",
        evidence: [], status: "open", created_at: "2026-10-17T05:00:00Z" }],
      { hasMore: false, limit: 100, max: 100 }));
      await page.goto(`${env.base}/memory/`, { waitUntil: "networkidle" });
      await page.getByRole("button", { name: /Client Profiles/ }).click();
      await page.getByText(/1\+ client profile/).waitFor();
      let body = await page.locator("body").innerText();
      assert.match(body, /Showing the first 1 client profiles, lowest compliance score first\. More exist that are not shown here\./);
      assert.doesNotMatch(body, /showing the first 100/, "the hard-coded sentence is back");
      await page.getByRole("button", { name: /Anomalies/ }).click();
      await page.getByText(/1 open anomal/).waitFor();
      body = await page.locator("body").innerText();
      assert.doesNotMatch(body, /More exist that are not shown here/, "a whole anomaly list was reported as cut short");
    },
  },
];
