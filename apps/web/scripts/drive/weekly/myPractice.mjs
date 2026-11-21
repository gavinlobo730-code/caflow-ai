/**
 * MY PRACTICE IS ONE WORKSPACE: THE FIRM'S OWN BOOKS AND THE SCREENS ABOUT RUNNING THE PRACTICE, IN THE CLIENT WORKSPACE'S FRAME
 * (POST-A-532), driven in a browser.
 *
 * Against a stubbed server, in Chromium:
 *
 *   1. a fixed practice screen (Billing Schedules) is drawn in the workspace frame and not the firm's: the bar says "My
 *      practice", the way out is the dashboard and not the client list, there is no client switcher, and the module grid
 *      lists the firm's books (each tile opening the practice's own client workspace) beside the practice's screens, with
 *      the open screen marked and without the sections the practice does not have;
 *   2. the practice's own client workspace says "My practice" too, opens on the same grid, and asks for no health score;
 *   3. a practice that is not set up says so in the books group and points at Practice home, and a read that failed says
 *      the books could not be read; neither draws a tile that leads nowhere, and the practice's screens stay listed;
 *   4. with guided tips on, Practice home draws the tip about the firm's own books beside the bar's menu button, the tip
 *      waits while the grid is open, and a client's workspace (the same button) draws none;
 *   5. an ordinary client is untouched: its name is the switcher and the way out is the client list.
 *
 * No scenario has a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";
import { ok, refuse } from "../stub.mjs";
import { CLIENT_ROW } from "../fixtures.mjs";

export const group = "my-practice";

const PRACTICE = /\/api\/practice$/;
const HEALTH = /\/api\/health\//;
const bar = (page) => page.locator("header").first();
const grid = (page) => page.locator("[data-practice-modules]");

function practiceIs(env, data, extra = {}) {
  env.stub.route({ method: "GET", re: PRACTICE, reply: () => ok(data), ...extra });
}

async function openGrid(page) {
  await page.locator('[aria-controls="client-module-menu"]').click();
  await grid(page).waitFor();
}

export const scenarios = [
  {
    id: "a-practice-screen-wears-the-workspace-frame",
    title: "Billing Schedules is in the My practice frame: its bar, the way out, and a grid of the firm's books and the practice's screens",
    async run(env) {
      const { page } = env;
      practiceIs(env, { internal_client_id: env.clientId, provisioned: true, firm_has_pan: true, can_provision: false, identity: null, entity_types: [] });
      await page.goto(`${env.base}/practice/billing/`, { waitUntil: "networkidle" });
      await page.locator("[data-my-practice]").waitFor();
      assert.match(await bar(page).innerText(), /My practice/);
      assert.equal(await bar(page).getByRole("link", { name: /Dashboard/ }).getAttribute("href"), "/");
      assert.equal(await bar(page).getByRole("link", { name: /All clients/ }).count(), 0, "the practice's way out is the client list");
      // The firm's navy bar is not drawn: one frame, not two.
      assert.equal(await page.locator('[aria-controls="workspace-menu"]').count(), 0, "the firm's menu bar is drawn as well");
      await openGrid(page);
      const books = grid(page).getByRole("region", { name: "Your firm's books" });
      const running = grid(page).getByRole("region", { name: "Running the practice" });
      await until(async () => (await books.getByRole("link").count()) > 5, "the books' tiles");
      assert.equal(await books.getByRole("link", { name: "Accounting", exact: true }).getAttribute("href"), `/clients/${env.clientId}/accounting/`);
      assert.equal(await books.getByRole("link", { name: "Bank", exact: true }).getAttribute("href"), `/clients/${env.clientId}/bank/`);
      // The firm's own staff payroll runs here (POST-A-532, second part).
      assert.equal(await books.getByRole("link", { name: "Payroll", exact: true }).getAttribute("href"), `/clients/${env.clientId}/payroll/`);
      for (const gone of ["Portal", "Lifecycle", "Health", "Knowledge", "Instructions"]) {
        assert.equal(await books.getByRole("link", { name: gone, exact: true }).count(), 0, `${gone} is offered for the practice`);
      }
      const here = running.getByRole("link", { name: "Billing Schedules", exact: true });
      assert.equal(await here.getAttribute("aria-current"), "page", "the open screen is not marked");
      assert.equal(await running.getByRole("link", { name: "Collections", exact: true }).getAttribute("href"), "/practice/collections/");
      assert.equal(await running.getByRole("link").count(), 11);
      // The team and its hours are pointed at, last, and lead out to the firm's own menus.
      const team = grid(page).getByRole("region", { name: "Your team and its hours" });
      assert.deepEqual(await team.getByRole("link").allInnerTexts(), ["Team", "Workload", "Time Tracking"]);
      assert.equal(await team.getByRole("link", { name: "Time Tracking" }).getAttribute("href"), "/time/");
    },
  },
  {
    id: "the-practices-own-workspace-says-my-practice",
    title: "the practice's client workspace: the bar says My practice, the front door is the same grid, no health score is asked for",
    async run(env) {
      const { page } = env;
      env.stub.setTable("clients", [{ ...CLIENT_ROW, client_name: "Sharma & Co", is_internal: true }]);
      const asked = [];
      page.on("request", (r) => { if (HEALTH.test(r.url())) asked.push(r.url()); });
      await page.goto(`${env.base}/clients/${env.clientId}/`, { waitUntil: "networkidle" });
      await page.locator("[data-my-practice]").waitFor();
      assert.match(await page.locator("[data-my-practice]").innerText(), /My practice\s*Sharma & Co/);
      assert.equal(await bar(page).getByRole("link", { name: /Dashboard/ }).getAttribute("href"), "/");
      // The front door is the practice's grid, drawn in the page.
      await grid(page).waitFor();
      assert.equal(await grid(page).getByRole("link", { name: "Revenue", exact: true }).getAttribute("href"), "/practice/revenue/");
      assert.equal(await grid(page).getByRole("link", { name: "Sales", exact: true }).getAttribute("href"), `/clients/${env.clientId}/sales/`);
      assert.equal(await grid(page).getByRole("link", { name: "Health", exact: true }).count(), 0);
      await page.waitForTimeout(600);
      assert.deepEqual(asked, [], "a health score was asked for the practice, which is left out of scoring");
    },
  },
  {
    id: "a-practice-not-set-up-or-unread-draws-no-dead-tile",
    title: "not set up: the books group says so and points at Practice home; unread: it says it could not be read; the practice's screens stay",
    async run(env) {
      const { page } = env;
      practiceIs(env, { internal_client_id: null, provisioned: false, firm_has_pan: false, can_provision: false, identity: null, entity_types: [] });
      await page.goto(`${env.base}/practice/revenue/`, { waitUntil: "networkidle" });
      await page.locator("[data-my-practice]").waitFor();
      await openGrid(page);
      const books = grid(page).getByRole("region", { name: "Your firm's books" });
      await until(async () => /not set up yet/.test(await books.innerText()), "the not-set-up sentence");
      assert.equal(await books.getByRole("link").count(), 1, "a books tile is drawn with no practice to open");
      assert.equal(await books.getByRole("link", { name: "Open Practice home" }).getAttribute("href"), "/practice/");
      assert.equal(await grid(page).getByRole("region", { name: "Running the practice" }).getByRole("link").count(), 11);
      // A read that failed is not "not set up".
      env.stub.route({ method: "GET", re: PRACTICE, ...refuse("Not just now.", 503) });
      await page.goto(`${env.base}/practice/revenue/`, { waitUntil: "networkidle" });
      await openGrid(page);
      await until(async () => /could not be read/.test(await books.innerText()), "the could-not-be-read sentence");
      assert.doesNotMatch(await books.innerText(), /not set up/);
      assert.equal(await books.getByRole("link").count(), 0);
    },
  },
  {
    id: "the-tip-about-the-firms-own-books-is-on-my-practice",
    title: "with tips on, Practice home draws the tip about the firm's own books beside the bar's menu button; a client's workspace, which has the same button, draws none",
    async run(env) {
      const { page } = env;
      practiceIs(env, { internal_client_id: env.clientId, provisioned: true, firm_has_pan: true, can_provision: false, identity: null, entity_types: [] });
      env.stub.route({ method: "GET", re: /\/api\/guided-tips$/, reply: () => ok({ on: true, chosen: false, seen: [] }) });
      await page.goto(`${env.base}/practice/`, { waitUntil: "networkidle" });
      await page.locator("[data-my-practice]").waitFor();
      const tip = page.locator("[data-guided-tip]");
      await until(async () => (await tip.count()) === 1 && (await tip.isVisible()), "the tip on Practice home");
      assert.equal(await tip.getAttribute("data-guided-tip"), "own-books");
      assert.match(await tip.innerText(), /Everything about your own firm is here/);
      const button = page.locator('[aria-controls="client-module-menu"]');
      assert.ok(await button.getAttribute("aria-describedby"), "the button the tip explains is not described by it");
      // Opening the grid draws a layer over the page, and the tip waits behind it.
      await openGrid(page);
      await until(async () => !(await tip.isVisible().catch(() => false)), "the tip to hide while the grid is open");
      // The same button on an ordinary client's bar explains nothing: the tip is Practice home's.
      await page.goto(`${env.base}/clients/${env.clientId}/`, { waitUntil: "networkidle" });
      await bar(page).getByRole("link", { name: /All clients/ }).waitFor();
      await page.waitForTimeout(600);
      assert.equal(await page.locator("[data-guided-tip]:visible").count(), 0, "a client's workspace drew the practice's tip");
    },
  },
  {
    id: "an-ordinary-client-is-untouched",
    title: "a client that is not the practice keeps its switcher, its way out to the client list and its own grid",
    async run(env) {
      const { page } = env;
      await page.goto(`${env.base}/clients/${env.clientId}/`, { waitUntil: "networkidle" });
      await bar(page).getByRole("link", { name: /All clients/ }).waitFor();
      assert.match(await bar(page).getByRole("link", { name: /All clients/ }).getAttribute("href"), /^\/clients\/?$/);
      assert.equal(await page.locator("[data-my-practice]").count(), 0);
      assert.equal(await grid(page).count(), 0, "an ordinary client was given the practice's grid");
      assert.match(await bar(page).innerText(), /Acme Traders Pvt Ltd/);
    },
  },
];
