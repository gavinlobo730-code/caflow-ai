/**
 * Group Q: applying a receipt to invoices, driven in a browser (POST-A-123, the receipt-allocation row of what was still missing).
 *
 * This modal REPLACES THE WHOLE SET of a receipt's allocations ("the endpoint reverses everything first and re-applies what it is
 * sent"), so what it submits is the money: a line left out un-applies an invoice, and a figure out by a paisa leaves an invoice
 * part-paid for good. The source guards hold that the amounts go through the one parser and that the button is the shared one;
 * this proves it in Chromium, against a stubbed server:
 *
 *   1. what is typed reaches the server as exact paise, and the lines the receipt ALREADY had on other invoices are sent again with
 *      it (a set, not one line), in the invoices' own order;
 *   2. two clicks on Apply in the same tick send ONE request;
 *   3. a figure that is not an amount ("1,500") holds Apply, says so on the line, and sends nothing; so does a figure over what the
 *      invoice still owes, and so does a total over what the receipt settles (cash plus the tax the customer deducted);
 *   4. "All" fills an invoice's own ceiling, which is what it still owes PLUS what this receipt already has on it;
 *   5. a refusal is shown as the server wrote it, the modal stays open with the figures typed, and Apply can be pressed again.
 */
import assert from "node:assert/strict";
import { sameTickDouble, expectWrites, until } from "../kit.mjs";
import { ok, refuse } from "../stub.mjs";
import { CUSTOMER } from "../fixtures.mjs";

export const group = "receipt-allocation";

const ALLOCATE = /api\/receipts\/r1\/allocate$/;

/** A receipt of ₹50,000 cash with ₹2,000 of TDS the customer deducted: it settles ₹52,000. */
const RECEIPT = {
  id: "r1", receipt_no: "RCT-0001", receipt_date: "2026-10-02", customer_id: CUSTOMER.id, amount_paise: 5_000_000, tds_paise: 200_000,
  payment_mode: "bank", bank_account_id: null, reference_no: null, allocated_paise: 100_000, unallocated_paise: 5_100_000, is_reversed: false,
  customers: { name: CUSTOMER.name },
};

/** Three open invoices. The third already has ₹1,000.00 of THIS receipt on it, so its ceiling is ₹19,000.00 + ₹1,000.00. */
const INVOICES = [
  { id: "i1", invoice_no: "INV/26-27/0001", invoice_date: "2026-08-01", total_paise: 3_540_000, outstanding_paise: 3_000_000, status: "issued" },
  { id: "i2", invoice_no: "INV/26-27/0002", invoice_date: "2026-08-15", total_paise: 1_770_000, outstanding_paise: 1_500_000, status: "issued" },
  { id: "i3", invoice_no: "INV/26-27/0003", invoice_date: "2026-09-01", total_paise: 2_360_000, outstanding_paise: 1_900_000, status: "issued" },
];

