/**
 * THE PHYSICAL STOCK COUNT SHEET IS DRIVEN IN A BROWSER (POST-A-555).
 *
 * POST-A-130's seventeenth step moved the count sheet onto the shared dialog and left it undriven: it needs a count on record. Against a stubbed
 * server, in Chromium, as a Partner on a client's Inventory screen, with Physical count pressed:
 *
 *   1. the sheet is a NAMED modal dialog (named for the count's reference), the page behind it is locked, Tab and Shift+Tab never leave it, and
 *      Escape closes it, gives the page its scroll back and returns focus to the Physical count button;
 *   2. while the counts are being saved it is HELD (its ×, Escape and a click beside it close nothing), the request goes ONCE and carries the
 *      typed quantity as typed, and the server's refusal is read inside the sheet.
 *
 * No scenario has a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";
import { ok, refuse } from "../stub.mjs";

export const group = "stock-count-sheet";

const focusInside = (dialog) => dialog.evaluate((d) => d.contains(document.activeElement));
const pageLocked = (page) => page.evaluate(() => document.body.style.overflow);

const SESSION = { id: "cs-1", client_id: "c1", count_date: "2026-10-07", reference_no: "CNT/2026-27/0001", status: "open", notes: null, posted_at: null };
const LINE = {
  service_catalogue_id: "sc1", item_name: "Copier paper", unit: "NOS", system_qty_units: "40", current_qty_units: "40",
  counted_qty_units: null, variance_qty_units: null, direction: null, reason: null, reverse_itc: null, itc_reversal_is_interstate: false,
  will_post: false, gaps: ["Count this item."], caveats: [], notes: "",
};
const SHEET = { session: SESSION, lines: [LINE], counted_count: 0, variance_count: 0, postable_count: 0, blocked_count: 1, gaps: [] };
const SAVE = /api\/inventory\/count-sessions\/cs-1$/;

async function atTheCountSheet(env, save) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { inventory: ["read", "write"], accounting: ["read", "write"] } }) });
  stub.route({ method: "GET", re: /api\/inventory\/items\?/, reply: () => ok([{
    id: "sc1", name: "Copier paper", description: null, hsn_sac: "4802", unit: "NOS", is_active: true, stock_qty_units: 40, avg_cost_paise: 25000, stock_value_paise: 1000000 }]) });
  stub.route({ method: "GET", re: /api\/inventory\/godowns\?/, reply: () => ok({ unallocated_means: "Stock not yet placed in a godown.", godowns: [] }) });
  stub.route({ method: "GET", re: /api\/inventory\/count-sessions\?/, reply: () => ok([SESSION]) });
  stub.route({ method: "GET", re: /api\/inventory\/count-sessions\/cs-1$/, reply: () => ok(SHEET) });
  stub.route({ method: "PATCH", re: SAVE, ...(save ?? { reply: () => ok({ ...SHEET, saved: 1 }) }) });
  await page.goto(env.at("/inventory/"), { waitUntil: "networkidle" });
  const opener = page.getByRole("button", { name: "Physical count", exact: true });
  await opener.waitFor();
  await opener.focus();
  await opener.click();
  const sheet = page.getByRole("dialog", { name: /^Physical stock count/ });
  await sheet.waitFor();
  await sheet.getByText("Copier paper").waitFor();
  return { sheet, opener };
}

export const scenarios = [
  {
    id: "the-physical-count-sheet-is-a-named-dialog-that-keeps-the-keyboard-and-gives-focus-back",
    title: "Inventory > Physical count: a dialog named for the count, the page locked, Tab and Shift+Tab kept inside, Escape closes it and focus returns to the Physical count button",
    async run(env) {
      const { page } = env;
      const { sheet, opener } = await atTheCountSheet(env);
      assert.equal(await page.getByRole("dialog").count(), 1, "more than one dialog is open");
      assert.equal(await sheet.getAttribute("aria-modal"), "true", "the count sheet does not say it is modal");
      assert.match(await sheet.innerText(), /CNT\/2026-27\/0001/, "the sheet does not say which count it is");
      assert.equal(await pageLocked(page), "hidden", "the page behind the count sheet can still scroll");
      await until(() => focusInside(sheet), "focus to move into the count sheet");
      for (let i = 0; i < 10; i += 1) {
        await page.keyboard.press("Tab");
        assert.equal(await focusInside(sheet), true, `Tab number ${i + 1} left the count sheet`);
      }
      for (let i = 0; i < 10; i += 1) {
        await page.keyboard.press("Shift+Tab");
        assert.equal(await focusInside(sheet), true, `Shift+Tab number ${i + 1} left the count sheet`);
      }
      await page.keyboard.press("Escape");
      await sheet.waitFor({ state: "detached" });
      assert.equal(await pageLocked(page), "", "the page is still locked after the count sheet closed");
      assert.equal(await opener.evaluate((el) => el === document.activeElement), true, "focus did not return to the Physical count button");
    },
  },
  {
    id: "the-physical-count-sheet-is-held-while-the-counts-are-saved-and-the-refusal-is-read-in-it",
    title: "Physical count > Save counts: while the save is out the sheet is held (the ×, Escape and a click beside it close nothing), the request goes once with the quantity as typed, and the refusal is read inside the sheet",
    async run(env) {
      const { page, stub } = env;
      const { sheet } = await atTheCountSheet(env, { delay: 2500, ...refuse("A stub refusal of the counts.", 422) });
      await sheet.getByLabel("Counted quantity for Copier paper").fill("37.5");
      stub.forgetWrites();
      await sheet.getByRole("button", { name: "Save counts", exact: true }).click();
      await sheet.getByRole("button", { name: "Saving…" }).waitFor({ timeout: 3000 });
      await sheet.getByRole("button", { name: "Close dialog", exact: true }).click({ force: true, timeout: 1500 }).catch(() => {});
      await page.keyboard.press("Escape");
      await page.mouse.click(5, 5);
      assert.equal(await sheet.count(), 1, "the ×, Escape or a click beside it closed the count sheet while the counts were being saved");
      await sheet.getByText("A stub refusal of the counts.").waitFor({ timeout: 8000 })
        .catch(() => { throw new Error("the server's refusal was not shown inside the count sheet"); });
      const sent = stub.writesTo(SAVE, "PATCH");
      assert.equal(sent.length, 1, "the counts were not sent exactly once");
      assert.deepEqual(JSON.parse(sent[0].body).entries, [{ service_catalogue_id: "sc1", counted_qty_units: 37.5 }], "the request did not carry the typed quantity");
    },
  },
];
