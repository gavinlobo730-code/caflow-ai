/**
 * AN ASSET'S PLACE AND KEEPER HAVE A DATED HISTORY (POST-A-112, its first half), driven in a browser.
 *
 * Against a stubbed server, in Chromium, on a client's fixed-asset register with one asset opened:
 *
 *   1. the row says where the asset is and who keeps it, in words where there is none, and lists its movements latest first, each with
 *      what changed, the note and who recorded it;
 *   2. Record a movement opens on where the asset is and who keeps it now, sends the day, what the form opened on and what it is AFTER
 *      the move, says it was recorded, shows the row's new place and keeper from the server's answer and reads the history again; two
 *      clicks in one tick send ONE movement;
 *   3. the server's refusal (a movement before the latest one) is shown in its own words and the form keeps what was typed, the
 *      register being where the form opened;
 *   4. a history the server could not read is said with Try again, never as an asset that has not moved, and Try again reads it;
 *   5. a refusal because somebody else moved the asset since the form opened closes the form, keeps the server's sentence, shows the
 *      row where the asset is now, and a new form starts from there.
 *
 * The date typed is judged by the one date module and is not this drive's subject; the dates group holds every date box's rules.
 */
import assert from "node:assert/strict";
import { sameTickDouble, until } from "../kit.mjs";
import { ok, refuse } from "../stub.mjs";

export const group = "asset-movements";

const ASSET = {
  id: "fa-1", asset_code: "FA-0001", asset_name: "Lathe", asset_category: "Plant & Machinery", location: "Factory", custodian: null,
  purchase_date: "2024-04-10", purchase_cost_paise: 10000000, salvage_value_paise: 0, depreciation_method: "WDV", wdv_rate_percent: 15,
  useful_life_years: null, accumulated_depreciation_paise: 0, is_disposed: false, notes: null,
};
const HISTORY = /\/api\/fixed-assets\/fa-1\/movements$/;
const MOVES = [
  { id: "m-2", moved_on: "2025-06-01", from_location: "Bay 2", to_location: "Factory", from_custodian: null, to_custodian: null,
    note: "Back after repairs", recorded_by: "Asha Rao" },
  { id: "m-1", moved_on: "2025-05-01", from_location: null, to_location: "Bay 2", from_custodian: null, to_custodian: "R. Iyer",
    note: null, recorded_by: null },
];

async function atTheAsset(env, { asset = ASSET, history = () => ok({ location: "Factory", custodian: null, movements: MOVES }) } = {}) {
  const { page, stub } = env;
  stub.setTable("fixed_assets", [asset]);
  const reads = [];
  stub.route({ method: "GET", re: HISTORY, reply: () => { reads.push(1); return history(reads.length); } });
  await page.goto(env.at("/fixed-assets/"), { waitUntil: "networkidle" });
  await page.getByText("Lathe", { exact: true }).first().click();
  await page.getByTestId("asset-movements-fa-1").waitFor();
  return reads;
}

const panel = (page) => page.getByTestId("asset-movements-fa-1");

