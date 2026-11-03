/**
 * Group P: the Add Asset drawer, driven in a browser (POST-A-123, the add-asset row of what was still missing).
 *
 * An asset's cost is the base of every depreciation charge that follows it ("read it wrong once and every Schedule II charge after
 * it is wrong too", says the drawer's own code), and creating one posts an acquisition journal. The source guards hold that the
 * amount goes through the one rupee parser and that the save is guarded by a ref; this proves it in Chromium:
 *
 *   1. a cost typed in rupees reaches the server as exact integer paise (two float traps), with the tax heads and the salvage value
 *      alongside, and the drawer closes and the register is read again;
 *   2. two clicks on Add Asset in the same tick send ONE create (the drawer's own comment records that one click once produced two
 *      identical assets with the full cost each);
 *   3. a cost the parser refuses (`1e3`, which a number box lets through) sends nothing and says why in the drawer;
 *   4. a refusal from the server is shown as the server wrote it, the drawer stays open with what was typed, and Add Asset can be
 *      pressed again and then succeeds with ONE more create.
 *
 * Not here, and why: a grouped amount (`1,25,000`) cannot be typed into these boxes at all. They are `<input type="number">`:
 * Playwright refuses text in one and Chromium drops a comma keyed into it, so `paiseFromRupeeInput`'s refusal of grouped text is
 * `lib/money/rupeeInput.test.ts`'s to hold, as `amounts.mjs` already says of the Record Payment modals.
 */
import assert from "node:assert/strict";
import { sameTickDouble, expectWrites, until } from "../kit.mjs";
import { ok, refuse } from "../stub.mjs";

export const group = "add-asset";

const CATEGORIES = [{
  category: "Computers and data processing", depreciable: true, residual_value_cap_percent: 5,
  classes: [
    { label: "Laptops and desktops", useful_life_years: 3, wdv_rate_percent: 63.16 },
    { label: "Servers and networks", useful_life_years: 6, wdv_rate_percent: 39.3 },
  ],
}];

const CREATE = /api\/fixed-assets$/;
const NAME = "e.g. Dell Laptop SN12345";

