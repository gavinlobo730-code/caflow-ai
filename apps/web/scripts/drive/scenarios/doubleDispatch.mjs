/**
 * Group A: two clicks in one tick make ONE write (frontend_ux-09).
 *
 * The defect this holds is the one that produced eleven journals from one Post Entry: a guard that is React
 * state lags the click by a render, so two click events dispatched before that render both pass. Each scenario
 * presses the control twice inside a single evaluate (`sameTickDouble`), against a stub that holds the write for
 * 700 ms so the second press lands while the first is still in flight, and then counts the writes the STUB saw.
 * The count is taken on the money URL and not on all traffic: a catalogue read or a timeline insert is not the
 * write that matters.
 *
 * WHICH CONTROLS ARE HERE, AND WHY THESE. A control is in this group when pressing it twice would put a second
 * thing in the books: a journal, an invoice and its issue (which posts the journal), a receipt, a vendor
 * payment, a bill's receipt (which posts the journal, withholds TDS and claims the credit), the issue of each of
 * the four kinds of note, and the deletion of a draft. The source guard beside this one cannot see most of them:
 * `a-button-that-writes-ignores-a-second-click` follows a handler declared in the same file, and the drawers'
 * Issue and Receive reach their write through a prop callback.
 */
import assert from "node:assert/strict";
import { expectWrites, pick, sameTick, sameTickDouble } from "../kit.mjs";
import { NOTE_KINDS, openBillDrawer, openInvoiceDrawer, openNoteDrawer } from "../flows.mjs";
import { ok, refuse } from "../stub.mjs";

export const group = "double-dispatch";

// ── the journal editor ──────────────────────────────────────────────────────────────────────────────────

async function journalReady({ page, stub, at }) {
  stub.route({ method: "POST", re: /accounting\/journal$/, reply: () => ok({ id: "j-1" }) });
  await page.goto(at("/accounting/journal/new/edit/"), { waitUntil: "networkidle" });
  await page.waitForSelector("#je-narration");
  await page.fill("#je-narration", "Being cash sale");
  await pick(page, page.locator("#je-account-l0"), "Cash in Hand");
  await page.locator('input[aria-label="Debit"]').first().fill("125000");
  await pick(page, page.locator("#je-account-l1"), "Sales");
}

const JOURNAL_WRITE = /\/accounting\/journal$/;

// ── the sales invoice editor ────────────────────────────────────────────────────────────────────────────

async function invoiceReady({ page, stub, at }) {
  stub.route({ method: "GET", re: /next-number/, reply: () => ok({ suggested_number: "INV-0001", series_head: "INV-" }) });
  stub.route({ method: "POST", re: /sales-invoices\/$/, reply: () => ok({ id: "inv-1", invoice_no: "INV-0001" }) });
  stub.route({ method: "POST", re: /sales-invoices\/inv-1\/issue$/, reply: () => ok({ id: "inv-1" }) });
  await page.goto(at("/sales/invoices/new/edit/"), { waitUntil: "networkidle" });
  await page.click('button:has-text("Select customer")');
  await page.locator("[role=listbox] [role=option]", { hasText: "Beta Stores" }).first().click();
  await page.click('button[aria-label="Line 1 product or service"]');
  await page.locator("[role=listbox] [role=option]", { hasText: "Consulting" }).first().click();
}

// ── the document drawers' second-step buttons ───────────────────────────────────────────────────────────

/** Open Record Payment over an issued invoice and return the modal's dialog. */
async function invoicePaymentModal(env) {
  const drawer = await openInvoiceDrawer(env, "issued");
  env.stub.route({ method: "POST", re: /receipts\/$/, reply: () => ok({ id: "r1" }) });
  await drawer.getByRole("button", { name: "Record Payment" }).first().click();
  const modal = env.page.getByRole("dialog").last();
  await modal.getByRole("button", { name: "Record Payment", exact: true }).waitFor();
  return modal;
}

/** Open Record Payment over a received bill and return the modal's dialog. */
async function billPaymentModal(env) {
  const drawer = await openBillDrawer(env, "received");
  env.stub.route({ method: "POST", re: /purchase-payments$/, reply: () => ok({ id: "pp1" }) });
  await drawer.getByRole("button", { name: "Record Payment" }).first().click();
  const modal = env.page.getByRole("dialog").last();
  await modal.getByRole("button", { name: "Record Payment", exact: true }).waitFor();
  return modal;
}