export const scenarios = [
  {
    id: "the-row-says-where-and-who-and-lists-the-movements-latest-first",
    title: "the row says where the asset is and who keeps it, and lists its movements latest first with what changed",
    async run(env) {
      const { page } = env;
      await atTheAsset(env);
      await page.getByText("nobody named").first().waitFor();
      const items = await panel(page).locator("li").allInnerTexts();
      assert.equal(items.length, 2);
      assert.match(items[0], /^01 Jun 2025 · Bay 2 → Factory · Back after repairs · recorded by Asha Rao$/);
      assert.match(items[1], /^01 May 2025 · no place recorded → Bay 2 · kept by nobody named → R\. Iyer · recorded by a member no longer with the firm$/);
    },
  },
  {
    id: "record-a-movement-sends-the-day-and-what-it-is-after-once-and-reads-the-history-again",
    title: "Record a movement: opens on the present place and keeper, one request for a double click, said and read again",
    async run(env) {
      const { page, stub } = env;
      const sent = [];
      stub.route({ method: "POST", re: HISTORY, delay: 300, reply: (_req, raw) => {
        sent.push(JSON.parse(raw));
        return ok({ id: "m-3", moved_on: "2025-07-01", from_location: "Factory", to_location: "Warehouse", from_custodian: null,
                    to_custodian: "Stores team", note: null, recorded_by: "Asha Rao" });
      } });
      const reads = await atTheAsset(env);
      await panel(page).getByRole("button", { name: "Record a movement" }).click();
      assert.equal(await page.getByLabel("Now at", { exact: true }).inputValue(), "Factory");
      assert.equal(await page.getByLabel("Now kept by", { exact: true }).inputValue(), "");
      await page.locator("#asset-moved-on-fa-1").fill("01/07/2025");
      await page.locator("#asset-moved-on-fa-1").press("Tab");
      await page.getByLabel("Now at", { exact: true }).fill("Warehouse");
      await page.getByLabel("Now kept by", { exact: true }).fill("Stores team");
      await sameTickDouble(page.getByRole("button", { name: "Record the movement" }));
      await page.getByText("Recorded. The register shows the asset where it is now.").waitFor();
      assert.equal(sent.length, 1, `the movement was sent ${sent.length} times`);
      assert.deepEqual(sent[0], { moved_on: "2025-07-01", from_location: "Factory", from_custodian: null, to_location: "Warehouse",
                                  to_custodian: "Stores team", note: null });
      await until(async () => reads.length >= 2, "the history to be read again");
      // The row shows where the asset is now, from the server's answer, and the confirmation stays on screen.
      await page.getByText("Stores team", { exact: true }).first().waitFor();
      assert.equal(await page.getByText("Recorded. The register shows the asset where it is now.").count(), 1);
    },
  },
  {
    id: "the-servers-refusal-is-said-in-its-words-and-the-form-keeps-what-was-typed",
    title: "a movement the server refuses: its sentence, and the form still holds what was typed",
    async run(env) {
      const { page, stub } = env;
      const sentence = "Moved on: the asset's latest movement is dated 01 Jun 2025, and one recorded before it would leave the register showing the wrong place. Record movements in the order they happened.";
      stub.route({ method: "POST", re: HISTORY, ...refuse(sentence) });
      const reads = await atTheAsset(env);
      await panel(page).getByRole("button", { name: "Record a movement" }).click();
      await page.locator("#asset-moved-on-fa-1").fill("15/05/2025");
      await page.locator("#asset-moved-on-fa-1").press("Tab");
      await page.getByLabel("Now at", { exact: true }).fill("Bay 3");
      await page.getByRole("button", { name: "Record the movement" }).click();
      await panel(page).getByText(sentence).waitFor();
      await until(async () => reads.length >= 2, "the history to be read again after the refusal");
      assert.equal(await page.getByLabel("Now at", { exact: true }).inputValue(), "Bay 3");
    },
  },
  {
    id: "a-history-not-read-is-said-with-try-again-never-as-an-asset-that-has-not-moved",
    title: "a history the server could not read: said with Try again, not as 'has not moved', and Try again reads it",
    async run(env) {
      const { page } = env;
      await atTheAsset(env, { history: (n) => (n === 1 ? { success: false, data: null, error: "The asset's movements could not be read." }
        : ok({ location: "Factory", custodian: null, movements: [] })) });
      await panel(page).getByText("The asset's movements could not be read.").waitFor();
      assert.equal(await panel(page).getByText("has not moved").count(), 0);
      await panel(page).getByRole("button", { name: "Try again" }).click();
      await panel(page).getByText("This asset has not moved since it was entered in the register.").waitFor();
    },
  },
  {
    id: "a-form-opened-before-somebody-else-moved-the-asset-is-closed-and-starts-again-from-where-it-is",
    title: "the asset moved since the form opened: the server's sentence stays, the form closes, the row and a new form show where it is",
    async run(env) {
      const { page, stub } = env;
      const sentence = "The asset has moved since this was opened: the register now has it at Bay 3, kept by nobody named. Nothing was recorded. Open the movement again, which starts from where the asset is now.";
      const sent = [];
      stub.route({ method: "POST", re: HISTORY, status: 409, reply: (_req, raw) => { sent.push(JSON.parse(raw)); return { detail: sentence }; } });
      const moved = [{ id: "m-9", moved_on: "2025-07-01", from_location: "Factory", to_location: "Bay 3", from_custodian: null,
                       to_custodian: null, note: null, recorded_by: "Ravi K" }, ...MOVES];
      const reads = await atTheAsset(env, { history: (n) => ok(n === 1 ? { location: "Factory", custodian: null, movements: MOVES }
        : { location: "Bay 3", custodian: null, movements: moved }) });
      await panel(page).getByRole("button", { name: "Record a movement" }).click();
      await page.locator("#asset-moved-on-fa-1").fill("02/07/2025");
      await page.locator("#asset-moved-on-fa-1").press("Tab");
      await page.getByLabel("Now kept by", { exact: true }).fill("R. Iyer");
      await page.getByRole("button", { name: "Record the movement" }).click();
      await panel(page).getByText(sentence).waitFor();
      assert.equal(sent.length, 1);
      assert.equal(sent[0].from_location, "Factory");
      await until(async () => reads.length >= 2, "the history to be read again");
      assert.equal(await page.getByLabel("Now at", { exact: true }).count(), 0, "the stale form is still open");
      await page.getByText("Bay 3", { exact: true }).first().waitFor();                          // the row, from the register read again
      assert.match((await panel(page).locator("li").allInnerTexts())[0], /^01 Jul 2025 · Factory → Bay 3 · recorded by Ravi K$/);
      await panel(page).getByRole("button", { name: "Record a movement" }).click();
      assert.equal(await page.getByLabel("Now at", { exact: true }).inputValue(), "Bay 3");
      assert.equal(await panel(page).getByText(sentence).count(), 0, "a new form clears the old refusal");
    },
  },
];
