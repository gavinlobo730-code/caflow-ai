/**
 * A NOTE THAT CAN MOVE STOCK ASKS WHETHER THE GOODS CAME BACK WHEREVER IT IS MADE, THE SERVER'S "STOCK WAS LEFT ALONE" SENTENCE IS PRINTED, AND THE BRANDING SCREEN SAYS ONLY WHAT THE
 * INVOICE PRINTS (POST-A-378, POST-A-375).
 *
 * POST-A-371 made a credit note or a purchase debit note say whether its goods came back, and the server refuses to issue one that names goods and has not. Only the two editors asked, so a
 * note raised from the invoice drawer or the bill drawer was a draft the CA could not issue until they opened it and answered. The two drawer modals ask now (only when a line's item is a
 * good), the answer travels with the draft, and the sentence the server adds when the answer was no ("Stock was not moved for credit note …") is printed by the screens that issue a note.
 *
 * And the Firm Branding screen drew a band in the secondary colour and set its text in the chosen font, which no printed document reads; the invoice PDF prints the logo, the tagline and the
 * primary colour only. It says so now, beside each setting that is kept on file, and the Invoice Templates screen no longer promises engagement documents.
 *
 * No scenario has a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";
import { ok } from "../stub.mjs";
import { ITEM } from "../fixtures.mjs";
import { NOTE_KINDS, openBillDrawer, openInvoiceDrawer, openNoteDrawer } from "../flows.mjs";

export const group = "goods-answer";

const NO = "No goods returned: a price, rate or discount correction (stock and cost do not move)";
const CREDIT_YES = "Goods returned: add them back to stock";
const DEBIT_YES = "Goods returned to the supplier: take them out of stock";
const LEGEND_CREDIT = "Did the goods come back?";
const LEGEND_DEBIT = "Did the goods go back to the supplier?";

const modalOf = (page) => page.getByRole("dialog").last();
const body = (stub, re) => JSON.parse(stub.writesTo(re)[0].body);

/** The catalogue as the modal's lookup finds it: one item, a good or a service. */
function catalogue(stub, kind) { stub.setTable("service_catalogue", [{ ...ITEM, kind }]); }

async function openCreditNoteModal(env, kind) {
  catalogue(env.stub, kind);
  const drawer = await openInvoiceDrawer(env, "issued");
  await drawer.getByRole("button", { name: "Credit Note", exact: true }).first().click();
  const modal = modalOf(env.page);
  await modal.getByRole("button", { name: "Create Credit Note", exact: true }).waitFor();
  env.stub.route({ method: "POST", re: /\/api\/credit-notes\/$/, reply: () => ok({ id: "n1", credit_note_no: "CN-1" }) });
  return modal;
}

async function openDebitNoteModal(env, kind) {
  catalogue(env.stub, kind);
  const drawer = await openBillDrawer(env, "received");
  await drawer.getByRole("button", { name: "Debit Note", exact: true }).first().click();
  const modal = modalOf(env.page);
  await modal.getByRole("button", { name: "Create Debit Note", exact: true }).waitFor();
  env.stub.route({ method: "POST", re: /\/api\/debit-notes\/$/, reply: () => ok({ id: "n1", debit_note_no: "DN-1" }) });
  return modal;
}

const CREDIT_WRITE = /\/api\/credit-notes\/$/;
const DEBIT_WRITE = /\/api\/debit-notes\/$/;
/** The question in the words of the note's own kind: a credit note's goods come back, a purchase debit note's go back to the supplier (the server's own question and sentence use the same verbs). */
const legendOf = (write) => (write === DEBIT_WRITE ? LEGEND_DEBIT : LEGEND_CREDIT);
const otherLegendOf = (write) => (write === DEBIT_WRITE ? LEGEND_CREDIT : LEGEND_DEBIT);

