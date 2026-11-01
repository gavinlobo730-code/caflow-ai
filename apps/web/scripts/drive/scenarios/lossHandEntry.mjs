/**
 * Group M: correcting a brought-forward loss record by hand, driven in a browser (POST-A-368, items 2 and 3, and PRE-A-015).
 *
 * The dialogs that record a year's use of a loss, or take a use off it, change a statutory carry-forward, so what a click really does matters:
 * a source guard (`a-loss-can-be-corrected-by-hand-from-the-computation-screen.test.ts`) reads that the confirm button is the shared
 * single-click one and that the page hands it the request's promise, and this proves it in Chromium.
 *
 *   1. two same-tick clicks on "Record" send ONE request carrying the year chosen, the amount in paise converted from the rupees typed and the
 *      reason, the dialog closes and the uses are read again (the screen does not work out what the record now holds);
 *   2. the dialog refuses to send with no reason, with no year and with an amount that is not an amount, and sends nothing;
 *   3. a refusal the server raised as an HTTP error (a year a return already holds) is shown in the dialog in the server's words, the dialog
 *      stays open, nothing is closed over it, and the person can press Record again;
 *   4. "Take back" on a use opens the dialog for it, says a filed return's entry comes back when that return's records are written again,
 *      and two same-tick clicks send ONE request naming that entry with the reason;
 *   5. a person without the compute tier is offered neither control, and the uses are still listed.
 */
import assert from "node:assert/strict";
import { ok, refuse } from "../stub.mjs";
import { sameTickDouble, expectWrites, until } from "../kit.mjs";
import { CLIENT_ROW } from "../fixtures.mjs";

export const group = "loss-hand-entry";

const LOSS_ID = "loss-1";
const LOSS = {
  id: LOSS_ID, client_id: CLIENT_ROW.id, assessment_year: "2023-24", loss_type: "business", original_amount_paise: 1_000_000_00,
  remaining_amount_paise: 700_000_00, utilized_amount_paise: 300_000_00, expiry_assessment_year: "2031-32", utilisations: {},
};
const FILING_USE = {
  entry_id: "filing-1", filing_id: "filing-1", financial_year: "2024-25", return_type: "original", amount_paise: 300_000_00,
  filing_found: true, acknowledgement_number: "ACK-2024-1",
};
const HAND_USE = {
  entry_id: "manual:2025-26", filing_id: "manual:2025-26", financial_year: "2025-26", return_type: "manual", amount_paise: 100_000_00,
  filing_found: null, acknowledgement_number: null,
};
const LIST_ROUTE = /itr\/bf-losses\?client_id=/;
const RECORD_ROUTE = /itr\/bf-losses\/loss-1\/year-use$/;
const TAKE_BACK_ROUTE = /itr\/bf-losses\/loss-1\/uses\/[^/]+\/take-back$/;

const served = (uses) => ok([{ ...LOSS, uses, hand_recorded_paise: 0 }]);

/** The Tax Computation screen with one loss listed, for a person holding `actions` on income tax. */
async function atTheLosses(env, actions, uses, { reads = null } = {}) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { income_tax: actions } }) });
  // The screen loads nothing until the server has said which year it is on (it never guesses one).
  stub.route({ method: "GET", re: /income-tax\/financial-years$/,
               reply: () => ok({ financial_years: [{ fy: "2026-27", verified: true }, { fy: "2025-26", verified: true }], current_fy: "2026-27" }) });
  stub.route({ method: "GET", re: LIST_ROUTE, reply: () => { if (reads) reads.count += 1; return served(typeof uses === "function" ? uses() : uses); } });
  stub.setTable("brought_forward_losses", [LOSS]);
  await page.goto(`${env.base}/clients/${CLIENT_ROW.id}/tax/computation/`, { waitUntil: "networkidle" });
  // The losses are a collapsed panel on this screen; open it by its own heading.
  await page.getByRole("button", { name: /Brought Forward Losses/ }).click();
  await page.getByText(/business Loss/i).first().waitFor();
}

const text = (page) => page.locator("body").innerText();