export const scenarios = [
  {
    id: "journal-post-entry",
    title: "two clicks on Post Entry in one tick write one journal",
    async run(env) {
      await journalReady(env);
      await sameTickDouble(env.page.getByRole("button", { name: "Post Entry" }));
      await expectWrites(env.stub, JOURNAL_WRITE, 1, "Post Entry pressed twice");
      const body = env.stub.writesTo(JOURNAL_WRITE)[0].body;
      // The amount is typed in rupees and goes over the wire as integer paise.
      assert.ok(body.includes("12500000"), `the debit did not reach the server as 12500000 paise: ${body.slice(0, 300)}`);
    },
  },
  {
    id: "journal-save-draft-and-post-together",
    title: "Save Draft and Post Entry pressed in the same tick write one journal between them",
    async run(env) {
      await journalReady(env);
      await sameTick(env.page.getByRole("button", { name: "Save Draft" }), env.page.getByRole("button", { name: "Post Entry" }));
      await expectWrites(env.stub, JOURNAL_WRITE, 1, "Save Draft and Post Entry together");
    },
  },
  {
    id: "invoice-save-and-issue",
    title: "two clicks on Save & Issue create one invoice and issue it once",
    async run(env) {
      await invoiceReady(env);
      await sameTickDouble(env.page.getByRole("button", { name: "Save & Issue" }));
      await expectWrites(env.stub, /sales-invoices\/$/, 1, "Save & Issue pressed twice (create)", "POST");
      await expectWrites(env.stub, /sales-invoices\/inv-1\/issue$/, 1, "Save & Issue pressed twice (issue)", "POST");
    },
  },
  {
    id: "invoice-drawer-record-payment",
    title: "two clicks on Record Payment in the sales drawer write one receipt",
    async run(env) {
      const modal = await invoicePaymentModal(env);
      await sameTickDouble(modal.getByRole("button", { name: "Record Payment", exact: true }));
      await expectWrites(env.stub, /receipts\/$/, 1, "Record Payment pressed twice", "POST");
    },
  },
  {
    id: "bill-drawer-record-payment",
    title: "two clicks on Record Payment in the purchase drawer write one vendor payment",
    async run(env) {
      const modal = await billPaymentModal(env);
      await sameTickDouble(modal.getByRole("button", { name: "Record Payment", exact: true }));
      await expectWrites(env.stub, /purchase-payments$/, 1, "Record Payment pressed twice", "POST");
    },
  },
  {
    id: "invoice-drawer-issue",
    title: "two clicks on Issue in the sales drawer post the invoice once",
    async run(env) {
      const drawer = await openInvoiceDrawer(env, "draft");
      env.stub.route({ method: "POST", re: /sales-invoices\/inv-9\/issue$/, reply: () => ok({ id: "inv-9" }) });
      await sameTickDouble(drawer.getByRole("button", { name: "Issue", exact: true }));
      await expectWrites(env.stub, /sales-invoices\/inv-9\/issue$/, 1, "Issue pressed twice", "POST");
    },
  },
  {
    id: "bill-drawer-receive",
    title: "two clicks on Receive in the purchase drawer post the bill once",
    async run(env) {
      // Scoped to the dialog: the list row has its own, already guarded, Receive, and pressing that one would
      // pass while the drawer's stayed broken.
      const drawer = await openBillDrawer(env, "draft");
      env.stub.route({ method: "POST", re: /purchase-bills\/b9\/receive$/, reply: () => ok({ id: "b9" }) });
      await sameTickDouble(drawer.getByRole("button", { name: "Receive", exact: true }));
      await expectWrites(env.stub, /purchase-bills\/b9\/receive$/, 1, "Receive pressed twice", "POST");
    },
  },
  ...NOTE_KINDS.map((kind) => ({
    id: `${kind.name.replace(/ /g, "-")}-drawer-issue`,
    title: `two clicks on Issue in the ${kind.name} drawer issue it once`,
    async run(env) {
      const drawer = await openNoteDrawer(env, kind);
      await sameTickDouble(drawer.getByRole("button", { name: "Issue", exact: true }));
      await expectWrites(env.stub, new RegExp(`/api/${kind.api}/n9/issue$`), 1, `Issue pressed twice on a ${kind.name}`, "POST");
    },
  })),
  {
    id: "invoice-delete-draft",
    title: "two clicks on Delete Draft delete the invoice once",
    async run(env) {
      const drawer = await openInvoiceDrawer(env, "draft");
      env.stub.route({ method: "DELETE", re: /sales-invoices\/inv-9$/, reply: () => ok(null) });
      await drawer.getByRole("button", { name: "Delete", exact: true }).first().click();
      await sameTickDouble(env.page.getByRole("button", { name: /Delete Draft/ }));
      await expectWrites(env.stub, /sales-invoices\/inv-9$/, 1, "Delete Draft pressed twice", "DELETE");
    },
  },
  {
    id: "bill-delete-draft",
    title: "two clicks on Delete Draft delete the purchase bill once",
    async run(env) {
      const drawer = await openBillDrawer(env, "draft");
      env.stub.route({ method: "DELETE", re: /purchase-bills\/b9$/, reply: () => ok(null) });
      await drawer.getByRole("button", { name: "Delete", exact: true }).first().click();
      await sameTickDouble(env.page.getByRole("button", { name: /Delete/ }).last());
      await expectWrites(env.stub, /purchase-bills\/b9$/, 1, "Delete pressed twice", "DELETE");
    },
  },
  {
    id: "refused-write-releases-the-button",
    title: "a refused write releases the button, and a second press then sends a second write",
    async run(env) {
      const modal = await invoicePaymentModal(env);
      env.stub.route({ method: "POST", re: /receipts\/$/, ...refuse("Receipt refused for the drive") });
      const submit = modal.getByRole("button", { name: "Record Payment", exact: true });
      await submit.click();
      // The refusal reaches the person as a toast (it has no role, so it is found by its words).
      await env.page.getByText("Receipt refused for the drive").first().waitFor({ timeout: 5000 });
      await expectWrites(env.stub, /receipts\/$/, 1, "the first press", "POST");
      assert.equal(await submit.isDisabled(), false, "the button is still disabled after the write was refused");
      // A held button would be the bug the guard exists to avoid in the other direction: a failed save that
      // can never be retried until the page is reloaded.
      await submit.click();
      await expectWrites(env.stub, /receipts\/$/, 2, "the second press, after the refusal", "POST");
    },
  },
];
