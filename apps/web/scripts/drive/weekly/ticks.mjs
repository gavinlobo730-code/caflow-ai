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
 *      says `scoped`, the whole of it when the server says not, and nothing at all when the server did not say.
 *
 * No scenario has a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
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
];
