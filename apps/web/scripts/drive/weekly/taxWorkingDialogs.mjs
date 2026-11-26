/**
 * FIVE INCOME-TAX DIALOGS ARE THE SHARED ONE (POST-A-130, thirteenth step), driven in a browser.
 *
 * Add Tax Audit (and Edit), Add IT Notice, Add Capital Gains Transaction, the reinvestment exemption working of a capital-gains record and
 * Add a §32 block were each a layer built by hand over the page: no name a screen reader announces, no Tab kept inside, no Escape, no
 * focus given back. Each is the shared Modal now. The source guard holds the five; this drives each of them:
 *
 *   1. Add Tax Audit, Add IT Notice and Add Capital Gains Transaction: each named, modal, its Cancel and saving button inside, the page
 *      locked, Tab and Shift+Tab kept inside, Escape closes it and the page is unlocked;
 *   2. the reinvestment exemption working: named for its record, Tab kept inside, Escape closes it and focus is back on the row's
 *      Exemption button;
 *   3. Add a §32 block: named for its year with its line of explanation, its buttons inside, Tab kept inside, Escape closes it and focus is
 *      back on Add block.
 *
 * What each dialog sends, and that the exemption working can be left while it is only being read, are the nightly set's (the date checks
 * and dialog-leftovers), which run on the same build.
 *
 * No scenario asserts a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";
import { ok } from "../stub.mjs";
import { CLIENT_ID } from "../fixtures.mjs";
import { openAddTaxAudit, openAddIncomeTaxNotice, openCapitalGainsRegister, openReinvestmentClaim } from "../scenarios/dates.mjs";

export const group = "tax-working-dialogs";

const focusInside = (dialog) => dialog.evaluate((d) => d.contains(document.activeElement));
const pageLocked = (page) => page.evaluate(() => document.body.style.overflow);

async function tabStaysInside(page, dialog, n, what) {
  await until(() => focusInside(dialog), `focus to be inside ${what}`);
  for (let i = 0; i < n; i += 1) {
    await page.keyboard.press("Tab");
    assert.equal(await focusInside(dialog), true, `Tab number ${i + 1} left ${what}`);
  }
  for (let i = 0; i < n; i += 1) {
    await page.keyboard.press("Shift+Tab");
    assert.equal(await focusInside(dialog), true, `Shift+Tab number ${i + 1} left ${what}`);
  }
}

const FORMS = [
  { id: "add-tax-audit", open: openAddTaxAudit, name: "Add Tax Audit", buttons: ["Cancel", "Add Audit"] },
  { id: "add-it-notice", open: openAddIncomeTaxNotice, name: "Add IT Notice", buttons: ["Cancel", "Add Notice"] },
  { id: "add-capital-gains-transaction", open: openCapitalGainsRegister, name: "Add Capital Gains Transaction", buttons: ["Cancel", "Save Transaction"] },
];

export const scenarios = [
  ...FORMS.map((f) => ({
    id: `${f.id}-is-a-named-dialog-that-keeps-the-keyboard`,
    title: `Income Tax > ${f.name}: a named modal dialog with its buttons inside, the page locked, Tab kept inside, Escape closes it`,
    async run(env) {
      const { page } = env;
      await f.open(env);
      const dialog = page.getByRole("dialog", { name: f.name, exact: true });
      await dialog.waitFor();
      assert.equal(await page.getByRole("dialog").count(), 1, `${f.name}: more than one dialog is open`);
      assert.equal(await dialog.getAttribute("aria-modal"), "true", `${f.name} does not say it is modal`);
      assert.equal(await pageLocked(page), "hidden", `the page behind ${f.name} can still scroll`);
      for (const name of f.buttons) {
        assert.equal(await dialog.getByRole("button", { name, exact: true }).count(), 1, `${f.name}: ${name} is not inside the dialog`);
      }
      await tabStaysInside(page, dialog, 10, f.name);
      await page.keyboard.press("Escape");
      await dialog.waitFor({ state: "detached" });
      assert.equal(await pageLocked(page), "", `the page is still locked after ${f.name} closed`);
    },
  })),
  {
    id: "the-reinvestment-exemption-working-is-a-named-dialog-that-gives-focus-back",
    title: "Income Tax > Capital gains > a record > Exemption: a dialog named for its record, Tab kept inside, Escape closes it and focus returns to the row's Exemption button",
    async run(env) {
      const { page } = env;
      await openReinvestmentClaim(env);
      const dialog = page.getByRole("dialog", { name: "Reinvestment exemption — Flat 402", exact: true });
      await dialog.waitFor();
      assert.equal(await dialog.getAttribute("aria-modal"), "true", "the exemption working does not say it is modal");
      assert.equal(await dialog.getByRole("button", { name: "Record claim", exact: true }).count(), 1, "Record claim is not inside the dialog");
      await tabStaysInside(page, dialog, 10, "the exemption working");
      await page.keyboard.press("Escape");
      await dialog.waitFor({ state: "detached" });
      const back = await page.evaluate(() => (document.activeElement?.textContent ?? "").trim());
      assert.equal(back, "Exemption", `focus did not return to the row's Exemption button (it is on "${back}")`);
    },
  },
  {
    id: "add-a-section-32-block-is-a-named-dialog-that-gives-focus-back",
    title: "Income Tax > Depreciation §32 > Add block: a dialog named for its year with its line of explanation and its buttons inside, Tab kept inside, Escape closes it and focus returns to Add block",
    async run(env) {
      const { page, stub } = env;
      // The screen opens on the permission its read asks on the server (income tax: compute).
      stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { income_tax: ["read", "write", "compute", "approve"] } }) });
      stub.route({ method: "GET", re: /api\/income-tax\/section-32\/itr-rows$/, reply: () => ok({ rows: [] }) });
      stub.route({ method: "GET", re: /api\/income-tax\/section-32\?/, reply: () => ok({
        financial_year: "2026-27", period_start: "2026-04-01", period_end: "2027-03-31", blocks: [], depreciation_paise: 0, additional_depreciation_paise: 0,
        allowance_paise: 0, short_term_capital_gain_paise: 0, unclassified_assets: [], blocks_without_opening_wdv: [],
        additional_depreciation: { reaches_the_assessee: false, gaps: [], caveats: [], verified: false }, statutory_gaps: [], is_complete: true }) });
      await page.goto(`${env.base}/income-tax/section-32/?client_id=${CLIENT_ID}`, { waitUntil: "networkidle" });
      const opener = page.getByRole("button", { name: "Add block" }).first();
      await until(async () => !(await opener.isDisabled()), "Add block to be offered once the client is chosen");
      await opener.focus();
      await opener.click();
      const dialog = page.getByRole("dialog", { name: /^Add a §32 block — FY \d{4}-\d{2}$/ });
      await dialog.waitFor();
      assert.equal(await dialog.getAttribute("aria-modal"), "true", "Add a §32 block does not say it is modal");
      assert.match(await dialog.innerText(), /A block is a group of assets of the same nature/, "the dialog lost its line of explanation");
      for (const name of ["Cancel", "Save block"]) {
        assert.equal(await dialog.getByRole("button", { name, exact: true }).count(), 1, `${name} is not inside the dialog`);
      }
      await tabStaysInside(page, dialog, 9, "Add a §32 block");
      await page.keyboard.press("Escape");
      await dialog.waitFor({ state: "detached" });
      assert.equal(await opener.evaluate((el) => el === document.activeElement), true, "focus did not return to Add block");
    },
  },
];
