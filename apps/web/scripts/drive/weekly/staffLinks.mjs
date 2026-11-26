/**
 * A TEAM SIGN-IN AND A RECORD IN THE FIRM'S OWN PAYROLL ARE SHOWN SIDE BY SIDE, LINKED AND NEVER MERGED (POST-A-540),
 * driven in a browser.
 *
 * Against a stubbed server, in Chromium:
 *
 *   1. a Partner on Team sees the list of sign-ins beside payroll records, each kind of row apart (a linked pair, with a
 *      word when the name is spelt differently; a sign-in with no payroll record; a payroll record with no sign-in), and the
 *      Team row of somebody on the payroll is marked; choosing a payroll record and pressing Link sends ONE request naming
 *      that employee and that member; Remove link asks first, No sends nothing, and Yes sends the link as null;
 *   2. inviting somebody offers to add them to the firm's payroll: the one employee form opens on the practice with the name
 *      started from the sign-in, says the two stay separate, and the create names the new member;
 *   3. a Manager on Team sees no such list and no mark, and the firm's payroll is never asked for;
 *   4. the server's refusal of a link is shown in its words with nothing changed on the screen, and a roster that could not
 *      be read says so and is not drawn as an empty payroll;
 *   5. on the practice's own Payroll page the same list is shown, a linked employee's row names their sign-in, and Invite to
 *      Team sends the invitation and then the link, in that order.
 *
 * No scenario has a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";
import { ok, refuse } from "../stub.mjs";
import { CLIENT_ROW } from "../fixtures.mjs";

export const group = "staff-links";

const PRACTICE = /\/api\/practice$/;
const USERS = /\/api\/identity\/users$/;
const ROSTER = /\/api\/payroll\/practice-staff$/;
const LINK = /\/api\/payroll\/employees\/([^/]+)\/staff-link$/;
const member = (id, full_name, role = "Executive") => ({ id, full_name, email: `${id}@firm.example`, role, is_active: true,
  member_state: "active", created_at: "2026-04-01T00:00:00Z", auth_user_id: `auth-${id}`, firm_id: "f-1" });
const MEMBERS = [member("u-asha", "Asha Rao"), member("u-dev", "Dev Mehta")];
const EMPLOYEES = [
  { id: "e-asha", name: "Asha R.", employee_code: "S001", designation: "Article", status: "active", staff_user_id: "u-asha" },
  { id: "e-meera", name: "Meera Iyer", employee_code: null, designation: null, status: "active", staff_user_id: null },
];

/** A firm whose practice has a payroll of its own, as the server answers it. `state` is mutable so a write changes the next read. */
function aFirmWithItsOwnPayroll(env, { enabled = true } = {}) {
  const state = { members: structuredClone(MEMBERS), employees: structuredClone(EMPLOYEES), links: [], asked: 0 };
  env.stub.route({ method: "GET", re: PRACTICE, reply: () => ok({ internal_client_id: env.clientId, provisioned: true, firm_has_pan: true,
    can_provision: false, identity: null, entity_types: [] }) });
  env.stub.route({ method: "GET", re: USERS, reply: () => ok({ users: state.members }) });
  env.stub.route({ method: "GET", re: ROSTER, reply: () => { state.asked += 1;
    return ok({ practice_client_id: env.clientId, payroll_enabled: enabled, employees: state.employees }); } });
  env.stub.route({ method: "PUT", re: LINK, reply: (_req, body, url) => {
    const employeeId = String(url).match(LINK)[1];
    const sent = JSON.parse(body);
    state.links.push({ employeeId, sent });
    const row = state.employees.find((e) => e.id === employeeId);
    row.staff_user_id = sent.staff_user_id ?? null;
    return ok(row);
  } });
  return state;
}

const panel = (page) => page.locator('[data-staff-links="ready"]');
const rowsOf = (page, kind) => panel(page).locator(`[data-staff-row="${kind}"]`);
const question = (page) => page.getByRole("alertdialog");

