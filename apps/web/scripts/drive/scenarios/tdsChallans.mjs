/**
 * Group L: retracting a TDS challan recorded in error, driven in a browser (POST-A-362 and PRE-A-015).
 *
 * The prompt that takes a challan out of the register is a money action on a statutory record, so what a click really does matters:
 * a source guard (`a-challan-is-retracted-with-a-reason-through-the-servers-door.test.ts`) reads that the confirm button is the shared
 * single-click one and that the page hands it the request's promise, and this proves it in Chromium.
 *
 *   1. two clicks on "Retract challan" in the same tick send ONE request, carrying the reason that was typed, and the server's two
 *      sentences about what the retraction did not change (a month of the calendar still reading filed, a statement already filed)
 *      are shown as written, with the challan gone from the list after the register is read again;
 *   2. a refusal the server raised as an HTTP error (`{"detail": "<sentence>"}`, which has no `success` or `error`) is shown in the
 *      prompt in the server's words, the prompt stays open, and the challan is still listed;
 *   3. a person without the write tier sees no Retract button at all, and the screen still lists the challan;
 *   4. a deposit worksheet whose answer is not a worksheet leaves the Challans tab standing and says the worksheet could not be read (the
 *      screen used to be replaced by its error page: the first run of this group found it).
 */
import assert from "node:assert/strict";
import { ok, refuse } from "../stub.mjs";
import { pick, sameTickDouble, expectWrites, until } from "../kit.mjs";
import { CLIENT_ROW } from "../fixtures.mjs";

export const group = "tds-challans";

const CHALLAN = {
  id: "ch-1", client_id: CLIENT_ROW.id, bsr_code: "0510001", challan_no: "00045", payment_date: "2026-07-05",
  total_paise: 1_250_000, tds_paise: 1_250_000, surcharge_paise: 0, interest_paise: 0, penalty_paise: 0, minor_head: "200",
  financial_year: "2026-27", quarter: "Q1", section: "194C", status: "deposited",
};

const CALENDAR_NOTE = "The compliance calendar still shows the monthly TDS deposit (non-salary) for April 2026 as filed. Retracting the challan does not reopen it.";
const STATEMENT_NOTE = "The TDS statement for this quarter is recorded as filed. Retracting a challan changes the register and does not change a statement already filed.";
const RETRACT_ROUTE = /tds-workspace\/challans\/ch-1\/retract$/;

/** The screen with one challan listed, for a person holding `actions` on tds; opens the Challans tab. */
async function atTheChallans(env, actions, { listAfter = null } = {}) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { tds: actions } }) });
  let retracted = false;
  stub.route({
    method: "GET", re: /tds-workspace\/challans\?/,
    reply: () => ok({ challans: retracted && listAfter ? listAfter : [CHALLAN], has_more: false, limit: 500, max_limit: 500 }),
  });
  await page.goto(`${env.base}/tds/`, { waitUntil: "networkidle" });
  await pick(page, page.locator('button:has-text("Select client")').first(), CLIENT_ROW.client_name);
  await page.getByRole("button", { name: "Challans", exact: true }).click();
  await page.getByText("00045").waitFor();
  return { markRetracted: () => { retracted = true; } };
}

const text = (page) => page.locator("body").innerText();

