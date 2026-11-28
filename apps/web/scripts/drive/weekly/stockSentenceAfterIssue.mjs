/**
 * THE SENTENCE A SCREEN PRINTS WHEN A DOCUMENT WAS ISSUED AND ITS STOCK WAS NOT ALL RECORDED, driven in a browser (POST-A-092, carried to POST-A-555).
 *
 * A sales invoice, a purchase bill, a credit note and a purchase debit note move stock after they are committed, and that step keeps its own
 * failures so a refused stock row can never un-issue a document that is already in the books. The server says so on the answer to the issue
 * (`stock_effect`, with its own sentence) and nine places in the product print it. Each was read and tested on the server and in the unit
 * tests of `lib/documents/stockEffect`; none had been seen in a browser. A sentence that is computed and never drawn is the failure this
 * file is for: the person issued a document, the stock report is now wrong, and the screen said "issued".
 *
 * WHAT IS DRIVEN. For each place: the document is issued through the screen, the stand-in server answers that the stock was not all recorded,
 * and the SERVER'S sentence is on the page, word for word, with exactly one request sent. One more scenario per screen answers that the
 * stock WAS recorded and holds that nothing is said about stock at all (a notice on every issue is a notice nobody reads).
 *
 * No scenario asserts a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { expectWrites, until } from "../kit.mjs";
import { ok } from "../stub.mjs";
import { billRow, invoiceRow } from "../fixtures.mjs";
import { NOTE_KINDS, openNoteDrawer } from "../flows.mjs";
import { openInvoice } from "../scenarios/dates.mjs";

export const group = "stock-sentence-after-issue";

export const SAID = "Stock for 1 of 2 goods lines of this document was not recorded: Steel rod 12mm. Complete it from Inventory > Documents whose stock was not all recorded.";
const NOT_ALL = { stock_effect: { recorded: false, problem: SAID } };
const ALL = { stock_effect: { recorded: true, problem: null } };

const asPartner = { method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { accounting: ["read", "write", "approve"], sales: ["read", "write"] } }) };

/** The server's sentence, wherever the screen put it (a toast, a notice, a message line), as a person would read it. */
async function theSentenceIsOnThePage(page, what) {
  await until(async () => (await page.getByText(SAID, { exact: false }).count()) > 0, `the server's stock sentence to be shown after ${what}`, 6000);
}

async function nothingIsSaidAboutStock(page, what) {
  await page.waitForTimeout(600);
  assert.equal(await page.getByText(/stock/i).filter({ hasText: /not recorded|could not be confirmed/i }).count(), 0, `${what}: a stock sentence is shown though the stock was recorded`);
}

const INVOICE = invoiceRow("draft", "inv-9");
const INVOICE_ISSUE = /api\/sales-invoices\/inv-9\/issue$/;

async function issueTheDraftInvoice(env, answer) {
  const { page, stub } = env;
  stub.route(asPartner);
  stub.setTable("client_sales_invoices", [INVOICE]);
  stub.route({ method: "POST", re: INVOICE_ISSUE, reply: () => ok({ id: "inv-9", status: "issued", invoice_no: "INV/2026-27/0009", ...answer }) });
  await page.goto(env.at("/sales/"), { waitUntil: "networkidle" });
  await page.getByLabel(/Actions for invoice/).first().click();
  await page.getByRole("button", { name: "Issue", exact: true }).first().click();
  const confirm = page.getByRole("dialog").getByRole("button", { name: /^Issue/ });
  if (await confirm.count()) await confirm.first().click();
  await expectWrites(stub, INVOICE_ISSUE, 1, "issuing the draft invoice", "POST");
}

const BILL = billRow("draft", "b9");
const BILL_RECEIVE = /api\/purchase-bills\/b9\/receive$/;

async function receiveTheDraftBill(env, answer) {
  const { page, stub } = env;
  stub.route(asPartner);
  stub.setTable("purchase_bills", [BILL]);
  stub.route({ method: "POST", re: BILL_RECEIVE, reply: () => ok({ id: "b9", status: "received", ...answer }) });
  await page.goto(env.at("/purchases/?tab=bills"), { waitUntil: "networkidle" });
  await page.getByLabel(/Actions for bill/).first().click();
  await page.getByRole("button", { name: /^Receive/ }).first().click();
  const confirm = page.getByRole("dialog").getByRole("button", { name: /^Receive/ });
  if (await confirm.count()) await confirm.first().click();
  await expectWrites(stub, BILL_RECEIVE, 1, "receiving the draft bill", "POST");
}

