/**
 * THE SETTINGS PAGES FOLLOW THE PERMISSIONS A PARTNER TICKED, AND SEEING A PAGE IS NOT CHANGING IT (POST-A-545), driven in a
 * browser.
 *
 * Each Settings page used to be opened by a role (a guard naming Partner, or Partner and Manager), which sent anybody else
 * home without a word, while the server asked a permission. Against a stubbed server, in Chromium, each role signed in with
 * its own permissions:
 *
 *   1. a Manager, who holds the permission to SEE branding and not to change it, is listed Branding on Settings, opens it, is
 *      told in one sentence that they can read it and not change it with a way to ask, and every control on it is switched
 *      off; the audit log, which they hold nothing for, says so at its address and offers Request access instead of sending
 *      them home;
 *   2. the same Manager with the permission to change branding ticked sees no such sentence and a live Save;
 *   3. an Executive reads the treaty rates and is offered no way to add or remove one, and Branding typed in says it is not
 *      part of their access;
 *   4. a Partner sees no read-only sentence anywhere and every control live.
 *
 * No scenario has a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";
import { ok } from "../stub.mjs";

export const group = "settings-ticks";

const BRANDING = /\/api\/settings\/branding$/;
const TREATY = /\/api\/tds\/treaty-rates$/;
const MINE = /\/api\/approvals\/access-requests\/mine$/;

function settingsReads(env) {
  const writes = [];
  env.stub.route({ method: "GET", re: BRANDING, reply: () => ok({ branding: { tagline: "Careful books", primary_color: "#0B5FFF" } }) });
  env.stub.route({ method: "PUT", re: BRANDING, reply: (_req, body) => { writes.push(JSON.parse(body)); return ok({}); } });
  env.stub.route({ method: "GET", re: TREATY, reply: () => ok({ natures: ["royalty", "fts"],
    rates: [{ id: "t1", country_code: "AE", nature: "royalty", rate_bps: 1000, article_ref: "Article 12(2)", verified_on: "2026-06-01", no_article: false }] }) });
  env.stub.route({ method: "GET", re: MINE, reply: () => ok({ requests: [] }) });
  return writes;
}

const notice = (page, pair) => page.locator(`[data-read-only-notice="${pair}"]`);
const part = (page, pair) => page.locator(`[data-change-part="${pair}"]`);
/** Whether the part of the page that changes something is switched off: the fieldset's own `disabled`, which is what makes the
 *  browser disable every control inside it (a fieldset is not itself a control, so "is it disabled" is asked of the attribute). */
const switchedOff = (page, pair) => part(page, pair).evaluate((el) => el.disabled === true);
const gate = (page, pair) => page.locator(`[data-tick-gate="${pair}"]`);
/** The Settings addresses the page links to, without the trailing slash a static export adds. */
const settingsLinks = async (page) => (await page.locator("main a[href^='/settings/']").evaluateAll((els) => els.map((a) => a.getAttribute("href"))))
  .map((href) => href.replace(/\/+$/, ""));

