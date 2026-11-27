/**
 * THE MARKS A CA PUTS ON A DOCUMENT WHOSE STOCK THEY PUT RIGHT BY HAND ARE DRIVEN IN A BROWSER (POST-A-092, the marks panel).
 *
 * POST-A-092 added "Mark as settled" to the Inventory tab's list of documents whose stock was not all recorded, and a list of the marked documents
 * with a way to take a mark off. The marks and their grants ran against a real database; the panel was never opened in a browser. Against a stubbed
 * server, in Chromium, on a client's Inventory screen:
 *
 *   1. Mark as settled opens a dialog NAMED for the document, keeps Tab inside it and closes on Escape with nothing sent; the reason is sent AS TYPED
 *      with the client, the kind and the document, once; the list is read again, the document leaves it and the marks section shows the reason, who
 *      marked it and when;
 *   2. the server's refusal of a mark is read inside the dialog, which stays open for the reason to be corrected;
 *   3. Take the mark off asks first (Cancel sends nothing); saying yes sends ONE delete for that mark;
 *   4. a read of the marks that failed says it could not read them and is NOT drawn as "none are marked";
 *   5. somebody who may read the books and not write them is shown neither button, and is told why;
 *   6. a purchase bill the retry cannot finish (landed charges, an oversold true-up) shows the server's sentence on its row and is not offered
 *      Complete the stock, while the document beside it is.
 *
 * No scenario has a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";
import { ok, refuse } from "../stub.mjs";

export const group = "stock-settled-marks";

const LIST = /api\/inventory\/stock-effects\/unrecorded/;
const SETTLED = /api\/inventory\/stock-effects\/settled\?/;
const SETTLE = /api\/inventory\/stock-effects\/settle$/;
const UNSETTLE = /api\/inventory\/stock-effects\/settled\/mark-1$/;

const DOC = {
  kind: "sales_invoice", document_id: "11111111-1111-4111-8111-111111111111", reference: "INV-77", document_date: "2026-04-20",
  owed_lines: 2, moved_lines: 1, unjournalled_rows: 0,
};
const MARK = {
  id: "mark-1", document_kind: "sales_invoice", document_id: DOC.document_id, reference: "INV-77", document_date: "2026-04-20",
  reason: "Adjusted by a stock adjustment on 21 April", settled_by_name: "Meera Shah", settled_at: "2026-05-02T09:30:00Z",
};

const focusInside = (dialog) => dialog.evaluate((d) => d.contains(document.activeElement));

/**
 * The Inventory screen with the panel listing one document and no marks. `state.marked` flips what the list and the marks answer from then on
 * (the stub takes the FIRST route that matches, so a later route would never be reached: the answers read the state instead). With `marked` the
 * list is empty and the panel shows only the marks, so the screen is ready when the way to take a mark off is.
 */
async function atTheInventory(env, { marked = false, marksReply, permissions } = {}) {
  const { page, stub } = env;
  const state = { marked };
  if (permissions) stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok(permissions) });
  stub.route({ method: "GET", re: LIST, reply: () => ok(state.marked ? { total: 0, documents: [] } : { total: 1, documents: [DOC] }) });
  stub.route({ method: "GET", re: SETTLED, reply: marksReply ?? (() => ok({ settlements: state.marked ? [MARK] : [] })) });
  await page.goto(env.at("/inventory/"), { waitUntil: "networkidle" });
  if (marked) await openTheMarks(page);
  else await page.getByText("Documents whose stock was not all recorded").waitFor();
  return state;
}

/** The marks sit in a collapsed section ("Marked as settled by hand (n)"); opening it is what a person does to reach them. */
async function openTheMarks(page) {
  const summary = page.getByText(/^Marked as settled by hand \(\d+\)$/);
  await summary.waitFor({ timeout: 8000 });
  const region = page.getByRole("region", { name: "Documents marked as settled by hand" });
  if (!(await region.isVisible())) await summary.click();
  await region.waitFor({ timeout: 8000 });
  return region;
}

const markButton = (page) => page.getByRole("button", { name: "Mark as settled", exact: true }).first();

