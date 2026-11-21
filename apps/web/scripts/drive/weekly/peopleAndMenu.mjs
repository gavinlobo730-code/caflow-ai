/**
 * THE PEOPLE SCREENS FOLLOW THE PERSON, AND THE FIRM MENU LISTS LESS (the owner's review of the live Test Firm, 21-11-2026),
 * driven in a browser.
 *
 * Against a stubbed server, in Chromium:
 *
 *   1. a Partner who opens Team is in My practice: its bar and not the firm's, the bar names the open screen, the grid has a
 *      People group with that screen marked, and moving to Workload from it stays inside My practice;
 *   2. a Manager who opens the same address is in the firm's frame, as before, and the firm menu offers Team and no My
 *      practice;
 *   3. a Partner's firm menu lists the daily areas, My practice and "More", with no separate Team entry; "More" opens the
 *      other areas in the same column and says what each is; pointing at My practice shows its list, where the row for the
 *      firm's books holds its place while the server is asked and the rows under it do not move when it answers, and the
 *      People screens are listed; and a click on an area opens that area's first screen and closes the menu.
 *
 * AND EACH ROLE WITH ITS OWN PERMISSIONS (the role walk of 21-11-2026, POST-A-542; `stub.signInAs` serves the role's own map,
 * written from the server's table):
 *
 *   4. an Executive's and a Reviewer's firm menu offers neither Team nor My practice, and the People address typed in says
 *      in words that the screen is withheld, with no tiles, no empty list and no button;
 *   5. a Manager reads Team and is not offered "Invite Member", which only a Partner can do;
 *   6. when the list of members cannot be read, the tiles show a dash and the list says it could not be read: never four
 *      zeros and "No team members yet".
 *
 * No scenario has a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";
import { ok, refuse } from "../stub.mjs";
import { FAKE_USERS_ROW } from "../fixtures.mjs";

export const group = "people-and-menu";

const PRACTICE = /\/api\/practice$/;
const READY = (env) => ({ internal_client_id: env.clientId, provisioned: true, firm_has_pan: true, can_provision: false, identity: null, entity_types: [] });
const USERS = /\/api\/identity\/users$/;
const MEMBERS = [
  { id: "u-1", full_name: "Asha Rao", email: "asha@firm.example", role: "Partner", is_active: true, member_state: "active", created_at: "2026-04-01T00:00:00Z", auth_user_id: "a-1", firm_id: "f-1" },
  { id: "u-2", full_name: "Dev Mehta", email: "dev@firm.example", role: "Executive", is_active: true, member_state: "active", created_at: "2026-05-01T00:00:00Z", auth_user_id: "a-2", firm_id: "f-1" },
];
const grid = (page) => page.locator("[data-practice-modules]");
const firmMenuButton = (page) => page.locator('header button[aria-controls="workspace-menu"]');
const areas = (page) => page.locator('#workspace-menu nav[aria-label="Workspaces"]');
const areaNames = async (page) => (await areas(page).locator("[data-area]").allInnerTexts()).map((t) => t.trim());

export const scenarios = [
  {
    id: "a-partner-opens-team-inside-my-practice",
    title: "a Partner on Team is in My practice: its bar, the screen named on it, a People group with the screen marked, and Workload opens in the same frame",
    async run(env) {
      const { page } = env;
      env.stub.route({ method: "GET", re: PRACTICE, reply: () => ok(READY(env)) });
      await page.goto(`${env.base}/team/`, { waitUntil: "networkidle" });
      await page.locator("[data-my-practice]").waitFor();
      assert.equal(await firmMenuButton(page).count(), 0, "the firm's bar is drawn on a Partner's Team screen");
      const switcher = page.locator('[aria-controls="client-module-menu"]');
      assert.match(await switcher.innerText(), /Team/);
      await switcher.click();
      await grid(page).waitFor();
      const people = grid(page).getByRole("region", { name: "People" });
      assert.deepEqual(await people.getByRole("link").allInnerTexts(), ["Team", "Assignments", "Approvals", "Workload", "Login History"]);
      assert.equal(await people.getByRole("link", { name: "Team", exact: true }).getAttribute("aria-current"), "page", "the open People screen is not marked");
      await people.getByRole("link", { name: "Workload", exact: true }).click();
      await page.waitForURL(/\/team\/workload\/$/);
      await page.locator("[data-my-practice]").waitFor();
      await until(async () => /Workload/.test(await page.locator('[aria-controls="client-module-menu"]').innerText()), "the bar to name Workload");
      assert.equal(await firmMenuButton(page).count(), 0, "moving between People screens left My practice");
    },
  },
  {
    id: "a-manager-opens-team-in-the-firm-frame",
    title: "a Manager on the same address is in the firm's frame, and the firm menu offers Team and no My practice",
    async run(env) {
      const { page } = env;
      env.stub.setTable("users", [{ ...FAKE_USERS_ROW, role: "Manager" }]);
      await page.goto(`${env.base}/team/`, { waitUntil: "networkidle" });
      await firmMenuButton(page).waitFor();
      await page.waitForTimeout(400);
      assert.equal(await page.locator("[data-my-practice]").count(), 0, "a Manager's Team screen is drawn in the My practice frame");
      await firmMenuButton(page).click();
      await areas(page).waitFor();
      assert.deepEqual(await areaNames(page), ["Home", "Clients", "Deadlines", "Work", "Team", "AI", "More"]);
    },
  },
  {
    id: "the-firm-menu-lists-less-and-a-click-opens-the-area",
    title: "a Partner's firm menu: the daily areas, My practice and More, no Team; More opens in the column; the books row holds its place; a click opens the area",
    async run(env) {
      const { page } = env;
      // The practice's own client is answered late, so the row that waits for it is seen waiting.
      env.stub.route({ method: "GET", re: PRACTICE, delay: 1500, reply: () => ok(READY(env)) });
      await page.goto(`${env.base}/clients/`, { waitUntil: "domcontentloaded" });
      await firmMenuButton(page).waitFor();
      await firmMenuButton(page).click();
      await areas(page).waitFor();
      assert.deepEqual(await areaNames(page), ["Home", "Clients", "Deadlines", "Work", "My practice", "AI", "More"]);

      // More: a disclosure in the same column, with a line about each area beside it.
      const more = areas(page).locator('[data-area="more"]');
      assert.equal(await more.getAttribute("aria-expanded"), "false");
      await more.hover();
      assert.equal(await more.getAttribute("aria-expanded"), "true");
      assert.deepEqual(await areaNames(page), [
        "Home", "Clients", "Deadlines", "Work", "My practice", "AI", "More",
        "Accounting", "Payroll", "Relationships", "Health", "Knowledge", "Engagements",
      ]);
      const described = page.locator("[data-more-areas] li");
      assert.equal(await described.count(), 6);
      assert.match(await described.first().innerText(), /Accounting\s+Chart of Accounts/);

      // My practice's list: the books row is there at once, and the row under it does not move when the server answers.
      await areas(page).locator('[data-area="practice"]').hover();
      const row = page.locator("#workspace-menu [data-practice-books]");
      await row.waitFor();
      const overview = page.locator("#workspace-menu").getByRole("link", { name: "Overview", exact: true });
      const before = await overview.boundingBox();
      await until(async () => (await row.getAttribute("data-practice-books")) === "ready", "the books row to become the link");
      const after = await overview.boundingBox();
      assert.ok(before && after && Math.abs(before.y - after.y) < 1, `the list moved by ${after && before ? after.y - before.y : "?"}px when the books row arrived`);
      assert.equal(await row.getAttribute("href"), `/clients/${env.clientId}/`);
      const people = page.locator("#workspace-menu [data-practice-people]");
      assert.deepEqual(await people.getByRole("link").allInnerTexts(), ["Team", "Assignments", "Approvals", "Workload", "Login History"]);

      // A click on an area opens it and closes the menu.
      await areas(page).locator('[data-area="deadlines"]').click();
      await page.waitForURL(/\/deadlines\/$/);
      await until(async () => (await page.locator("#workspace-menu").count()) === 0, "the menu to close");
    },
  },
  ...["Executive", "Reviewer"].map((role) => ({
    id: `${role.toLowerCase()}-is-told-a-people-screen-is-withheld`,
    title: `${role}: the firm menu follows their permissions (Deadlines and Work, no Team, no My practice), and a People address typed in says Team is not part of their access`,
    async run(env) {
      const { page } = env;
      env.stub.signInAs(role);
      // The server's own answer to somebody who may not read the team.
      env.stub.route({ method: "GET", re: USERS, ...refuse("Your role does not allow this.", 403) });
      await page.goto(`${env.base}/clients/`, { waitUntil: "networkidle" });
      await firmMenuButton(page).click();
      await areas(page).waitFor();
      // The menu follows the permissions the person holds (POST-A-543): both roles hold the compliance and task permissions,
      // so Deadlines and Work are theirs; neither holds a People permission, and My practice is a Partner's alone.
      await until(async () => !(await areaNames(page)).includes("Team") && (await areaNames(page)).includes("More"), "the menu to settle on the person's own areas");
      assert.deepEqual(await areaNames(page), ["Home", "Clients", "Deadlines", "Work", "AI", "More"]);
      await page.keyboard.press("Escape");

      for (const address of ["/team/", "/team/assignments/", "/team/workload/", "/approvals/", "/team/login-history/"]) {
        await page.goto(`${env.base}${address}`, { waitUntil: "networkidle" });
        // The one gate on every firm screen answers: the whole Team area is not theirs, so it names the area.
        const gate = page.locator("[data-tick-gate]");
        await gate.waitFor();
        assert.match(await gate.innerText(), /Team is not part of your access/, address);
        assert.match(await gate.innerText(), /that is not the same as there being nothing/);
        assert.equal(await page.getByRole("button", { name: /Invite Member/ }).count(), 0, `${address}: an Invite button is offered`);
        assert.equal(await page.getByText("No team members yet").count(), 0, `${address}: an empty list is claimed`);
        assert.equal(await page.locator("[data-my-practice]").count(), 0, `${address}: drawn in the My practice frame`);
      }
    },
  })),
  {
    id: "a-manager-reads-the-team-and-is-not-offered-invite",
    title: "a Manager with a Manager's own permissions reads Team, sees its members, and is not offered Invite Member",
    async run(env) {
      const { page } = env;
      env.stub.signInAs("Manager");
      env.stub.route({ method: "GET", re: USERS, reply: () => ok({ users: MEMBERS }) });
      await page.goto(`${env.base}/team/`, { waitUntil: "networkidle" });
      await page.getByRole("heading", { name: "Team", exact: true }).waitFor();
      await page.getByText("asha@firm.example").waitFor();
      assert.equal(await page.locator("[data-tick-gate], [data-people-gate]").count(), 0, "a Manager is told Team is withheld");
      assert.equal(await page.getByRole("button", { name: /Invite Member/ }).count(), 0, "a Manager is offered Invite Member, which the server refuses");
    },
  },
  {
    id: "a-partner-is-offered-invite-and-an-unread-list-is-not-an-empty-one",
    title: "a Partner is offered Invite Member; when the list cannot be read the tiles show a dash and the list says so, never zeros and 'No team members yet'",
    async run(env) {
      const { page } = env;
      env.stub.route({ method: "GET", re: PRACTICE, reply: () => ok(READY(env)) });
      let fail = true;
      env.stub.route({ method: "GET", re: USERS, status: () => (fail ? 500 : 200), reply: () => (fail ? { detail: "The team could not be read just now." } : ok({ users: MEMBERS })) });
      await page.goto(`${env.base}/team/`, { waitUntil: "networkidle" });
      const unread = page.locator("[data-team-unread]");
      await unread.waitFor();
      assert.match(await unread.innerText(), /could not be read[\s\S]*not the same as there being no team members/);
      assert.equal(await page.getByText("No team members yet").count(), 0);
      const tiles = await page.locator("main .grid p.text-lg").allInnerTexts();
      assert.ok(tiles.length === 4 && tiles.every((t) => t.trim() === "—"), `the tiles read ${JSON.stringify(tiles)} after a failed read`);
      assert.doesNotMatch(await page.locator("main .grid").first().innerText(), /\b0 active\b/, "a tile counts the active members after a failed read");
      assert.equal(await page.getByRole("button", { name: /Invite Member/ }).count(), 1, "a Partner is not offered Invite Member");
      // And the list comes back when asked again.
      fail = false;
      await unread.getByRole("button", { name: "Try again" }).click();
      await page.getByText("asha@firm.example").waitFor();
      assert.equal(await unread.count(), 0);
    },
  },
];
