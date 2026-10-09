/**
 * Group G: an amount typed in rupees reaches the server as exact integer paise.
 *
 * "Every rupee calculation uses integer paise arithmetic, never floating point", and the browser is where a typed
 * amount first becomes paise. `lib/money/rupeeInput` concatenates the digits so it cannot go through a float; the
 * old `Math.round(parseFloat(x) * 100)` could, and `0.29 * 100` is 28.999999999999996 in binary floating point
 * (`Math.round` rescues that one; a truncation does not, and neither does a stray factor of ten).
 * The source guards forbid the multiplication; this types the amount into the two Record Payment modals and reads
 * the integer that arrives at the server, for two figures that are float traps and one that is not.
 *
 * NO SCENARIO HERE TYPES A GROUPED AMOUNT, and none can in these two modals. Both use `<input type="number">` for
 * the amount: Playwright's `fill` refuses text in it, and a comma keyed in is dropped by Chromium (measured on
 * Chromium 1194: keying `1,25,000` leaves the value 125000, the figure meant), so `paiseFromRupeeInput`'s refusal of
 * grouped text and its "without commas" error are not reachable from them. That refusal belongs to the amount
 * fields that take text and is `lib/money/rupeeInput.test.ts`'s to hold (it pins `1,000` as null); whether to accept
 * validly grouped Indian commas there is a product decision, and this drive does not take it.
 */
import assert from "node:assert/strict";
import { expectWrites } from "../kit.mjs";
import { openBillDrawer, openInvoiceDrawer } from "../flows.mjs";
import { ok } from "../stub.mjs";

export const group = "amounts";

/** Typed rupees and the integer paise they must become. 0.29 and 4999.99 are both float traps. */
const AMOUNTS = [["0.29", 29], ["4999.99", 499999], ["1180", 118000]];

async function typeAmountAndRecord(env, drawer) {
  await drawer.getByRole("button", { name: "Record Payment" }).first().click();
  const modal = env.page.getByRole("dialog").last();
  return modal;
}

export const scenarios = AMOUNTS.flatMap(([typed, paise]) => [
  {
    id: `invoice-payment-of-${typed.replace(".", "-")}`,
    title: `₹${typed} on an invoice: the receipt and its allocation carry ${paise} paise exactly`,
    async run(env) {
      const drawer = await openInvoiceDrawer(env, "issued");
      env.stub.route({ method: "POST", re: /receipts\/$/, reply: () => ok({ id: "r1" }) });
      const modal = await typeAmountAndRecord(env, drawer);
      await modal.locator('input[type="number"]').first().fill(typed);
      await modal.getByRole("button", { name: "Record Payment", exact: true }).click();
      await expectWrites(env.stub, /receipts\/$/, 1, `₹${typed} on an invoice`, "POST");
      const body = JSON.parse(env.stub.writesTo(/receipts\/$/)[0].body);
      assert.strictEqual(body.amount_paise, paise, `₹${typed} became ${body.amount_paise} paise, not ${paise}`);
      assert.strictEqual(body.allocations[0].allocated_paise, paise,
        `the allocation of ₹${typed} is ${body.allocations[0].allocated_paise} paise, not ${paise}`);
    },
  },
  {
    id: `bill-payment-of-${typed.replace(".", "-")}`,
    title: `₹${typed} on a bill: the vendor payment carries ${paise} paise exactly`,
    async run(env) {
      const drawer = await openBillDrawer(env, "received");
      env.stub.route({ method: "POST", re: /purchase-payments$/, reply: () => ok({ id: "pp1" }) });
      const modal = await typeAmountAndRecord(env, drawer);
      await modal.locator('input[type="number"]').first().fill(typed);
      await modal.getByRole("button", { name: "Record Payment", exact: true }).click();
      await expectWrites(env.stub, /purchase-payments$/, 1, `₹${typed} on a bill`, "POST");
      const body = JSON.parse(env.stub.writesTo(/purchase-payments$/)[0].body);
      assert.strictEqual(body.amount_paise, paise, `₹${typed} became ${body.amount_paise} paise, not ${paise}`);
    },
  },
]);
