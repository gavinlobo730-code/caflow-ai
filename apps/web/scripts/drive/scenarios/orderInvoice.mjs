/**
 * AN INVOICE IS RAISED FROM AN ORDER FOR WHAT IS UNBILLED, AND ITS LINES NAME THE ORDER LINES THEY BILL (POST-A-104), driven in a browser.
 *
 * The order panel on the sales cycle tab showed INVOICED as zero on every line and nothing raised an invoice from an order. It now offers
 * "Raise an invoice for what is unbilled" while a line has something left; the server answers the lines (each naming its order line)
 * and the sentences to read first; the ordinary invoice editor opens prefilled, and a save sends each line with the order line it bills.
 * Against a stubbed server, in Chromium:
 *
 *   1. an order with something unbilled offers the button; pressing it sends ONE request, the server's sentences are shown before the
 *      editor opens, and "Open the invoice" lands on the new-invoice editor with the order's line in it (description and quantity);
 *   2. saving that invoice sends the line WITH the order line it bills;
 *   3. an order whose every line is billed offers no button;
 *   4. the server's refusal is shown beside the button in its own words, and nothing is opened;
 *   5. an answer that arrives after the order was closed opens nothing and says nothing (the independent read's F6);
 *   6. the editor says on the line that it bills an order, and "stop billing the order" sends the line without the link;
 *   7. an order line picked from the catalogue on the order form sends the item it was picked from, so an invoice raised from the
 *      order has the item every invoice line needs (the independent read's F4).
 *
 * No scenario has a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { pick, until } from "../kit.mjs";
import { ITEM } from "../fixtures.mjs";
import { ok, refuse } from "../stub.mjs";

export const group = "order-invoice";

const ORDER = {
  id: "so-1", document_no: "SO/26-27/0001", document_date: "2026-07-01", customer_po_no: null, expected_delivery_date: null,
  status: "confirmed", total_paise: 7_080_000, customer_id: "cu1",
};
const LINE = (unbilled) => ({
  order_line_id: "ol-1", description: "Consulting", ordered_qty: "10.000", delivered_qty: "4.000",
  invoiced_qty: unbilled === "0.000" ? "10.000" : "4.000", undelivered_qty: "6.000", unbilled_qty: unbilled,
});
const SEED = {
  order: { id: "so-1", document_no: ORDER.document_no },
  seed: {
    customer_id: "cu1", supply_state_code: "27", is_interstate: false,
    lines: [{
      description: "Consulting", hsn_sac: "998313", quantity: "6", unit: "HRS", rate_paise: 500_000, gst_rate_bps: 1800,
      is_service: true, service_catalogue_id: "sc1", discount_percent_bps: null, cess_rate_bps: null, cess_specific_paise_per_unit: null,
      sales_order_line_id: "ol-1",
    }],
  },
  notes: ["The order's discount on the whole document is not carried: enter it on the invoice if it applies to what is billed."],
};

/** The tab on its Sales Orders with the order's position open. */
async function atTheOrder(env, unbilled = "6.000") {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /sales-cycle\/vocabulary/, reply: () => ok({ challan_reasons: [], goods_kinds: [], quote_kinds: [] }) });
  stub.route({ method: "GET", re: /sales-cycle\/quotations\?/, reply: () => ok([]) });
  stub.route({ method: "GET", re: /sales-cycle\/orders\?/, reply: () => ok([ORDER]) });
  stub.route({ method: "GET", re: /sales-cycle\/challans\?/, reply: () => ok([]) });
  stub.route({ method: "GET", re: /sales-cycle\/orders\/so-1\/position\?/, reply: () => ok({
    order: ORDER, lines: [LINE(unbilled)], status_would_be: "partially_delivered",
    gaps: ["Invoiced counts the issued invoices raised from this order."],
  }) });
  await page.goto(env.at("/sales/?tab=sales-cycle"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Sales Orders" }).click();
  await page.getByText(ORDER.document_no).first().click();
  await page.getByText("What is still open").waitFor();
}

const SEED_ROUTE = /sales-cycle\/orders\/so-1\/invoice-seed\?/;

export const scenarios = [
  {
    id: "an-order-with-something-unbilled-opens-a-prefilled-invoice-after-its-sentences",
    title: "one press, the server's sentences first, then the new-invoice editor with the order's line in it",
    async run(env) {
      const { page, stub } = env;
      const asked = [];
      stub.route({ method: "GET", re: SEED_ROUTE, reply: (req, body, url) => { asked.push(url.pathname); return ok(SEED); } });
      stub.route({ method: "GET", re: /next-number/, reply: () => ok({ suggested_number: "INV-0007", series_head: "INV-" }) });
      await atTheOrder(env);
      const button = page.getByTestId("raise-invoice-from-order");
      await button.dblclick();
      await page.getByTestId("order-invoice-notes").waitFor();
      assert.equal(asked.length, 1, `the seed was asked ${asked.length} times`);
      assert.match(await page.getByTestId("order-invoice-notes").innerText(), /discount on the whole document is not carried/);
      await page.getByRole("button", { name: "Open the invoice" }).click();
      await page.waitForURL(/\/sales\/invoices\/new\/edit/);
      await until(async () => (await page.locator('input[aria-label="Line 1 quantity"]').inputValue().catch(() => "")) === "6",
        "the order's unbilled quantity in the first line");
    },
  },
  {
    id: "the-saved-invoice-sends-each-line-with-the-order-line-it-bills",
    title: "saving the prefilled invoice sends the line with sales_order_line_id",
    async run(env) {
      const { page, stub } = env;
      const sent = [];
      stub.route({ method: "GET", re: SEED_ROUTE, reply: () => ok({ ...SEED, notes: [] }) });
      stub.route({ method: "GET", re: /next-number/, reply: () => ok({ suggested_number: "INV-0007", series_head: "INV-" }) });
      stub.route({ method: "POST", re: /sales-invoices\/$/, reply: (req, body) => { sent.push(JSON.parse(body)); return ok({ id: "inv-7", invoice_no: "INV-0007" }); } });
      await atTheOrder(env);
      await page.getByTestId("raise-invoice-from-order").click();
      await page.waitForURL(/\/sales\/invoices\/new\/edit/);
      await until(async () => (await page.locator('input[aria-label="Line 1 quantity"]').inputValue().catch(() => "")) === "6", "the prefilled line");
      await page.getByRole("button", { name: "Save Draft" }).first().click();
      await until(async () => sent.length > 0, "the invoice was saved");
      const line = (sent[0].lines ?? [])[0] ?? {};
      assert.equal(line.sales_order_line_id, "ol-1", `the saved line does not name its order line: ${JSON.stringify(line)}`);
    },
  },
  {
    id: "an-order-with-nothing-unbilled-offers-no-button",
    title: "every line billed: no button",
    async run(env) {
      const { page } = env;
      await atTheOrder(env, "0.000");
      assert.equal(await page.getByTestId("raise-invoice-from-order").count(), 0);
    },
  },
  {
    id: "a-refusal-is-said-beside-the-button-and-nothing-opens",
    title: "the server's refusal in its own words, and no editor",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "GET", re: SEED_ROUTE, ...refuse("Every line of this order has been invoiced or is on a draft invoice, so there is nothing left to bill.", 409) });
      await atTheOrder(env);
      await page.getByTestId("raise-invoice-from-order").click();
      await page.getByRole("alert").filter({ hasText: "nothing left to bill" }).waitFor();
      assert.ok(!/\/sales\/invoices\/new\/edit/.test(page.url()), "the editor was opened after a refusal");
    },
  },
  {
    id: "an-answer-that-arrives-after-the-order-was-closed-opens-nothing",
    title: "the seed answers late, after Close: no notes, no editor, and the button is not left on Preparing",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "GET", re: SEED_ROUTE, delay: 1500, reply: () => ok(SEED) });
      await atTheOrder(env);
      await page.getByTestId("raise-invoice-from-order").click();
      await page.getByRole("button", { name: "Close" }).click();
      await page.waitForTimeout(2500);
      assert.ok(!/\/sales\/invoices\/new\/edit/.test(page.url()), "the editor was opened for an order that was closed");
      assert.equal(await page.getByTestId("order-invoice-notes").count(), 0, "the closed order's sentences were shown");
      await page.getByText(ORDER.document_no).first().click();
      await page.getByText("What is still open").waitFor();
      assert.equal(await page.getByTestId("raise-invoice-from-order").innerText(), "Raise an invoice for what is unbilled");
    },
  },
  {
    id: "the-editor-says-a-line-bills-an-order-and-can-stop",
    title: "the prefilled line says it bills a sales order; stop billing the order sends the line without the link",
    async run(env) {
      const { page, stub } = env;
      const sent = [];
      stub.route({ method: "GET", re: SEED_ROUTE, reply: () => ok({ ...SEED, notes: [] }) });
      stub.route({ method: "GET", re: /next-number/, reply: () => ok({ suggested_number: "INV-0007", series_head: "INV-" }) });
      stub.route({ method: "POST", re: /sales-invoices\/$/, reply: (req, body) => { sent.push(JSON.parse(body)); return ok({ id: "inv-7", invoice_no: "INV-0007" }); } });
      await atTheOrder(env);
      await page.getByTestId("raise-invoice-from-order").click();
      await page.waitForURL(/\/sales\/invoices\/new\/edit/);
      await page.getByTestId("line-1-bills-an-order").waitFor();
      await page.getByRole("button", { name: "stop billing the order" }).click();
      assert.equal(await page.getByTestId("line-1-bills-an-order").count(), 0);
      await page.getByRole("button", { name: "Save Draft" }).first().click();
      await until(async () => sent.length > 0, "the invoice was saved");
      const line = (sent[0].lines ?? [])[0] ?? {};
      assert.ok(!("sales_order_line_id" in line), `the line still names the order line: ${JSON.stringify(line)}`);
    },
  },
  {
    id: "an-order-line-picked-from-the-catalogue-sends-its-item",
    title: "New sales order: Line 1 picked from the catalogue saves with service_catalogue_id and is_service",
    async run(env) {
      const { page, stub } = env;
      const sent = [];
      stub.route({ method: "GET", re: /sales-cycle\/vocabulary/, reply: () => ok({ challan_reasons: [], goods_kinds: [], quote_kinds: [] }) });
      stub.route({ method: "GET", re: /sales-cycle\/quotations\?/, reply: () => ok([]) });
      stub.route({ method: "GET", re: /sales-cycle\/orders\?/, reply: () => ok([]) });
      stub.route({ method: "GET", re: /sales-cycle\/challans\?/, reply: () => ok([]) });
      stub.route({ method: "GET", re: /\/customers/, reply: () => ok([{ id: "cu1", name: "Beta Stores" }]) });
      stub.route({ method: "GET", re: /api\/service-catalogue\/?\?/, reply: () => ok([{ ...ITEM, kind: "service" }]) });
      stub.route({ method: "POST", re: /api\/sales-cycle\/orders$/, reply: (req, body) => { sent.push(JSON.parse(body)); return ok({ id: "so-9" }); } });
      await page.goto(env.at("/sales/?tab=sales-cycle"), { waitUntil: "networkidle" });
      await page.getByRole("button", { name: "Sales Orders" }).click();
      await page.getByRole("button", { name: "New", exact: true }).click();
      await page.getByText("Number", { exact: true }).waitFor();
      await page.locator("select:has(option[value='cu1'])").first().selectOption("cu1");
      await page.locator("label:has-text('Number') input").first().fill("SO/26-27/0009");
      await pick(page, page.locator('button[aria-label="Line 1 product or service"]'), "Consulting");
      assert.equal(await page.getByLabel("Line 1 description").inputValue(), "Consulting hours");
      await page.getByRole("button", { name: "Save", exact: true }).click();
      await until(async () => sent.length > 0, "the order was saved");
      const [line] = sent[0].lines ?? [];
      assert.equal(line?.service_catalogue_id, "sc1", `the order line does not name its item: ${JSON.stringify(line)}`);
      assert.equal(line?.is_service, true);
      assert.equal(line?.rate_paise, 500000);
    },
  },
];
