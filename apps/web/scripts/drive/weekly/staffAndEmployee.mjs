/**
 * ONE SIGN-IN MAY BE BOTH A MEMBER OF STAFF AND A PORTAL EMPLOYEE (POST-A-549), driven in a browser.
 *
 * A practice that runs its own payroll here invites its own staff to the payslip portal, at the address they already sign in
 * with. Decided on 22-11-2026: that one sign-in serves both. Against a stubbed server, in Chromium:
 *
 *   1. a member of staff who opens the invitation's link is told their payslips are linked to the sign-in they already use, is
 *      NOT asked to set a password (setting one would replace the one they sign in to the practice with), and nothing is sent
 *      to the sign-in service to change one;
 *   2. somebody who is not a member of staff is asked to choose a password, as before;
 *   3. a member of staff who is also a portal employee finds "My payslips" in the account menu, leading to the payslip portal;
 *      the server is asked only when the menu is opened, and once;
 *   4. a member of staff who is not sees no such link.
 *
 * No scenario has a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";
import { ok } from "../stub.mjs";

export const group = "staff-and-employee";

const ACCEPT = /api\/portal\/employee\/accept-invite$/;
const ACCESS = /api\/portal\/employee\/access$/;

/** Every request to the sign-in service that would change the account (a password set here is the staff password replaced). */
function accountChanges(page) {
  const seen = [];
  page.on("request", (r) => { if (/\/auth\/v1\/user/.test(r.url()) && r.method() !== "GET") seen.push(`${r.method()} ${r.url()}`); });
  return seen;
}

async function openTheInvitation({ page, stub, base }, staffSignIn) {
  stub.route({ method: "POST", re: ACCEPT, reply: () => ok({ employee_id: "emp-1", name: "Asha Rao", client_id: "c-1", staff_sign_in: staffSignIn }) });
  await page.goto(`${base}/portal/employee/activate/?token=the-mailed-token`, { waitUntil: "networkidle" });
}

async function openTheAccountMenu({ page, stub, base }, enabled) {
  let asked = 0;
  stub.route({ method: "GET", re: ACCESS, reply: () => { asked += 1; return ok({ enabled }); } });
  await page.goto(`${base}/tasks/`, { waitUntil: "networkidle" });
  assert.equal(asked, 0, "the server was asked about the person's own payslips before the menu was opened");
  await page.getByRole("button", { name: "Account" }).first().click();
  await until(async () => asked >= 1, "the server to be asked once the menu is open");
  return () => asked;
}

export const scenarios = [
  {
    id: "a-member-of-staff-who-accepts-is-told-it-is-linked-and-is-asked-for-no-password",
    title: "Payslip portal invitation, opened by a member of staff: the page says the payslips are linked to the sign-in they already use, asks for no password and changes nothing on the account",
    async run(env) {
      const { page, stub } = env;
      const changes = accountChanges(page);
      await openTheInvitation(env, true);
      const said = page.locator("[data-activation-linked]");
      await said.waitFor({ timeout: 15000 });
      const text = (await said.innerText()).replace(/\s+/g, " ");
      assert.match(text, /Your payslips are linked to your sign-in/);
      assert.match(text, /there is no new password to set: you sign in the same way as before/);
      assert.equal(await page.locator('input[type="password"]').count(), 0, "a member of staff is asked to choose a password");
      assert.equal(stub.writesTo(ACCEPT, "POST").length, 1, "the invitation was not accepted exactly once");
      assert.match(String(stub.writesTo(ACCEPT, "POST")[0].body), /the-mailed-token/);
      assert.deepEqual(changes, [], "something on the account was changed");
      assert.equal(await page.getByRole("button", { name: "View my payslips" }).count(), 1);
    },
  },
  {
    id: "somebody-who-is-not-staff-is-asked-to-choose-a-password-as-before",
    title: "Payslip portal invitation, opened by an employee who is not a member of staff: the password step is offered, as before",
    async run(env) {
      const { page } = env;
      await openTheInvitation(env, false);
      await until(async () => (await page.locator('input[type="password"]').count()) >= 1, "the password step", 15000);
      assert.equal(await page.locator("[data-activation-linked]").count(), 0, "an employee with no staff sign-in was told there is no password to set");
    },
  },
  {
    id: "a-member-of-staff-on-the-payroll-finds-my-payslips-in-the-account-menu",
    title: "Account menu: a member of staff who is also a portal employee is offered My payslips, leading to the payslip portal, and the server is asked once, when the menu opens",
    async run(env) {
      const { page } = env;
      const asked = await openTheAccountMenu(env, true);
      const link = page.locator("[data-my-payslips]");
      await link.waitFor({ timeout: 5000 });
      assert.equal((await link.innerText()).trim(), "My payslips");
      assert.match(await link.getAttribute("href"), /^\/portal\/employee\/?$/);
      // Closing (a click anywhere outside the menu) and opening again does not ask again, and the link is still there.
      await page.mouse.click(700, 400);
      await until(async () => (await link.count()) === 0, "the menu to close");
      await page.getByRole("button", { name: "Account" }).first().click();
      await link.waitFor({ timeout: 5000 });
      await page.waitForTimeout(300);
      assert.equal(asked(), 1, `the server was asked ${asked()} times about the same person's payslips`);
    },
  },
  {
    id: "a-member-of-staff-not-on-the-payroll-sees-no-such-link",
    title: "Account menu: a member of staff who is not a portal employee is offered Sign out and no My payslips",
    async run(env) {
      const { page } = env;
      await openTheAccountMenu(env, false);
      await page.getByRole("button", { name: "Sign out" }).first().waitFor({ timeout: 5000 });
      await page.waitForTimeout(300);
      assert.equal(await page.locator("[data-my-payslips]").count(), 0, "My payslips is offered to somebody the server says is not a portal employee");
    },
  },
];
