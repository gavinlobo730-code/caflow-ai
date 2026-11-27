/**
 * THE TWO SIDE SHEETS OPENED FROM A PURCHASE BILL'S MENU (Landed costs, and the Self-invoice / Payment voucher) ARE DRIVEN IN A BROWSER (POST-A-555).
 *
 * POST-A-130 moved both onto the shared side sheet and read them; no scenario opened either, and the second of them was only ever type-checked.
 * Against a stubbed server, in Chromium, on a client's Purchases screen, from a bill's menu:
 *
 *   1. Landed costs is a NAMED modal dialog, the page behind it is locked, Tab and Shift+Tab never leave it, and Escape closes it and gives the
 *      page its scroll back;
 *   2. while a charge is being recorded the sheet is HELD (its ×, Escape and a click beside it close nothing), the request goes ONCE, and the
 *      server's refusal is read inside the sheet, not in a page behind it;
 *   3. the Self-invoice sheet is a named modal dialog with the same keyboard promises, and a bill the Act does not ask a self-invoice for is
 *      told so in the server's words (the screen decides nothing about the section).
 *
 * No scenario has a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";
import { ok, refuse } from "../stub.mjs";
import { billRow } from "../fixtures.mjs";

export const group = "bill-menu-panels";

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

const BILL = "b9";
const LANDED = new RegExp(`purchase-bills/${BILL}/landed-costs`);
const SELF_INVOICE_PREVIEW = /rcm-documents\/preview\/self-invoice/;

const LANDED_COSTS = {
  found: true, bill_no: "GS/114", bill_status: "draft",
  basis: "value", basis_label: "In proportion to taxable value", client_basis: null, bill_basis: null, basis_is_recorded: false,
  bases: [{ value: "value", label: "In proportion to taxable value" }, { value: "quantity", label: "In proportion to quantity" }],
  charges: [], lines: [], total_paise: 0, unapportioned_paise: 0, gaps: [], notes: [],
  weight_and_volume_refused: "Weight and volume are not offered: the bill does not record either.",
  freight_outward_is_not_cost: "Freight outward is a selling cost and is not recorded here.",
};

const NOT_DUE = {
  kind: "self_invoice", section: "CGST Act s.31(3)(f)", rule: "Rule 47", due: false,
  reasons: ["The supplier is registered, so the Act does not ask for a self-invoice on this bill."], gaps: [],
  vendor_registration: "registered", existing: null, particulars: null,
};

/** The Purchases screen's Bills tab with one draft bill, its row menu opened. */
async function atTheBillMenu(env) {
  const { page, stub } = env;
  stub.setTable("purchase_bills", [billRow("draft", BILL)]);
  stub.route({ method: "GET", re: LANDED, reply: () => ok(LANDED_COSTS) });
  stub.route({ method: "GET", re: SELF_INVOICE_PREVIEW, reply: () => ok(NOT_DUE) });
  await page.goto(env.at("/purchases/?tab=bills"), { waitUntil: "networkidle" });
  const opener = page.getByLabel(/Actions for bill/).first();
  await opener.waitFor();
  return opener;
}

