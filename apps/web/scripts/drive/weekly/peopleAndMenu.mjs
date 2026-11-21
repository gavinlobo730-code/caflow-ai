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
 * No scenario has a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";
import { ok } from "../stub.mjs";
import { FAKE_USERS_ROW } from "../fixtures.mjs";

export const group = "people-and-menu";

const PRACTICE = /\/api\/practice$/;
const READY = (env) => ({ internal_client_id: env.clientId, provisioned: true, firm_has_pan: true, can_provision: false, identity: null, entity_types: [] });
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
];