const asksAndSends = (id, title, open, write, button, choice, expected) => ({
  id, title,
  async run(env) {
    const { page, stub } = env;
    const modal = await open(env, "good");
    await modal.getByText(legendOf(write)).waitFor();
    assert.equal(await modal.getByText(otherLegendOf(write)).count(), 0, `the question is worded for the other kind of note: ${otherLegendOf(write)}`);
    assert.equal(await modal.getByText("Required before you issue this note.").count(), 1, "the choice does not say that an answer is needed before the note is issued");
    await modal.getByLabel(choice).check();
    stub.forgetWrites();
    await modal.getByRole("button", { name: button, exact: true }).click();
    await until(() => stub.writesTo(write).length === 1, "the draft was not sent");
    assert.equal(body(stub, write).goods_returned, expected, `the draft carries ${JSON.stringify(body(stub, write).goods_returned)}, not ${expected}`);
  },
});

const draftWithoutAnAnswer = (id, title, open, write, button) => ({
  id, title,
  async run(env) {
    const { stub } = env;
    const modal = await open(env, "good");
    await modal.getByText(legendOf(write)).waitFor();
    stub.forgetWrites();
    await modal.getByRole("button", { name: button, exact: true }).click();
    await until(() => stub.writesTo(write).length === 1, "a draft with no answer was refused by the screen: it is the server that refuses to ISSUE");
    assert.equal("goods_returned" in body(stub, write), false, "an unanswered draft carries an answer nobody gave");
  },
});

const servicesAskNothing = (id, title, open, write, button) => ({
  id, title,
  async run(env) {
    const { page, stub } = env;
    const modal = await open(env, "service");
    // the lookup has had every chance to answer: a good would have shown the choice by now
    await page.waitForTimeout(1200);
    assert.equal(await modal.getByText(legendOf(write)).count(), 0, "a note that names no goods asks whether the goods came back");
    stub.forgetWrites();
    await modal.getByRole("button", { name: button, exact: true }).click();
    await until(() => stub.writesTo(write).length === 1, "the draft was not sent");
    assert.equal("goods_returned" in body(stub, write), false, "a note that names no goods carries an answer");
  },
});

// the server's own sentence (`domain/inventory/note_goods.declined`): a debit note's goods "went back to the supplier", a credit note's "came back"
const ISSUE_SENTENCE = (kind, no) => `Stock was not moved for ${kind} ${no}: it says no goods ${kind === "debit note" ? "went back to the supplier" : "came back"} (a price, rate or discount correction). If goods did move, record that with a stock adjustment.`;

