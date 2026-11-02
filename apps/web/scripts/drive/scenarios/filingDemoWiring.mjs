/**
 * Group V: the filing walk-through is offered where the SERVER says it exists, on the filings it covers, and nowhere else, driven in a browser
 * (POST-A-003, the firm-level MCA tracker).
 *
 * The walk-through is a SIMULATION that transmits and files nothing; the kill switch is the server's, and a screen asks the server before it
 * draws a control. The source guards read that each screen probes first and gates on the flow and the filing's own status; this proves what
 * the page DOES, in Chromium, against the stub:
 *
 *   1. with the flow offered, "File (demo)" is drawn on an annual form that is not filed (AOC-4), on no form the walk-through does not cover
 *      (MSME-1) and on no filing already filed; pressing it starts the walk-through for THAT filing and THAT client (the preview request
 *      carries the filing's id);
 *   2. with the walk-through switched off on the server, no control is drawn at all;
 *   3. with the probe failing, no control is drawn either (a capability that cannot be confirmed is absent).
 */
import assert from "node:assert/strict";
import { ok, refuse } from "../stub.mjs";
import { until } from "../kit.mjs";
import { CLIENT_ROW, FAKE_USERS_ROW } from "../fixtures.mjs";

export const group = "filing-demo";

const filing = (id, form, status, filed = null) => ({
  id, firm_id: FAKE_USERS_ROW.firm_id, client_id: CLIENT_ROW.id, client_name: "Acme Traders", company_cin: "U12345MH2020PTC123456",
  form_type: form, period: "FY 2024-25", due_date: "2025-10-30", filed_date: filed, srn: null, status, notes: null,
});
const ROWS = [filing("m-aoc", "AOC-4", "not_started"), filing("m-msme", "MSME-1", "not_started"), filing("m-done", "MGT-7", "filed", "2025-09-20")];
const CAPABILITIES = /filing-demo\/capabilities$/;
const PREVIEW = /filing-demo\/mca\/preview$/;

async function atTheTracker(env) {
  const { page, stub } = env;
  stub.setTable("mca_filings", ROWS);
  await page.goto(`${env.base}/mca/`, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Filings", exact: true }).click();
  await page.locator("tr", { hasText: "Acme Traders" }).first().waitFor();
}
const rowOf = (page, form) => page.locator("tr", { hasText: form }).first();
const demoButtons = (page) => page.getByRole("button", { name: "File (demo)" });

export const scenarios = [
  {
    id: "the-walk-through-is-offered-on-an-unfiled-annual-form-and-starts-for-that-filing",
    title: "with the flow offered, File (demo) is on the unfiled AOC-4 only, and pressing it asks the server to walk THAT filing through",
    async run(env) {
      const { stub } = env;
      stub.route({ method: "GET", re: CAPABILITIES, reply: () => ok({ enabled: true, flows: ["mca"] }) });
      stub.route({ method: "POST", re: PREVIEW, ...refuse("This specimen is not part of the drive.", 422) });
      await atTheTracker(env);
      await until(async () => (await demoButtons(env.page).count()) === 1, "exactly one File (demo) control to be drawn");
      assert.ok((await rowOf(env.page, "AOC-4").innerText()).includes("File (demo)"), "the control is not on the unfiled AOC-4");
      assert.ok(!(await rowOf(env.page, "MSME-1").innerText()).includes("File (demo)"), "a form the walk-through does not cover was offered it");
      assert.ok(!(await rowOf(env.page, "MGT-7").innerText()).includes("File (demo)"), "a filing already filed was offered it");

      await demoButtons(env.page).click();
      await until(() => stub.writesTo(PREVIEW, "POST").length === 1, "the walk-through to ask the server for its script");
      const [asked] = stub.writesTo(PREVIEW, "POST").map((w) => JSON.parse(w.body));
      assert.deepStrictEqual(asked, { client_id: CLIENT_ROW.id, ref: { filing_id: "m-aoc" } }, `the walk-through asked for ${JSON.stringify(asked)}`);
    },
  },
  {
    id: "with-the-walk-through-switched-off-on-the-server-no-control-is-drawn",
    title: "the server says the demos are off: no File (demo) anywhere on the tracker",
    async run(env) {
      env.stub.route({ method: "GET", re: CAPABILITIES, reply: () => ok({ enabled: false, flows: ["mca"] }) });
      await atTheTracker(env);
      await env.page.waitForTimeout(600);
      assert.strictEqual(await demoButtons(env.page).count(), 0, "a control was drawn for a walk-through the server has switched off");
    },
  },
  {
    id: "a-probe-that-fails-draws-no-control",
    title: "the capabilities probe fails: no control (a capability that cannot be confirmed is absent)",
    async run(env) {
      env.stub.route({ method: "GET", re: CAPABILITIES, ...refuse("down", 500) });
      await atTheTracker(env);
      await env.page.waitForTimeout(600);
      assert.strictEqual(await demoButtons(env.page).count(), 0, "a control was drawn although the probe failed");
    },
  },
];
