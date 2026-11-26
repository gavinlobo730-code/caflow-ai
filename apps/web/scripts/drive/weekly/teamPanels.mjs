/**
 * THE TEAM, TASK AND EMPLOYEE PANELS ARE THE SHARED MENU, DIALOG OR SIDE SHEET (POST-A-130, twenty-first step), driven in a browser.
 *
 * The Team page's row menu was a menu plus an invisible layer over the whole window; Edit Capacity was a layer built by hand; Member
 * access, Task Detail and the employee sheet were side panels built by hand, the last with a key listener of its own. The row menu is the
 * shared row menu now, Edit Capacity the shared Modal and the three panels the shared Drawer. The source guard holds the five; this drives
 * four of them:
 *
 *   1. the Team page's row menu opens from the keyboard with focus on its first action, closes on Escape with focus back on the row's
 *      button, and nothing covers the window while it is open;
 *   2. Member access is a modal side sheet that keeps Tab inside and closes on Escape;
 *   3. Task Detail is a named modal side sheet that keeps Tab inside; Edit moves focus to the Title box and Cancel gives it back to Edit
 *      (found while driving this: the switch removed the button pressed and left focus on nothing); while the task is being saved the ×,
 *      Escape and a click beside it do not close it; the server's refusal is then read and the request went once;
 *   4. the employee sheet is a modal side sheet named for the employee that keeps Tab inside; with nothing typed Escape closes it and
 *      gives focus back to the row's Open button; with something typed Escape asks first, Escape on the question dismisses the question
 *      ALONE, and the sheet and what was typed are still there.
 *
 * Edit Capacity needs the workload the browser assembles from several tables and is not driven here. The tick screen inside Member
 * access is the weekly `ticks` group's, on the same build.
 *
 * No scenario asserts a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import fs from "node:fs";
import { until } from "../kit.mjs";
import { ok, refuse } from "../stub.mjs";
import { openEditTask, openEmployeeDrawer } from "../scenarios/dates.mjs";

export const group = "team-panels";

const ROLE_MAPS = JSON.parse(fs.readFileSync(new URL("../role-permissions.json", import.meta.url), "utf8"));
const MEMBERS = [
  { id: "u-1", full_name: "Asha Rao", email: "asha@firm.example", role: "Partner", is_active: true, member_state: "active", created_at: "2026-04-01T00:00:00Z", auth_user_id: "a-1", firm_id: "f-1" },
  { id: "u-2", full_name: "Dev Mehta", email: "dev@firm.example", role: "Executive", is_active: true, member_state: "active", created_at: "2026-05-01T00:00:00Z", auth_user_id: "a-2", firm_id: "f-1" },
];

function teamReads(env) {
  const vocabulary = Object.entries(ROLE_MAPS.Partner).flatMap(([resource, actions]) =>
    actions.map((action) => ({ resource, action, privilege_changing: false, unrevokable_for_partner: false })));
  const gridFor = (id) => {
    const member = MEMBERS.find((m) => m.id === id);
    const role_defaults = ROLE_MAPS[member.role];
    return { user_id: id, full_name: member.full_name, email: member.email, role: member.role, role_defaults, overrides: {}, effective: role_defaults };
  };
  env.stub.signInAs("Partner");
  env.stub.route({ method: "GET", re: /\/api\/identity\/users$/, reply: () => ok({ users: MEMBERS }) });
  env.stub.route({ method: "GET", re: /\/api\/identity\/role-matrix$/, reply: () => ok({ roles: Object.keys(ROLE_MAPS), matrix: ROLE_MAPS }) });
  env.stub.route({ method: "GET", re: /\/api\/identity\/permission-vocabulary$/, reply: () => ok({ permissions: vocabulary }) });
  env.stub.route({ method: "GET", re: /\/api\/identity\/users\/(u-\d)\/permissions$/, reply: (req, body, url) => ok(gridFor(/users\/(u-\d)\//.exec(String(url ?? req.url))[1])) });
}

const focusInside = (dialog) => dialog.evaluate((d) => d.contains(document.activeElement));
const pageLocked = (page) => page.evaluate(() => document.body.style.overflow);
const focusIsOn = (locator) => locator.evaluate((el) => el === document.activeElement);

async function tabStaysInside(page, dialog, n, what) {
  await until(() => focusInside(dialog), `focus to be inside ${what}`);
  for (let i = 0; i < n; i += 1) {
    await page.keyboard.press("Tab");
    assert.equal(await focusInside(dialog), true, `Tab number ${i + 1} left ${what}`);
  }
  for (let i = 0; i < n; i += 1) {
    await page.keyboard.press("Shift+Tab");
    assert.equal(await focusInside(dialog), true, `Shift+Tab number ${i + 1} left ${what}`);
  }
}

export const scenarios = [
  {
    id: "the-team-row-menu-opens-from-the-keyboard-and-gives-focus-back",
    title: "Team > a member's actions: opened from the keyboard, focus is on the first action; Escape closes it and focus is back on the row's button; nothing covers the window while it is open",
    async run(env) {
      const { page } = env;
      teamReads(env);
      await page.goto(`${env.base}/team/`, { waitUntil: "networkidle" });
      const opener = page.getByRole("button", { name: "Actions for Dev Mehta", exact: true });
      await opener.waitFor();
      assert.equal(await opener.getAttribute("aria-expanded"), "false", "the row's button says it is expanded before it is pressed");
      await opener.focus();
      await page.keyboard.press("Enter");
      const menu = page.locator("[data-row-menu]");
      await menu.waitFor();
      assert.equal(await opener.getAttribute("aria-expanded"), "true", "the row's button does not say its menu is open");
      assert.match(await page.evaluate(() => (document.activeElement?.textContent ?? "").trim()), /^Edit Role$/, "focus is not on the menu's first action");
      // Nothing covers the window: the element at a point far from the menu is the page, not a layer.
      const covered = await page.evaluate(() => {
        const el = document.elementFromPoint(40, window.innerHeight - 40);
        return !!el && getComputedStyle(el).position === "fixed" && el.getBoundingClientRect().width >= window.innerWidth;
      });
      assert.equal(covered, false, "a layer covers the window while the menu is open");
      await page.keyboard.press("Escape");
      await menu.waitFor({ state: "detached" });
      assert.equal(await focusIsOn(opener), true, "focus did not return to the row's button");
      assert.equal(await opener.getAttribute("aria-expanded"), "false", "the row's button still says its menu is open");
      // A click on the page outside closes it too.
      await opener.click();
      await menu.waitFor();
      await page.mouse.click(40, 40);
      await menu.waitFor({ state: "detached" });
    },
  },
  {
    id: "member-access-is-a-modal-side-sheet-that-keeps-the-keyboard",
    title: "Team > Permissions > Edit: Member access is a modal side sheet under the member's name that keeps Tab inside, locks the page and closes on Escape",
    async run(env) {
      const { page } = env;
      teamReads(env);
      await page.goto(`${env.base}/team/`, { waitUntil: "networkidle" });
      await page.getByRole("button", { name: "Permissions" }).click();
      await page.locator("tr", { hasText: "Dev Mehta" }).getByRole("button", { name: "Edit" }).click();
      const sheet = page.getByRole("dialog", { name: "Member access" });
      await sheet.waitFor();
      await sheet.locator("[data-menu-preview]").waitFor();
      assert.equal(await sheet.getAttribute("aria-modal"), "true", "Member access does not say it is modal");
      assert.equal(await sheet.getByRole("heading", { name: "Dev Mehta" }).count(), 1, "the member's name is not the sheet's heading");
      assert.equal(await pageLocked(page), "hidden", "the page behind Member access can still scroll");
      await tabStaysInside(page, sheet, 12, "Member access");
      await page.keyboard.press("Escape");
      await sheet.waitFor({ state: "detached" });
      assert.equal(await pageLocked(page), "", "the page is still locked after Member access closed");
    },
  },
  {
    id: "task-detail-is-a-named-side-sheet-held-while-the-task-is-saved",
    title: "Tasks > a task: Task Detail is a named modal side sheet that keeps Tab inside; while the task is being saved Cancel is held and the ×, Escape and a click beside it do not close it; the refusal is then read and the request went once",
    async run(env) {
      const { page, stub } = env;
      await openEditTask(env);
      const sheet = page.getByRole("dialog", { name: "Task Detail", exact: true });
      await sheet.waitFor();
      assert.equal(await sheet.getAttribute("aria-modal"), "true", "Task Detail does not say it is modal");
      assert.equal(await pageLocked(page), "hidden", "the page behind Task Detail can still scroll");
      // FOUND WHILE DRIVING THIS: Edit removes the button that was pressed, and focus was left on nothing. It goes to the Title box,
      // and back to Edit when the form is left.
      const title = sheet.getByLabel("Title", { exact: true });
      await until(() => focusIsOn(title), "focus to move to the Title box after Edit");
      await sheet.getByRole("button", { name: "Cancel", exact: true }).click();
      const edit = sheet.getByRole("button", { name: "Edit", exact: true });
      await until(() => focusIsOn(edit), "focus to return to Edit after Cancel");
      await page.keyboard.press("Enter");
      await until(() => focusIsOn(title), "focus to move to the Title box after Edit from the keyboard");
      await tabStaysInside(page, sheet, 8, "Task Detail");
      stub.route({ method: "PATCH", re: /api\/tasks\/t-1$/, delay: 2500, ...refuse("A stub refusal of the task.", 422) });
      await sheet.getByLabel("Title", { exact: true }).fill("File GSTR-3B for September (revised)");
      await sheet.getByRole("button", { name: "Save", exact: true }).click();
      await sheet.getByRole("button", { name: "Saving…" }).waitFor({ timeout: 3000 });
      await sheet.getByRole("button", { name: "Close", exact: true }).click();
      await page.keyboard.press("Escape");
      await page.mouse.click(5, 5);
      assert.equal(await sheet.count(), 1, "the ×, Escape or a click beside it closed Task Detail while the task was being saved");
      await page.getByText("A stub refusal of the task.").first().waitFor({ timeout: 8000 }).catch(() => { throw new Error("the server's refusal was not shown"); });
      assert.equal(await sheet.count(), 1, "Task Detail closed on a refusal");
      assert.equal(stub.writesTo(/api\/tasks\/t-1$/).length, 1, "the task was not sent exactly once");
    },
  },
  {
    id: "the-employee-sheet-is-a-modal-side-sheet-and-escape-asks-about-typed-work-once",
    title: "Payroll > Open an employee: a modal side sheet named for the employee that keeps Tab inside; Escape closes it and gives focus back; with something typed Escape asks first, and Escape on the question dismisses the question alone",
    async run(env) {
      const { page } = env;
      await openEmployeeDrawer(null)(env);
      const opener = page.getByRole("button", { name: "Open", exact: true }).first();
      const sheet = page.getByRole("dialog", { name: "Asha Rao", exact: true });
      await sheet.waitFor();
      assert.equal(await sheet.getAttribute("aria-modal"), "true", "the employee sheet does not say it is modal");
      assert.equal(await pageLocked(page), "hidden", "the page behind the employee sheet can still scroll");
      await tabStaysInside(page, sheet, 10, "the employee sheet");
      await page.keyboard.press("Escape");
      await sheet.waitFor({ state: "detached" });
      assert.equal(await page.getByRole("alertdialog").count(), 0, "Escape with nothing typed asked about unsaved changes");
      assert.equal(await focusIsOn(opener), true, "focus did not return to the row's Open button");

      await opener.click();
      await sheet.waitFor();
      const pan = sheet.getByLabel("PAN", { exact: true }).first();
      await pan.fill("ABCPR1234K");
      await page.keyboard.press("Escape");
      const question = page.getByRole("alertdialog");
      await question.waitFor();
      assert.equal(await question.count(), 1, "the leave question was asked more than once");
      assert.match(await question.innerText(), /unsaved changes/i);
      await page.keyboard.press("Escape");
      await question.waitFor({ state: "detached" });
      assert.equal(await sheet.count(), 1, "Escape on the question closed the employee sheet too");
      assert.equal(await page.getByRole("alertdialog").count(), 0, "the second Escape started another question");
      assert.equal(await pan.inputValue(), "ABCPR1234K", "what was typed did not survive the question");
    },
  },
];