export const scenarios = [
  {
    id: "two-clicks-on-retract-challan-send-one-request-and-show-the-servers-notes",
    title: "a same-tick double click on Retract challan sends one request with the typed reason, shows both of the server's notes, and the challan leaves the list",
    async run(env) {
      const { page, stub } = env;
      const screen = await atTheChallans(env, ["read", "compute", "write"], { listAfter: [] });
      stub.route({
        method: "POST", re: RETRACT_ROUTE,
        reply: () => {
          screen.markRetracted();
          return ok({ retracted: "ch-1", challan_no: "00045", payment_date: "2026-07-05", total_paise: 1_250_000,
                      calendar_note: CALENDAR_NOTE, statement_note: STATEMENT_NOTE });
        },
      });

      await page.getByRole("button", { name: /^Retract challan 00045/ }).click();
      const dialog = page.getByRole("dialog");
      const confirm = dialog.getByRole("button", { name: "Retract challan", exact: true });
      assert.equal(await confirm.isDisabled(), true, "the confirm button was live with no reason typed");
      await dialog.getByLabel("Why is it being retracted?").fill("Keyed under the wrong quarter");
      assert.equal(await confirm.isDisabled(), false, "the confirm button stayed disabled with a reason typed");

      await sameTickDouble(confirm);

      await expectWrites(stub, RETRACT_ROUTE, 1, "two same-tick clicks on Retract challan");
      const [write] = stub.writesTo(RETRACT_ROUTE);
      assert.deepEqual(JSON.parse(write.body), { reason: "Keyed under the wrong quarter" }, "the typed reason was not what was sent");
      await page.getByText(CALENDAR_NOTE).waitFor();
      const body = await text(page);
      assert.ok(body.includes(STATEMENT_NOTE), "the statement note was not shown as the server wrote it");
      assert.match(body, /Challan retracted\. What it did not change:/);
      await until(async () => !(await text(page)).includes("00045"), "the retracted challan to leave the list");
      assert.equal(await page.getByRole("dialog").count(), 0, "the prompt stayed open after a retraction");
    },
  },
  {
    id: "a-refusal-raised-as-an-http-error-is-shown-in-the-prompt-in-the-servers-words",
    title: "a refusal that arrives as a FastAPI detail (a locked year) is shown in the prompt as written, the prompt stays open and the challan stays listed",
    async run(env) {
      const { page, stub } = env;
      const LOCKED = "The financial year 2026-27 is locked, so a challan dated in it cannot be retracted. Ask a Partner to unlock it first.";
      await atTheChallans(env, ["read", "compute", "write"]);
      stub.route({ method: "POST", re: RETRACT_ROUTE, ...refuse(LOCKED, 422) });

      await page.getByRole("button", { name: /^Retract challan 00045/ }).click();
      const dialog = page.getByRole("dialog");
      await dialog.getByLabel("Why is it being retracted?").fill("Wrong quarter");
      await dialog.getByRole("button", { name: "Retract challan", exact: true }).click();

      await dialog.getByRole("alert").filter({ hasText: LOCKED }).waitFor();
      assert.equal(await page.getByRole("dialog").count(), 1, "the prompt closed on a refusal");
      assert.ok((await text(page)).includes("00045"), "a refused retraction took the challan out of the list");
      // The person can try again: the guard is released when the request settles, on a refusal as on a success.
      assert.equal(await dialog.getByRole("button", { name: "Retract challan", exact: true }).isDisabled(), false,
        "the confirm button stayed held after a refusal");
    },
  },
  {
    id: "a-worksheet-answer-that-is-not-a-worksheet-does-not-take-the-screen-down",
    title: "when the deposit worksheet's answer is not a worksheet, the Challans tab still lists the challan and says the worksheet could not be read",
    async run(env) {
      const { page, stub } = env;
      // Found by driving this tab: the stub's default answer to a read is a list, and the panel read `.length` of a field a list does not
      // have, so the whole screen was replaced by "TDS could not be displayed". The same happens to a deploy that is behind the screen.
      stub.route({ method: "GET", re: /tds-workspace\/deposit-due\?/, reply: () => ok([]) });
      await atTheChallans(env, ["read", "compute", "write"]);
      await page.getByText("The deposit worksheet came back in a shape this screen cannot read.").waitFor();
      assert.ok((await text(page)).includes("00045"), "the challan was not listed beside a worksheet that could not be read");
      assert.doesNotMatch(await text(page), /TDS could not be displayed/, "the screen was replaced by its error page");
    },
  },
  {
    id: "without-the-write-tier-there-is-no-retract-button",
    title: "a person who can record a challan but not remove one sees the challan and no Retract button",
    async run(env) {
      const { page } = env;
      await atTheChallans(env, ["read", "compute"]);
      assert.equal(await page.getByRole("button", { name: /^Retract challan/ }).count(), 0, "a Retract button was offered without tds.write");
      assert.ok((await text(page)).includes("00045"), "the challan was not listed");
    },
  },
];