const NOTE = (name) => NOTE_KINDS.find((k) => k.name === name);

/** A draft note opened from its list and issued from its drawer, the server answering `answer`. */
async function issueTheDraftNote(env, kind, answer) {
  const { page, stub } = env;
  stub.route(asPartner);
  const drawer = await openNoteDrawer(env, kind);
  const ISSUE = new RegExp(`/api/${kind.api}/n9/issue$`);
  stub.route({ method: "POST", re: ISSUE, reply: () => ok({ id: "n9", status: "issued", ...answer }) });
  stub.forgetWrites();
  await drawer.getByRole("button", { name: "Issue", exact: true }).click();
  const confirm = page.getByRole("dialog").getByRole("button", { name: /^(Issue|Confirm)/ }).last();
  await page.waitForTimeout(300);
  if ((await stub.writesTo(ISSUE, "POST").length) === 0 && await confirm.count()) await confirm.click().catch(() => {});
  await expectWrites(stub, ISSUE, 1, `issuing the ${kind.name}`, "POST");
}

/** One draft ticked in its list and issued through the list's own bulk action, the server answering `answer`. */
async function issueThroughTheBulkAction(env, { tab, table, row, issue, action, what }, answer) {
  const { page, stub } = env;
  stub.route(asPartner);
  stub.setTable(table, [row]);
  stub.route({ method: "POST", re: issue, reply: () => ok({ id: row.id, status: "issued", ...answer }) });
  await page.goto(env.at(tab), { waitUntil: "networkidle" });
  const tick = page.getByRole("checkbox").last();
  await tick.waitFor();
  await tick.check();
  await page.getByRole("button", { name: action }).first().click();
  // The bulk action asks first, in the product's own dialog: its last button is the one that goes ahead.
  const goAhead = page.getByRole("button", { name: "OK", exact: true });
  await goAhead.waitFor({ timeout: 5000 });
  await goAhead.click();
  try {
    await expectWrites(stub, issue, 1, what, "POST");
  } catch (e) {
    const seen = await page.evaluate(() => ({
      dialogs: [...document.querySelectorAll('[role="dialog"],[role="alertdialog"]')].map((d) => [...d.querySelectorAll("button")].map((b) => (b.textContent ?? "").trim())),
      ticked: [...document.querySelectorAll('input[type="checkbox"]')].map((c) => c.checked),
      buttons: [...document.querySelectorAll("button")].map((b) => (b.textContent ?? "").trim()).filter((t) => /issue|receive|draft|selected/i.test(t)).slice(0, 12),
    }));
    throw new Error(`${e.message} || on the page: ${JSON.stringify(seen)}`);
  }
}

const BULK = [
  { key: "invoices", tab: "/sales/", table: "client_sales_invoices", row: INVOICE, issue: INVOICE_ISSUE, action: /Issue draft\(s\)/, what: "issuing the ticked draft invoice",
    where: "Sales > tick a draft invoice > Issue draft(s)" },
  { key: "bills", tab: "/purchases/?tab=bills", table: "purchase_bills", row: BILL, issue: BILL_RECEIVE, action: /Receive draft\(s\)/, what: "receiving the ticked draft bill",
    where: "Purchases > tick a draft bill > Receive draft(s)" },
  { key: "credit-notes", tab: NOTE("sales credit note").tab, table: NOTE("sales credit note").table, row: NOTE("sales credit note").row, issue: /api\/credit-notes\/n9\/issue$/,
    action: /Issue draft\(s\)/, what: "issuing the ticked draft credit note", where: "Sales > Credit Notes > tick a draft note > Issue draft(s)" },
  { key: "purchase-debit-notes", tab: NOTE("purchase debit note").tab, table: NOTE("purchase debit note").table, row: NOTE("purchase debit note").row,
    issue: /api\/debit-notes\/n9\/issue$/, action: /Issue draft\(s\)/, what: "issuing the ticked draft purchase debit note", where: "Purchases > Debit Notes > tick a draft note > Issue draft(s)" },
];

