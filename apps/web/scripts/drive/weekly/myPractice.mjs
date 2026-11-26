/**
 * MY PRACTICE IS ONE WORKSPACE: THE FIRM'S OWN BOOKS AND THE SCREENS ABOUT RUNNING THE PRACTICE, IN THE CLIENT WORKSPACE'S FRAME
 * (POST-A-532), driven in a browser.
 *
 * Against a stubbed server, in Chromium:
 *
 *   1. a fixed practice screen (Billing Schedules) is drawn in the workspace frame and not the firm's: the bar says "My
 *      practice", the way out is the dashboard and not the client list, there is no client switcher, and the module grid
 *      lists the firm's books (each tile opening the practice's own client workspace) beside the practice's screens and
 *      the firm's people, with the open screen marked and without the sections the practice does not have;
 *   2. the practice's own client workspace says "My practice" too, opens on the same grid, and asks for no health score;
 *   3. a practice that is not set up says so in the books group and points at Practice home, and a read that failed says
 *      the books could not be read; neither draws a tile that leads nowhere, and the practice's screens stay listed;
 *   4. the dashboard's first-day card draws a second list for a Partner, "Your own firm", whose steps open My practice
 *      (POST-A-533); with no such list sent, a firm that has done its four steps sees no card;
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
      // The firm's people are a group of My practice (the owner's decision of 21-11-2026): the screens a Manager reaches from
      // the firm's Team menu, opened in this frame. Hours are recorded by everybody, in Work, and are not listed here.
      const people = grid(page).getByRole("region", { name: "People" });
      assert.deepEqual(await people.getByRole("link").allInnerTexts(), ["Team", "Assignments", "Approvals", "Workload", "Login History"]);
      assert.equal(await people.getByRole("link", { name: "Team", exact: true }).getAttribute("href"), "/team/");
      assert.equal(await grid(page).getByRole("link", { name: "Time Tracking" }).count(), 0);
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
    id: "the-first-day-card-walks-a-partner-through-the-firms-own-practice",
    title: "the dashboard's first-day card draws a second list, Your own firm, whose steps open My practice; with no practice list sent the card is the four steps it was",
    async run(env) {
      const { page } = env;
      const step = (id, title, done) => ({ id, title, why: "Why this matters.", done, done_at: null });
      const clients = [step("first_client", "Add your first client", true), step("first_invoice", "Raise your first invoice", true),
        step("first_statement", "Import a bank statement", true), step("invite_colleague", "Invite a colleague", true)];
      const firstRun = (practice) => ({
        steps: clients, total: 4, done_count: 4, complete: true, next_step: null, unreadable: [], dismissed: false,
        visible: practice !== null, minutes_to_first_invoice: 12, practice,
      });
      const ownFirm = {
        steps: [step("practice_identity", "Check your own firm's details", true), step("practice_books", "Start your own firm's books", false),
          step("practice_statement", "Import your firm's own bank statement", null), step("practice_fee_bill", "Raise your first fee bill", false)],
        total: 4, done_count: 1, complete: false, next_step: "practice_books", unreadable: ["practice_statement"], client_id: env.clientId,
      };
      let sent = ownFirm;
      env.stub.route({ method: "GET", re: /\/api\/onboarding\/status/, reply: () => ok({ checks: {}, score: 0, total: 0, first_run: firstRun(sent) }) });
      await page.goto(`${env.base}/`, { waitUntil: "networkidle" });
      const card = page.locator("[data-first-run]");
      await card.waitFor();
      // Both lists are counted: four client steps done and one of the practice's four.
      assert.match(await card.innerText(), /5 of 8 done/);
      const own = card.locator("[data-first-run-practice]");
      assert.match(await own.innerText(), /Your own firm/);
      assert.equal(await own.locator("li").count(), 4);
      assert.equal(await own.locator('li[data-step="practice_statement"]').getAttribute("data-done"), "unknown");
      // The practice's next step is the one to start with, since the clients' list has none left.
      const books = own.locator('li[data-step="practice_books"]').getByRole("link");
      assert.match(await books.innerText(), /Start here/);
      assert.equal(await books.getAttribute("href"), `/clients/${env.clientId}/accounting/?tab=opening-balances`);
      assert.equal(await own.locator('li[data-step="practice_fee_bill"]').getByRole("link").getAttribute("href"), "/practice/billing/");
      assert.equal(await own.locator('li[data-step="practice_identity"]').getByRole("link").count(), 0, "a step that is done still offers its link");
      // Somebody who is sent no practice list (a Manager) and has done the four steps sees no card at all.
      sent = null;
      await page.goto(`${env.base}/`, { waitUntil: "networkidle" });
      await page.waitForTimeout(600);
      assert.equal(await page.locator("[data-first-run]").count(), 0);
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
