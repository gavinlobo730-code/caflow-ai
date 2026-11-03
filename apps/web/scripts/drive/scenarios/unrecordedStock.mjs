/**
 * Group Q: the documents whose stock was not all recorded, driven in a browser (POST-A-092, the stock side).
 *
 * The panel on the client's Inventory tab lists what the database function counted and asks the server to complete one document. The
 * source guard holds that the panel reads the right endpoints and decides nothing; this proves in Chromium what a person sees and what
 * a click sends:
 *
 *   1. a listed document says how many of its goods lines have stock rows, and pressing Complete the stock sends ONE retry naming the
 *      client, the kind and the document, shows the server's sentence as it came, and reads the list again;
 *   2. two clicks in the same tick send ONE retry;
 *   3. a refusal is shown as the server wrote it and the document stays listed;
 *   4. a read that failed says it could not check and lists nothing (an empty panel would have meant every document has its stock).
 */
import assert from "node:assert/strict";
import { sameTickDouble, expectWrites, until } from "../kit.mjs";
import { ok, refuse } from "../stub.mjs";

export const group = "unrecorded-stock";

const LIST = /api\/inventory\/stock-effects\/unrecorded/;
const RETRY = /api\/inventory\/stock-effects\/retry/;

const DOC = {
  kind: "sales_invoice", document_id: "11111111-1111-4111-8111-111111111111", reference: "INV-77", document_date: "2026-04-20",
  owed_lines: 2, moved_lines: 1, unjournalled_rows: 0,
};

async function atTheInventory(env, listReply) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: LIST, reply: listReply });
  await page.goto(env.at("/inventory/"), { waitUntil: "networkidle" });
}

const complete = (page) => page.getByRole("button", { name: "Complete the stock" }).first();
/** The question every press asks first (a document already put right by hand would be moved a second time). */
const sure = (page) => page.getByRole("alertdialog").getByRole("button", { name: "Complete the stock" });
const retries = (stub) => stub.writesTo(RETRY, "POST").map((w) => JSON.parse(w.body));

export const scenarios = [
  {
    id: "a-listed-document-is-completed-with-one-retry-and-the-servers-sentence",
    title: "the panel says how many goods lines have stock rows, one press sends one retry for that document, and the server's sentence is shown",
    async run(env) {
      const { page, stub } = env;
      let listed = true;
      await atTheInventory(env, () => ok(listed ? { total: 1, documents: [DOC] } : { total: 0, documents: [] }));
      await page.getByText("Documents whose stock was not all recorded").waitFor();
      await page.getByText("Stock recorded for 1 of 2 goods lines.").waitFor();
      assert.ok(await page.getByText("Sales invoice INV-77").isVisible());
      const SAID = "The stock for sales invoice INV-77 is recorded in full.";
      stub.route({ method: "POST", re: RETRY, reply: () => { listed = false; return ok({ recorded: true, message: SAID, stock_effect: null }); } });
      await complete(page).click();
      const question = page.getByRole("alertdialog");
      await question.waitFor();
      assert.match(await question.innerText(), /already adjusted this stock by hand/, "the question does not warn about a hand adjustment");
      assert.strictEqual(retries(stub).length, 0, "the retry was sent before the question was answered");
      await sure(page).click();
      await page.getByText(SAID).waitFor();
      await expectWrites(stub, RETRY, 1, "one press on Complete the stock", "POST");
      assert.deepStrictEqual(retries(stub)[0], { client_id: env.clientId, kind: "sales_invoice", document_id: DOC.document_id });
      await until(async () => (await complete(page).count()) === 0, "the completed document to leave the list");
    },
  },
  {
    id: "two-presses-on-complete-the-stock-in-one-tick-send-one-retry",
    title: "Complete the stock pressed twice in the same tick sends ONE retry",
    async run(env) {
      const { page, stub } = env;
      await atTheInventory(env, () => ok({ total: 1, documents: [DOC] }));
      await complete(page).waitFor();
      stub.route({ method: "POST", re: RETRY, reply: () => ok({ recorded: false, message: "Still not finished.", stock_effect: null }) });
      await sameTickDouble(complete(page));
      await page.getByRole("alertdialog").waitFor();
      await sure(page).click();
      await expectWrites(stub, RETRY, 1, "two same-tick presses on Complete the stock", "POST");
    },
  },
  {
    id: "a-refusal-is-shown-as-the-server-wrote-it-and-the-document-stays-listed",
    title: "a refusal is shown in the server's words and the document is still in the list",
    async run(env) {
      const { page, stub } = env;
      const REFUSED = "Sales invoice INV-77 was cancelled, so it has no stock effect to complete.";
      await atTheInventory(env, () => ok({ total: 1, documents: [DOC] }));
      await complete(page).waitFor();
      stub.route({ method: "POST", re: RETRY, ...refuse(REFUSED, 409) });
      await complete(page).click();
      await sure(page).click();
      await page.getByText(REFUSED).waitFor();
      assert.ok(await complete(page).isVisible(), "the document left the list although the server refused");
      assert.strictEqual(await complete(page).isDisabled(), false, "the button stayed held after a refusal");
    },
  },
  {
    id: "cancelling-the-question-sends-nothing",
    title: "Cancel on the question sends no retry and leaves the document listed",
    async run(env) {
      const { page, stub } = env;
      await atTheInventory(env, () => ok({ total: 1, documents: [DOC] }));
      await complete(page).click();
      await page.getByRole("alertdialog").getByRole("button", { name: "Cancel" }).click();
      await expectWrites(stub, RETRY, 0, "a cancelled question", "POST");
      assert.ok(await complete(page).isVisible());
      assert.strictEqual(await complete(page).isDisabled(), false, "the button stayed held after Cancel");
    },
  },
  {
    id: "a-read-that-failed-says-it-could-not-check-and-lists-nothing",
    title: "a failed read says it could not check, and is not rendered as an empty panel",
    async run(env) {
      const { page } = env;
      await atTheInventory(env, () => ({ success: false, data: null, error: "down" }));
      await page.getByText(/check which documents have unrecorded stock/).waitFor();
      assert.strictEqual(await complete(page).count(), 0);
    },
  },
];