async function atTheModal(env) {
  const { page, stub } = env;
  stub.setTable("receipts", [RECEIPT]);
  stub.setTable("customers", [CUSTOMER]);
  stub.setTable("client_sales_invoices", INVOICES);
  stub.setTable("receipt_allocations", [{ receipt_id: "r1", sales_invoice_id: "i3", allocated_paise: 100_000 }]);
  await page.goto(env.at("/sales/?tab=receipts"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Apply", exact: true }).first().click();
  await page.getByLabel("Amount to apply to INV/26-27/0001").waitFor();
}

const box = (page, n) => page.getByLabel(`Amount to apply to INV/26-27/000${n}`);
const applyButton = (page) => page.getByRole("button", { name: "Apply", exact: true }).last();
const sent = (stub) => stub.writesTo(ALLOCATE, "PATCH").map((w) => JSON.parse(w.body));

export const scenarios = [
  {
    id: "what-is-typed-reaches-the-server-in-exact-paise-with-the-lines-the-receipt-already-had",
    title: "₹12,345.67 and ₹0.29 reach the server as 1234567 and 29 paise, together with the receipt's existing ₹1,000.00 on the third invoice",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "PATCH", re: ALLOCATE, reply: () => ok({ receipt_id: "r1", unallocated_paise: 3_765_404 }) });
      await atTheModal(env);
      assert.strictEqual(await box(page, 3).inputValue(), "1000", "the receipt's existing allocation was not loaded into its invoice");
      await box(page, 1).fill("12345.67");
      await box(page, 2).fill("0.29");
      await applyButton(page).click();
      await expectWrites(stub, ALLOCATE, 1, "applying a receipt", "PATCH");
      const [body] = sent(stub);
      assert.deepStrictEqual(body.allocations, [
        { sales_invoice_id: "i1", allocated_paise: 1234567 },
        { sales_invoice_id: "i2", allocated_paise: 29 },
        { sales_invoice_id: "i3", allocated_paise: 100000 },
      ], `the set sent was ${JSON.stringify(body.allocations)}`);
      await page.getByLabel("Amount to apply to INV/26-27/0001").waitFor({ state: "detached" });
    },
  },
  {
    id: "two-clicks-on-apply-in-one-tick-send-one-request",
    title: "Apply pressed twice in the same tick sends ONE allocation request",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "PATCH", re: ALLOCATE, reply: () => ok({ receipt_id: "r1", unallocated_paise: 0 }) });
      await atTheModal(env);
      await box(page, 1).fill("1000");
      await sameTickDouble(applyButton(page));
      await expectWrites(stub, ALLOCATE, 1, "two same-tick clicks on Apply", "PATCH");
    },
  },
  {
    id: "a-grouped-figure-or-an-overrun-holds-apply-and-sends-nothing",
    title: "1,500 (not an amount), more than an invoice owes, and more than the receipt settles each hold Apply and say why",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "PATCH", re: ALLOCATE, reply: () => ok({ receipt_id: "r1" }) });
      await atTheModal(env);

      await box(page, 1).fill("1,500");
      await page.getByText("Not an amount.").waitFor();
      assert.ok(await applyButton(page).isDisabled(), "Apply stayed live over a figure that is not an amount");

      await box(page, 1).fill("30000.01");
      await page.getByText("More than this document still owes.").waitFor();
      assert.ok(await applyButton(page).isDisabled(), "Apply stayed live over more than the invoice owes");

      // Each invoice within its own ceiling, the total past the ₹52,000.00 the receipt settles: 30,000 + 15,000 + 20,000 = 65,000.
      await box(page, 1).fill("30000");
      await box(page, 2).fill("15000");
      await box(page, 3).fill("20000");
      await page.getByText(/more than the receipt settles/).waitFor();
      assert.ok(await applyButton(page).isDisabled(), "Apply stayed live over more than the receipt settles");

      await expectWrites(stub, ALLOCATE, 0, "figures Apply was held over", "PATCH");
    },
  },
  {
    id: "all-fills-an-invoices-own-ceiling-including-what-this-receipt-already-has",
    title: "All puts what the invoice still owes, plus what this receipt already has on it, into the box",
    async run(env) {
      const { page } = env;
      await atTheModal(env);
      const rows = page.locator("tr", { hasText: "INV/26-27/0003" });
      await rows.getByRole("button", { name: "All", exact: true }).click();
      assert.strictEqual(await box(page, 3).inputValue(), "20000", "All did not fill 19,000.00 owed + 1,000.00 already applied");
      await page.locator("tr", { hasText: "INV/26-27/0001" }).getByRole("button", { name: "All", exact: true }).click();
      assert.strictEqual(await box(page, 1).inputValue(), "30000");
    },
  },
  {
    id: "a-refusal-is-shown-and-the-modal-keeps-the-figures-and-can-be-pressed-again",
    title: "a refusal is shown as the server wrote it, the modal keeps what was typed, and the next press sends a second request",
    async run(env) {
      const { page, stub } = env;
      const REFUSED = "Invoice INV/26-27/0001 has only ₹29,000.00 outstanding.";
      stub.route({ method: "PATCH", re: ALLOCATE, ...refuse(REFUSED, 422) });
      await atTheModal(env);
      await box(page, 1).fill("1000");
      await applyButton(page).click();
      await page.getByText(REFUSED).waitFor();
      assert.strictEqual(await box(page, 1).inputValue(), "1000", "the typed figure was lost on a refusal");
      assert.strictEqual(await applyButton(page).isDisabled(), false, "Apply stayed held after a refusal");
      await expectWrites(stub, ALLOCATE, 1, "the refused press", "PATCH");

      stub.route({ method: "PATCH", re: ALLOCATE, reply: () => ok({ receipt_id: "r1", unallocated_paise: 0 }) });
      await applyButton(page).click();
      await until(() => sent(stub).length === 2, "the second request to arrive");
    },
  },
];
