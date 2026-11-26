/**
 * A SCREEN BEHIND A TICK IS OFFERED, AND OPENS, BY THAT TICK (POST-A-543, the safety step), driven in a browser.
 *
 * Against a stubbed server, in Chromium, each person signed in with their role's OWN permissions (`stub.signInAs`):
 *
 *   1. an Executive is not offered Pipeline on the Clients page or Engagements under More; the Pipeline and Engagements
 *      addresses typed in say the screen is not part of their access, and the lists are never asked for; the Workflows
 *      screen shows no statistics tiles and no Analytics tab, and the statistics are never requested;
 *   2. a Manager is offered Pipeline and Engagements, both open, and Workflows shows its statistics;
 *   3. the related-party register says which answer the server gave (POST-A-544): part of the register when the server
 *      says `scoped`, the whole of it when the server says not, and nothing at all when the server did not say;
 *   4. a Reviewer has no Accounting and its addresses say so; a tick for accounting read puts it on the menu and opens it,
 *      and a screen in it that asks something more still says so;
 *   5. an Executive a Partner blocked from TDS is offered no TDS and the address says so, while GST is untouched;
 *   6. the Partner's tick screen: the permissions sit under the menu's own names, "Their menu" is the person's menu, an
 *      Allow or a Block moves the preview before anything is saved, and Save sends exactly the choices that changed;
 *   7. a Manager reads the Permissions tab and is not offered Edit, which the server would refuse on Save;
 *   8. Request access: the notice offers it, the request is exactly the permission the notice named with the person's
 *      note, and the notice then says it is waiting; somebody who already asked is not offered a second request; somebody
 *      a Partner declined is told the reason and may ask again; a refusal is shown in the server's words;
 *   9. a Partner sees the request in Approvals in a person's words, is asked before it is given, and the approval is sent.
 *
 * No scenario has a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import fs from "node:fs";
import { until } from "../kit.mjs";
import { ok } from "../stub.mjs";

export const group = "ticks";

const LEADS = /\/api\/lifecycle\/leads/;
const LETTERS = /\/api\/engagement-letters/;
const STATS = /\/api\/workflows\/analytics/;
const TEMPLATES = /\/api\/workflows\/templates/;
const firmMenuButton = (page) => page.locator('header button[aria-controls="workspace-menu"]');
const areas = (page) => page.locator('#workspace-menu nav[aria-label="Workspaces"]');
const areaNames = async (page) => (await areas(page).locator("[data-area]").allInnerTexts()).map((t) => t.trim());

// The Team screen's own reads, for the tick screen. The role maps are the server's (`role-permissions.json`).
const ROLE_MAPS = JSON.parse(fs.readFileSync(new URL("../role-permissions.json", import.meta.url), "utf8"));
const USERS = /\/api\/identity\/users$/;
const MEMBERS = [
  { id: "u-1", full_name: "Asha Rao", email: "asha@firm.example", role: "Partner", is_active: true, member_state: "active", created_at: "2026-04-01T00:00:00Z", auth_user_id: "a-1", firm_id: "f-1" },
  { id: "u-2", full_name: "Dev Mehta", email: "dev@firm.example", role: "Executive", is_active: true, member_state: "active", created_at: "2026-05-01T00:00:00Z", auth_user_id: "a-2", firm_id: "f-1" },
];
function teamReads(env) {
  const saved = { changes: null };
  const vocabulary = Object.entries(ROLE_MAPS.Partner).flatMap(([resource, actions]) =>
    actions.map((action) => ({ resource, action, privilege_changing: false, unrevokable_for_partner: false })));
  const gridFor = (id, overrides = {}) => {
    const member = MEMBERS.find((m) => m.id === id);
    const role_defaults = ROLE_MAPS[member.role];
    return { user_id: id, full_name: member.full_name, email: member.email, role: member.role, role_defaults, overrides, effective: role_defaults };
  };
  env.stub.route({ method: "GET", re: USERS, reply: () => ok({ users: MEMBERS }) });
  env.stub.route({ method: "GET", re: /\/api\/identity\/role-matrix$/, reply: () => ok({ roles: Object.keys(ROLE_MAPS), matrix: ROLE_MAPS }) });
  env.stub.route({ method: "GET", re: /\/api\/identity\/permission-vocabulary$/, reply: () => ok({ permissions: vocabulary }) });
  env.stub.route({ method: "GET", re: /\/api\/identity\/users\/(u-\d)\/permissions$/, reply: (req, body, url) => ok(gridFor(/users\/(u-\d)\//.exec(String(url ?? req.url))[1])) });
  env.stub.route({ method: "PUT", re: /\/api\/identity\/users\/u-2\/permissions$/, reply: (req, body) => {
    saved.changes = JSON.parse(body).changes;
    const overrides = Object.fromEntries(Object.entries(saved.changes).filter(([, v]) => v !== null));
    return ok(gridFor("u-2", overrides));
  } });
  return saved;
}

function watch(env) {
  const asked = { leads: 0, letters: 0, stats: 0 };
  env.stub.route({ method: "GET", re: LEADS, reply: () => { asked.leads += 1; return ok({ leads: [], has_more: false }); } });
  env.stub.route({ method: "GET", re: LETTERS, reply: () => { asked.letters += 1; return ok([]); } });
  env.stub.route({ method: "GET", re: STATS, reply: () => { asked.stats += 1; return ok({
    summary: { total_templates: 3, total_executions: 40, overall_success_rate: 95, pending_approvals: 2, unresolved_failures: 1 },
    by_template: [], top_templates: [], failure_patterns: [] }); } });
  env.stub.route({ method: "GET", re: TEMPLATES, reply: () => ok({ templates: [] }) });
  return asked;
}

export const scenarios = [
  {
    id: "an-executive-is-not-offered-and-cannot-open-what-they-hold-no-tick-for",
    title: "an Executive: no Pipeline entry, no Engagements under More; both addresses say 'not part of your access' and ask for nothing; Workflows shows no statistics",
    async run(env) {
      const { page } = env;
      env.stub.signInAs("Executive");
      const asked = watch(env);
      await page.goto(`${env.base}/clients/`, { waitUntil: "networkidle" });
      await page.waitForTimeout(400);
      assert.equal(await page.locator('main a[href="/pipeline/"], main a[href="/pipeline"]').count(), 0, "the Clients page offers Pipeline to an Executive");
      await firmMenuButton(page).click();
      await areas(page).waitFor();
      await areas(page).locator('[data-area="more"]').hover();
      await until(async () => (await areaNames(page)).includes("Knowledge"), "More to open");
      assert.ok(!(await areaNames(page)).includes("Engagements"), "Engagements is on an Executive's menu");
      await page.keyboard.press("Escape");

      for (const [address, name, pair] of [["/pipeline/", "Pipeline", "pipeline:read"], ["/engagements/", "Engagements", "engagement:read"]]) {
        await page.goto(`${env.base}${address}`, { waitUntil: "networkidle" });
        const gate = page.locator(`[data-tick-gate="${pair}"]`);
        await gate.waitFor();
        assert.match(await gate.innerText(), new RegExp(`${name} is not part of your access`));
        assert.match(await gate.innerText(), /that is not the same as there being nothing/);
      }
      assert.deepEqual({ leads: asked.leads, letters: asked.letters }, { leads: 0, letters: 0 }, "a list was requested for somebody the server refuses");

      await page.goto(`${env.base}/workflows/`, { waitUntil: "networkidle" });
      await page.getByRole("button", { name: "templates" }).waitFor();
      assert.equal(await page.locator("[data-workflow-stats]").count(), 0, "statistics tiles are shown to somebody who may not read them");
      assert.equal(await page.getByRole("button", { name: "analytics" }).count(), 0, "the Analytics tab is offered");
      assert.equal(asked.stats, 0, "the statistics were requested by somebody the server refuses");
    },
  },
  {
    id: "a-manager-is-offered-and-opens-the-same-screens",
    title: "a Manager: Pipeline is offered and opens, Engagements is under More and opens, Workflows shows its statistics",
    async run(env) {
      const { page } = env;
      env.stub.signInAs("Manager");
      const asked = watch(env);
      await page.goto(`${env.base}/clients/`, { waitUntil: "networkidle" });
      await until(async () => (await page.locator('main a[href="/pipeline/"], main a[href="/pipeline"]').count()) === 1, "the Pipeline link");
      await firmMenuButton(page).click();
      await areas(page).waitFor();
      await areas(page).locator('[data-area="more"]').hover();
      await until(async () => (await areaNames(page)).includes("Engagements"), "Engagements under More");
      await page.keyboard.press("Escape");

      await page.goto(`${env.base}/pipeline/`, { waitUntil: "networkidle" });
      assert.equal(await page.locator("[data-tick-gate]").count(), 0, "a Manager is told the pipeline is not part of their access");
      await until(async () => asked.leads >= 1, "the pipeline's list to be asked for");
      await page.goto(`${env.base}/engagements/`, { waitUntil: "networkidle" });
      assert.equal(await page.locator("[data-tick-gate]").count(), 0);
      await until(async () => asked.letters >= 1, "the engagement letters to be asked for");

      await page.goto(`${env.base}/workflows/`, { waitUntil: "networkidle" });
      const tiles = page.locator("[data-workflow-stats]");
      await tiles.waitFor();
      await until(async () => /40/.test(await tiles.innerText()), "the statistics to be shown");
      assert.match(await tiles.innerText(), /Success Rate\s*95%/i);
      assert.equal(await page.getByRole("button", { name: "analytics" }).count(), 1);
    },
  },
  {
    id: "the-register-says-which-answer-the-server-gave",
    title: "the related-party register: 'part of this register' when the server says scoped, 'the whole register' when it says not, no claim when it did not say",
    async run(env) {
      const { page } = env;
      const rows = [{ id: "e-1", full_name: "Asha Rao", entity_type: "Individual", pan: "AAAPA1111A" }];
      const part = page.getByText("You are shown part of this register");
      const whole = page.getByText("You are shown the whole register");
      const answer = (extra) => env.stub.route({ method: "GET", re: /\/api\/relationships\/entities/, reply: () => ok({
        entities: rows, returned: 1, has_more: false, limit: 2000, max_limit: 2000, ...extra }) });

      env.stub.signInAs("Executive");
      answer({ scoped: true });
      await page.goto(`${env.base}/relationships/`, { waitUntil: "networkidle" });
      await part.waitFor();
      assert.equal(await whole.count(), 0);
      assert.match(await page.locator("main").innerText(), /ask a Partner to add them to yours/);
      assert.doesNotMatch(await page.locator("main").innerText(), /shared across the whole practice/i);

      env.stub.signInAs("Partner");
      answer({ scoped: false });
      await page.goto(`${env.base}/relationships/`, { waitUntil: "networkidle" });
      await whole.waitFor();
      assert.equal(await part.count(), 0);

      answer({});
      await page.goto(`${env.base}/relationships/`, { waitUntil: "networkidle" });
      await page.getByText("Asha Rao").first().waitFor();
      assert.equal((await part.count()) + (await whole.count()), 0, "the screen made a claim the server did not");
    },
  },
  {
    id: "a-reviewer-is-told-accounting-is-not-theirs-and-a-tick-opens-it",
    title: "a Reviewer has no Accounting on the menu and its addresses say so; with the accounting tick the area is on the menu and opens, and a screen that asks more still says so",
    async run(env) {
      const { page } = env;
      env.stub.signInAs("Reviewer");
      await page.goto(`${env.base}/clients/`, { waitUntil: "networkidle" });
      await firmMenuButton(page).click();
      await areas(page).waitFor();
      await areas(page).locator('[data-area="more"]').hover();
      await until(async () => (await areaNames(page)).includes("Knowledge"), "More to open");
      assert.ok(!(await areaNames(page)).includes("Accounting"), "Accounting is on a Reviewer's menu");
      await page.keyboard.press("Escape");
      for (const address of ["/accounting/", "/accounting/banking/", "/accounting/budget/"]) {
        await page.goto(`${env.base}${address}`, { waitUntil: "networkidle" });
        const gate = page.locator('[data-tick-gate="accounting:read"]');
        await gate.waitFor();
        assert.match(await gate.innerText(), /Accounting is not part of your access/, address);
      }

      // A Partner ticks accounting read for this one person: the area is on their menu and its home opens.
      env.stub.signInAs("Reviewer", { grant: ["accounting:read"] });
      await page.goto(`${env.base}/accounting/`, { waitUntil: "networkidle" });
      assert.equal(await page.locator("[data-tick-gate]").count(), 0, "the ticked area still says it is not theirs");
      await firmMenuButton(page).click();
      await areas(page).waitFor();
      await areas(page).locator('[data-area="more"]').hover();
      await until(async () => (await areaNames(page)).includes("Accounting"), "Accounting to be on the menu");
      await page.keyboard.press("Escape");
      // The area is theirs; a screen in it that asks something more still says so, by its own name.
      await page.goto(`${env.base}/accounting/retainer/`, { waitUntil: "networkidle" });
      const own = page.locator('[data-tick-gate="billing:read"]');
      await own.waitFor();
      assert.doesNotMatch(await own.innerText(), /^Accounting is not part of your access/);
    },
  },
  {
    id: "a-desk-a-partner-unticked-is-off-the-menu-and-says-so",
    title: "an Executive a Partner blocked from TDS: no TDS under Deadlines, the TDS address says it is not part of their access, and GST is untouched",
    async run(env) {
      const { page } = env;
      env.stub.signInAs("Executive", { block: ["tds:read"] });
      await page.goto(`${env.base}/gst/`, { waitUntil: "networkidle" });
      assert.equal(await page.locator("[data-tick-gate]").count(), 0, "blocking TDS took GST away");
      await firmMenuButton(page).click();
      await areas(page).waitFor();
      await areas(page).locator('[data-area="deadlines"]').hover();
      const menu = page.locator("#workspace-menu");
      await until(async () => (await menu.locator('a[href="/gst/"], a[href="/gst"]').count()) >= 1, "the Deadlines list");
      assert.equal(await menu.locator('a[href="/tds/"], a[href="/tds"]').count(), 0, "TDS is offered to somebody blocked from it");
      assert.equal(await menu.locator('a[href*="type=TDS"]').count(), 0, "the TDS deadlines filter is offered to somebody blocked from TDS");
      await page.keyboard.press("Escape");
      await page.goto(`${env.base}/tds/`, { waitUntil: "networkidle" });
      const gate = page.locator('[data-tick-gate="tds:read"]');
      await gate.waitFor();
      assert.match(await gate.innerText(), /is not part of your access/);
    },
  },
  {
    id: "the-tick-screen-is-in-the-menus-names-and-previews-the-persons-menu",
    title: "a Partner's tick screen: permissions under the menu's names, 'Their menu' is the person's menu, a choice moves the preview before saving, and Save sends exactly what changed",
    async run(env) {
      const { page } = env;
      env.stub.signInAs("Partner");
      const saved = teamReads(env);
      await page.goto(`${env.base}/team/`, { waitUntil: "networkidle" });
      await page.getByRole("button", { name: "Permissions" }).click();
      const devRow = page.locator("tr", { hasText: "Dev Mehta" });
      await devRow.getByRole("button", { name: "Edit" }).click();
      const drawer = page.getByRole("dialog", { name: "Member access" });
      const preview = drawer.locator("[data-menu-preview]");
      await preview.waitFor();
      assert.match(await preview.innerText(), /Their menu now/);
      assert.equal((await drawer.locator("[data-menu-preview-main]").innerText()).trim(), "Home · Clients · Deadlines · Work · AI");
      assert.equal((await drawer.locator("[data-menu-preview-more]").innerText()).trim(), "Under More: Accounting · Relationships · Health · Knowledge");

      // The groups are the menu's areas, in the menu's order, and a permission is in a person's words with what it opens.
      const groups = await drawer.locator("[data-menu-group]").evaluateAll((els) => els.map((el) => el.getAttribute("data-menu-group")));
      // After the areas, Settings: not an area of the menu (everybody has it), but each of its pages is opened by a tick (POST-A-545).
      assert.deepEqual(groups, ["clients", "deadlines", "work", "team", "ai", "accounting", "payroll", "relationships", "health", "knowledge", "engagements", "settings"]);
      const brandingTick = drawer.locator('[data-menu-group="settings"] [data-permission="branding:read"]');
      assert.match(await brandingTick.innerText(), /Opens: Branding, Email templates, Invoice numbering, Invoice templates\./);
      assert.doesNotMatch(await drawer.locator('[data-menu-group="settings"]').innerText(), /Puts Settings on the menu/);
      assert.match(await drawer.locator('[data-menu-group="settings"]').innerText(), /Settings is on everybody's menu/);
      const gst = drawer.locator('[data-menu-group="deadlines"] [data-permission="gst:read"]');
      assert.match(await gst.innerText(), /See the GST desk/);
      assert.match(await gst.innerText(), /Puts Deadlines on the menu/);
      assert.match(await gst.innerText(), /role allows/);
      assert.doesNotMatch(await drawer.locator("[data-menu-group]").first().innerText(), /compliance_record|Compliance Record/);

      // A choice moves the preview before anything is saved.
      await drawer.locator('[data-menu-group="payroll"] [data-permission="payroll:read"]').getByRole("button", { name: "Allow" }).click();
      await until(async () => /Payroll/.test(await drawer.locator("[data-menu-preview-more]").innerText()), "Payroll on the preview");
      assert.match(await preview.innerText(), /Their menu once you save/);
      assert.match(await preview.innerText(), /nothing has changed until you save/);
      await drawer.locator('[data-menu-group="accounting"] [data-permission="accounting:read"]').getByRole("button", { name: "Block" }).click();
      await until(async () => !/Accounting/.test(await drawer.locator("[data-menu-preview-more]").innerText()), "Accounting off the preview");
      assert.equal(saved.changes, null, "something was sent before Save");

      await drawer.getByRole("button", { name: "Save", exact: true }).click();
      await until(async () => saved.changes !== null, "the save to be sent");
      assert.deepEqual(saved.changes, { "payroll:read": true, "accounting:read": false });
      await until(async () => /Their menu now/.test(await preview.innerText()), "the drawer to hold the server's answer");
      assert.equal((await drawer.locator("[data-menu-preview-more]").innerText()).trim(), "Under More: Payroll · Relationships · Health · Knowledge");
      // My practice is never on somebody's preview who is not a Partner.
      assert.doesNotMatch(await drawer.locator("[data-menu-preview-main]").innerText(), /My practice/);
    },
  },
  {
    id: "a-manager-reads-the-permissions-tab-and-is-not-offered-edit",
    title: "a Manager with a Manager's own permissions reads the Permissions tab and is not offered Edit, which the server would refuse on Save",
    async run(env) {
      const { page } = env;
      env.stub.signInAs("Manager");
      teamReads(env);
      await page.goto(`${env.base}/team/`, { waitUntil: "networkidle" });
      await page.getByRole("button", { name: "Permissions" }).click();
      const devRow = page.locator("tr", { hasText: "Dev Mehta" });
      await devRow.waitFor();
      assert.equal(await page.getByRole("button", { name: "Edit" }).count(), 0, "a Manager is offered Edit on somebody's access");
    },
  },
  {
    id: "request-access-asks-for-the-permission-the-notice-named",
    title: "Request access: sends exactly the named permission and the note, then says it is waiting; a waiting request offers no second one; a declined one shows the reason; a refusal is the server's words",
    async run(env) {
      const { page } = env;
      env.stub.signInAs("Reviewer");
      let mine = [];
      const sent = [];
      let refuseWith = null;
      env.stub.route({ method: "GET", re: /\/api\/approvals\/access-requests\/mine$/, reply: () => ok({ requests: mine }) });
      env.stub.route({ method: "POST", re: /\/api\/approvals\/access-requests$/, reply: (req, body) => {
        sent.push(JSON.parse(body));
        if (refuseWith) return { success: false, data: null, error: refuseWith };
        return ok({ id: "apr-1", status: "pending", asked_at: "2026-11-21T10:00:00Z" });
      } });

      // 1. Nothing asked yet: the notice offers the request, and it carries the permission the notice named.
      await page.goto(`${env.base}/accounting/`, { waitUntil: "networkidle" });
      const gate = page.locator('[data-tick-gate="accounting:read"]');
      await gate.waitFor();
      await gate.locator('[data-access-request="none"]').waitFor();
      await gate.getByLabel(/Why you need it/).fill("Reviewing the March books for Sharma Traders");
      await gate.getByRole("button", { name: "Request access" }).click();
      await gate.locator('[data-access-request="waiting"]').waitFor();
      assert.deepEqual(sent, [{ resource: "accounting", action: "read", asked_from: "Accounting", note: "Reviewing the March books for Sharma Traders" }]);
      assert.match(await gate.innerText(), /You asked for this on 21 Nov 2026\. A Partner has not decided yet/);
      assert.equal(await gate.getByRole("button", { name: "Request access" }).count(), 0);

      // 2. Somebody who already asked is told so on arrival and is not offered a second request.
      mine = [{ id: "apr-1", resource: "accounting", action: "read", status: "pending", asked_at: "2026-11-20T08:00:00Z", decided_at: null, reason: null }];
      await page.goto(`${env.base}/accounting/budget/`, { waitUntil: "networkidle" });
      await page.locator('[data-access-request="waiting"]').waitFor();
      assert.match(await page.locator("[data-tick-gate]").innerText(), /You asked for this on 20 Nov 2026/);
      assert.equal(await page.getByRole("button", { name: "Request access" }).count(), 0);

      // 3. A Partner declined: the reason is shown, and they may ask again. The server's refusal is shown as worded.
      mine = [{ id: "apr-1", resource: "accounting", action: "read", status: "rejected", asked_at: "2026-11-20T08:00:00Z", decided_at: "2026-11-21T09:00:00Z", reason: "Books are the Manager's this year" }];
      await page.goto(`${env.base}/accounting/`, { waitUntil: "networkidle" });
      const declined = page.locator('[data-access-request="declined"]');
      await declined.waitFor();
      assert.match(await declined.innerText(), /A Partner declined your last request for this on 21 Nov 2026\. Reason given: Books are the Manager's this year/);
      refuseWith = "There is no active Partner to decide this request.";
      sent.length = 0;
      await declined.getByRole("button", { name: "Request access" }).click();
      await page.getByRole("alert").filter({ hasText: "There is no active Partner to decide this request." }).waitFor();
      assert.equal(sent.length, 1);
      assert.equal("note" in sent[0], false, "an empty note was sent as a note");
    },
  },
  {
    id: "a-partner-sees-a-request-for-access-in-plain-words-and-gives-it",
    title: "a Partner: the request reads in a person's words with the note, a question is asked before it is given, and the approval is sent",
    async run(env) {
      const { page } = env;
      env.stub.signInAs("Partner");
      let approved = 0;
      let rejectedWith = "unset";
      const pending = () => [{ id: "apr-9", request_type: "access_request", status: "pending", summary: "Dev Mehta (dev@firm.example) asks for access: payroll read (asked from Payroll)",
        requested_by: "u-2", requested_by_email: "dev@firm.example", created_at: "2026-11-21T10:00:00Z",
        payload: { user_id: "u-2", user_name: "Dev Mehta", user_email: "dev@firm.example", user_role: "Executive", resource: "payroll", action: "read", asked_from: "Payroll", note: "Covering payroll in March" } }];
      env.stub.route({ method: "GET", re: /\/api\/approvals(\?status=pending)?$/, reply: () => ok({ requests: approved ? [] : pending() }) });
      env.stub.route({ method: "POST", re: /\/api\/approvals\/apr-9\/approve$/, reply: () => { approved += 1; return ok({ id: "apr-9", status: "approved" }); } });
      env.stub.route({ method: "POST", re: /\/api\/approvals\/apr-9\/reject$/, reply: (req, body) => { rejectedWith = JSON.parse(body).reason; return ok({ id: "apr-9", status: "rejected" }); } });
      await page.goto(`${env.base}/approvals/`, { waitUntil: "networkidle" });
      const row = page.locator("div", { hasText: "Dev Mehta asks to: See payroll" }).last();
      await row.waitFor();
      assert.match(await page.locator("[data-access-request-detail]").innerText(), /Executive\. Asked from the Payroll screen\. Their note: Covering payroll in March/);
      // Declining asks for a reason, which may be left empty; closing the question declines nothing; what is sent is what
      // the Partner typed and never a stock phrase, because the asker is shown it as the Partner's own words.
      const decline = page.getByRole("alertdialog").or(page.getByRole("dialog")).filter({ hasText: "Decline this request?" });
      await page.getByRole("button", { name: /Reject/ }).click();
      await decline.waitFor();
      await decline.getByRole("button", { name: "Cancel" }).click();
      await page.waitForTimeout(200);
      assert.equal(rejectedWith, "unset", "the request was declined although the Partner closed the question");
      await page.getByRole("button", { name: /Reject/ }).click();
      await decline.getByRole("textbox").fill("  Payroll is Meera's this year  ");
      await decline.getByRole("button", { name: "Decline" }).click();
      await until(async () => rejectedWith !== "unset", "the rejection to be sent");
      assert.equal(rejectedWith, "Payroll is Meera's this year");
      // Approving asks first, in a person's words, and a "no" sends nothing.
      await page.getByRole("button", { name: /Approve/ }).click();
      const dialog = page.getByRole("alertdialog").or(page.getByRole("dialog")).filter({ hasText: "Give this access?" });
      await dialog.waitFor();
      assert.match(await dialog.innerText(), /Dev Mehta will be allowed to: See payroll/);
      await dialog.getByRole("button", { name: "Cancel" }).click();
      await page.waitForTimeout(200);
      assert.equal(approved, 0, "the approval was sent although the Partner said no");
      await page.getByRole("button", { name: /Approve/ }).click();
      await dialog.getByRole("button", { name: "Give access" }).click();
      await until(async () => approved === 1, "the approval to be sent");
    },
  },
];