export const scenarios = [
  {
    id: "a-partner-sees-sign-ins-beside-payroll-records-and-links-and-unlinks-them",
    title: "Team, a Partner: four kinds of row kept apart, the mark on a Team row, Link sends one request naming both, Remove link asks and sends null",
    async run(env) {
      const { page } = env;
      const state = aFirmWithItsOwnPayroll(env);
      await page.goto(`${env.base}/team/`, { waitUntil: "networkidle" });
      await panel(page).waitFor();

      assert.equal(await rowsOf(page, "linked").count(), 1);
      assert.match(await rowsOf(page, "linked").innerText(), /Asha Rao[\s\S]*Asha R\. \(S001\)/);
      assert.equal(await rowsOf(page, "linked").locator("[data-names-differ]").count(), 1, "a name spelt two ways is not said");
      assert.equal(await rowsOf(page, "member-only").count(), 1);
      assert.match(await rowsOf(page, "member-only").innerText(), /Dev Mehta[\s\S]*Not in the firm's payroll/);
      assert.equal(await rowsOf(page, "employee-only").count(), 1);
      assert.match(await rowsOf(page, "employee-only").innerText(), /No sign-in on Team[\s\S]*Meera Iyer/);
      assert.equal(await panel(page).getByRole("link", { name: "Open the firm's payroll" }).getAttribute("href"), `/clients/${env.clientId}/payroll/`);
      // ...and the dates that payroll owes are the practice's own, so the way to them is beside it and leads to the practice's own
      // Compliance page, never to a calendar across the firm's clients (POST-A-534).
      assert.equal(await panel(page).locator("[data-own-payroll-dates]").getAttribute("href"), `/clients/${env.clientId}/compliance/`);
      assert.equal((await panel(page).locator("[data-own-payroll-dates]").innerText()).trim(), "Its statutory dates");

      // The Team list itself marks who is on the payroll, by the link and by nothing else.
      const teamRow = (name) => page.locator("table").first().locator("tr", { hasText: name });
      assert.equal(await teamRow("asha@firm.example").locator("[data-on-payroll]").count(), 1, "a linked member's Team row is not marked");
      assert.equal(await teamRow("dev@firm.example").locator("[data-on-payroll]").count(), 0, "a member with no payroll record is marked");

      // Link Dev's sign-in to Meera's payroll record: nothing is sent until Link is pressed.
      const devRow = rowsOf(page, "member-only");
      assert.equal(await devRow.getByRole("button", { name: "Link", exact: true }).isDisabled(), true, "Link is live with nobody chosen");
      await devRow.getByLabel("A payroll record to link to Dev Mehta").selectOption({ label: "Meera Iyer" });
      assert.equal(state.links.length, 0, "choosing in the box wrote the link");
      await devRow.getByRole("button", { name: "Link", exact: true }).click();
      await until(() => state.links.length === 1, "the link was not sent");
      assert.deepEqual(state.links[0], { employeeId: "e-meera", sent: { staff_user_id: "u-dev" } });
      await until(async () => (await rowsOf(page, "linked").count()) === 2, "the list was not read again after the link");
      assert.match(await panel(page).locator('[data-staff-notice="done"]').innerText(), /Dev Mehta's sign-in is linked to the payroll record of Meera Iyer/);
      assert.equal(await rowsOf(page, "member-only").count() + await rowsOf(page, "employee-only").count(), 0);

      // Remove a link: the question says neither record is changed; No sends nothing; Yes sends null.
      const ashaRow = rowsOf(page, "linked").filter({ hasText: "Asha Rao" });
      await ashaRow.getByRole("button", { name: "Remove link" }).click();
      await question(page).waitFor();
      assert.match(await question(page).innerText(), /Neither record is changed or removed/);
      await question(page).getByRole("button", { name: "Cancel", exact: true }).click();
      await question(page).waitFor({ state: "detached" });
      assert.equal(state.links.length, 1, "saying no still wrote");
      await ashaRow.getByRole("button", { name: "Remove link" }).click();
      await question(page).getByRole("button").filter({ hasNotText: "Cancel" }).last().click();
      await until(() => state.links.length === 2, "the removal was not sent");
      assert.deepEqual(state.links[1], { employeeId: "e-asha", sent: { staff_user_id: null } });
      await until(async () => (await rowsOf(page, "employee-only").count()) === 1, "the removed link is still drawn");
      assert.equal(state.links.length, 2, "a link was written more than once");
    },
  },
  {
    id: "inviting-somebody-offers-to-add-them-to-the-firms-payroll-linked",
    title: "Team, a Partner: an invitation's result offers the firm's payroll; the employee form opens on the practice with the name started from the sign-in, and the create names the member",
    async run(env) {
      const { page } = env;
      const state = aFirmWithItsOwnPayroll(env);
      const created = [];
      env.stub.route({ method: "POST", re: USERS, reply: (_req, body) => {
        const sent = JSON.parse(body);
        const row = member("u-new", sent.full_name, sent.role);
        state.members.push({ ...row, email: sent.email, member_state: "invited" });
        return ok({ id: "u-new", full_name: sent.full_name, email: sent.email, role: sent.role, member_state: "invited",
          invite_expires_at: "2026-10-15T08:00:00Z", invite_mail: { sent: true, problem: null } });
      } });
      env.stub.route({ method: "POST", re: /\/api\/payroll\/employees$/, reply: (_req, body) => {
        const sent = JSON.parse(body); created.push(sent);
        state.employees.push({ id: "e-new", name: sent.name, employee_code: null, designation: null, status: "active", staff_user_id: sent.staff_user_id ?? null });
        return ok({ id: "e-new" });
      } });
      await page.goto(`${env.base}/team/`, { waitUntil: "networkidle" });
      await panel(page).waitFor();
      await page.getByRole("button", { name: "Invite Member" }).first().click();
      const invite = page.getByRole("dialog");
      await invite.getByLabel("Full Name").fill("Kiran Shah");
      await invite.getByLabel("Email Address").fill("kiran@firm.example");
      await invite.getByRole("button", { name: "Send Invitation" }).click();
      const offer = page.locator("[data-payroll-offer]");
      await offer.waitFor();
      assert.match(await offer.innerText(), /kept\s+separate and linked/);
      await offer.getByRole("button", { name: "Add to the firm's payroll" }).click();

      const form = page.getByRole("dialog").last();
      await form.getByRole("heading", { name: "Add Employee" }).waitFor();
      assert.equal(await form.getByLabel("Name", { exact: true }).inputValue(), "Kiran Shah", "the name did not start from the sign-in");
      assert.match(await form.locator("[data-linked-team-member]").innerText(), /linked to the team sign-in of Kiran Shah[\s\S]*stay separate/);
      await form.getByLabel("Name", { exact: true }).fill("Kiran J. Shah");      // the two names may differ: the record is payroll's
      await form.getByLabel("Basic Salary (Rs/month)").fill("40000");
      assert.equal(created.length, 0);
      await form.getByRole("button", { name: "Add Employee", exact: true }).click();
      await until(() => created.length === 1, "the employee was not created");
      assert.equal(created[0].client_id, env.clientId, "the employee was not created on the practice");
      assert.equal(created[0].staff_user_id, "u-new", "the create did not name the member");
      assert.equal(created[0].name, "Kiran J. Shah");
      await until(async () => (await rowsOf(page, "linked").filter({ hasText: "Kiran Shah" }).count()) === 1, "the new pair is not on the list");
      assert.equal(await rowsOf(page, "linked").filter({ hasText: "Kiran Shah" }).locator("[data-names-differ]").count(), 1);
      assert.equal(created.length, 1, "the employee was created more than once");
    },
  },
  {
    id: "a-manager-on-team-is-shown-nothing-of-the-firms-payroll",
    title: "Team, a Manager: no list, no mark on any row, and the firm's own payroll is never asked for",
    async run(env) {
      const { page } = env;
      const state = aFirmWithItsOwnPayroll(env);
      env.stub.signInAs("Manager");
      const asked = [];
      page.on("request", (r) => { if (ROSTER.test(new URL(r.url()).pathname)) asked.push(r.url()); });
      await page.goto(`${env.base}/team/`, { waitUntil: "networkidle" });
      await page.getByText("asha@firm.example").first().waitFor();
      await page.waitForTimeout(500);
      assert.equal(await page.locator("[data-staff-links]").count(), 0, "a Manager is shown who is on the firm's payroll");
      assert.equal(await page.locator("[data-on-payroll]").count(), 0, "a Manager's Team list marks who is on the firm's payroll");
      assert.deepEqual(asked, [], "the firm's payroll was asked for on a Manager's screen");
      assert.equal(state.asked, 0);
    },
  },
  {
    id: "a-refused-link-is-said-in-the-servers-words-and-an-unread-payroll-is-not-an-empty-one",
    title: "the server's refusal of a link is shown as worded and nothing on the list moves; a roster that could not be read says so",
    async run(env) {
      const { page } = env;
      aFirmWithItsOwnPayroll(env);
      const REFUSAL = "That team member is already linked to Asha R. in the firm's own payroll. Remove that link first: one person is one employee.";
      let tried = 0;
      env.stub.route({ method: "PUT", re: LINK, ...refuse(REFUSAL, 409), reply: () => { tried += 1; return { detail: REFUSAL }; } });
      await page.goto(`${env.base}/team/`, { waitUntil: "networkidle" });
      await panel(page).waitFor();
      const devRow = rowsOf(page, "member-only");
      await devRow.getByLabel("A payroll record to link to Dev Mehta").selectOption({ label: "Meera Iyer" });
      await devRow.getByRole("button", { name: "Link", exact: true }).click();
      await until(() => tried === 1, "the link was not sent");
      const said = panel(page).locator('[data-staff-notice="problem"]');
      await said.waitFor();
      assert.equal((await said.innerText()).trim(), REFUSAL);
      assert.equal(await said.getAttribute("role"), "alert");
      assert.equal(await rowsOf(page, "linked").count(), 1, "a refused link is drawn as made");
      assert.equal(await devRow.getByRole("button", { name: "Link", exact: true }).isDisabled(), false, "the row stayed held after the refusal");
      assert.equal(tried, 1, "the link was sent more than once");

      // A roster that cannot be read: said in words, with no table that would read as "nobody is on the payroll".
      env.stub.route({ method: "GET", re: ROSTER, status: 500, reply: () => ({ detail: "The firm's payroll could not be read just now." }) });
      await page.reload({ waitUntil: "networkidle" });
      const unread = page.locator('[data-staff-links="unread"]');
      await unread.waitFor();
      assert.match(await unread.getByRole("alert").innerText(), /could not be read/);
      assert.equal(await page.locator("[data-staff-row]").count(), 0);
      assert.equal(await page.locator("[data-on-payroll]").count(), 0);
    },
  },
  {
    id: "the-practices-payroll-page-shows-the-same-list-and-invites-an-employee-to-team",
    title: "the practice's Payroll page: the list, the sign-in named on a linked employee's row, and Invite to Team sends the invitation and then the link",
    async run(env) {
      const { page, stub } = env;
      const state = aFirmWithItsOwnPayroll(env);
      stub.setTable("clients", [{ ...CLIENT_ROW, client_name: "Sharma & Co", is_internal: true }]);
      stub.route({ method: "GET", re: /api\/payroll\/employees\?/, reply: () => ok(state.employees.map((e) => ({ ...e, basic_paise: 40_000_00,
        hra_percent: 40, pf_applicable: true, esi_applicable: false, pt_applicable: false }))) });
      const order = [];
      stub.route({ method: "POST", re: USERS, reply: (_req, body) => {
        const sent = JSON.parse(body); order.push(["invite", sent]);
        state.members.push({ ...member("u-meera", sent.full_name, sent.role), email: sent.email, member_state: "invited" });
        return ok({ id: "u-meera", full_name: sent.full_name, email: sent.email, role: sent.role, member_state: "invited",
          invite_expires_at: "2026-10-15T08:00:00Z", invite_mail: { sent: true, problem: null } });
      } });
      await page.goto(env.at("/payroll/?tab=inputs"), { waitUntil: "networkidle" });
      await panel(page).waitFor();
      assert.equal(await panel(page).getByRole("link", { name: "Open Team" }).getAttribute("href"), "/team/");
      assert.match(await page.locator("[data-team-sign-in]").first().innerText(), /Team sign-in: Asha Rao/);
      assert.equal(await page.locator("[data-team-sign-in]").count(), 1, "an employee with no link is shown a sign-in");

      await rowsOf(page, "employee-only").getByRole("button", { name: "Invite to Team" }).click();
      const dialog = page.getByRole("dialog").last();
      await dialog.getByRole("heading", { name: "Invite to Team" }).waitFor();
      assert.equal(await dialog.getByLabel("Full Name").inputValue(), "Meera Iyer");
      assert.equal(await dialog.getByRole("button", { name: "Send invitation and link" }).isDisabled(), true, "an invitation with no address can be sent");
      await dialog.getByLabel("Email Address").fill("meera@firm.example");
      await dialog.getByRole("button", { name: "Send invitation and link" }).click();
      await until(() => state.links.length === 1, "the link was not sent after the invitation");
      assert.deepEqual(order.map(([what]) => what), ["invite"]);
      assert.deepEqual(order[0][1], { full_name: "Meera Iyer", email: "meera@firm.example", role: "Executive" });
      assert.deepEqual(state.links[0], { employeeId: "e-meera", sent: { staff_user_id: "u-meera" } });
      await until(async () => (await rowsOf(page, "linked").count()) === 2, "the new pair is not on the list");
      assert.match(await panel(page).locator('[data-staff-notice="done"]').innerText(), /Meera Iyer is invited to Team at meera@firm\.example\. The sign-in is linked/);
      assert.equal(await page.locator("[data-team-sign-in]").count(), 2, "the employee's own row does not name the new sign-in");
    },
  },
];