export const scenarios = [
  {
    id: "a-manager-reads-branding-and-cannot-change-it-and-the-audit-log-says-it-is-not-theirs",
    title: "a Manager: Branding is listed and opens read-only with one sentence and a way to ask, every control off; the audit log's address says it is not part of their access",
    async run(env) {
      const { page } = env;
      env.stub.signInAs("Manager");
      const writes = settingsReads(env);

      await page.goto(`${env.base}/settings/?tab=documents`, { waitUntil: "networkidle" });
      const listed = await settingsLinks(page);
      assert.ok(listed.includes("/settings/branding"), `a Manager holds the permission to see branding and is not listed it: ${listed.join(", ")}`);

      await page.goto(`${env.base}/settings/branding/`, { waitUntil: "networkidle" });
      await page.getByRole("heading", { name: "Firm Branding" }).waitFor();
      await notice(page, "branding:write").waitFor();
      assert.match(await notice(page, "branding:write").innerText(), /You can read this page and cannot change it/);
      await notice(page, "branding:write").getByRole("button", { name: /Request access/ }).waitFor();
      assert.equal(await switchedOff(page, "branding:write"), true, "the part of the page that changes branding is live for somebody who cannot change it");
      assert.equal(await page.getByRole("button", { name: /Save Branding/ }).isDisabled(), true);
      assert.equal(await page.getByLabel("Tagline").isDisabled(), true);
      assert.equal(await page.getByLabel("Tagline").inputValue(), "Careful books", "the saved branding is not shown to somebody who may read it");
      await page.getByRole("button", { name: /Save Branding/ }).click({ force: true, timeout: 2000 }).catch(() => {});
      await page.waitForTimeout(300);
      assert.deepEqual(writes, [], "a save was sent by somebody who may not change branding");

      await page.goto(`${env.base}/settings/?tab=security`, { waitUntil: "networkidle" });
      assert.ok(!(await settingsLinks(page)).includes("/settings/audit-log"), "a Manager is listed the audit log, which they hold nothing for");
      await page.goto(`${env.base}/settings/audit-log/`, { waitUntil: "networkidle" });
      await gate(page, "audit:read").waitFor();
      assert.match(await gate(page, "audit:read").innerText(), /Audit log is not part of your access/);
      assert.match(page.url(), /\/settings\/audit-log\/$/, "the person was sent somewhere else instead of being told");
      await gate(page, "audit:read").getByRole("button", { name: /Request access/ }).waitFor();
    },
  },
  {
    id: "a-manager-ticked-to-change-branding-is-offered-the-form",
    title: "the same Manager with the permission to change branding: no read-only sentence, the controls are live and a save is sent",
    async run(env) {
      const { page } = env;
      env.stub.signInAs("Manager", { grant: ["branding:write"] });
      const writes = settingsReads(env);
      await page.goto(`${env.base}/settings/branding/`, { waitUntil: "networkidle" });
      await page.getByRole("heading", { name: "Firm Branding" }).waitFor();
      await page.getByLabel("Tagline").waitFor();
      assert.equal(await notice(page, "branding:write").count(), 0, "somebody who may change branding is told they cannot");
      assert.equal(await switchedOff(page, "branding:write"), false);
      await page.getByLabel("Tagline").fill("Careful books, on time");
      await page.getByRole("button", { name: /Save Branding/ }).click();
      await until(() => writes.length === 1, "the save was not sent");
      assert.equal(writes[0].tagline, "Careful books, on time");
    },
  },
  {
    id: "an-executive-reads-the-treaty-rates-and-is-offered-no-way-to-change-them",
    title: "an Executive: the treaty rates open with the readings listed, no Add and no Remove, and the sentence; Branding typed in says it is not part of their access",
    async run(env) {
      const { page } = env;
      env.stub.signInAs("Executive");
      settingsReads(env);
      await page.goto(`${env.base}/settings/treaty-rates/`, { waitUntil: "networkidle" });
      await page.getByRole("heading", { name: "DTAA Treaty Rates" }).waitFor();
      await page.getByText("Article 12(2)").waitFor();
      await notice(page, "tds:write").waitFor();
      assert.equal(await page.getByRole("button", { name: /Add reading/ }).count(), 0, "an Executive is offered Add reading, which the server would refuse");
      assert.equal(await page.getByRole("button", { name: /^Remove / }).count(), 0, "an Executive is offered Remove on a reading");

      await page.goto(`${env.base}/settings/branding/`, { waitUntil: "networkidle" });
      await gate(page, "branding:read").waitFor();
      assert.match(await gate(page, "branding:read").innerText(), /Branding is not part of your access/);
      assert.equal(await page.getByRole("heading", { name: "Firm Branding" }).count(), 0, "the page is drawn behind the notice");
    },
  },
  {
    id: "a-partner-sees-every-settings-page-live-and-no-read-only-sentence",
    title: "a Partner: branding and the treaty rates carry no read-only sentence, the controls are live, and the audit log opens",
    async run(env) {
      const { page } = env;
      env.stub.signInAs("Partner");
      settingsReads(env);
      await page.goto(`${env.base}/settings/branding/`, { waitUntil: "networkidle" });
      await page.getByLabel("Tagline").waitFor();
      assert.equal(await page.locator("[data-read-only-notice]").count(), 0);
      assert.equal(await switchedOff(page, "branding:write"), false);
      await page.goto(`${env.base}/settings/treaty-rates/`, { waitUntil: "networkidle" });
      await page.getByText("Article 12(2)").waitFor();
      assert.equal(await page.locator("[data-read-only-notice]").count(), 0);
      await page.getByRole("button", { name: /Add reading/ }).waitFor();
      assert.equal(await page.getByRole("button", { name: /^Remove / }).count(), 1);
      await page.goto(`${env.base}/settings/audit-log/`, { waitUntil: "networkidle" });
      await page.waitForTimeout(400);
      assert.equal(await page.locator("[data-tick-gate]").count(), 0, "a Partner is refused the audit log");
    },
  },
];