export const scenarios = [
  {
    id: "an-invoice-issued-with-its-stock-not-all-recorded-says-so-in-the-servers-words",
    title: "Sales > a draft invoice's menu > Issue: when the server answers that the stock was not all recorded, its sentence is on the page word for word and one issue was sent",
    async run(env) {
      await issueTheDraftInvoice(env, NOT_ALL);
      await theSentenceIsOnThePage(env.page, "an invoice is issued");
    },
  },
  {
    id: "an-invoice-issued-with-its-stock-recorded-says-nothing-about-stock",
    title: "Sales > a draft invoice's menu > Issue: when the stock was recorded nothing is said about stock",
    async run(env) {
      await issueTheDraftInvoice(env, ALL);
      await nothingIsSaidAboutStock(env.page, "an invoice issued with its stock recorded");
    },
  },
  {
    id: "a-bill-received-with-its-stock-not-all-recorded-says-so-in-the-servers-words",
    title: "Purchases > a draft bill's menu > Receive: when the server answers that the stock was not all recorded, its sentence is on the page word for word and one receive was sent",
    async run(env) {
      await receiveTheDraftBill(env, NOT_ALL);
      await theSentenceIsOnThePage(env.page, "a bill is received");
    },
  },
  {
    id: "a-bill-received-with-its-stock-recorded-says-nothing-about-stock",
    title: "Purchases > a draft bill's menu > Receive: when the stock was recorded nothing is said about stock",
    async run(env) {
      await receiveTheDraftBill(env, ALL);
      await nothingIsSaidAboutStock(env.page, "a bill received with its stock recorded");
    },
  },
  {
    id: "a-credit-note-issued-with-its-stock-not-all-recorded-says-so-in-the-servers-words",
    title: "Sales > Credit Notes > a draft note > Issue: when the server answers that the returned goods were not all put back into stock, its sentence is on the page word for word and one issue was sent",
    async run(env) {
      await issueTheDraftNote(env, NOTE("sales credit note"), NOT_ALL);
      await theSentenceIsOnThePage(env.page, "a credit note is issued");
    },
  },
  {
    id: "a-purchase-debit-note-issued-with-its-stock-not-all-recorded-says-so-in-the-servers-words",
    title: "Purchases > Debit Notes > a draft note > Issue: when the server answers that the goods sent back were not all taken out of stock, its sentence is on the page word for word and one issue was sent",
    async run(env) {
      await issueTheDraftNote(env, NOTE("purchase debit note"), NOT_ALL);
      await theSentenceIsOnThePage(env.page, "a purchase debit note is issued");
    },
  },
  {
    id: "a-note-issued-with-its-stock-recorded-says-nothing-about-stock",
    title: "Sales > Credit Notes and Purchases > Debit Notes > Issue: when the stock was recorded nothing is said about stock",
    async run(env) {
      await issueTheDraftNote(env, NOTE("sales credit note"), ALL);
      await nothingIsSaidAboutStock(env.page, "a credit note issued with its stock recorded");
    },
  },
  ...BULK.map((b) => ({
    id: `${b.key}-issued-in-bulk-with-stock-not-all-recorded-say-so-with-the-servers-sentence`,
    title: `${b.where}: when the server answers that the stock was not all recorded, the screen says how many and shows the server's sentence, and one request was sent`,
    async run(env) {
      await issueThroughTheBulkAction(env, b, NOT_ALL);
      await theSentenceIsOnThePage(env.page, b.what);
    },
  })),
  {
    id: "an-invoice-saved-and-issued-from-its-editor-with-stock-not-all-recorded-says-so",
    title: "Sales > New invoice > Save & Issue: when the server answers the issue that the stock was not all recorded, its sentence is shown after the editor closes",
    async run(env) {
      const { page, stub } = env;
      stub.route(asPartner);
      await openInvoice(env);
      const ISSUE = /api\/sales-invoices\/inv-1\/issue$/;
      stub.route({ method: "POST", re: ISSUE, reply: () => ok({ id: "inv-1", status: "issued", ...NOT_ALL }) });
      await page.getByRole("button", { name: "Save & Issue", exact: true }).first().click();
      const confirm = page.getByRole("dialog").getByRole("button").last();
      await page.waitForTimeout(400);
      if ((await stub.writesTo(ISSUE, "POST").length) === 0 && await confirm.count()) await confirm.click();
      await expectWrites(stub, ISSUE, 1, "Save & Issue", "POST");
      await theSentenceIsOnThePage(page, "an invoice is saved and issued from its editor");
    },
  },
];