export const scenarios = [
  {
    id: "mark-as-settled-is-a-named-dialog-and-sends-the-reason-as-typed-once",
    title: "Inventory > a listed document > Mark as settled: a named dialog that keeps Tab inside and closes on Escape with nothing sent; the reason is sent as typed once, and the marked document is shown with its reason, who and when",
    async run(env) {
      const { page, stub } = env;
      const state = await atTheInventory(env);
      await markButton(page).focus();
      await markButton(page).click();
      const dialog = page.getByRole("dialog", { name: /^Mark .* as settled by hand$/ });
      await dialog.waitFor();
      assert.equal(await dialog.getAttribute("aria-modal"), "true", "the mark dialog does not say it is modal");
      await until(() => focusInside(dialog), "focus to move into the mark dialog");
      for (let i = 0; i < 8; i += 1) {
        await page.keyboard.press("Tab");
        assert.equal(await focusInside(dialog), true, `Tab number ${i + 1} left the mark dialog`);
      }
      await page.keyboard.press("Escape");
      await dialog.waitFor({ state: "detached" });
      assert.equal(stub.writesTo(SETTLE, "POST").length, 0, "Escape sent a mark");

      const REASON = "  Adjusted by a stock adjustment on 21 April  ";
      stub.route({ method: "POST", re: SETTLE, reply: () => ok({ ...MARK, message: "Sales invoice INV-77 is marked as settled by hand." }) });
      await markButton(page).click();
      await dialog.waitFor();
      await dialog.getByLabel(/What did you do to put it right/).fill(REASON);
      stub.forgetWrites();
      // From here the list and the marks answer as they do once the mark is on record.
      state.marked = true;
      await dialog.getByRole("button", { name: "Mark as settled", exact: true }).click();
      await page.getByText("Sales invoice INV-77 is marked as settled by hand.").waitFor({ timeout: 8000 });
      const sent = stub.writesTo(SETTLE, "POST");
      assert.equal(sent.length, 1, "the mark was not sent exactly once");
      assert.deepEqual(JSON.parse(sent[0].body), { client_id: env.clientId, kind: "sales_invoice", document_id: DOC.document_id, reason: REASON },
        "the mark did not carry the client, the kind, the document and the reason exactly as typed");
      const region = await openTheMarks(page);
      const text = await region.innerText();
      assert.match(text, /Adjusted by a stock adjustment on 21 April/, "the marks section does not show the reason");
      assert.match(text, /Meera Shah/, "the marks section does not say who marked it");
      assert.equal(await markButton(page).count(), 0, "the marked document is still offered Mark as settled");
    },
  },
  {
    id: "a-refused-mark-is-read-inside-the-dialog-which-stays-open",
    title: "Mark as settled: the server's refusal (a reason that says nothing) is shown inside the dialog, which stays open for the reason to be corrected",
    async run(env) {
      const { page, stub } = env;
      await atTheInventory(env);
      stub.route({ method: "POST", re: SETTLE, ...refuse("A stub refusal of the mark.", 422) });
      await markButton(page).click();
      const dialog = page.getByRole("dialog", { name: /^Mark .* as settled by hand$/ });
      await dialog.waitFor();
      await dialog.getByLabel(/What did you do to put it right/).fill("done");
      await dialog.getByRole("button", { name: "Mark as settled", exact: true }).click();
      await dialog.getByText("A stub refusal of the mark.").waitFor({ timeout: 8000 })
        .catch(() => { throw new Error("the server's refusal of the mark was not shown inside the dialog"); });
      assert.equal(await dialog.count(), 1, "the dialog closed on a refusal, so the reason could not be corrected");
      assert.equal(stub.writesTo(SETTLE, "POST").length, 1, "the mark was not sent exactly once");
    },
  },
  {
    id: "taking-a-mark-off-asks-first-and-sends-one-delete-for-that-mark",
    title: "Take the mark off: the question is asked first, Cancel sends nothing, and saying yes sends ONE delete for that mark",
    async run(env) {
      const { page, stub } = env;
      await atTheInventory(env, { marked: true });
      stub.route({ method: "DELETE", re: UNSETTLE, reply: () => ok({ removed: true, message: "The mark is taken off Sales invoice INV-77." }) });
      const off = page.getByRole("button", { name: /Take the mark off/ }).first();
      await off.waitFor();
      await off.click();
      const question = page.getByRole("alertdialog");
      await question.waitFor();
      assert.match(await question.innerText(), /Take the mark off\?/, "the question does not name what it asks");
      await question.getByRole("button", { name: "Cancel" }).click();
      assert.equal(stub.writesTo(UNSETTLE, "DELETE").length, 0, "Cancel took the mark off");
      await off.click();
      await page.getByRole("alertdialog").getByRole("button", { name: "Take the mark off" }).click();
      await page.getByText("The mark is taken off Sales invoice INV-77.").waitFor({ timeout: 8000 });
      assert.equal(stub.writesTo(UNSETTLE, "DELETE").length, 1, "the mark was not taken off exactly once");
    },
  },
  {
    id: "a-bill-the-retry-cannot-finish-says-what-to-do-by-hand-and-is-not-offered-complete-the-stock",
    title: "A purchase bill with landed charges or an oversold true-up that was not posted: the server's sentence is shown on its row, Complete the stock is not offered for it, and Mark as settled still is",
    async run(env) {
      const { page, stub } = env;
      const SAYS = "Purchase bill BILL-9 received goods that covered units sold earlier while the item was oversold, so the cost of those units belongs in Cost of Goods Sold, and the entry that moves it was not posted. Post that true-up by hand, then mark it as settled by hand, with a note of what you posted.";
      const HAND = { kind: "purchase_bill", document_id: "22222222-2222-4222-8222-222222222222", reference: "BILL-9", document_date: "2026-05-04",
        owed_lines: 1, moved_lines: 1, unjournalled_rows: 0, hand_fix: "oversold_trueup", hand_fix_says: SAYS };
      stub.route({ method: "GET", re: LIST, reply: () => ok({ total: 2, documents: [HAND, DOC] }) });
      stub.route({ method: "GET", re: SETTLED, reply: () => ok({ settlements: [] }) });
      await page.goto(env.at("/inventory/"), { waitUntil: "networkidle" });
      await page.getByText("Documents whose stock was not all recorded").waitFor();
      const handRow = page.getByRole("row").filter({ hasText: "BILL-9" });
      await handRow.getByText(SAYS).waitFor({ timeout: 8000 });
      assert.equal(await handRow.getByRole("button", { name: "Complete the stock" }).count(), 0, "Complete the stock is offered for a bill the retry cannot finish");
      assert.equal(await handRow.getByRole("button", { name: "Mark as settled", exact: true }).count(), 1, "Mark as settled is not offered for it");
      // The ordinary document beside it is unchanged: it is still offered both.
      const ordinary = page.getByRole("row").filter({ hasText: "INV-77" });
      assert.equal(await ordinary.getByRole("button", { name: "Complete the stock" }).count(), 1, "the ordinary document lost its Complete the stock button");
      assert.equal(stub.writesTo(/api\/inventory\/stock-effects\/retry/, "POST").length, 0, "something was sent");
    },
  },
  {
    id: "a-failed-read-of-the-marks-says-so-and-is-not-drawn-as-none-marked",
    title: "A read of the marks that failed says it could not read them, and the section is not drawn as an empty list",
    async run(env) {
      const { page } = env;
      await atTheInventory(env, { marksReply: () => ({ success: false, data: null, error: "down" }) });
      await page.getByText(/Couldn.t read the documents marked as settled by hand/).waitFor({ timeout: 8000 });
      assert.equal(await page.getByRole("region", { name: "Documents marked as settled by hand" }).count(), 0, "a failed read was drawn as a list");
    },
  },
  {
    id: "somebody-who-may-read-the-books-and-not-write-them-is-offered-neither-button",
    title: "A reader without write access to the books is shown neither Complete the stock nor Mark as settled, and the panel says why",
    async run(env) {
      const { page } = env;
      await atTheInventory(env, { permissions: { role: "Executive", permissions: { inventory: ["read"], accounting: ["read"] } } });
      await page.getByText(/needs write access to the books, so those buttons are not shown to you/).waitFor({ timeout: 8000 });
      assert.equal(await markButton(page).count(), 0, "Mark as settled is offered to somebody who may not write the books");
      assert.equal(await page.getByRole("button", { name: "Complete the stock" }).count(), 0, "Complete the stock is offered to somebody who may not write the books");
    },
  },
];