/** The register page with the drawer open and its categories loaded. */
async function atTheDrawer(env, create) {
  const { page, stub } = env;
  stub.setTable("fixed_assets", []);
  stub.route({ method: "GET", re: /fixed-assets\/categories/, reply: () => ok(CATEGORIES) });
  if (create) stub.route({ method: "POST", re: CREATE, ...create });
  await page.goto(env.at("/fixed-assets/"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Add Asset" }).first().click();
  await page.getByPlaceholder(NAME).waitFor();
  // The category list lands after the drawer opens; the form is not ready until it has chosen the first one.
  await until(async () => (await categorySelect(page).inputValue()) === "Computers and data processing", "the first category to be chosen");
}

/** The drawer's labels are not tied to their boxes (the form-control name ratchet still lists this page), so a box is found by what it is. */
const categorySelect = (page) => page.locator("select", { has: page.locator("option", { hasText: "Computers and data processing" }) });
const numberBoxes = (page) => page.locator('input[type="number"]');

async function fillTheForm(page, cost, { salvage } = {}) {
  await page.getByPlaceholder(NAME).fill("Dell Laptop");
  await page.getByPlaceholder("100000").fill(cost);
  // Cost, then salvage value, then the WDV rate, in the drawer's order.
  if (salvage !== undefined) await numberBoxes(page).nth(1).fill(salvage);
}

const addButton = (page) => page.getByRole("button", { name: "Add Asset", exact: true }).last();
const created = (stub) => stub.writesTo(CREATE, "POST").map((w) => JSON.parse(w.body));

/** Typed rupees and the integer paise they must become. 4999.99 and 0.29 are the float traps; 125000.50 is the ordinary case. */
const COSTS = [["125000.50", 12500050], ["4999.99", 499999], ["0.29", 29]];

export const scenarios = [
  ...COSTS.map(([typed, paise]) => ({
    id: `an-asset-costing-${typed.replace(".", "-")}-is-created-with-${paise}-paise`,
    title: `a cost of ₹${typed} reaches the server as ${paise} paise, with the salvage value and the category it was given`,
    async run(env) {
      const { page, stub } = env;
      await atTheDrawer(env, { reply: () => ok({ id: "fa-1" }) });
      await fillTheForm(page, typed, { salvage: "100.25" });
      await addButton(page).click();
      await expectWrites(stub, CREATE, 1, `an asset costing ₹${typed}`, "POST");
      const [body] = created(stub);
      assert.strictEqual(body.purchase_cost_paise, paise, `₹${typed} became ${body.purchase_cost_paise} paise, not ${paise}`);
      assert.strictEqual(body.salvage_value_paise, 10025, `a salvage value of ₹100.25 became ${body.salvage_value_paise} paise`);
      assert.strictEqual(body.asset_category, "Computers and data processing");
      assert.strictEqual(body.asset_name, "Dell Laptop");
      await page.getByPlaceholder(NAME).waitFor({ state: "detached" });
    },
  })),
  {
    id: "two-clicks-on-add-asset-in-one-tick-create-one-asset",
    title: "Add Asset pressed twice in the same tick sends ONE create",
    async run(env) {
      const { page, stub } = env;
      await atTheDrawer(env, { reply: () => ok({ id: "fa-1" }) });
      await fillTheForm(page, "125000");
      await sameTickDouble(addButton(page));
      await expectWrites(stub, CREATE, 1, "two same-tick clicks on Add Asset", "POST");
      assert.strictEqual(created(stub)[0].purchase_cost_paise, 12500000);
    },
  },
  {
    id: "a-cost-the-parser-refuses-sends-nothing-and-says-why",
    title: "a cost of 1e3 (a number box lets it through) is refused in words and nothing is created",
    async run(env) {
      const { page, stub } = env;
      await atTheDrawer(env, { reply: () => ok({ id: "fa-1" }) });
      await fillTheForm(page, "1e3");
      await addButton(page).click();
      await page.getByText(/must be amounts in rupees/).waitFor();
      await expectWrites(stub, CREATE, 0, "a cost of 1e3", "POST");
      assert.ok(await page.getByPlaceholder(NAME).isVisible(), "the drawer closed over a refused cost");
      assert.strictEqual(await addButton(page).isDisabled(), false, "the button stayed held after a refusal made in the browser");
    },
  },
  {
    id: "a-server-refusal-is-shown-and-the-next-press-creates-one-asset",
    title: "a refusal is shown as the server wrote it, the drawer keeps what was typed, and the next press sends one more create",
    async run(env) {
      const { page, stub } = env;
      const REFUSED = "The financial year 2025-26 is locked for posting.";
      await atTheDrawer(env);
      stub.route({ method: "POST", re: CREATE, ...refuse(REFUSED, 422) });
      await fillTheForm(page, "125000");
      await addButton(page).click();
      await page.getByText(REFUSED).waitFor();
      assert.strictEqual(await page.getByPlaceholder("100000").inputValue(), "125000", "the typed cost was lost on a refusal");
      assert.strictEqual(await addButton(page).isDisabled(), false, "the button stayed held after a server refusal");
      await expectWrites(stub, CREATE, 1, "the refused press", "POST");

      // The newest route wins, so this replaces the refusal for the next press.
      stub.route({ method: "POST", re: CREATE, reply: () => ok({ id: "fa-1" }) });
      await addButton(page).click();
      await until(() => created(stub).length === 2, "the second create to arrive");
      await page.getByPlaceholder(NAME).waitFor({ state: "detached" });
    },
  },
  {
    id: "escape-with-the-cursor-in-the-purchase-date-asks-before-it-closes-and-keeps-the-date",
    title: "Escape pressed while the purchase date is still being typed asks about unsaved changes first; the drawer stays open and the date is kept (POST-A-126, POST-A-130)",
    async run(env) {
      const { page, stub } = env;
      await atTheDrawer(env, { reply: () => ok({ id: "fa-1" }) });
      // The date is the ONLY unsaved typing, and a date commits on blur: before the shared Drawer left the box first, the question was
      // never asked and the drawer simply closed with the date in it.
      const box = page.getByLabel("Purchase date");
      await box.click();
      await box.fill("");
      await box.pressSequentially("15/6");
      assert.strictEqual(await box.evaluate((el) => document.activeElement === el), true, "the cursor must still be in the date box");
      await page.keyboard.press("Escape");
      const question = page.getByRole("alertdialog");
      await question.waitFor();
      assert.match(await question.innerText(), /unsaved changes/i, "the question that appeared is not the unsaved-changes one");
      assert.ok(await page.getByPlaceholder(NAME).isVisible(), "the drawer closed over a date nobody had saved");
      // One Escape answers the QUESTION (the top dialog) and the drawer beneath it stays: the stack, driven.
      await page.keyboard.press("Escape");
      await question.waitFor({ state: "detached" });
      assert.ok(await page.getByPlaceholder(NAME).isVisible(), "the Escape that answered the question also closed the drawer");
      assert.match(await box.inputValue(), /^15\/06\/20\d\d$/, "the typed date was lost or left unread");
      await expectWrites(stub, CREATE, 0, "an Escape that was answered Cancel", "POST");
      // With nothing unsaved the same Escape just closes: clear the box's date and the form is as it was opened.
    },
  },
  {
    id: "escape-while-a-save-is-in-flight-keeps-the-drawer-open",
    title: "Escape pressed while Add Asset is saving is ignored: the drawer stays until the server answers, then closes with the asset created once",
    async run(env) {
      const { page, stub } = env;
      await atTheDrawer(env, { reply: () => ok({ id: "fa-1" }) });
      await fillTheForm(page, "125000");
      await addButton(page).click();
      // The stub holds a write for a moment, so the request is in flight here. The leave question reads `dirty && !saving` and so says "leave"
      // without asking the moment a save starts: the drawer closed mid-request, lost a refusal, and on success the late close shut whichever
      // drawer was open by then (found by an independent review).
      await page.keyboard.press("Escape");
      await page.waitForTimeout(250);
      assert.ok(await page.getByPlaceholder(NAME).isVisible(), "Escape closed the drawer while its save was in flight");
      await expectWrites(stub, CREATE, 1, "an Escape pressed while the save was in flight", "POST");
      await page.getByPlaceholder(NAME).waitFor({ state: "detached" });
    },
  },
];
