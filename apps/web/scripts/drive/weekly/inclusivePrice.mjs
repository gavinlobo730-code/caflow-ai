/**
 * A PRICE INCLUDING GST IS WORKED BACK BY THE SERVER, AND THE LINE TAKES ITS RATE ONLY WHEN THE PERSON ACCEPTS (POST-A-490),
 * driven in a browser.
 *
 * Against a stubbed server, in Chromium, on a new sales invoice:
 *
 *   1. the calculator beside a line's rate opens the box; a price that is not a figure is refused in words and nothing is
 *      sent; a figure is sent with the line's own quantity and GST rate, in paise and basis points, and nothing worked out;
 *      the server's sentence and figures are shown; "Use … as the rate" writes the server's rate into the line's rate box
 *      and closes the box;
 *   2. an answer that is the nearest rate and not an exact one is shown as such, in the attention colour, with the server's
 *      sentence saying by how much; closing the box without accepting leaves the rate as it was;
 *   3. a refusal from the server (a line with compensation cess) is shown in the server's words and the rate is untouched.
 *
 * No scenario has a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";
import { ok, refuse } from "../stub.mjs";

export const group = "inclusive-price";

const RATE = /\/api\/sales-invoices\/inclusive-rate$/;
const dialog = (page) => page.getByRole("dialog");
const result = (page) => page.locator("[data-inclusive-answer]");
const rateBox = (page) => page.getByLabel("Line 1 rate", { exact: true });

const EXACT = {
  rate_paise: 1000000, typed_total_paise: 1180000, list_value_paise: 1000000, list_tax_paise: 180000, list_total_paise: 1180000,
  difference_paise: 0, exact: true, discount_paise: 0, taxable_paise: 1000000, tax_paise: 180000, total_paise: 1180000,
  sentence: "A price of ₹10,000.00 a unit before GST gives exactly the ₹11,800.00 you typed for the line: ₹10,000.00 and ₹1,800.00 of GST.",
};
const NEAREST = {
  rate_paise: 84661, typed_total_paise: 99900, list_value_paise: 84661, list_tax_paise: 15238, list_total_paise: 99899,
  difference_paise: -1, exact: false, discount_paise: 0, taxable_paise: 84661, tax_paise: 15238, total_paise: 99899,
  sentence: "The nearest price is ₹846.61 a unit before GST. The line then comes to ₹998.99 (₹846.61 and ₹152.38 of GST), which is ₹0.01 less than the ₹999.00 you typed.",
};

async function openEditor(env) {
  const { page } = env;
  env.stub.route({ method: "GET", re: /next-number/, reply: () => ok({ suggested_number: "INV-0001", series_head: "INV-" }) });
  await page.goto(env.at("/sales/invoices/new/edit/"), { waitUntil: "networkidle" });
  await rateBox(page).waitFor();
}

async function openBox(page) {
  await page.getByRole("button", { name: "Line 1: work out the rate from a price including GST" }).click();
  await dialog(page).waitFor();
}

export const scenarios = [
  {
    id: "an-inclusive-price-becomes-the-lines-rate-when-accepted",
    title: "a price that is not a figure is refused unsent; a figure is sent with the line's own facts; the server's answer is shown; accepting writes its rate",
    async run(env) {
      const { page } = env;
      const asked = [];
      env.stub.route({ method: "POST", re: RATE, reply: (_req, body) => { asked.push(JSON.parse(body)); return ok(EXACT); } });
      await openEditor(env);
      const gstPercent = Number(await page.getByLabel("Line 1 GST rate", { exact: true }).inputValue());
      await openBox(page);
      assert.match(await dialog(page).innerText(), /Line 1: price including GST/);

      const price = dialog(page).getByLabel("Price including GST (₹)");
      await price.fill("118,00");
      await dialog(page).getByRole("button", { name: "Work out the rate" }).click();
      await until(async () => (await result(page).getAttribute("data-inclusive-answer")) === "problem", "the refusal");
      assert.match(await result(page).innerText(), /price including GST as an amount in rupees/);
      assert.equal(asked.length, 0, "a price that is not a figure was sent to the server");

      // A price grouped the way amounts are written is read, and sent as the plain figure (POST-A-567).
      await price.fill("11,800");
      await price.press("Enter");
      await until(async () => (await result(page).getAttribute("data-inclusive-answer")) === "exact", "the answer");
      assert.equal(asked.length, 1);
      assert.deepEqual(asked[0], {
        client_id: env.clientId, inclusive_paise: 1180000, basis: "line", quantity: 1,
        gst_rate_bps: Math.round(gstPercent * 100), discount_percent_bps: null, has_cess: false,
      });
      const shown = await result(page).innerText();
      assert.ok(shown.includes(EXACT.sentence), "the server's sentence is not on the screen as sent");
      assert.match(shown, /Rate before GST, a unit\s+₹10,000\.00/);
      assert.match(shown, /Line total\s+₹11,800\.00/);
      assert.equal(await rateBox(page).inputValue(), "", "the rate changed before the person accepted");

      await dialog(page).getByRole("button", { name: /Use ₹10,000\.00 as the rate/ }).click();
      await until(async () => (await dialog(page).count()) === 0, "the box to close");
      assert.equal(await rateBox(page).inputValue(), "10000.00");
    },
  },
  {
    id: "a-nearest-rate-is-shown-as-not-exact-and-closing-changes-nothing",
    title: "a nearest rate is shown as not exact with the server's sentence; a price for one unit says so; closing without accepting leaves the rate",
    async run(env) {
      const { page } = env;
      const asked = [];
      env.stub.route({ method: "POST", re: RATE, reply: (_req, body) => { asked.push(JSON.parse(body)); return ok(NEAREST); } });
      await openEditor(env);
      await rateBox(page).fill("500");
      await openBox(page);
      await dialog(page).getByLabel("Price including GST (₹)").fill("999");
      await dialog(page).getByLabel("one unit").check();
      await dialog(page).getByRole("button", { name: "Work out the rate" }).click();
      await until(async () => (await result(page).getAttribute("data-inclusive-answer")) === "nearest", "the answer");
      assert.equal(asked[0].basis, "unit");
      assert.equal(asked[0].inclusive_paise, 99900);
      const shown = await result(page).innerText();
      assert.match(shown, /Nearest rate, not exact/);
      assert.ok(shown.includes("which is ₹0.01 less than the ₹999.00 you typed"), "the difference the server stated is not shown");
      await dialog(page).getByRole("button", { name: "Cancel", exact: true }).click();
      await until(async () => (await dialog(page).count()) === 0, "the box to close");
      assert.equal(await rateBox(page).inputValue(), "500", "closing the box without accepting changed the rate");
    },
  },
  {
    id: "a-refusal-is-shown-in-the-servers-words",
    title: "what the server cannot work back is shown in its own sentence and the rate is untouched",
    async run(env) {
      const { page } = env;
      const sentence = "This line carries compensation cess, and a price that includes both GST and cess cannot be worked back yet. Type the price before tax for this line.";
      env.stub.route({ method: "POST", re: RATE, ...refuse(sentence, 422) });
      await openEditor(env);
      await openBox(page);
      await dialog(page).getByLabel("Price including GST (₹)").fill("11800");
      await dialog(page).getByRole("button", { name: "Work out the rate" }).click();
      await until(async () => (await result(page).getAttribute("data-inclusive-answer")) === "problem", "the refusal");
      assert.ok((await result(page).innerText()).includes(sentence), "the server's refusal is not shown in its own words");
      assert.equal(await dialog(page).getByRole("button", { name: /as the rate/ }).count(), 0, "a refused question still offers a rate");
      await page.keyboard.press("Escape");
      await until(async () => (await dialog(page).count()) === 0, "the box to close");
      assert.equal(await rateBox(page).inputValue(), "");
    },
  },
];
