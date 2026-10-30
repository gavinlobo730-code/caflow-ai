/**
 * Group H: the firm-level e-invoice screen shows records and writes none (POST-A-065).
 *
 * It used to take a client id pasted into a box and an invoice number typed into a form, and store a record that
 * named no invoice. It now picks the client by name, lists that client's records and says, for each, where the
 * next step happens: on the invoice. This drives what a source guard cannot: that picking a client really asks
 * for THAT client's records, that a record naming no invoice says so and offers nothing to open, that a failed
 * read is said in words and Retry asks again, and that nothing on the screen writes.
 */
import assert from "node:assert/strict";
import { pick, until } from "../kit.mjs";
import { ok } from "../stub.mjs";
import { CLIENT_ID } from "../fixtures.mjs";

export const group = "einvoice";

const IRN = "a".repeat(64);
const RECORDS = [
  { id: "r1", client_id: CLIENT_ID, invoice_number: "INV-0001", invoice_date: "2026-09-12", sales_invoice_id: "inv-1",
    irn: null, ack_number: null, status: "draft", gst_treatment: "export_without_payment", created_at: "2026-09-12T05:00:00Z" },
  { id: "r2", client_id: CLIENT_ID, invoice_number: "INV-0002", invoice_date: "2026-09-14", sales_invoice_id: "inv-2",
    irn: IRN, ack_number: "112600000001", status: "generated", gst_treatment: null, created_at: "2026-09-14T05:00:00Z" },
  { id: "r3", client_id: CLIENT_ID, invoice_number: "OLD-77", invoice_date: "2026-04-02", sales_invoice_id: null,
    irn: IRN, ack_number: "112600000002", status: "generated", gst_treatment: null, created_at: "2026-04-02T05:00:00Z" },
];

/** The server's window over a client's records (apps/api/core/list_window.py). */
const windowOf = (rows, { hasMore = false, limit = 100 } = {}) =>
  ok({ records: rows, returned: rows.length, has_more: hasMore, limit, max_limit: 500 });

const WORKLIST = { scope: "firm", invoices: [], counts: {}, caveats: [], clients_not_assessed: [] };

function stubScreen(env, recordsReply) {
  const asked = [];
  env.stub.route({ method: "GET", re: /einvoice\/missing-irn/, reply: () => ok(WORKLIST) });
  env.stub.route({
    method: "GET", re: /einvoice\/records/,
    reply: (req) => { asked.push(req.url ?? ""); return recordsReply(asked.length); },
  });
  return asked;
}

async function openAndPick(env) {
  const { page } = env;
  await page.goto(`${env.base}/einvoice/`, { waitUntil: "networkidle" });
  await page.getByText("Select a client to see its e-invoice records.").waitFor();
  await pick(page, page.locator('button[aria-label="Client"]'), "Acme Traders");
}