export const scenarios = [
  {
    id: "two-clicks-on-record-send-one-request-with-the-year-the-paise-and-the-reason",
    title: "a same-tick double click on Record sends one request carrying the year, the amount in paise and the typed reason, closes the dialog and reads the uses again",
    async run(env) {
      const { page, stub } = env;
      const reads = { count: 0 };
      let recorded = false;
      await atTheLosses(env, ["read", "compute"], () => (recorded ? [FILING_USE, HAND_USE] : [FILING_USE]), { reads });
      stub.route({
        method: "POST", re: RECORD_ROUTE,
        reply: () => { recorded = true; return ok({ state: "written", loss_id: LOSS_ID, financial_year: "2025-26", recorded_paise: 100_000_00,
                                                    message: "FY 2025-26 is recorded as having used ₹1,00,000 of this loss." }); },
      });
      const before = reads.count;

      await page.getByRole("button", { name: "Record a year's use by hand" }).click();
      const dialog = page.getByRole("dialog");
      const confirm = dialog.getByRole("button", { name: "Record", exact: true });
      assert.equal(await confirm.isDisabled(), true, "the confirm button was live with nothing typed");

      await dialog.getByLabel("Financial year that used the loss").selectOption("2025-26");
      await dialog.getByLabel("Amount of the loss it used (₹)").fill("100000");
      assert.equal(await confirm.isDisabled(), true, "the confirm button was live with no reason typed");
      await dialog.getByLabel("Why is this being recorded?").fill("Filed on the portal before we took over the books");
      assert.equal(await confirm.isDisabled(), false, "the confirm button stayed disabled with every field filled");

      await sameTickDouble(confirm);

      await expectWrites(stub, RECORD_ROUTE, 1, "two same-tick clicks on Record");
      const [write] = stub.writesTo(RECORD_ROUTE);
      assert.deepEqual(JSON.parse(write.body),
        { financial_year: "2025-26", amount_paise: 100_000_00, reason: "Filed on the portal before we took over the books" },
        "the year, the paise or the reason sent was not what was chosen and typed");
      await until(async () => (await page.getByRole("dialog").count()) === 0, "the dialog to close after a record");
      await until(async () => reads.count > before, "the uses to be read again after the write");
      await page.getByText("FY 2025-26, recorded by hand: ₹1,00,000").first().waitFor();
      assert.match(await text(page), /Take back/);
    },
  },
  {
    id: "the-dialog-refuses-to-send-without-a-year-an-amount-or-a-reason",
    title: "Record stays disabled with no reason, no year, nothing typed or an amount that is not an amount, and nothing is sent",
    async run(env) {
      const { page, stub } = env;
      await atTheLosses(env, ["read", "compute"], [FILING_USE]);
      await page.getByRole("button", { name: "Record a year's use by hand" }).click();
      const dialog = page.getByRole("dialog");
      const confirm = dialog.getByRole("button", { name: "Record", exact: true });
      await dialog.getByLabel("Why is this being recorded?").fill("A reason");
      await dialog.getByLabel("Amount of the loss it used (₹)").fill("100000");
      assert.equal(await confirm.isDisabled(), true, "the confirm button was live with no year chosen");
      await dialog.getByLabel("Financial year that used the loss").selectOption("2025-26");
      assert.equal(await confirm.isDisabled(), false, "the confirm button stayed disabled with everything filled");

      for (const bad of ["abc", "1e3", "12.345", "0", "-5", "1,00,000"]) {
        await dialog.getByLabel("Amount of the loss it used (₹)").fill(bad);
        assert.equal(await confirm.isDisabled(), true, `the confirm button was live with the amount "${bad}"`);
      }
      await dialog.getByLabel("Amount of the loss it used (₹)").fill("1,00,000");
      await dialog.getByText("Enter the amount in rupees with no commas").waitFor();
      await dialog.getByLabel("Amount of the loss it used (₹)").fill("0");
      await dialog.getByText("Enter more than nothing.").waitFor();
      await dialog.getByLabel("Amount of the loss it used (₹)").fill("100000");
      await dialog.getByLabel("Why is this being recorded?").fill("   ");
      assert.equal(await confirm.isDisabled(), true, "the confirm button was live with a reason of spaces");
      await expectWrites(stub, RECORD_ROUTE, 0, "a dialog that was never confirmed");
    },
  },
  {
    id: "a-refusal-raised-as-an-http-error-is-shown-in-the-dialog-in-the-servers-words",
    title: "a refusal that arrives as a FastAPI detail (a year a return already holds) is shown in the dialog as written, the dialog stays open and can be tried again",
    async run(env) {
      const { page, stub } = env;
      const HELD = "A return on file already holds FY 2024-25's use of this loss, so it is corrected on that return (the Tax Filing screen writes its loss records again) and not by hand.";
      await atTheLosses(env, ["read", "compute"], [FILING_USE]);
      stub.route({ method: "POST", re: RECORD_ROUTE, ...refuse(HELD, 409) });

      await page.getByRole("button", { name: "Record a year's use by hand" }).click();
      const dialog = page.getByRole("dialog");
      await dialog.getByLabel("Financial year that used the loss").selectOption("2024-25");
      await dialog.getByLabel("Amount of the loss it used (₹)").fill("50000");
      await dialog.getByLabel("Why is this being recorded?").fill("Typed from the old return");
      await dialog.getByRole("button", { name: "Record", exact: true }).click();

      await dialog.getByRole("alert").filter({ hasText: HELD }).waitFor();
      assert.equal(await page.getByRole("dialog").count(), 1, "the dialog closed on a refusal");
      assert.equal(await dialog.getByRole("button", { name: "Record", exact: true }).isDisabled(), false,
        "the confirm button stayed held after a refusal");
    },
  },
  {
    id: "take-back-names-the-entry-says-a-returns-entry-comes-back-and-sends-one-request",
    title: "Take back on a filed return's use says it comes back when that return's records are written again, and a same-tick double click sends one request naming the entry",
    async run(env) {
      const { page, stub } = env;
      let taken = false;
      await atTheLosses(env, ["read", "compute"], () => (taken ? [] : [FILING_USE]));
      stub.route({
        method: "POST", re: TAKE_BACK_ROUTE,
        reply: () => { taken = true; return ok({ state: "written", loss_id: LOSS_ID, entry_id: "filing-1",
                                                 message: "The use of ₹3,00,000 for FY 2024-25 was taken off this loss." }); },
      });

      await page.getByRole("button", { name: "Take back" }).click();
      const dialog = page.getByRole("dialog");
      await dialog.getByText("comes back the next time that return's loss records are written").waitFor();
      const confirm = dialog.getByRole("button", { name: "Take it off", exact: true });
      assert.equal(await confirm.isDisabled(), true, "the confirm button was live with no reason typed");
      await dialog.getByLabel("Why is it being taken off?").fill("The return was filed against the wrong loss");

      await sameTickDouble(confirm);

      await expectWrites(stub, TAKE_BACK_ROUTE, 1, "two same-tick clicks on Take it off");
      const [write] = stub.writesTo(TAKE_BACK_ROUTE);
      assert.match(write.path, /\/uses\/filing-1\/take-back$/, "the entry named was not the one clicked");
      assert.deepEqual(JSON.parse(write.body), { reason: "The return was filed against the wrong loss" });
      await until(async () => (await page.getByRole("dialog").count()) === 0, "the dialog to close after a take-back");
      await until(async () => !(await text(page)).includes("acknowledgement ACK-2024-1"), "the taken-back use to leave the list");
    },
  },
  {
    id: "a-hand-entry-is-taken-back-without-the-comes-back-note",
    title: "Take back on a use recorded by hand does not say it comes back, and names the entry in the path",
    async run(env) {
      const { page, stub } = env;
      await atTheLosses(env, ["read", "compute"], [HAND_USE]);
      stub.route({ method: "POST", re: TAKE_BACK_ROUTE, reply: () => ok({ state: "written", loss_id: LOSS_ID, entry_id: "manual:2025-26", message: "taken off" }) });
      await page.getByRole("button", { name: "Take back" }).click();
      const dialog = page.getByRole("dialog");
      assert.doesNotMatch(await dialog.innerText(), /comes back the next time/, "a hand entry was said to come back");
      await dialog.getByLabel("Why is it being taken off?").fill("Typed against the wrong loss");
      await dialog.getByRole("button", { name: "Take it off", exact: true }).click();
      await expectWrites(stub, TAKE_BACK_ROUTE, 1, "Take it off");
      assert.match(stub.writesTo(TAKE_BACK_ROUTE)[0].path, /\/uses\/manual:2025-26\/take-back$/);
    },
  },
  {
    id: "a-person-without-the-compute-tier-is-offered-neither-control",
    title: "a person who can read but not compute sees the uses and neither Record nor Take back",
    async run(env) {
      const { page } = env;
      await atTheLosses(env, ["read"], [FILING_USE, HAND_USE]);
      await page.getByText("acknowledgement ACK-2024-1").first().waitFor();
      assert.equal(await page.getByRole("button", { name: "Take back" }).count(), 0, "Take back was offered without the tier");
      assert.equal(await page.getByRole("button", { name: "Record a year's use by hand" }).count(), 0, "Record was offered without the tier");
      assert.ok((await text(page)).includes("FY 2025-26, recorded by hand"), "the hand entry was not listed");
    },
  },
];