export const scenarios = [
  {
    id: "landed-costs-is-a-named-side-sheet-that-keeps-the-keyboard-and-locks-the-page",
    title: "Purchases > a bill's menu > Landed costs: a named modal side sheet, the page locked, Tab and Shift+Tab kept inside, Escape closes it and gives the page its scroll back",
    async run(env) {
      const { page } = env;
      const opener = await atTheBillMenu(env);
      await opener.click();
      await page.getByRole("button", { name: "Landed costs", exact: true }).click();
      const sheet = page.getByRole("dialog", { name: "Landed costs", exact: true });
      await sheet.waitFor();
      assert.equal(await page.getByRole("dialog").count(), 1, "more than one dialog is open");
      assert.equal(await sheet.getAttribute("aria-modal"), "true", "Landed costs does not say it is modal");
      assert.equal(await pageLocked(page), "hidden", "the page behind Landed costs can still scroll");
      await sheet.getByText("Add a charge").waitFor();
      await tabStaysInside(page, sheet, 10, "Landed costs");
      await page.keyboard.press("Escape");
      await sheet.waitFor({ state: "detached" });
      assert.equal(await pageLocked(page), "", "the page is still locked after Landed costs closed");
    },
  },
  {
    id: "a-landed-cost-is-held-while-it-is-recorded-and-the-refusal-is-read-in-the-sheet",
    title: "Landed costs > Add: while the charge is out the sheet is held (the ×, Escape and a click beside it close nothing), the request goes once, and the server's refusal is shown inside the sheet",
    async run(env) {
      const { page, stub } = env;
      const opener = await atTheBillMenu(env);
      stub.route({ method: "POST", re: LANDED, delay: 2500, ...refuse("A stub refusal of the charge.", 422) });
      await opener.click();
      await page.getByRole("button", { name: "Landed costs", exact: true }).click();
      const sheet = page.getByRole("dialog", { name: "Landed costs", exact: true });
      await sheet.waitFor();
      await sheet.getByLabel("What it is").fill("Freight inward");
      await sheet.getByLabel("Amount (₹)").fill("1,250");
      stub.forgetWrites();
      await sheet.getByRole("button", { name: "Add", exact: true }).click();
      await until(async () => (await sheet.getByRole("button", { name: "Add", exact: true }).isDisabled()), "the Add button to be held while the charge is out");
      // The side sheet's × is named "Close" (the shared dialog's is "Close dialog"), and its footer has a Close button too: the × comes first.
      await sheet.getByRole("button", { name: "Close", exact: true }).first().click({ force: true, timeout: 1500 }).catch(() => {});
      await page.keyboard.press("Escape");
      await page.mouse.click(5, 5);
      assert.equal(await sheet.count(), 1, "the ×, Escape or a click beside it closed Landed costs while a charge was being recorded");
      await sheet.getByText("A stub refusal of the charge.").waitFor({ timeout: 8000 }).catch(() => { throw new Error("the server's refusal was not shown inside Landed costs"); });
      const sent = stub.writesTo(LANDED, "POST");
      assert.equal(sent.length, 1, "the charge was not sent exactly once");
      assert.equal(JSON.parse(sent[0].body).amount_paise, 125000, "the charge did not carry the typed amount (1,250) as paise");
      assert.equal(await sheet.getByRole("button", { name: "Add", exact: true }).isDisabled(), false, "Add stayed held after the answer");
    },
  },
  {
    id: "an-amount-with-a-comma-in-the-wrong-place-is-refused-in-a-sentence-that-names-the-amount",
    title: "Landed costs > Add: 1,2,5 sends nothing and the sentence says the AMOUNT is the problem and how an amount may look; a blank description is told to say what the charge is",
    async run(env) {
      const { page, stub } = env;
      const opener = await atTheBillMenu(env);
      await opener.click();
      await page.getByRole("button", { name: "Landed costs", exact: true }).click();
      const sheet = page.getByRole("dialog", { name: "Landed costs", exact: true });
      await sheet.waitFor();
      stub.forgetWrites();
      await sheet.getByLabel("What it is").fill("Freight inward");
      await sheet.getByLabel("Amount (₹)").fill("1,2,5");
      await sheet.getByRole("button", { name: "Add", exact: true }).click();
      await sheet.getByText(/The amount is not readable\./).waitFor({ timeout: 4000 });
      assert.match(await sheet.innerText(), /for example 1250, 1250\.50 or 1,25,000/, "the sentence does not say how an amount may look");
      assert.equal(stub.writesTo(LANDED, "POST").length, 0, "an unreadable amount was sent");
      await sheet.getByLabel("What it is").fill("");
      await sheet.getByLabel("Amount (₹)").fill("1,25,000");
      await sheet.getByRole("button", { name: "Add", exact: true }).click();
      await sheet.getByText(/Say what the charge is/).waitFor({ timeout: 4000 });
      assert.equal(stub.writesTo(LANDED, "POST").length, 0, "a charge with no description was sent");
    },
  },
  {
    id: "the-self-invoice-sheet-is-a-named-side-sheet-that-says-in-the-servers-words-why-none-is-due",
    title: "Purchases > a bill's menu > Self-invoice: a named modal side sheet that keeps Tab inside and closes on Escape, and a supplier who is registered is told so in the server's words",
    async run(env) {
      const { page } = env;
      const opener = await atTheBillMenu(env);
      await opener.click();
      await page.getByRole("button", { name: /^Self-invoice/ }).click();
      const sheet = page.getByRole("dialog", { name: "Self-invoice", exact: true });
      await sheet.waitFor();
      assert.equal(await sheet.getAttribute("aria-modal"), "true", "the Self-invoice sheet does not say it is modal");
      assert.equal(await pageLocked(page), "hidden", "the page behind the Self-invoice sheet can still scroll");
      await sheet.getByText("the Act does not ask for a self-invoice on this bill").waitFor({ timeout: 8000 })
        .catch(() => { throw new Error("the server's reason for no self-invoice was not shown"); });
      await tabStaysInside(page, sheet, 8, "the Self-invoice sheet");
      await page.keyboard.press("Escape");
      await sheet.waitFor({ state: "detached" });
      assert.equal(await pageLocked(page), "", "the page is still locked after the Self-invoice sheet closed");
    },
  },
];