export const scenarios = [
  {
    id: "records-are-listed-for-the-picked-client-and-nothing-is-written",
    title: "picking a client lists its records, each says where its next step is, a record with no invoice says so, and nothing is written",
    async run(env) {
      const { page, stub } = env;
      const asked = stubScreen(env, () => windowOf(RECORDS));
      await page.goto(`${env.base}/einvoice/`, { waitUntil: "networkidle" });
      await page.getByText("Select a client to see its e-invoice records.").waitFor();
      assert.equal(asked.length, 0, "records were requested before any client was picked");
      assert.equal(await page.locator('input[type="date"]').count(), 0, "a native date box is on the screen");
      assert.equal(await page.getByRole("button", { name: /New E-Invoice|Create/ }).count(), 0, "a create control is on the screen");

      await pick(page, page.locator('button[aria-label="Client"]'), "Acme Traders");
      await page.getByText("INV-0001").waitFor();
      assert.equal(asked.length, 1, `expected one read of the records, saw ${asked.length}`);
      assert.match(asked[0], new RegExp(`client_id=${CLIENT_ID}`), "the read was not for the picked client");
      assert.match(asked[0], /limit=100/, "the read did not ask for a window");
      assert.doesNotMatch(asked[0], /sales_invoice_id/, "the screen lists the client's records, not one invoice's");
      assert.equal(await page.getByText("More exist that are not shown here").count(), 0,
        "a whole list was reported as cut short");

      const rows = page.locator("ul > li");
      assert.equal(await rows.count(), 3);

      const first = rows.nth(0);
      const firstText = await first.innerText();
      assert.match(firstText, /INV-0001 — 12 Sep 2026/, "the invoice date is not shown as a date");
      assert.match(firstText, /Export under LUT\/Bond/, "the record's treatment is not shown");
      const open = first.getByRole("link", { name: "Open invoice to record the IRN" });
      assert.equal(await open.count(), 1, "a prepared record has no way to its invoice");
      assert.match(await open.getAttribute("href"), /inv-1/, "the link does not open this record's invoice");

      const second = rows.nth(1);
      assert.match(await second.innerText(), /IRN recorded against the invoice/);
      assert.equal(await second.getByRole("link", { name: "Open invoice" }).count(), 1);

      const third = rows.nth(2);
      assert.match(await third.innerText(), /Names no invoice in this product/);
      assert.equal(await third.getByRole("link").count(), 0, "a record with no invoice offers something to open");

      await stub.quiet();
      assert.equal(stub.allWrites().length, 0,
        `the screen wrote: ${stub.allWrites().map((w) => `${w.method} ${w.path}`).join(", ")}`);
    },
  },
  {
    id: "a-failed-read-is-said-and-retry-asks-again",
    title: "a failed read says so in words, never an empty list, and Retry reads again",
    async run(env) {
      const { page } = env;
      const asked = stubScreen(env, (n) => (n === 1 ? { success: false, data: null, error: "The records could not be read." } : windowOf(RECORDS)));
      await openAndPick(env);
      await page.getByText("The records could not be read.").waitFor();
      assert.equal(await page.getByText("No e-invoice records found").count(), 0, "a failed read was shown as an empty list");
      await page.getByRole("button", { name: "Retry" }).click();
      await page.getByText("INV-0001").waitFor();
      assert.equal(asked.length, 2, `Retry should read again once, saw ${asked.length} reads`);
    },
  },
  {
    id: "no-records-says-where-to-prepare-one",
    title: "a client with no records is told to prepare one from the invoice, with nothing to click here",
    async run(env) {
      const { page } = env;
      stubScreen(env, () => windowOf([]));
      await openAndPick(env);
      await page.getByText("No e-invoice records found").waitFor();
      const body = await page.locator("body").innerText();
      assert.match(body, /compliance panel/, "the empty state does not say where a record is prepared");
      assert.equal(await page.getByRole("button", { name: /New E-Invoice|Create/ }).count(), 0);
    },
  },
  {
    id: "a-cut-short-list-says-so-and-show-more-asks-for-a-bigger-window",
    title: "a client with more records than the window says the list stopped, and Show more reads again with a larger limit",
    async run(env) {
      const { page } = env;
      const asked = stubScreen(env, (n) => windowOf(RECORDS, { hasMore: n < 2, limit: n < 2 ? 100 : 200 }));
      await openAndPick(env);
      await page.getByText("INV-0001").waitFor();
      const body = await page.locator("body").innerText();
      assert.match(body, /Showing the latest 3 e-invoice records\. More exist that are not shown here\./,
        "a list the server said was cut short was not reported as cut short");
      await page.getByRole("button", { name: "Show more" }).click();
      await until(() => asked.length >= 2, "the second read");
      assert.equal(asked.length, 2, `Show more should read once more, saw ${asked.length} reads`);
      assert.match(asked[1], /limit=200/, "the next window is not one step larger");
      await page.getByText("More exist that are not shown here").waitFor({ state: "detached" });
      assert.equal(await page.getByText("More exist that are not shown here").count(), 0,
        "the server said nothing more exists, so the notice goes away");
    },
  },
];