export const scenarios = [
  asksAndSends("a-credit-note-raised-from-an-invoice-that-names-goods-asks-and-sends-no", "Invoice drawer > Credit Note, a goods line: the question is asked and 'No goods returned' is sent as false",
    openCreditNoteModal, CREDIT_WRITE, "Create Credit Note", NO, false),
  asksAndSends("a-credit-note-raised-from-an-invoice-that-names-goods-asks-and-sends-yes", "Invoice drawer > Credit Note, a goods line: 'Goods returned' is sent as true",
    openCreditNoteModal, CREDIT_WRITE, "Create Credit Note", CREDIT_YES, true),
  draftWithoutAnAnswer("a-credit-note-draft-can-be-saved-before-the-goods-question-is-answered", "Invoice drawer > Credit Note, a goods line: the draft is saved without an answer and carries none",
    openCreditNoteModal, CREDIT_WRITE, "Create Credit Note"),
  servicesAskNothing("a-credit-note-for-services-asks-nothing", "Invoice drawer > Credit Note, a service line: no question is asked and none is sent",
    openCreditNoteModal, CREDIT_WRITE, "Create Credit Note"),
  asksAndSends("a-debit-note-raised-from-a-bill-that-names-goods-asks-and-sends-yes", "Bill drawer > Debit Note, a goods line: 'Goods returned to the supplier' is sent as true",
    openDebitNoteModal, DEBIT_WRITE, "Create Debit Note", DEBIT_YES, true),
  asksAndSends("a-debit-note-raised-from-a-bill-that-names-goods-asks-and-sends-no", "Bill drawer > Debit Note, a goods line: 'No goods returned' is sent as false",
    openDebitNoteModal, DEBIT_WRITE, "Create Debit Note", NO, false),
  servicesAskNothing("a-debit-note-for-services-asks-nothing", "Bill drawer > Debit Note, a service line: no question is asked and none is sent",
    openDebitNoteModal, DEBIT_WRITE, "Create Debit Note"),

  {
    id: "issuing-a-credit-note-that-said-no-goods-came-back-prints-the-sentence-the-server-sent",
    title: "Credit notes tab > a draft's drawer > Issue: the server's 'stock was not moved' sentence is in the message",
    async run(env) {
      const { page, stub } = env;
      const drawer = await openNoteDrawer(env, NOTE_KINDS[0]);
      stub.route({ method: "POST", re: /api\/credit-notes\/n9\/issue$/, reply: () => ok({ id: "n9", stock_not_moved: ISSUE_SENTENCE("credit note", "CN-0009") }) });
      await drawer.getByRole("button", { name: "Issue", exact: true }).click();
      await page.getByText(ISSUE_SENTENCE("credit note", "CN-0009")).waitFor();
      assert.equal(await page.getByText(/Credit note issued/).count() >= 1, true, "the message does not say that the note was issued");
    },
  },
  {
    id: "issuing-a-credit-note-with-no-such-sentence-says-only-that-it-was-issued",
    title: "Credit notes tab > a draft's drawer > Issue: with no 'stock was not moved' sentence the message is the plain one",
    async run(env) {
      const { page } = env;
      const drawer = await openNoteDrawer(env, NOTE_KINDS[0]);
      await drawer.getByRole("button", { name: "Issue", exact: true }).click();
      await page.getByText(/Credit note issued/).first().waitFor();
      assert.equal(await page.getByText(/Stock was not moved/).count(), 0, "a sentence about stock appears over a note that left none alone");
    },
  },
  {
    id: "issuing-a-debit-note-that-said-no-goods-went-back-prints-the-sentence-the-server-sent",
    title: "Debit notes tab > a draft's drawer > Issue: the server's 'stock was not moved' sentence is in the message line",
    async run(env) {
      const { page, stub } = env;
      const drawer = await openNoteDrawer(env, NOTE_KINDS[2]);
      stub.route({ method: "POST", re: /api\/debit-notes\/n9\/issue$/, reply: () => ok({ id: "n9", stock_not_moved: ISSUE_SENTENCE("debit note", "PDN-0009") }) });
      await drawer.getByRole("button", { name: "Issue", exact: true }).click();
      await page.getByText(ISSUE_SENTENCE("debit note", "PDN-0009")).waitFor();
      assert.equal(await page.getByText(/Debit note issued\./).count() >= 1, true, "the message does not say that the note was issued");
    },
  },

  {
    id: "the-branding-screen-draws-only-what-the-invoice-prints",
    title: "Settings > Firm Branding: the preview is the top of the invoice PDF (the title in the primary colour, no band), applies neither the chosen font nor the secondary colour, and each setting that is kept on file says so",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "GET", re: /api\/settings\/branding$/, reply: () => ok({ branding: {
        primary_color: "#2563EB", secondary_color: "#FF0000", accent_color: "#00FF00", font_family: "Poppins", tagline: "Chartered Accountants", social_links: {},
      } }) });
      await page.goto(`${env.base}/settings/branding/`, { waitUntil: "networkidle" });
      await page.getByText("Secondary colour: kept on file. The invoice PDF does not print it.").waitFor();
      await page.getByText("Accent colour: kept on file. The invoice PDF does not print it.").waitFor();
      await page.getByText("Font (Poppins): kept on file. The invoice PDF is always set in Helvetica.").waitFor();
      await page.getByText("Only the primary colour is printed (as the colour of the invoice title).", { exact: false }).waitFor();
      await page.getByText("Kept on file. No document prints these links.").waitFor();
      // the logo's limits are the PDF's own: bytes (not a unit that two computers count differently), and the wait the server gives a picture
      await page.getByText("The invoice PDF prints a PNG, JPEG or WebP logo of up to 2,000,000 bytes (about 2 MB) that the server can fetch within three seconds.", { exact: false }).waitFor();
      // the sketch speaks the PDF's words and its currency (Helvetica has no rupee sign, so the PDF prints "Rs.")
      await page.getByText("Bill To", { exact: true }).waitFor();
      await page.getByText("Invoice No", { exact: true }).waitFor();
      await page.getByText("Rs. 59,000.00", { exact: true }).waitFor();
      assert.equal(await page.getByText(/₹/).count(), 0, "the sketch shows a rupee sign: the invoice PDF prints 'Rs.'");
      // the sample invoice's text is not set in the chosen font
      const family = await page.getByText("Sample Client Pvt. Ltd.").evaluate((el) => getComputedStyle(el).fontFamily);
      assert.doesNotMatch(family, /Poppins/, `the preview sets its text in the chosen font (${family}): the invoice PDF is always Helvetica`);
      // the title is the one thing in the primary colour, and it is the colour of its TEXT
      const title = await page.getByText("TAX INVOICE", { exact: true }).evaluate((el) => getComputedStyle(el).color);
      assert.equal(title, "rgb(37, 99, 235)", `the title is not in the primary colour (${title})`);
      // nothing in the preview is drawn as a block in the primary colour (the PDF has no band) and nothing but the one-dot swatch is in the secondary colour
      const drawn = await page.evaluate(() => {
        const preview = Array.from(document.querySelectorAll("p")).find((p) => p.textContent === "Sample Client Pvt. Ltd.")?.closest(".shadow-sm");
        if (!preview) return { problem: "NO PREVIEW" };
        const secondary = [];
        const primaryBlocks = [];
        for (const el of preview.querySelectorAll("*")) {
          const cs = getComputedStyle(el);
          const box = el.getBoundingClientRect();
          if (cs.backgroundColor === "rgb(255, 0, 0)") secondary.push({ tag: el.tagName, hidden: el.getAttribute("aria-hidden"), w: Math.round(box.width), h: Math.round(box.height) });
          if (cs.backgroundColor === "rgb(37, 99, 235)") primaryBlocks.push({ tag: el.tagName, w: Math.round(box.width), h: Math.round(box.height) });
        }
        const tagline = Array.from(preview.querySelectorAll("p")).some((p) => p.textContent === "Chartered Accountants");
        return { secondary, primaryBlocks, tagline };
      });
      assert.ok(!drawn.problem, drawn.problem);
      assert.ok(drawn.secondary.length >= 1, "the secondary colour is not shown at all, not even as a swatch");
      for (const d of drawn.secondary) assert.ok(d.hidden === "true" && d.w <= 16 && d.h <= 16, `something larger than a swatch is drawn in the secondary colour: ${JSON.stringify(d)}`);
      assert.deepEqual(drawn.primaryBlocks, [], "a block is drawn in the primary colour in the preview: the invoice PDF has no band");
      assert.equal(drawn.tagline, true, "the tagline the firm set is not in the preview");
      // the page no longer promises documents that do not read it
      assert.equal(await page.getByText(/all documents|client communications|client documents/).count(), 0, "the Branding screen promises documents that do not read it");
      assert.equal(await page.getByText(/no document prints them yet|No document prints these links yet/).count(), 0, "a 'yet' promises a build nobody has planned");
      await page.getByText("no document prints them", { exact: false }).first().waitFor();
    },
  },
  {
    id: "the-branding-preview-prints-no-tagline-the-firm-did-not-set",
    title: "Settings > Firm Branding: a firm with no tagline has none in the preview (the PDF prints none then)",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "GET", re: /api\/settings\/branding$/, reply: () => ok({ branding: { primary_color: "#2563EB", secondary_color: "#1E40AF", accent_color: "#3B82F6", font_family: "Inter", tagline: null, social_links: {} } }) });
      await page.goto(`${env.base}/settings/branding/`, { waitUntil: "networkidle" });
      await page.getByText("TAX INVOICE", { exact: true }).waitFor();
      assert.equal(await page.getByText("Chartered Accountants", { exact: true }).count(), 0, "the preview prints a tagline nobody set");
    },
  },
  {
    id: "the-invoice-templates-screen-sells-no-style-and-says-what-changes-the-invoice",
    title: "Settings > Invoice Templates: the subtitle names what the layout reaches, and the five styles are names with no description",
    async run(env) {
      const { page } = env;
      await page.goto(`${env.base}/settings/invoice-templates/`, { waitUntil: "networkidle" });
      await page.getByText("Choose where the logo and the signature sit on the invoices your practice issues to its own clients.", { exact: false }).waitFor();
      await page.getByText("Engagement letters and your clients' own invoices do not use it.", { exact: false }).waitFor();
      assert.equal(await page.getByText(/and engagement documents/).count(), 0, "the screen promises engagement documents");
      // with no template yet, the empty state says what a template sets: where the logo and the signature sit, and nothing about the footer's words
      await page.getByText("A template sets where the logo and the signature sit on the invoices your practice issues to its own clients.", { exact: false }).waitFor();
      assert.equal(await page.getByText(/what the footer says/).count(), 0, "the empty state says a template sets what the footer says");
      await page.getByRole("button", { name: "New Template" }).first().click();
      await page.getByText("The style is a name for the template and does not change how the invoice is drawn.", { exact: false }).waitFor();
      await page.getByText("Style name", { exact: true }).waitFor();
      assert.equal(await page.getByText("Layout Style", { exact: true }).count(), 0, "five names that change nothing are headed Layout Style");
      for (const promise of [/bold typography/, /ICAI branding guidelines/, /numbers and key details only/, /Traditional layout/, /Formal layout/]) {
        assert.equal(await page.getByText(promise).count(), 0, `a layout style is described again: ${promise}`);
      }
      for (const label of ["Classic", "Modern", "Professional CA", "Corporate", "Minimal"]) await page.getByText(label, { exact: true }).first().waitFor();
    },
  },
  {
    id: "the-settings-hub-and-the-payment-details-screen-say-what-the-invoice-carries",
    title: "Settings hub and Invoice Settings: the branding and payment-details sentences name the practice's own invoices and not every document or every invoice",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: {} }) });
      await page.goto(`${env.base}/settings/`, { waitUntil: "networkidle" });
      await page.getByText("Logo, tagline and primary colour for your practice's own invoices; the other settings are kept on file.", { exact: false }).waitFor();
      await page.getByText("Where the logo and the signature sit on your practice's own invoices.", { exact: false }).waitFor();
      assert.equal(await page.getByText(/applied to all client documents|Layout styles: Classic/).count(), 0, "the hub promises what no document does");
      await page.goto(`${env.base}/settings/invoice-settings/`, { waitUntil: "networkidle" });
      await page.getByText("A client's own invoices do not carry them.", { exact: false }).waitFor();
      assert.equal(await page.getByText(/appear on every invoice/).count(), 0, "the payment details are said to be on every invoice");
      // the block prints only when a bank name, an account number or a UPI ID is set, and the QR picture has the logo's limits
      await page.getByText("when a bank name, an account number or a UPI ID is filled in", { exact: false }).waitFor();
      await page.getByText("The account holder and the IFSC code are printed with the bank details, and the QR picture with either.", { exact: false }).waitFor();
      await page.getByText("Printed only if it is a PNG, JPEG or WebP of up to 2,000,000 bytes (about 2 MB) that the server can fetch within three seconds.", { exact: false }).waitFor();
    },
  },
];
