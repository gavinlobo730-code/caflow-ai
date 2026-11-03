/**
 * Group Q: the bank's entry dialog and the three it opens from inside itself STACK, and one Escape closes only the top one
 * (POST-A-128, POST-A-130).
 *
 * The entry dialog was hand-built, with no Escape, no focus handling and no Tab trap, and opened a split, a settlement and a match finder
 * that were hand-built too. It could not move onto the shared Modal until the Modal stacked (two Modals both heard one Escape) and took a
 * footer. All four are the shared Modal now, and this drives what that is for in Chromium:
 *
 *   1. the entry opens as a NAMED dialog and the page behind it is locked;
 *   2. "Split across several" opens a second dialog over it; Tab and Shift+Tab never leave the TOP one; one Escape closes only that one, the
 *      entry dialog is still open and focus is back on the button that opened the split;
 *   3. the same for "Find the invoice", the match finder, whose footer (the paging line) stays in view;
 *   4. a second Escape closes the entry dialog, gives the page its scroll back and returns focus to the row.
 */
import assert from "node:assert/strict";
import { ok } from "../stub.mjs";
import { until } from "../kit.mjs";

export const group = "bank-dialogs";

const ENTRY = {
  id: "e-1", transaction_date: "2026-05-04", description: "NEFT KUMAR AGENCIES 4471", reference_no: null,
  debit_paise: 0, credit_paise: 1180000, match_status: "unmatched", category: null, account_id: null,
  matched_entity_type: null, matched_entity_id: null, matched_document_no: null, posted_journal_id: null,
  transfer_pair_id: null, transfer_is_primary: null, payee_name: null, payee_type: null, payee_id: null,
  has_splits: false, kind: "receipt", entry_state: "needs_you",
  draft_source: null, draft_grade: null, draft_label: null, draft_reason: null,
  draft_account_id: null, draft_category: null, draft_entity_type: null, draft_entity_id: null,
  draft_rule_id: null, draft_gst_rate_bps: null, draft_is_interstate: false, draft_error: null, drafted_at: null,
  posted_by_rule_id: null, gst_allowed: false, attachments: [], splits: [], parsed: null,
};
const COUNTS = { needs_you: 1, proposed: 0, ready: 0, covered: 0, passed: 0, set_aside: 0, to_do: 1, undrafted: 0, trusted_pending: 0, tds_decision_pending: 0 };

async function atTheEntry(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /api\/banking\/entries\/counts/, reply: () => ok(COUNTS) });
  stub.route({ method: "GET", re: /api\/banking\/entries\/e-1/, reply: () => ok({ ...ENTRY, suggestions: [], history: null, suggested_payee: null, transfer_candidate: null }) });
  stub.route({ method: "GET", re: /api\/banking\/entries\?/, reply: () => ok({ rows: [ENTRY], total: 1, ledger_order: [] }) });
  stub.route({ method: "GET", re: /api\/banking\/transactions\/e-1\/splits/, reply: () => ok([]) });
  stub.route({ method: "GET", re: /api\/banking\/candidates|api\/banking\/.*search/, reply: () => ok({ results: [], total: 0, allowed_types: [], truncated: false }) });
  await page.goto(env.at("/bank/"), { waitUntil: "networkidle" });
  const row = page.locator("tr[data-row-clickable]").first();
  await row.waitFor();
  await row.focus();
  await row.click();
  const entry = page.getByRole("dialog").first();
  await entry.waitFor();
  return { row, entry };
}

const insideTopDialog = (page) => page.evaluate(() => {
  const dialogs = [...document.querySelectorAll('[role="dialog"]')];
  const top = dialogs[dialogs.length - 1];
  return !!top && top.contains(document.activeElement);
});

export const scenarios = [
  {
    id: "the-entry-dialog-and-the-dialogs-it-opens-stack-and-one-escape-closes-only-the-top-one",
    title: "the entry dialog is a named, locked dialog; a split and a match finder open over it, trap Tab, and close one at a time on Escape; the last Escape returns focus to the row",
    async run(env) {
      const { page } = env;
      const { row, entry } = await atTheEntry(env);
      assert.equal(await entry.getAttribute("aria-modal"), "true", "the entry dialog does not say it is modal");
      assert.ok((await entry.getAttribute("aria-labelledby")), "the entry dialog has no name");
      assert.equal(await page.evaluate(() => document.body.style.overflow), "hidden", "the page behind the entry dialog can still scroll");

      // 2. the split over the entry
      await until(async () => (await page.getByRole("button", { name: /Split across several/ }).count()) > 0, "the Split button to be offered");
      const splitButton = page.getByRole("button", { name: /Split across several/ }).first();
      await splitButton.focus();
      await splitButton.click();
      const split = page.getByRole("dialog", { name: "Split across ledgers" });
      await split.waitFor();
      assert.equal(await page.getByRole("dialog").count(), 2, "the split should be a second dialog over the entry");
      await until(() => insideTopDialog(page), "focus to move into the split dialog");
      for (const key of ["Tab", "Tab", "Tab", "Tab", "Tab", "Shift+Tab", "Shift+Tab", "Shift+Tab"]) {
        await page.keyboard.press(key);
        assert.equal(await insideTopDialog(page), true, `${key} left the split dialog`);
      }
      await page.keyboard.press("Escape");
      await split.waitFor({ state: "detached" });
      assert.equal(await page.getByRole("dialog").count(), 1, "one Escape closed more than the top dialog");
      assert.ok(await entry.isVisible(), "the entry dialog closed with the split");
      assert.equal(await page.evaluate(() => document.body.style.overflow), "hidden", "the page was unlocked while the entry dialog is still open");
      assert.equal(await splitButton.evaluate((el) => el === document.activeElement), true, "focus did not return to the button that opened the split");

      // 3. the match finder over the entry; its paging footer stays in view
      const find = page.getByRole("button", { name: /Find the invoice/ }).first();
      await find.focus();
      await find.click();
      const finder = page.getByRole("dialog", { name: "Find other matches" });
      await finder.waitFor();
      assert.equal(await page.getByRole("dialog").count(), 2);
      assert.ok(await finder.getByText(/No documents|of \d+/).isVisible(), "the match finder's footer is not in view");
      await page.keyboard.press("Escape");
      await finder.waitFor({ state: "detached" });
      assert.equal(await page.getByRole("dialog").count(), 1, "one Escape closed more than the match finder");
      assert.equal(await find.evaluate((el) => el === document.activeElement), true, "focus did not return to the button that opened the finder");

      // 4. the last Escape closes the entry dialog and gives the page back
      await page.keyboard.press("Escape");
      await entry.waitFor({ state: "detached" });
      assert.equal(await page.evaluate(() => document.body.style.overflow), "", "the page is still locked after the last dialog closed");
      assert.equal(await row.evaluate((el) => el === document.activeElement), true, "focus did not return to the row that opened the entry");
    },
  },
];
