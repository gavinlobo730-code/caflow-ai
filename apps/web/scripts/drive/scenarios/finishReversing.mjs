/**
 * Group: a depreciation reversal that did not finish is finished from the Depreciation tab (POST-A-349, driven in a browser).
 *
 * A reversal writes the register back a month first and reverses the month's journal second. If it stops between the two, the
 * register no longer counts the month while its journal may still be on the ledger, and the asset carries a marker that holds every
 * post off for fifteen minutes. The tab used to offer only "Reverse {posted-through month}", which the server then refused, naming a
 * remedy nobody could press. Now the schedule serves the unfinished reversal in the server's words and the row offers
 * "Finish reversing {month}" once it can be finished. This drives what a person sees:
 *
 *   1. a reversal that can be finished: the server's sentence, the Finish control, no ordinary Reverse; one click sends ONE reverse of
 *      that month (two clicks in one tick still one) and the table is read again;
 *   2. one that may still be running: the sentence with its times, and no control at all;
 *   3. a refusal from the server is shown in the row in its own words.
 */
import assert from "node:assert/strict";
import { expectWrites, sameTickDouble, until } from "../kit.mjs";
import { ok, refuse } from "../stub.mjs";

export const group = "finish-reversing";

const ASSET = "a5870000-0000-0000-0000-000000000001";
const REVERSE = /api\/fixed-assets\/a5870000-0000-0000-0000-000000000001\/depreciation\/2025-06\/reverse$/;

function scheduleRow(unfinished) {
  return {
    asset_id: ASSET, asset_code: "FA-0001", asset_name: "Lathe", asset_category: "Plant & Machinery",
    purchase_cost_paise: 2_40_000_00, accumulated_paise: 25_000_00, current_wdv_paise: 2_15_000_00,
    annual_depreciation_paise: 45_000_00, monthly_depreciation_paise: 3_750_00, depreciation_method: "WDV",
    salvage_value_paise: 0, wdv_rate_percent: 18.1, useful_life_years: 15,
    depreciation_posted_through: "2025-05", statutory_gap: null, unfinished_reversal: unfinished,
  };
}

const DEAD = {
  month: "2025-06", started_at: "2026-10-08T04:00:00+00:00", free_at: "2026-10-08T04:15:00+00:00", can_finish_now: true,
  sentence: "A reversal of 2025-06 started at 09:30 IST on 08 Oct 2026 and did not finish: the register no longer counts 2025-06 and "
    + "its journal may still be on the ledger. Finish reversing 2025-06 to take it off, or post 2025-06 again to keep it.",
};
const RUNNING = {
  month: "2025-06", started_at: "2026-10-08T04:00:00+00:00", free_at: "2026-10-08T04:15:00+00:00", can_finish_now: false,
  sentence: "A reversal of 2025-06 started at 09:30 IST on 08 Oct 2026 and has not finished. If it is still running it ends in moments; "
    + "if it stopped, Finish reversing 2025-06 is offered from 09:45 IST on 08 Oct 2026.",
};

async function atTheTab(env, unfinished, reverse) {
  const { page, stub } = env;
  const reads = { n: 0 };
  stub.route({
    method: "GET", re: /api\/fixed-assets\/depreciation-schedule/,
    reply: () => { reads.n += 1; return ok([scheduleRow(reads.n === 1 ? unfinished : null)]); },
  });
  if (reverse) stub.route({ method: "POST", re: REVERSE, ...reverse });
  await page.goto(env.at("/fixed-assets/?tab=depreciation"), { waitUntil: "networkidle" });
  await page.getByText("Lathe").first().waitFor();
  return reads;
}

const row = (page) => page.getByTestId(`unfinished-reversal-${ASSET}`);

export const scenarios = [
  {
    id: "a-reversal-that-did-not-finish-is-finished-with-one-request-and-the-table-read-again",
    title: "the row says what happened, offers Finish reversing 2025-06 and not Reverse 2025-05, and two clicks send one reverse",
    async run(env) {
      const { page, stub } = env;
      const reads = await atTheTab(env, DEAD, { reply: () => ok({ asset_id: ASSET, period: "2025-06", completed: true }), delay: 300 });
      assert.match(await row(page).innerText(), /did not finish: the register no longer counts 2025-06/);
      assert.equal(await page.getByRole("button", { name: "Reverse 2025-05" }).count(), 0, "the ordinary Reverse was offered beside it");
      await sameTickDouble(page.getByRole("button", { name: "Finish reversing 2025-06" }));
      await expectWrites(stub, REVERSE, 1, "Finish reversing", "POST");
      await until(async () => reads.n >= 2, "the table to be read again");
      await until(async () => (await row(page).count()) === 0, "the unfinished reversal to leave the row");
    },
  },
  {
    id: "a-reversal-that-may-still-be-running-offers-nothing-to-press",
    title: "within the hold the row shows the server's times and no Finish control",
    async run(env) {
      const { page, stub } = env;
      await atTheTab(env, RUNNING);
      assert.match(await row(page).innerText(), /Finish reversing 2025-06 is offered from 09:45 IST on 08 Oct 2026/);
      assert.equal(await page.getByRole("button", { name: "Finish reversing 2025-06" }).count(), 0);
      assert.equal(await page.getByRole("button", { name: "Reverse 2025-05" }).count(), 0);
      await expectWrites(stub, REVERSE, 0, "nothing pressed", "POST");
    },
  },
  {
    id: "a-refusal-to-finish-is-shown-in-the-servers-words",
    title: "a 409 from the server lands in the row as the server wrote it",
    async run(env) {
      const { page } = env;
      const sentence = "This asset changed while the reversal of 2025-06 was being finished (a month was posted over it, or another "
        + "request finished it first). Nothing was reversed; reload the asset.";
      await atTheTab(env, DEAD, refuse(sentence, 409));
      await page.getByRole("button", { name: "Finish reversing 2025-06" }).click();
      await page.getByText(sentence).waitFor();
    },
  },
];
